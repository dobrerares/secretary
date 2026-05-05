"""Action seam — concentrated reversibility for Root entities.

This module is the single seam through which CRUD on Root entities
(Task, Event) is logged and undone. It owns three concerns per
Root entity, each pluggable through the `_RECORDS` registry:

- **snapshot**: derive the canonical "one card" from a live ORM instance
- **recreate**: rebuild a Root entity from a Snapshot (used to undo deletes)
- **restore**: reapply a Snapshot's fields to a live entity, including
  children — tags and subtasks ride inside their root's Snapshot
  (used to undo updates)

Vocabulary (from CONTEXT.md):

- **Action** — a logged, reversible operation on a Root entity
- **Snapshot** — the canonical record of a Root entity, one shape used
  for both ActionLog storage and the AI tool result
- **Root entity** — Task or Event; only these have an Action seam.
  Subtasks and Tags are children, not Root entities.
- **Batch** — a UUID grouping Actions that should undo together
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from secretary.db.models import ActionLog, Event, Subtask, Tag, Task, task_tags


# ---------------------------------------------------------------------------
# Snapshot builders — one card per Root entity type
# ---------------------------------------------------------------------------


def _snapshot_task(task: Task) -> dict:
    """Build a Task Snapshot. Subtasks and tags ride inside this dict —
    they are not Root entities of their own."""
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
            {
                "id": s.id,
                "title": s.title,
                "is_complete": s.is_complete,
                "position": s.position,
            }
            for s in task.subtasks
        ],
        "tags": [t.name for t in task.tags],
    }


def _snapshot_event(event: Event) -> dict:
    """Build an Event Snapshot."""
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


async def _get_or_create_tag(session: AsyncSession, name: str) -> Tag:
    normalized = name.strip().lower()
    result = await session.execute(select(Tag).where(Tag.name == normalized))
    tag = result.scalar_one_or_none()
    if not tag:
        tag = Tag(name=normalized)
        session.add(tag)
        await session.flush()
    return tag


async def _load_task(session: AsyncSession, task_id: int) -> Task | None:
    result = await session.execute(
        select(Task)
        .options(selectinload(Task.subtasks), selectinload(Task.tags))
        .where(Task.id == task_id)
    )
    return result.scalar_one_or_none()


async def _load_event(session: AsyncSession, event_id: int) -> Event | None:
    result = await session.execute(select(Event).where(Event.id == event_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Recreate — rebuild a Root entity from its Snapshot (undo of delete)
# ---------------------------------------------------------------------------


async def _recreate_task(session: AsyncSession, snap: dict) -> None:
    task = Task(
        id=snap["id"],
        title=snap["title"],
        description=snap.get("description"),
        area=snap.get("area"),
        priority=snap.get("priority", "none"),
        status=snap.get("status", "to_do"),
        due_at=_parse_dt(snap.get("due_at")),
        scheduled_at=_parse_dt(snap.get("scheduled_at")),
        time_estimate_minutes=snap.get("time_estimate_minutes"),
        recurrence_rule=snap.get("recurrence_rule"),
        source=snap.get("source", "manual"),
        inbox_item_id=snap.get("inbox_item_id"),
    )
    session.add(task)
    await session.flush()

    # Subtasks and tags ride inside the Snapshot — recreate them too.
    for s in snap.get("subtasks", []) or []:
        subtask = Subtask(
            id=s.get("id"),
            task_id=task.id,
            title=s["title"],
            is_complete=s.get("is_complete", False),
            position=s.get("position", 0),
        )
        session.add(subtask)

    for tag_name in snap.get("tags", []) or []:
        tag = await _get_or_create_tag(session, tag_name)
        await session.execute(task_tags.insert().values(task_id=task.id, tag_id=tag.id))

    await session.flush()


async def _recreate_event(session: AsyncSession, snap: dict) -> None:
    event = Event(
        id=snap["id"],
        title=snap["title"],
        description=snap.get("description"),
        area=snap.get("area"),
        start_at=_parse_dt(snap["start_at"]),
        end_at=_parse_dt(snap["end_at"]),
        location=snap.get("location"),
        is_all_day=snap.get("is_all_day", False),
        calendar_source=snap.get("calendar_source", "internal"),
        external_id=snap.get("external_id"),
        recurrence_rule=snap.get("recurrence_rule"),
        inbox_item_id=snap.get("inbox_item_id"),
    )
    session.add(event)
    await session.flush()


# ---------------------------------------------------------------------------
# Restore — reapply a Snapshot's fields to a live entity (undo of update)
# ---------------------------------------------------------------------------


_TASK_DT_FIELDS = {"due_at", "scheduled_at"}
_TASK_SCALAR_FIELDS = (
    "title",
    "description",
    "area",
    "priority",
    "status",
    "time_estimate_minutes",
    "recurrence_rule",
    "source",
    "inbox_item_id",
)


async def _restore_task(session: AsyncSession, task: Task, snap: dict) -> None:
    """Reapply a Task Snapshot. This INCLUDES tags and subtasks — they ride
    inside the Root's Snapshot, so undoing an update must roll them back too."""
    for field in _TASK_SCALAR_FIELDS:
        if field in snap:
            setattr(task, field, snap[field])
    for field in _TASK_DT_FIELDS:
        if field in snap:
            setattr(task, field, _parse_dt(snap[field]))

    # Restore tags exactly to the Snapshot's set.
    await session.execute(task_tags.delete().where(task_tags.c.task_id == task.id))
    for tag_name in snap.get("tags", []) or []:
        tag = await _get_or_create_tag(session, tag_name)
        await session.execute(task_tags.insert().values(task_id=task.id, tag_id=tag.id))

    # Restore subtasks exactly to the Snapshot's list.
    for s in list(task.subtasks):
        await session.delete(s)
    await session.flush()
    for s in snap.get("subtasks", []) or []:
        subtask = Subtask(
            task_id=task.id,
            title=s["title"],
            is_complete=s.get("is_complete", False),
            position=s.get("position", 0),
        )
        session.add(subtask)
    await session.flush()
    # Expire cached relationships so the next eager load reflects the
    # raw INSERT/DELETE writes above.
    session.expire(task, ["tags", "subtasks"])


_EVENT_DT_FIELDS = {"start_at", "end_at"}
_EVENT_SCALAR_FIELDS = (
    "title",
    "description",
    "area",
    "location",
    "is_all_day",
    "calendar_source",
    "external_id",
    "recurrence_rule",
    "inbox_item_id",
)


async def _restore_event(session: AsyncSession, event: Event, snap: dict) -> None:
    for field in _EVENT_SCALAR_FIELDS:
        if field in snap:
            setattr(event, field, snap[field])
    for field in _EVENT_DT_FIELDS:
        if field in snap:
            setattr(event, field, _parse_dt(snap[field]))
    await session.flush()


# ---------------------------------------------------------------------------
# Registry — Root entity → (snapshot, recreate, restore)
# ---------------------------------------------------------------------------


SnapshotFn = Callable[[object], dict]
RecreateFn = Callable[[AsyncSession, dict], Awaitable[None]]
RestoreFn = Callable[[AsyncSession, object, dict], Awaitable[None]]


_RECORDS: dict[str, tuple[SnapshotFn, RecreateFn, RestoreFn]] = {
    "task": (_snapshot_task, _recreate_task, _restore_task),
    "event": (_snapshot_event, _recreate_event, _restore_event),
}


# ---------------------------------------------------------------------------
# Public seam — make_snapshot, log_*, undo_*, get_*
# ---------------------------------------------------------------------------


def make_snapshot(entity_type: str, entity: object) -> dict:
    """Build the canonical Snapshot for a Root entity.

    The Snapshot is one shape with two jobs: ActionLog storage AND the
    AI tool result. Per CONTEXT.md, only Task and Event are Root entities.
    """
    record = _RECORDS.get(entity_type)
    if record is None:
        raise ValueError(
            f"{entity_type!r} is not a Root entity; only "
            f"{sorted(_RECORDS.keys())} can be snapshotted."
        )
    snapshot_fn, _, _ = record
    return snapshot_fn(entity)


async def _record(
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


async def log_create(
    session: AsyncSession,
    entity_type: str,
    entity: object,
    batch_id: str,
) -> ActionLog:
    """Record a create Action — `after_state` is the new entity's Snapshot."""
    snap = make_snapshot(entity_type, entity)
    return await _record(
        session,
        action_type="create",
        entity_type=entity_type,
        entity_id=snap["id"],
        before_state=None,
        after_state=snap,
        batch_id=batch_id,
    )


async def log_update(
    session: AsyncSession,
    entity_type: str,
    before: dict,
    after_entity: object,
    batch_id: str,
) -> ActionLog:
    """Record an update Action with the pre-update Snapshot and the
    fresh post-update Snapshot."""
    after = make_snapshot(entity_type, after_entity)
    return await _record(
        session,
        action_type="update",
        entity_type=entity_type,
        entity_id=after["id"],
        before_state=before,
        after_state=after,
        batch_id=batch_id,
    )


async def log_delete(
    session: AsyncSession,
    entity_type: str,
    before_entity: object,
    batch_id: str,
) -> ActionLog:
    """Record a delete Action — `before_state` is the deleted entity's Snapshot."""
    snap = make_snapshot(entity_type, before_entity)
    return await _record(
        session,
        action_type="delete",
        entity_type=entity_type,
        entity_id=snap["id"],
        before_state=snap,
        after_state=None,
        batch_id=batch_id,
    )


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


async def _replay_before_state(session: AsyncSession, action: ActionLog) -> None:
    """Apply the undo for a single Action by routing through the registry."""
    record = _RECORDS.get(action.entity_type)
    if record is None:
        # Should never happen given the CHECK constraint, but stay defensive.
        return
    _, recreate_fn, restore_fn = record

    if action.action_type == "create":
        # Undo a create by deleting the entity.
        if action.entity_type == "task":
            entity = await _load_task(session, action.entity_id)
        else:
            entity = await _load_event(session, action.entity_id)
        if entity is not None:
            await session.delete(entity)

    elif action.action_type == "delete":
        if action.before_state:
            await recreate_fn(session, action.before_state)

    elif action.action_type == "update":
        if action.before_state:
            if action.entity_type == "task":
                entity = await _load_task(session, action.entity_id)
            else:
                entity = await _load_event(session, action.entity_id)
            if entity is not None:
                await restore_fn(session, entity, action.before_state)


async def undo_action(session: AsyncSession, action_log_id: int) -> bool:
    """Undo a single Action. Returns True on success."""
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
    """Undo all Actions in a Batch (in reverse order). Returns the count
    of Actions undone."""
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


# ---------------------------------------------------------------------------
# Read-only helpers
# ---------------------------------------------------------------------------


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
