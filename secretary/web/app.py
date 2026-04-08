"""Web UI router — Jinja2 + HTMX + Alpine.js + Tailwind CSS."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from secretary.config.settings import settings

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# -- Template globals -------------------------------------------------------

def _is_overdue(task) -> bool:
    """Check if a task is overdue (for use in templates)."""
    if not task.due_at or task.status in ("done", "cancelled"):
        return False
    now = datetime.now(timezone.utc)
    return task.due_at < now


templates.env.globals["is_overdue"] = _is_overdue

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Require auth_token cookie or ?token= query param when web_auth_token is set."""

    SKIP_PREFIXES = ("/health", "/docs", "/openapi.json", "/api/")

    async def dispatch(self, request: Request, call_next):
        # Only protect /web paths
        if not request.url.path.startswith("/web"):
            return await call_next(request)

        # If no token configured, skip auth (Tailscale / trusted network)
        if not settings.web_auth_token:
            return await call_next(request)

        # Allow static assets through
        if request.url.path.startswith("/web/static"):
            return await call_next(request)

        # Check cookie or query param
        token = request.cookies.get("auth_token") or request.query_params.get("token")
        if token == settings.web_auth_token:
            response = await call_next(request)
            # Set cookie if provided via query param so subsequent requests work
            if request.query_params.get("token") and not request.cookies.get("auth_token"):
                response.set_cookie("auth_token", token, httponly=True, samesite="lax", max_age=86400 * 30)
            return response

        return HTMLResponse(
            content=_auth_page(),
            status_code=401,
        )


def _auth_page() -> str:
    return """<!DOCTYPE html>
<html><head><title>Secretary - Login</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-slate-900 flex items-center justify-center min-h-screen">
<div class="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-sm">
  <h1 class="text-2xl font-bold text-slate-800 mb-1">Secretary</h1>
  <p class="text-slate-500 text-sm mb-6">Enter your access token to continue.</p>
  <form method="GET" class="space-y-4">
    <input name="token" type="password" placeholder="Access token"
           class="w-full border border-slate-300 rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500" autofocus />
    <button type="submit"
            class="w-full bg-indigo-600 text-white rounded-lg px-4 py-2.5 font-medium hover:bg-indigo-700 transition">
      Sign in</button>
  </form>
</div>
</body></html>"""


# ---------------------------------------------------------------------------
# Mount sub-routers
# ---------------------------------------------------------------------------

from secretary.web.routes.tasks import router as tasks_router      # noqa: E402
from secretary.web.routes.events import router as events_router    # noqa: E402
from secretary.web.routes.inbox import router as inbox_router      # noqa: E402
from secretary.web.routes.settings import router as settings_router  # noqa: E402
from secretary.web.routes.history import router as history_router  # noqa: E402

router.include_router(tasks_router)
router.include_router(events_router)
router.include_router(inbox_router)
router.include_router(settings_router)
router.include_router(history_router)


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def web_root():
    return RedirectResponse(url="/web/tasks", status_code=302)


# ---------------------------------------------------------------------------
# Mount static files
# ---------------------------------------------------------------------------

def mount_static(app):
    """Mount static files on the main app (sub-router mounts don't resolve correctly with prefixes)."""
    app.mount("/web/static", StaticFiles(directory=str(STATIC_DIR)), name="web_static")
