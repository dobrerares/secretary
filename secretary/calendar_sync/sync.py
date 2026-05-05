"""Calendar sync orchestrator.

Pulls events from every configured calendar source (Google Calendar, CalDAV)
and upserts them into the local database, deduplicating on
``(calendar_source, external_id)``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.calendar_sync.caldav_client import CalDAVSync
from secretary.calendar_sync.google import GoogleCalendarSync
from secretary.config.settings import settings
from secretary.core.schemas import EventCreate
from secretary.db.models import Event

logger = logging.getLogger(__name__)

# Default sync window: pull events from 7 days ago to 30 days ahead.
_LOOKBACK_DAYS = 7
_LOOKAHEAD_DAYS = 30


async def sync_all_calendars(session: AsyncSession) -> dict[str, object]:
    """Run sync for every enabled calendar source.

    Returns a summary dict like::

        {
            "google": {"fetched": 12, "created": 3, "updated": 9, "errors": 0},
            "caldav":  {"fetched": 5,  "created": 1, "updated": 4, "errors": 0},
        }

    Each source is isolated: a failure in one does not block the others.
    """
    now = datetime.now(timezone.utc)
    time_min = now - timedelta(days=_LOOKBACK_DAYS)
    time_max = now + timedelta(days=_LOOKAHEAD_DAYS)

    results: dict[str, object] = {}

    # --- Google Calendar ---
    if settings.google_calendar_enabled:
        try:
            google = GoogleCalendarSync()
            events = await google.fetch_events(time_min, time_max)
            stats = await _upsert_events(session, events)
            results["google"] = stats
            logger.info("Google Calendar sync complete: %s", stats)
        except Exception:
            logger.exception("Google Calendar sync failed")
            results["google"] = {"error": "sync failed — see logs"}

    # --- CalDAV ---
    if settings.caldav_url:
        try:
            caldav_sync = CalDAVSync(
                url=settings.caldav_url,
                username=settings.caldav_username,
                password=settings.caldav_password,
            )
            events = await caldav_sync.fetch_events(time_min, time_max)
            stats = await _upsert_events(session, events)
            results["caldav"] = stats
            logger.info("CalDAV sync complete: %s", stats)
        except Exception:
            logger.exception("CalDAV sync failed")
            results["caldav"] = {"error": "sync failed — see logs"}

    if not results:
        logger.info("No calendar sources configured; nothing to sync.")

    return results


async def _upsert_events(
    session: AsyncSession,
    events: list[EventCreate],
) -> dict[str, int]:
    """Insert or update events, deduplicating on (calendar_source, external_id).

    Returns counts of fetched / created / updated / errors.
    """
    created = 0
    updated = 0
    errors = 0

    for ev in events:
        try:
            existing = await _find_existing(session, ev.calendar_source, ev.external_id)
            if existing is not None:
                _apply_update(existing, ev)
                updated += 1
            else:
                new_event = Event(
                    title=ev.title,
                    description=ev.description,
                    area=ev.area,
                    start_at=ev.start_at,
                    end_at=ev.end_at,
                    location=ev.location,
                    is_all_day=ev.is_all_day,
                    calendar_source=ev.calendar_source,
                    external_id=ev.external_id,
                    recurrence_rule=ev.recurrence_rule,
                    inbox_item_id=None,
                )
                session.add(new_event)
                created += 1
        except Exception:
            logger.exception(
                "Failed to upsert event external_id=%s source=%s",
                ev.external_id,
                ev.calendar_source,
            )
            errors += 1

    # Flush all pending changes in one go.
    await session.flush()

    return {
        "fetched": len(events),
        "created": created,
        "updated": updated,
        "errors": errors,
    }


async def _find_existing(
    session: AsyncSession,
    calendar_source: str,
    external_id: str | None,
) -> Event | None:
    """Look up an event by its source + external_id pair."""
    if not external_id:
        return None
    result = await session.execute(
        select(Event).where(
            Event.calendar_source == calendar_source,
            Event.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


def _apply_update(existing: Event, incoming: EventCreate) -> None:
    """Overwrite mutable fields on *existing* with values from *incoming*."""
    existing.title = incoming.title
    existing.description = incoming.description
    existing.start_at = incoming.start_at
    existing.end_at = incoming.end_at
    existing.location = incoming.location
    existing.is_all_day = incoming.is_all_day
    existing.recurrence_rule = incoming.recurrence_rule
    # Deliberately leave area, inbox_item_id, and calendar_source untouched:
    # area may have been set locally, inbox_item_id is for internal events only,
    # and calendar_source should not change.
