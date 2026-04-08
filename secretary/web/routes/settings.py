"""Settings web routes."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.config.settings import settings as app_settings
from secretary.core.schemas import SettingsUpdate
from secretary.core.settings import get_settings, update_settings
from secretary.db.session import get_session
from secretary.web.app import templates

router = APIRouter(prefix="/settings", tags=["web-settings"])

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def _mask(value: str, visible: int = 4) -> str:
    if not value or len(value) <= visible:
        return value
    return value[:visible] + "•" * min(len(value) - visible, 20)


def _server_config() -> dict:
    from secretary.calendar_sync.google import CREDENTIALS_FILE
    return {
        "llm_model": app_settings.llm_model,
        "llm_api_key_masked": _mask(app_settings.llm_api_key),
        "whisper_mode": app_settings.whisper_mode,
        "google_calendar_enabled": app_settings.google_calendar_enabled,
        "google_client_id": app_settings.google_client_id,
        "google_connected": CREDENTIALS_FILE.exists(),
        "caldav_url": app_settings.caldav_url,
        "caldav_username": app_settings.caldav_username,
        "caldav_password_masked": _mask(app_settings.caldav_password),
        "calendar_sync_interval_minutes": app_settings.calendar_sync_interval_minutes,
    }


@router.get("", response_class=HTMLResponse)
async def settings_page(request: Request, session: AsyncSession = Depends(get_session)):
    user_settings = await get_settings(session)
    return templates.TemplateResponse(request, "settings.html", {
        "settings": user_settings,
        "server": _server_config(),
    })


@router.post("", response_class=HTMLResponse)
async def settings_update(request: Request, session: AsyncSession = Depends(get_session)):
    form = await request.form()

    areas_raw = form.get("areas_json", "[]")
    try:
        areas = json.loads(areas_raw)
    except (json.JSONDecodeError, TypeError):
        areas = []

    memory_raw = form.get("memory_json", "[]")
    try:
        memory = json.loads(memory_raw)
    except (json.JSONDecodeError, TypeError):
        memory = []

    undo_expiry_raw = form.get("undo_expiry_minutes", "").strip()
    undo_expiry = int(undo_expiry_raw) if undo_expiry_raw else 60

    ai_ctx_raw = form.get("ai_context_messages", "").strip()
    ai_ctx = int(ai_ctx_raw) if ai_ctx_raw else 20

    data = SettingsUpdate(
        wake_time=form.get("wake_time", "08:00"),
        wind_down_time=form.get("wind_down_time", "22:00"),
        timezone=form.get("timezone", "UTC"),
        notification_level=form.get("notification_level", "balanced"),
        auto_approve_mode=form.get("auto_approve_mode", "off"),
        areas=areas,
        memory=memory,
        undo_expiry_minutes=undo_expiry,
        ai_context_messages=ai_ctx,
    )

    await update_settings(session, data)
    await session.commit()

    return RedirectResponse(url="/web/settings?saved=1", status_code=303)


@router.post("/server", response_class=HTMLResponse)
async def server_config_update(request: Request):
    """Update .env server configuration. Applied live — no restart needed."""
    form = await request.form()

    if not ENV_PATH.exists():
        return RedirectResponse(url="/web/settings?saved=1", status_code=303)

    env_lines = ENV_PATH.read_text().splitlines()
    updates: dict[str, str] = {}

    # LLM model
    llm_model = form.get("llm_model", "").strip()
    if llm_model:
        updates["SECRETARY_LLM_MODEL"] = llm_model

    # LLM API key — only update if not masked placeholder
    llm_key = form.get("llm_api_key", "").strip()
    if llm_key and "•" not in llm_key:
        updates["SECRETARY_LLM_API_KEY"] = llm_key

    # Whisper
    whisper_mode = form.get("whisper_mode", "local")
    updates["SECRETARY_WHISPER_MODE"] = whisper_mode

    # Calendar
    google_enabled = "true" if form.get("google_calendar_enabled") else "false"
    updates["SECRETARY_GOOGLE_CALENDAR_ENABLED"] = google_enabled

    caldav_url = form.get("caldav_url", "").strip()
    updates["SECRETARY_CALDAV_URL"] = caldav_url

    caldav_user = form.get("caldav_username", "").strip()
    updates["SECRETARY_CALDAV_USERNAME"] = caldav_user

    caldav_pass = form.get("caldav_password", "").strip()
    if caldav_pass and "•" not in caldav_pass:
        updates["SECRETARY_CALDAV_PASSWORD"] = caldav_pass

    sync_interval = form.get("calendar_sync_interval_minutes", "15").strip()
    updates["SECRETARY_CALENDAR_SYNC_INTERVAL_MINUTES"] = sync_interval

    # Apply updates to .env
    new_lines = []
    updated_keys = set()
    for line in env_lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Append any new keys not already in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n")

    # Hot-reload: apply new values to the running process immediately
    from secretary.config.settings import reload_settings
    reload_settings()

    return RedirectResponse(url="/web/settings?saved=1", status_code=303)


# ---------------------------------------------------------------------------
# Google Calendar OAuth flow
# ---------------------------------------------------------------------------

GOOGLE_CALLBACK_PATH = "/web/settings/google/callback"


@router.get("/google/connect")
async def google_connect(request: Request):
    """Redirect user to Google OAuth consent screen."""
    from secretary.calendar_sync.google import GoogleCalendarSync
    gcal = GoogleCalendarSync()
    redirect_uri = str(request.base_url).rstrip("/") + GOOGLE_CALLBACK_PATH
    auth_url = gcal.get_auth_url(redirect_uri)
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_callback(request: Request, code: str = "", error: str = ""):
    """Handle Google OAuth callback."""
    if error or not code:
        return RedirectResponse(url="/web/settings?google_error=" + (error or "no_code"))

    from secretary.calendar_sync.google import GoogleCalendarSync
    gcal = GoogleCalendarSync()
    redirect_uri = str(request.base_url).rstrip("/") + GOOGLE_CALLBACK_PATH
    gcal.handle_callback(code, redirect_uri)
    return RedirectResponse(url="/web/settings?google=connected")


@router.get("/google/disconnect")
async def google_disconnect():
    """Remove stored Google credentials."""
    from secretary.calendar_sync.google import CREDENTIALS_FILE
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()
    return RedirectResponse(url="/web/settings?google=disconnected")
