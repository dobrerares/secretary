"""Scheduled calendar sync job."""

import logging

from secretary.db.session import async_session_factory

logger = logging.getLogger(__name__)


async def calendar_sync_job() -> None:
    """Scheduled job: sync all configured calendar sources."""
    logger.info("Running calendar sync job")
    try:
        from secretary.calendar_sync.sync import sync_all_calendars

        async with async_session_factory() as session:
            results = await sync_all_calendars(session)
            await session.commit()
        logger.info("Calendar sync complete: %s", results)
    except Exception:
        logger.exception("Calendar sync job failed")
