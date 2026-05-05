"""CalDAV integration for Apple Calendar, Fastmail, Nextcloud, etc."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING

import caldav

from secretary.core.schemas import EventCreate

if TYPE_CHECKING:
    from secretary.db.models import Event

logger = logging.getLogger(__name__)

# Name of the calendar we create/use on the CalDAV server for writing events
APP_CALENDAR_NAME = "Secretary"


class CalDAVSync:
    """Read/write events on a CalDAV server.

    All CalDAV network calls are synchronous (the ``caldav`` library is blocking),
    so the public ``async`` methods delegate to a thread-pool executor.
    """

    def __init__(self, url: str, username: str, password: str) -> None:
        self.url = url
        self.username = username
        self.password = password

    # ------------------------------------------------------------------
    # Internal helpers (synchronous, run in executor)
    # ------------------------------------------------------------------

    def _connect(self) -> caldav.DAVClient:
        return caldav.DAVClient(
            url=self.url,
            username=self.username,
            password=self.password,
        )

    # ------------------------------------------------------------------
    # Fetch events (sync)
    # ------------------------------------------------------------------

    def _fetch_events_sync(
        self,
        time_min: datetime,
        time_max: datetime,
    ) -> list[EventCreate]:
        client = self._connect()
        principal = client.principal()
        calendars = principal.calendars()

        all_events: list[EventCreate] = []
        for cal in calendars:
            try:
                results = cal.search(
                    start=time_min,
                    end=time_max,
                    event=True,
                    expand=True,
                )
            except Exception:
                logger.exception("CalDAV: failed to search calendar %s", cal.name)
                continue

            for item in results:
                try:
                    parsed = self._parse_vevent(item)
                    if parsed is not None:
                        all_events.append(parsed)
                except Exception:
                    logger.exception("CalDAV: failed to parse event from %s", cal.name)

        return all_events

    @staticmethod
    def _parse_vevent(cal_event: caldav.Event) -> EventCreate | None:
        """Parse an iCalendar VEVENT into an ``EventCreate``."""
        ical = cal_event.icalendar_instance
        if ical is None:
            return None

        for component in ical.walk():
            if component.name != "VEVENT":
                continue

            uid = str(component.get("UID", ""))
            summary = str(component.get("SUMMARY", "(No title)"))
            description = component.get("DESCRIPTION")
            if description is not None:
                description = str(description)
            location = component.get("LOCATION")
            if location is not None:
                location = str(location)

            dtstart = component.get("DTSTART")
            dtend = component.get("DTEND")
            if dtstart is None:
                return None

            start_val = dtstart.dt
            # Determine all-day: date-only (not datetime) means all-day
            is_all_day = not isinstance(start_val, datetime)

            if is_all_day:
                start_at = datetime(start_val.year, start_val.month, start_val.day, tzinfo=timezone.utc)
                if dtend is not None:
                    end_val = dtend.dt
                    end_at = datetime(end_val.year, end_val.month, end_val.day, tzinfo=timezone.utc)
                else:
                    end_at = start_at
            else:
                start_at = _ensure_utc(start_val)
                if dtend is not None:
                    end_at = _ensure_utc(dtend.dt)
                else:
                    end_at = start_at

            rrule = component.get("RRULE")
            recurrence_rule = None
            if rrule:
                recurrence_rule = rrule.to_ical().decode("utf-8")

            return EventCreate(
                title=summary,
                description=description,
                area=None,
                start_at=start_at,
                end_at=end_at,
                location=location,
                is_all_day=is_all_day,
                calendar_source="caldav",
                external_id=uid,
                recurrence_rule=recurrence_rule,
                inbox_item_id=None,
            )

        return None

    # ------------------------------------------------------------------
    # Write event (sync)
    # ------------------------------------------------------------------

    def _write_event_sync(self, event: "Event") -> str:
        """Create (or update) an event on the CalDAV server and return its UID."""
        client = self._connect()
        principal = client.principal()

        # Find or create the app-specific calendar
        target_cal = None
        for cal in principal.calendars():
            if cal.name == APP_CALENDAR_NAME:
                target_cal = cal
                break
        if target_cal is None:
            target_cal = principal.make_calendar(name=APP_CALENDAR_NAME)
            logger.info("CalDAV: created calendar '%s'", APP_CALENDAR_NAME)

        uid = event.external_id or str(uuid.uuid4())
        ics_data = _build_ics(event, uid)

        target_cal.save_event(ics_data)
        logger.info("CalDAV: saved event uid=%s title=%r", uid, event.title)
        return uid

    # ------------------------------------------------------------------
    # Async public API
    # ------------------------------------------------------------------

    async def fetch_events(
        self,
        time_min: datetime,
        time_max: datetime,
    ) -> list[EventCreate]:
        """Fetch events from all CalDAV calendars in the given time range."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(self._fetch_events_sync, time_min, time_max),
        )

    async def write_event(self, event: "Event") -> str:
        """Write a single event to the CalDAV server. Returns the external_id (UID)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(self._write_event_sync, event),
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _ensure_utc(dt_val: datetime) -> datetime:
    """Ensure a datetime has a timezone; assume UTC if naive."""
    if dt_val.tzinfo is None:
        return dt_val.replace(tzinfo=timezone.utc)
    return dt_val.astimezone(timezone.utc)


def _format_dt(dt_val: datetime, all_day: bool = False) -> str:
    """Format a datetime for iCalendar.

    All-day events use VALUE=DATE (``YYYYMMDD``); timed events use UTC
    (``YYYYMMDDTHHMMSSz``).
    """
    if all_day:
        return dt_val.strftime("%Y%m%d")
    utc = dt_val.astimezone(timezone.utc)
    return utc.strftime("%Y%m%dT%H%M%SZ")


def _ics_escape(text: str) -> str:
    """Escape special characters for iCalendar text values."""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text


def _build_ics(event: "Event", uid: str) -> str:
    """Build a minimal but valid iCalendar VEVENT string."""
    is_all_day = getattr(event, "is_all_day", False)

    if is_all_day:
        dtstart_line = f"DTSTART;VALUE=DATE:{_format_dt(event.start_at, all_day=True)}"
        dtend_line = f"DTEND;VALUE=DATE:{_format_dt(event.end_at, all_day=True)}"
    else:
        dtstart_line = f"DTSTART:{_format_dt(event.start_at)}"
        dtend_line = f"DTEND:{_format_dt(event.end_at)}"

    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Secretary//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now_stamp}",
        dtstart_line,
        dtend_line,
        f"SUMMARY:{_ics_escape(event.title)}",
    ]

    if event.description:
        lines.append(f"DESCRIPTION:{_ics_escape(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{_ics_escape(event.location)}")
    if event.recurrence_rule:
        # Expect an RRULE value like "FREQ=WEEKLY;BYDAY=MO"
        rule = event.recurrence_rule
        if not rule.upper().startswith("RRULE:"):
            rule = f"RRULE:{rule}"
        lines.append(rule)

    lines += [
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    return "\r\n".join(lines)
