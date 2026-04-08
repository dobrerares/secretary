"""Action logging and undo system.

Every write operation records before/after state snapshots in ActionLog.
batch_id groups related actions for batch undo.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.db.models import ActionLog, Event, InboxItem, Subtask, Task


def task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "area": task.area,
        "priority": task.priority,
        "status": task.status,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "time_estimate_minutes": task.time_estimate_minutes,
        "recurrence_rule": task.recurrence_rule,
        "source": task.source,
        "inbox_item_id": task.inbox_item_id,
        "subtasks": [
            {"id": s.id, "title": s.title, "is_complete": s.is_complete, "position": s.position}
            for s in task.subtasks
        ],
        "tags": [t.name for t in task.tags],
    }


def event_to_dict(event: Event) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "area": event.area,
        "start_at": event.start_at.isoformat() if event.start_at else None,
        "end_at": event.end_at.isoformat() if event.end_at else None,
        "location": event.location,
        "is_all_day": event.is_all_day,
        "calendar_source": event.calendar_source,
        "external_id": event.external_id,
        "recurrence_rule": event.recurrence_rule,
        "inbox_item_id": event.inbox_item_id,
    }


def subtask_to_dict(subtask: Subtask) -> dict:
    return {
        "id": subtask.id,
        "task_id": subtask.task_id,
        "title": subtask.title,
        "is_complete": subtask.is_complete,
        "position": subtask.position,
    }


async def record_action(
    session: AsyncSession,
    action_type: str,
    entity_type: str,
    entity_id: int,
    before_state: dict | None,
    after_state: dict | None,
    batch_id: str,
    expiry_minutes: int = 60,
) -> ActionLog:
    now = datetime.now(timezone.utc)
    action = ActionLog(
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        before_state=before_state,
        after_state=after_state,
        batch_id=batch_id,
        created_at=now,
        expires_at=now + timedelta(minutes=expiry_minutes),
    )
    session.add(action)
    await session.flush()
    return action


async def undo_action(session: AsyncSession, action_log_id: int) -> bool:
    """Undo a single action. Returns True if successful."""
    result = await session.execute(select(ActionLog).where(ActionLog.id == action_log_id))
    action = result.scalar_one_or_none()
    if not action or action.is_undone:
        return False

    now = datetime.now(timezone.utc)
    if action.expires_at < now:
        return False

    await _replay_before_state(session, action)
    action.is_undone = True
    return True


async def undo_batch(session: AsyncSession, batch_id: str) -> int:
    """Undo all actions in a batch (in reverse order). Returns count of undone actions."""
    result = await session.execute(
        select(ActionLog)
        .where(ActionLog.batch_id == batch_id, ActionLog.is_undone == False)  # noqa: E712
        .order_by(ActionLog.id.desc())
    )
    actions = result.scalars().all()

    now = datetime.now(timezone.utc)
    count = 0
    for action in actions:
        if action.expires_at < now:
            continue
        await _replay_before_state(session, action)
        action.is_undone = True
        count += 1

    return count


async def get_recent_actions(session: AsyncSession, limit: int = 20) -> list[ActionLog]:
    result = await session.execute(
        select(ActionLog)
        .where(ActionLog.is_undone == False)  # noqa: E712
        .order_by(ActionLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_last_batch_id(session: AsyncSession) -> str | None:
    result = await session.execute(
        select(ActionLog.batch_id)
        .where(ActionLog.is_undone == False)  # noqa: E712
        .order_by(ActionLog.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _replay_before_state(session: AsyncSession, action: ActionLog) -> None:
    """Replay the before_state to undo an action."""
    if action.action_type == "create":
        # Undo create = delete the entity
        entity = await _load_entity(session, action.entity_type, action.entity_id)
        if entity:
            await session.delete(entity)

    elif action.action_type == "delete":
        # Undo delete = re-create from before_state
        if action.before_state:
            await _recreate_entity(session, action.entity_type, action.before_state)

    elif action.action_type == "update":
        # Undo update = restore before_state fields
        if action.before_state:
            entity = await _load_entity(session, action.entity_type, action.entity_id)
            if entity:
                await _restore_fields(entity, action.entity_type, action.before_state)


async def _load_entity(session: AsyncSession, entity_type: str, entity_id: int):
    model_map = {"task": Task, "event": Event, "inbox_item": InboxItem, "subtask": Subtask}
    model = model_map.get(entity_type)
    if not model:
        return None
    result = await session.execute(select(model).where(model.id == entity_id))
    return result.scalar_one_or_none()


async def _recreate_entity(session: AsyncSession, entity_type: str, state: dict) -> None:
    """Recreate a deleted entity from its snapshot."""
    from datetime import datetime as dt

    def parse_dt(v):
        if v is None:
            return None
        return dt.fromisoformat(v)

    if entity_type == "task":
        task = Task(
            id=state["id"],
            title=state["title"],
            description=state.get("description"),
            area=state.get("area"),
            priority=state.get("priority", "none"),
            status=state.get("status", "to_do"),
            due_at=parse_dt(state.get("due_at")),
            scheduled_at=parse_dt(state.get("scheduled_at")),
            time_estimate_minutes=state.get("time_estimate_minutes"),
            recurrence_rule=state.get("recurrence_rule"),
            source=state.get("source", "manual"),
            inbox_item_id=state.get("inbox_item_id"),
        )
        session.add(task)

    elif entity_type == "event":
        event = Event(
            id=state["id"],
            title=state["title"],
            description=state.get("description"),
            area=state.get("area"),
            start_at=parse_dt(state["start_at"]),
            end_at=parse_dt(state["end_at"]),
            location=state.get("location"),
            is_all_day=state.get("is_all_day", False),
            calendar_source=state.get("calendar_source", "internal"),
            external_id=state.get("external_id"),
            recurrence_rule=state.get("recurrence_rule"),
            inbox_item_id=state.get("inbox_item_id"),
        )
        session.add(event)

    elif entity_type == "subtask":
        subtask = Subtask(
            id=state["id"],
            task_id=state["task_id"],
            title=state["title"],
            is_complete=state.get("is_complete", False),
            position=state.get("position", 0),
        )
        session.add(subtask)


async def _restore_fields(entity, entity_type: str, state: dict) -> None:
    """Restore an entity's fields from a snapshot."""
    from datetime import datetime as dt

    def parse_dt(v):
        if v is None:
            return None
        return dt.fromisoformat(v)

    skip_keys = {"id", "subtasks", "tags", "created_at", "updated_at"}
    dt_fields = {"due_at", "scheduled_at", "start_at", "end_at"}

    for key, value in state.items():
        if key in skip_keys:
            continue
        if key in dt_fields:
            value = parse_dt(value)
        if hasattr(entity, key):
            setattr(entity, key, value)
