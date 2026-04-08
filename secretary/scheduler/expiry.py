"""Undo-window expiry cleanup job."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from secretary.db.models import ActionLog
from secretary.db.session import async_session_factory

logger = logging.getLogger(__name__)


async def expire_undo_windows_job() -> None:
    """Scheduled job (every 10 min): mark expired undo windows.

    The undo handler already checks ``expires_at`` before allowing an undo,
    so this is purely informational housekeeping -- it sets ``is_undone`` on
    stale entries so they no longer appear in "recent actions" queries.
    """
    logger.debug("Running expire_undo_windows_job")
    try:
        async with async_session_factory() as session:
            now = datetime.now(timezone.utc)
            stmt = (
                update(ActionLog)
                .where(
                    ActionLog.expires_at < now,
                    ActionLog.is_undone == False,  # noqa: E712
                )
                .values(is_undone=True)
            )
            result = await session.execute(stmt)
            expired_count = result.rowcount
            await session.commit()

            if expired_count:
                logger.info("Expired %d undo window(s)", expired_count)
    except Exception:
        logger.exception("expire_undo_windows_job failed")
