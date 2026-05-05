"""Reminder notifications -- deadline alerts, conflict detection, idle nudges."""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from secretary.config.settings import settings as app_settings
from secretary.core.events import list_events
from secretary.core.schemas import EventFilter, TaskFilter
from secretary.core.settings import get_settings
from secretary.core.tasks import list_tasks
from secretary.db.session import async_session_factory

logger = logging.getLogger(__name__)

# In-memory reminder tracking.  Maps task_id -> last UTC datetime we sent a
# reminder.  This is intentionally simple -- survives only within a single
# process lifetime.  A persistent approach (e.g. a DB column) can be added
# later if needed.
_reminded: dict[int, datetime] = {}

# Minimum interval between repeat reminders for the same task.
_REMINDER_COOLDOWN = timedelta(hours=1)


async def check_reminders_job() -> None:
    """Scheduled job (every 5 min): send deadline & contextual reminders."""
    logger.debug("Running check_reminders_job")
    try:
        async with async_session_factory() as session:
            user_settings = await get_settings(session)
            level = user_settings.notification_level  # minimal | balanced | aggressive
            tz = ZoneInfo(user_settings.timezone)

            now_utc = datetime.now(timezone.utc)

            # ------------------------------------------------------------------
            # 1. Deadline reminders (all notification levels)
            # ------------------------------------------------------------------
            upcoming_cutoff = now_utc + timedelta(hours=1)
            due_soon_tasks = await list_tasks(
                session,
                TaskFilter(due_before=upcoming_cutoff, due_after=now_utc),
            )

            messages: list[str] = []

            for task in due_soon_tasks:
                if task.status in ("done", "cancelled"):
                    continue
                if _was_recently_reminded(task.id, now_utc):
                    continue

                local_due = task.due_at.astimezone(tz) if task.due_at else None
                due_str = local_due.strftime("%H:%M") if local_due else "soon"
                messages.append(f'<b>Reminder:</b> "{task.title}" is due at {due_str}  #{task.id}')
                _reminded[task.id] = now_utc

            # ------------------------------------------------------------------
            # 2. Conflict detection (balanced + aggressive)
            # ------------------------------------------------------------------
            if level in ("balanced", "aggressive"):
                conflict_msgs = await _detect_conflicts(session, tz, now_utc)
                messages.extend(conflict_msgs)

            # ------------------------------------------------------------------
            # 3. Context-switch alerts (aggressive only)
            # ------------------------------------------------------------------
            if level == "aggressive":
                ctx_msgs = await _context_switch_alerts(session, tz, now_utc)
                messages.extend(ctx_msgs)

            # ------------------------------------------------------------------
            # 4. Idle nudges (aggressive only)
            # ------------------------------------------------------------------
            if level == "aggressive":
                nudge = await _idle_nudge(session, tz, now_utc)
                if nudge:
                    messages.append(nudge)

        # --- Send collected messages ---
        if messages:
            from secretary.bot.setup import bot

            if bot is None:
                logger.warning("Bot not initialised -- skipping reminders")
                return
            text = "\n\n".join(messages)
            await bot.send_message(
                chat_id=app_settings.telegram_user_id,
                text=text,
                parse_mode="HTML",
            )
            logger.info("Sent %d reminder(s)", len(messages))
    except Exception:
        logger.exception("check_reminders_job failed")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _was_recently_reminded(task_id: int, now: datetime) -> bool:
    last = _reminded.get(task_id)
    if last is None:
        return False
    return (now - last) < _REMINDER_COOLDOWN


async def _detect_conflicts(session, tz: ZoneInfo, now_utc: datetime) -> list[str]:
    """Find overlapping events in the next 3 hours."""
    window_end = now_utc + timedelta(hours=3)
    events = await list_events(
        session,
        EventFilter(start_after=now_utc, start_before=window_end),
    )
    messages: list[str] = []
    # Simple O(n^2) overlap check -- fine for a personal calendar
    for i, ev_a in enumerate(events):
        for ev_b in events[i + 1 :]:
            if ev_a.start_at < ev_b.end_at and ev_b.start_at < ev_a.end_at:
                a_start = ev_a.start_at.astimezone(tz).strftime("%H:%M")
                b_start = ev_b.start_at.astimezone(tz).strftime("%H:%M")
                messages.append(f'<b>Conflict:</b> "{ev_a.title}" ({a_start}) overlaps with "{ev_b.title}" ({b_start})')
    return messages


async def _context_switch_alerts(session, tz: ZoneInfo, now_utc: datetime) -> list[str]:
    """Alert about events starting in the next 15 minutes with pending tasks for that area."""
    window_end = now_utc + timedelta(minutes=15)
    upcoming_events = await list_events(
        session,
        EventFilter(start_after=now_utc, start_before=window_end),
    )

    messages: list[str] = []
    for ev in upcoming_events:
        area = ev.area
        mins = int((ev.start_at - now_utc).total_seconds() / 60) if ev.start_at else 0

        # Gather pending tasks for this event's area
        task_list_str = ""
        if area:
            area_tasks = await list_tasks(session, TaskFilter(area=area, status="to_do"))
            if area_tasks:
                titles = [t.title for t in area_tasks[:3]]
                task_list_str = f" Pending for {area}: " + ", ".join(titles)
                if len(area_tasks) > 3:
                    task_list_str += f" (+{len(area_tasks) - 3} more)"

        messages.append(f'\U0001f4cd Your <b>"{ev.title}"</b> starts in {mins} min.{task_list_str}')
    return messages


async def _idle_nudge(session, tz: ZoneInfo, now_utc: datetime) -> str | None:
    """If no tasks are in_progress and there are pending tasks, nudge."""
    in_progress = await list_tasks(session, TaskFilter(status="in_progress"))
    if in_progress:
        return None  # user is already working on something

    active_tasks = await list_tasks(session, TaskFilter())
    if not active_tasks:
        return None

    top = active_tasks[0]
    return f'<b>Nudge:</b> You have no tasks in progress. How about starting "{top.title}"?  #{top.id}'
