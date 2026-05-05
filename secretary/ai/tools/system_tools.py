"""System tools — Tool entries that aren't tied to a single Root entity:
``get_briefing``, ``read_settings``, ``update_memory``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.tools._types import Tool, ToolCategory
from secretary.core.actions import make_snapshot
from secretary.core.events import list_events
from secretary.core.schemas import (
    EventFilter,
    GetBriefingArgs,
    ReadSettingsArgs,
    SettingsUpdate,
    TaskFilter,
    UpdateMemoryArgs,
)
from secretary.core.settings import get_settings, update_settings
from secretary.core.tasks import list_tasks


def _serialize_task(task) -> dict:
    return make_snapshot("task", task)


def _serialize_event(event) -> dict:
    return make_snapshot("event", event)


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


async def _get_briefing(session: AsyncSession, args: GetBriefingArgs, batch_id: str) -> dict:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7 if args.type == "weekly" else 1)

    upcoming_tasks = await list_tasks(session, TaskFilter(due_before=end))
    overdue_tasks = await list_tasks(session, TaskFilter(overdue=True))
    upcoming_events = await list_events(session, EventFilter(start_after=now, start_before=end))

    return {
        "result": {
            "type": args.type,
            "period_start": now.isoformat(),
            "period_end": end.isoformat(),
            "upcoming_tasks": [_serialize_task(t) for t in upcoming_tasks],
            "overdue_tasks": [_serialize_task(t) for t in overdue_tasks],
            "upcoming_events": [_serialize_event(e) for e in upcoming_events],
        }
    }


async def _read_settings(session: AsyncSession, args: ReadSettingsArgs, batch_id: str) -> dict:
    s = await get_settings(session)
    return {
        "result": {
            "timezone": s.timezone,
            "wake_time": s.wake_time,
            "wind_down_time": s.wind_down_time,
            "notification_level": s.notification_level,
            "auto_approve_mode": s.auto_approve_mode,
            "areas": s.areas,
            "memory": s.memory,
        }
    }


async def _update_memory(session: AsyncSession, args: UpdateMemoryArgs, batch_id: str) -> dict:
    fact = args.fact.strip()
    s = await get_settings(session)
    current_memory: list = list(s.memory) if isinstance(s.memory, list) else []
    if fact not in current_memory:
        current_memory.append(fact)
        await update_settings(session, SettingsUpdate(memory=current_memory))
    return {"result": {"stored": True, "fact": fact, "total_facts": len(current_memory)}}


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


SYSTEM_TOOLS = [
    Tool(
        name="get_briefing",
        description="Generate a daily or weekly briefing summarizing upcoming tasks and events.",
        args_schema=GetBriefingArgs,
        execute=_get_briefing,
        category=ToolCategory.READ,
    ),
    Tool(
        name="read_settings",
        description="Read the current user settings (areas, memory, notification preferences, etc.).",
        args_schema=ReadSettingsArgs,
        execute=_read_settings,
        category=ToolCategory.READ,
    ),
    Tool(
        name="update_memory",
        description="Store a fact or preference about the user for future reference.",
        args_schema=UpdateMemoryArgs,
        execute=_update_memory,
        category=ToolCategory.WRITE,
    ),
]
