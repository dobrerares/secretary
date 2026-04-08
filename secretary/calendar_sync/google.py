"""Google Calendar integration via OAuth2 and the Calendar API."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from secretary.core.schemas import EventCreate

logger = logging.getLogger(__name__)

# If modifying scopes, delete the stored credentials file so re-auth is triggered.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

CREDENTIALS_DIR = Path("data")
CREDENTIALS_FILE = CREDENTIALS_DIR / "google_credentials.json"
CLIENT_SECRET_FILE = CREDENTIALS_DIR / "google_client_secret.json"


class GoogleCalendarSync:
    """Handles Google Calendar OAuth2 and event fetching.

    Workflow:
        1. Place your Google OAuth client-secret JSON at data/google_client_secret.json.
        2. Call ``get_auth_url(redirect_uri)`` and redirect the user to that URL.
        3. Google redirects back; call ``handle_callback(code, redirect_uri)`` with
           the authorization code to exchange it for credentials.
        4. Credentials (including a refresh token) are persisted to
           data/google_credentials.json for future use.
        5. Call ``fetch_events(time_min, time_max)`` to pull events.
    """

    def __init__(self) -> None:
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------

    def get_auth_url(self, redirect_uri: str) -> str:
        """Return a Google OAuth2 consent URL for the user to visit.

        ``redirect_uri`` must match one of the URIs registered in the
        Google Cloud console for the OAuth client.
        """
        flow = Flow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE),
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )
        return auth_url

    def handle_callback(self, code: str, redirect_uri: str) -> Credentials:
        """Exchange the authorization *code* for credentials and persist them."""
        flow = Flow.from_client_secrets_file(
            str(CLIENT_SECRET_FILE),
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        self._save_credentials(creds)
        return creds

    # ------------------------------------------------------------------
    # Credential storage
    # ------------------------------------------------------------------

    @staticmethod
    def _save_credentials(creds: Credentials) -> None:
        payload = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes or []),
        }
        CREDENTIALS_FILE.write_text(json.dumps(payload, indent=2))
        logger.info("Google credentials saved to %s", CREDENTIALS_FILE)

    @staticmethod
    def _load_credentials() -> Credentials | None:
        if not CREDENTIALS_FILE.exists():
            return None
        data = json.loads(CREDENTIALS_FILE.read_text())
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes"),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GoogleCalendarSync._save_credentials(creds)
        return creds

    # ------------------------------------------------------------------
    # Event fetching (sync, intended to run inside an executor)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_service(creds: Credentials):
        """Build and return a Google Calendar API service object."""
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    @staticmethod
    def _fetch_events_sync(
        time_min: datetime,
        time_max: datetime,
    ) -> list[EventCreate]:
        """Synchronous implementation: load creds, query the API, return EventCreate list."""
        creds = GoogleCalendarSync._load_credentials()
        if creds is None:
            logger.warning("No Google credentials found; skipping Google Calendar sync.")
            return []

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GoogleCalendarSync._save_credentials(creds)

        service = GoogleCalendarSync._build_service(creds)

        # Ensure we have proper RFC3339 timestamps in UTC
        t_min = time_min.astimezone(timezone.utc).isoformat()
        t_max = time_max.astimezone(timezone.utc).isoformat()

        all_events: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=t_min,
                    timeMax=t_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=250,
                    pageToken=page_token,
                )
                .execute()
            )
            all_events.extend(result.get("items", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        return [GoogleCalendarSync._convert_event(ev) for ev in all_events]

    @staticmethod
    def _convert_event(item: dict[str, Any]) -> EventCreate:
        """Convert a single Google Calendar event dict to an ``EventCreate``."""
        start_raw = item.get("start", {})
        end_raw = item.get("end", {})

        is_all_day = "date" in start_raw and "dateTime" not in start_raw

        if is_all_day:
            start_at = datetime.fromisoformat(start_raw["date"])
            # Google all-day end dates are exclusive; keep as-is for storage.
            end_at = datetime.fromisoformat(end_raw["date"])
        else:
            start_at = datetime.fromisoformat(start_raw["dateTime"])
            end_at = datetime.fromisoformat(end_raw["dateTime"])

        recurrence = None
        if item.get("recurrence"):
            # Google sends a list of RRULE strings; join them.
            recurrence = ";".join(item["recurrence"])

        return EventCreate(
            title=item.get("summary", "(No title)"),
            description=item.get("description"),
            area=None,
            start_at=start_at,
            end_at=end_at,
            location=item.get("location"),
            is_all_day=is_all_day,
            calendar_source="google",
            external_id=item["id"],
            recurrence_rule=recurrence,
            inbox_item_id=None,
        )

    # ------------------------------------------------------------------
    # Async public API
    # ------------------------------------------------------------------

    async def fetch_events(
        self,
        time_min: datetime,
        time_max: datetime,
    ) -> list[EventCreate]:
        """Fetch Google Calendar events in a thread-pool executor.

        Returns a (possibly empty) list of ``EventCreate`` objects with
        ``calendar_source="google"``.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(self._fetch_events_sync, time_min, time_max),
        )
