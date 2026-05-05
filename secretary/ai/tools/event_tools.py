"""Event tools — the four Tool entries that operate on Event root entities."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.tools._types import Tool, ToolCategory
from secretary.core.actions import make_snapshot
from secretary.core.events import (
    create_event,
    delete_event,
    list_events,
    update_event,
)
from secretary.core.schemas import (
    EventCreate,
    EventCreateArgs,
    EventDeleteArgs,
    EventFilter,
    EventUpdate,
    EventUpdateArgs,
    ListEventsArgs,
)


def _serialize_event(event) -> dict:
    return make_snapshot("event", event)


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


async def _create_event(session: AsyncSession, args: EventCreateArgs, batch_id: str) -> dict:
    data = EventCreate(**args.model_dump())
    event = await create_event(session, data, batch_id)
    return {"result": _serialize_event(event)}


async def _update_event(session: AsyncSession, args: EventUpdateArgs, batch_id: str) -> dict:
    payload = args.model_dump(exclude_unset=True, exclude={"event_id"})
    data = EventUpdate(**payload)
    event = await update_event(session, args.event_id, data, batch_id)
    if event is None:
        return {"error": f"Event {args.event_id} not found"}
    return {"result": _serialize_event(event)}


async def _delete_event(session: AsyncSession, args: EventDeleteArgs, batch_id: str) -> dict:
    deleted = await delete_event(session, args.event_id, batch_id)
    if not deleted:
        return {"error": f"Event {args.event_id} not found"}
    return {"result": {"deleted": True, "event_id": args.event_id}}


async def _list_events(session: AsyncSession, args: ListEventsArgs, batch_id: str) -> dict:
    payload = args.model_dump(exclude_unset=True)
    filters = EventFilter(**payload) if payload else None
    events = await list_events(session, filters)
    return {"result": [_serialize_event(e) for e in events]}


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


EVENT_TOOLS = [
    Tool(
        name="create_event",
        description="Create a new calendar event.",
        args_schema=EventCreateArgs,
        execute=_create_event,
        category=ToolCategory.WRITE,
    ),
    Tool(
        name="update_event",
        description="Update an existing calendar event.",
        args_schema=EventUpdateArgs,
        execute=_update_event,
        category=ToolCategory.WRITE,
    ),
    Tool(
        name="delete_event",
        description="Permanently delete a calendar event.",
        args_schema=EventDeleteArgs,
        execute=_delete_event,
        category=ToolCategory.DESTRUCTIVE_WRITE,
    ),
    Tool(
        name="list_events",
        description="List calendar events with optional filters.",
        args_schema=ListEventsArgs,
        execute=_list_events,
        category=ToolCategory.READ,
    ),
]
