"""Scheduled briefing generation -- daily and weekly summaries."""

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from secretary.config.settings import settings as app_settings
from secretary.core.events import list_events
from secretary.core.schemas import EventFilter, TaskFilter
from secretary.core.settings import get_settings
from secretary.core.tasks import list_tasks
from secretary.db.session import async_session_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helper -- used by jobs AND /briefing command
# ---------------------------------------------------------------------------


async def generate_briefing_text(session: AsyncSession, briefing_type: str) -> str:
    """Build a plain-text briefing string.

    Args:
        session: An active DB session.
        briefing_type: ``"daily"`` or ``"weekly"``.

    Returns:
        Telegram-friendly HTML string.
    """
    if briefing_type == "weekly":
        return await _build_weekly_text(session)
    return await _build_daily_text(session)


# ---------------------------------------------------------------------------
# Daily briefing
# ---------------------------------------------------------------------------


async def _build_daily_text(session: AsyncSession) -> str:
    user_settings = await get_settings(session)
    tz = ZoneInfo(user_settings.timezone)

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    today_start = datetime.combine(now_local.date(), time.min, tzinfo=tz).astimezone(timezone.utc)
    today_end = datetime.combine(now_local.date(), time.max, tzinfo=tz).astimezone(timezone.utc)

    # --- Queries ---
    today_events = await list_events(
        session,
        EventFilter(start_after=today_start, start_before=today_end),
    )

    overdue_tasks = await list_tasks(
        session,
        TaskFilter(overdue=True),
    )

    tasks_due_today = await list_tasks(
        session,
        TaskFilter(due_before=today_end, due_after=today_start),
    )

    # Top 3 by priority + earliest deadline (reuse the default ordering from
    # list_tasks which is due_at ASC NULLS LAST, created_at DESC). We pull a
    # small set of active tasks and pick the best ones.
    top_tasks = await _top_priority_tasks(session, limit=3)

    # --- Format ---
    date_str = now_local.strftime("%A, %B %d")
    parts: list[str] = [f"<b>Good morning! Daily Briefing for {date_str}</b>\n"]

    # Events
    parts.append("<b>Today's Schedule</b>")
    if today_events:
        for ev in today_events:
            ev_start = ev.start_at.astimezone(tz) if ev.start_at else None
            ev_end = ev.end_at.astimezone(tz) if ev.end_at else None
            if ev.is_all_day:
                parts.append(f"  All day -- {ev.title}")
            elif ev_start and ev_end:
                parts.append(f"  {ev_start.strftime('%H:%M')}-{ev_end.strftime('%H:%M')} -- {ev.title}")
            else:
                parts.append(f"  {ev.title}")
    else:
        parts.append("  No events today.")
    parts.append("")

    # Overdue tasks
    if overdue_tasks:
        parts.append(f"<b>Overdue Tasks ({len(overdue_tasks)})</b>")
        for t in overdue_tasks[:5]:
            due_str = _fmt_due(t.due_at, tz)
            parts.append(f"  - {t.title}{due_str}  #{t.id}")
        if len(overdue_tasks) > 5:
            parts.append(f"  ... and {len(overdue_tasks) - 5} more")
        parts.append("")

    # Tasks due today
    parts.append("<b>Tasks Due Today</b>")
    if tasks_due_today:
        for t in tasks_due_today:
            pri = f" [{t.priority}]" if t.priority not in ("none", None) else ""
            parts.append(f"  - {t.title}{pri}  #{t.id}")
    else:
        parts.append("  No tasks due today.")
    parts.append("")

    # Top priority tasks
    if top_tasks:
        parts.append("<b>Top Priority</b>")
        for t in top_tasks:
            due_str = _fmt_due(t.due_at, tz)
            pri = f" [{t.priority}]" if t.priority not in ("none", None) else ""
            parts.append(f"  - {t.title}{pri}{due_str}  #{t.id}")
        parts.append("")

    parts.append("<i>Reply with any task ID to take action.</i>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Weekly review
# ---------------------------------------------------------------------------


async def _build_weekly_text(session: AsyncSession) -> str:
    user_settings = await get_settings(session)
    tz = ZoneInfo(user_settings.timezone)

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)

    # This week: Monday .. Sunday
    week_start = datetime.combine(
        now_local.date() - timedelta(days=now_local.weekday()),
        time.min,
        tzinfo=tz,
    ).astimezone(timezone.utc)
    week_end = datetime.combine(now_local.date(), time.max, tzinfo=tz).astimezone(timezone.utc)

    # Next week
    next_week_start = datetime.combine(now_local.date() + timedelta(days=1), time.min, tzinfo=tz).astimezone(
        timezone.utc
    )
    next_week_end = datetime.combine(now_local.date() + timedelta(days=7), time.max, tzinfo=tz).astimezone(timezone.utc)

    # --- Queries ---
    # Completed this week
    completed_tasks = await list_tasks(
        session,
        TaskFilter(status="done", due_after=week_start, due_before=week_end),
    )
    # Also grab completed tasks without due dates that were updated this week
    all_done = await list_tasks(session, TaskFilter(status="done"))
    recently_done = [t for t in all_done if t.updated_at and t.updated_at >= week_start.replace(tzinfo=None)]
    # Merge and deduplicate
    completed_ids = {t.id for t in completed_tasks}
    for t in recently_done:
        if t.id not in completed_ids:
            completed_tasks.append(t)

    # Slipped: due this week, not done
    slipped_tasks = await list_tasks(
        session,
        TaskFilter(due_before=week_end, due_after=week_start),
    )
    slipped_tasks = [t for t in slipped_tasks if t.status not in ("done", "cancelled")]

    # Upcoming deadlines next week
    upcoming_tasks = await list_tasks(
        session,
        TaskFilter(due_after=next_week_start, due_before=next_week_end),
    )

    # Upcoming events next week
    upcoming_events = await list_events(
        session,
        EventFilter(start_after=next_week_start, start_before=next_week_end),
    )

    # Areas with no scheduled activity next week
    active_areas: set[str] = set()
    for t in upcoming_tasks:
        if t.area:
            active_areas.add(t.area)
    for e in upcoming_events:
        if e.area:
            active_areas.add(e.area)

    configured_areas = user_settings.areas or []
    idle_areas = [a for a in configured_areas if a not in active_areas]

    # --- Format ---
    week_label = now_local.strftime("%B %d")
    parts: list[str] = [f"<b>Weekly Review -- Week of {week_label}</b>\n"]

    # Completed
    parts.append(f"<b>Completed This Week ({len(completed_tasks)})</b>")
    if completed_tasks:
        for t in completed_tasks[:10]:
            parts.append(f"  - {t.title}")
        if len(completed_tasks) > 10:
            parts.append(f"  ... and {len(completed_tasks) - 10} more")
    else:
        parts.append("  Nothing completed this week.")
    parts.append("")

    # Slipped
    if slipped_tasks:
        parts.append(f"<b>Slipped ({len(slipped_tasks)})</b>")
        for t in slipped_tasks[:5]:
            due_str = _fmt_due(t.due_at, tz)
            parts.append(f"  - {t.title}{due_str}  #{t.id}")
        if len(slipped_tasks) > 5:
            parts.append(f"  ... and {len(slipped_tasks) - 5} more")
        parts.append("")

    # Upcoming deadlines
    parts.append("<b>Upcoming Deadlines (Next Week)</b>")
    if upcoming_tasks:
        for t in upcoming_tasks[:8]:
            due_str = _fmt_due(t.due_at, tz)
            parts.append(f"  - {t.title}{due_str}  #{t.id}")
    else:
        parts.append("  No deadlines next week.")
    parts.append("")

    # Upcoming events
    parts.append("<b>Next Week's Events</b>")
    if upcoming_events:
        for ev in upcoming_events[:8]:
            ev_start = ev.start_at.astimezone(tz) if ev.start_at else None
            day_str = ev_start.strftime("%a %H:%M") if ev_start else ""
            parts.append(f"  - {day_str} -- {ev.title}")
    else:
        parts.append("  No events next week.")
    parts.append("")

    # Idle areas
    if idle_areas:
        parts.append("<b>Areas With No Activity Next Week</b>")
        for a in idle_areas:
            parts.append(f"  - {a}")
        parts.append("")

    parts.append("<i>Plan your week ahead! Use /addtask to schedule work.</i>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}


async def _top_priority_tasks(session: AsyncSession, limit: int = 3) -> list:
    """Return the top N active tasks ranked by priority then due date."""
    tasks = await list_tasks(session, TaskFilter())  # active, default ordering
    tasks.sort(
        key=lambda t: (
            _PRIORITY_ORDER.get(t.priority, 99),
            t.due_at or datetime.max.replace(tzinfo=timezone.utc),
        )
    )
    return tasks[:limit]


def _fmt_due(due_at: datetime | None, tz: ZoneInfo) -> str:
    if due_at is None:
        return ""
    local = due_at.astimezone(tz)
    return f" (due {local.strftime('%b %d')})"


# ---------------------------------------------------------------------------
# Scheduled job entry points
# ---------------------------------------------------------------------------


async def daily_briefing_job() -> None:
    """Scheduled job: send the daily briefing via Telegram."""
    logger.info("Running daily briefing job")
    try:
        async with async_session_factory() as session:
            text = await generate_briefing_text(session, "daily")

        from secretary.bot.setup import bot

        if bot is None:
            logger.warning("Bot not initialised -- skipping daily briefing")
            return
        await bot.send_message(
            chat_id=app_settings.telegram_user_id,
            text=text,
            parse_mode="HTML",
        )
        logger.info("Daily briefing sent")
    except Exception:
        logger.exception("Failed to send daily briefing")


async def weekly_review_job() -> None:
    """Scheduled job: send the weekly review via Telegram."""
    logger.info("Running weekly review job")
    try:
        async with async_session_factory() as session:
            text = await generate_briefing_text(session, "weekly")

        from secretary.bot.setup import bot

        if bot is None:
            logger.warning("Bot not initialised -- skipping weekly review")
            return
        await bot.send_message(
            chat_id=app_settings.telegram_user_id,
            text=text,
            parse_mode="HTML",
        )
        logger.info("Weekly review sent")
    except Exception:
        logger.exception("Failed to send weekly review")
