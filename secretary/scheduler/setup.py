"""APScheduler setup -- create scheduler, register jobs, start/stop."""

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from secretary.db.session import async_session_factory
from secretary.core.settings import get_settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def start_scheduler() -> None:
    """Configure and start the APScheduler instance.

    Reads the user's *wake_time*, *wind_down_time* and *timezone* from the DB
    to set the cron triggers for daily briefing and weekly review.
    """
    # --- Load user settings for schedule times ---
    try:
        async with async_session_factory() as session:
            user_settings = await get_settings(session)
        wake_time = user_settings.wake_time  # e.g. "08:00"
        wind_down_time = user_settings.wind_down_time  # e.g. "22:00"
        user_tz_str = user_settings.timezone  # e.g. "America/New_York"
    except Exception:
        logger.warning("Could not load user settings for scheduler -- using defaults")
        wake_time = "08:00"
        wind_down_time = "22:00"
        user_tz_str = "UTC"

    try:
        user_tz = ZoneInfo(user_tz_str)
    except Exception:
        logger.warning("Invalid timezone %r -- falling back to UTC", user_tz_str)
        user_tz = ZoneInfo("UTC")

    wake_hour, wake_minute = _parse_time(wake_time)
    wind_hour, wind_minute = _parse_time(wind_down_time)

    # --- Import job functions (lazy to avoid circular imports) ---
    from secretary.scheduler.briefings import daily_briefing_job, weekly_review_job
    from secretary.scheduler.notifications import check_reminders_job
    from secretary.scheduler.expiry import expire_undo_windows_job
    from secretary.scheduler.calendar_job import calendar_sync_job

    # --- Register jobs ---

    # Daily briefing -- every day at user's wake_time
    scheduler.add_job(
        daily_briefing_job,
        trigger=CronTrigger(hour=wake_hour, minute=wake_minute, timezone=user_tz),
        id="daily_briefing",
        name="Daily briefing",
        replace_existing=True,
    )

    # Weekly review -- every Sunday at user's wind_down_time
    scheduler.add_job(
        weekly_review_job,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=wind_hour,
            minute=wind_minute,
            timezone=user_tz,
        ),
        id="weekly_review",
        name="Weekly review",
        replace_existing=True,
    )

    # Check reminders -- every 5 minutes
    scheduler.add_job(
        check_reminders_job,
        trigger=IntervalTrigger(minutes=5),
        id="check_reminders",
        name="Check reminders",
        replace_existing=True,
    )

    # Expire undo windows -- every 10 minutes
    scheduler.add_job(
        expire_undo_windows_job,
        trigger=IntervalTrigger(minutes=10),
        id="expire_undo_windows",
        name="Expire undo windows",
        replace_existing=True,
    )

    # Calendar sync -- every N minutes (default 15)
    from secretary.config.settings import settings as app_settings

    sync_interval = app_settings.calendar_sync_interval_minutes
    scheduler.add_job(
        calendar_sync_job,
        trigger=IntervalTrigger(minutes=sync_interval),
        id="calendar_sync",
        name="Calendar sync",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started -- daily briefing at %s, weekly review Sunday at %s (%s)",
        wake_time,
        wind_down_time,
        user_tz_str,
    )


async def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse an ``"HH:MM"`` string into (hour, minute)."""
    try:
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 8, 0
