"""Tool call execution -- dispatches to core CRUD functions."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.action_log import event_to_dict, task_to_dict
from secretary.core.events import (
    create_event,
    delete_event,
    list_events,
    update_event,
)
from secretary.core.schemas import (
    EventCreate,
    EventFilter,
    EventUpdate,
    SettingsUpdate,
    TaskCreate,
    TaskFilter,
    TaskUpdate,
)
from secretary.core.settings import get_settings, update_settings
from secretary.core.tasks import (
    complete_task,
    create_task,
    delete_task,
    list_tasks,
    update_task,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime string, returning None for empty/None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _serialize_task(task) -> dict:
    """Serialize a Task model to a plain dict for tool results."""
    return task_to_dict(task)


def _serialize_event(event) -> dict:
    """Serialize an Event model to a plain dict for tool results."""
    return event_to_dict(event)


async def execute_tool(
    session: AsyncSession,
    tool_name: str,
    arguments: dict,
    batch_id: str,
) -> dict:
    """Dispatch a tool call to the matching core function.

    Returns a dict with either {"result": ...} or {"error": ...}.
    """
    try:
        handler = _HANDLERS.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}
        return await handler(session, arguments, batch_id)
    except Exception as exc:
        logger.exception("Tool execution error for %s: %s", tool_name, exc)
        return {"error": f"Failed to execute {tool_name}: {str(exc)}"}


# ---------------------------------------------------------------------------
# Individual tool handlers
# ---------------------------------------------------------------------------


async def _handle_create_task(session: AsyncSession, args: dict, batch_id: str) -> dict:
    data = TaskCreate(
        title=args["title"],
        description=args.get("description"),
        area=args.get("area"),
        priority=args.get("priority", "none"),
        due_at=_parse_dt(args.get("due_at")),
        scheduled_at=_parse_dt(args.get("scheduled_at")),
        time_estimate_minutes=args.get("time_estimate_minutes"),
        tags=args.get("tags", []),
        source="ai_suggested",
    )
    task = await create_task(session, data, batch_id)
    return {"result": _serialize_task(task)}


async def _handle_update_task(session: AsyncSession, args: dict, batch_id: str) -> dict:
    task_id = args.pop("task_id", None) or args.pop("id", None)
    if task_id is None:
        return {"error": "task_id is required"}

    update_data: dict = {}
    for field in ("title", "description", "area", "priority", "status", "time_estimate_minutes", "tags"):
        if field in args:
            update_data[field] = args[field]
    for dt_field in ("due_at", "scheduled_at"):
        if dt_field in args:
            update_data[dt_field] = _parse_dt(args[dt_field])

    data = TaskUpdate(**update_data)
    task = await update_task(session, int(task_id), data, batch_id)
    if not task:
        return {"error": f"Task {task_id} not found"}
    return {"result": _serialize_task(task)}


async def _handle_complete_task(session: AsyncSession, args: dict, batch_id: str) -> dict:
    task_id = args.get("task_id") or args.get("id")
    if task_id is None:
        return {"error": "task_id is required"}
    task = await complete_task(session, int(task_id), batch_id)
    if not task:
        return {"error": f"Task {task_id} not found"}
    return {"result": _serialize_task(task)}


async def _handle_delete_task(session: AsyncSession, args: dict, batch_id: str) -> dict:
    task_id = args.get("task_id") or args.get("id")
    if task_id is None:
        return {"error": "task_id is required"}
    deleted = await delete_task(session, int(task_id), batch_id)
    if not deleted:
        return {"error": f"Task {task_id} not found"}
    return {"result": {"deleted": True, "task_id": int(task_id)}}


async def _handle_list_tasks(session: AsyncSession, args: dict, batch_id: str) -> dict:
    filter_kwargs: dict = {}
    for field in ("area", "priority", "status", "search"):
        if field in args and args[field] is not None:
            filter_kwargs[field] = args[field]
    for dt_field in ("due_before", "due_after"):
        if dt_field in args and args[dt_field] is not None:
            filter_kwargs[dt_field] = _parse_dt(args[dt_field])
    if args.get("overdue"):
        filter_kwargs["overdue"] = True

    filters = TaskFilter(**filter_kwargs) if filter_kwargs else None
    tasks = await list_tasks(session, filters)
    return {"result": [_serialize_task(t) for t in tasks]}


async def _handle_create_event(session: AsyncSession, args: dict, batch_id: str) -> dict:
    start_at = _parse_dt(args.get("start_at"))
    end_at = _parse_dt(args.get("end_at"))
    if not start_at or not end_at:
        return {"error": "start_at and end_at are required and must be valid ISO 8601 datetimes"}

    data = EventCreate(
        title=args["title"],
        description=args.get("description"),
        area=args.get("area"),
        start_at=start_at,
        end_at=end_at,
        location=args.get("location"),
        is_all_day=args.get("is_all_day", False),
    )
    event = await create_event(session, data, batch_id)
    return {"result": _serialize_event(event)}


async def _handle_update_event(session: AsyncSession, args: dict, batch_id: str) -> dict:
    event_id = args.pop("event_id", None) or args.pop("id", None)
    if event_id is None:
        return {"error": "event_id is required"}

    update_data: dict = {}
    for field in ("title", "description", "area", "location", "is_all_day"):
        if field in args:
            update_data[field] = args[field]
    for dt_field in ("start_at", "end_at"):
        if dt_field in args:
            update_data[dt_field] = _parse_dt(args[dt_field])

    data = EventUpdate(**update_data)
    event = await update_event(session, int(event_id), data, batch_id)
    if not event:
        return {"error": f"Event {event_id} not found"}
    return {"result": _serialize_event(event)}


async def _handle_delete_event(session: AsyncSession, args: dict, batch_id: str) -> dict:
    event_id = args.get("event_id") or args.get("id")
    if event_id is None:
        return {"error": "event_id is required"}
    deleted = await delete_event(session, int(event_id), batch_id)
    if not deleted:
        return {"error": f"Event {event_id} not found"}
    return {"result": {"deleted": True, "event_id": int(event_id)}}


async def _handle_list_events(session: AsyncSession, args: dict, batch_id: str) -> dict:
    filter_kwargs: dict = {}
    if args.get("area"):
        filter_kwargs["area"] = args["area"]
    for dt_field in ("start_after", "start_before"):
        if dt_field in args and args[dt_field] is not None:
            filter_kwargs[dt_field] = _parse_dt(args[dt_field])

    filters = EventFilter(**filter_kwargs) if filter_kwargs else None
    events = await list_events(session, filters)
    return {"result": [_serialize_event(e) for e in events]}


async def _handle_get_briefing(session: AsyncSession, args: dict, batch_id: str) -> dict:
    briefing_type = args.get("type", "daily")
    now = datetime.now(timezone.utc)

    if briefing_type == "weekly":
        end = now + timedelta(days=7)
    else:
        end = now + timedelta(days=1)

    # Gather tasks
    task_filter = TaskFilter(due_before=end)
    tasks = await list_tasks(session, task_filter)

    overdue_filter = TaskFilter(overdue=True)
    overdue_tasks = await list_tasks(session, overdue_filter)

    # Gather events
    event_filter = EventFilter(start_after=now, start_before=end)
    events = await list_events(session, event_filter)

    return {
        "result": {
            "type": briefing_type,
            "period_start": now.isoformat(),
            "period_end": end.isoformat(),
            "upcoming_tasks": [_serialize_task(t) for t in tasks],
            "overdue_tasks": [_serialize_task(t) for t in overdue_tasks],
            "upcoming_events": [_serialize_event(e) for e in events],
        }
    }


async def _handle_read_settings(session: AsyncSession, args: dict, batch_id: str) -> dict:
    settings = await get_settings(session)
    return {
        "result": {
            "timezone": settings.timezone,
            "wake_time": settings.wake_time,
            "wind_down_time": settings.wind_down_time,
            "notification_level": settings.notification_level,
            "auto_approve_mode": settings.auto_approve_mode,
            "areas": settings.areas,
            "memory": settings.memory,
        }
    }


async def _handle_update_memory(session: AsyncSession, args: dict, batch_id: str) -> dict:
    fact = args.get("fact", "").strip()
    if not fact:
        return {"error": "fact is required and cannot be empty"}

    settings = await get_settings(session)
    current_memory: list = list(settings.memory) if isinstance(settings.memory, list) else []

    # Avoid duplicates
    if fact not in current_memory:
        current_memory.append(fact)
        await update_settings(session, SettingsUpdate(memory=current_memory))

    return {"result": {"stored": True, "fact": fact, "total_facts": len(current_memory)}}


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

_HANDLERS = {
    "create_task": _handle_create_task,
    "update_task": _handle_update_task,
    "complete_task": _handle_complete_task,
    "delete_task": _handle_delete_task,
    "list_tasks": _handle_list_tasks,
    "create_event": _handle_create_event,
    "update_event": _handle_update_event,
    "delete_event": _handle_delete_event,
    "list_events": _handle_list_events,
    "get_briefing": _handle_get_briefing,
    "read_settings": _handle_read_settings,
    "update_memory": _handle_update_memory,
}
