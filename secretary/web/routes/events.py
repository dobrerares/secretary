"""Event web routes."""

import calendar as cal
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.actions import get_recent_actions
from secretary.core.events import create_event, delete_event, get_event, list_events, update_event
from secretary.core.schemas import EventCreate, EventFilter, EventUpdate
from secretary.core.settings import get_settings
from secretary.core.tasks import list_tasks
from secretary.core.schemas import TaskFilter
from secretary.db.session import get_session
from secretary.web.app import templates

router = APIRouter(prefix="/events", tags=["web-events"])


async def _undo_redirect(session: AsyncSession, url: str, msg: str) -> RedirectResponse:
    """Redirect with undo query params from the most recent action."""
    from urllib.parse import urlencode
    actions = await get_recent_actions(session, limit=1)
    if actions:
        sep = "&" if "?" in url else "?"
        url += f"{sep}" + urlencode({"action_id": actions[0].id, "action_msg": msg})
    return RedirectResponse(url=url, status_code=303)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Calendar (month view)
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def events_root():
    return RedirectResponse(url="/web/events/calendar", status_code=302)


@router.get("/calendar", response_class=HTMLResponse)
async def events_calendar(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    today = date.today()
    y = year or today.year
    m = month or today.month

    # First and last day of month
    first_day = date(y, m, 1)
    days_in_month = cal.monthrange(y, m)[1]
    last_day = date(y, m, days_in_month)

    # Start of week containing first day (Monday = 0)
    start_weekday = first_day.weekday()  # 0=Mon
    grid_start = first_day - timedelta(days=start_weekday)

    # End of week containing last day
    end_weekday = last_day.weekday()
    grid_end = last_day + timedelta(days=(6 - end_weekday))

    # Build grid of weeks
    weeks = []
    current = grid_start
    while current <= grid_end:
        week = []
        for _ in range(7):
            week.append(current)
            current += timedelta(days=1)
        weeks.append(week)

    # Fetch events for the grid range
    start_dt = datetime.combine(grid_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(grid_end, time.max, tzinfo=timezone.utc)
    events = await list_events(session, EventFilter(start_after=start_dt, start_before=end_dt))

    # Fetch tasks due in range
    tasks = await list_tasks(session, TaskFilter(due_after=start_dt, due_before=end_dt))

    # Map events/tasks by date
    events_by_date: dict[date, list] = {}
    for ev in events:
        d = ev.start_at.date() if ev.start_at else None
        if d:
            events_by_date.setdefault(d, []).append(ev)

    tasks_by_date: dict[date, list] = {}
    for t in tasks:
        d = t.due_at.date() if t.due_at else None
        if d:
            tasks_by_date.setdefault(d, []).append(t)

    # Prev / next month
    if m == 1:
        prev_year, prev_month = y - 1, 12
    else:
        prev_year, prev_month = y, m - 1
    if m == 12:
        next_year, next_month = y + 1, 1
    else:
        next_year, next_month = y, m + 1

    ctx = {
        "weeks": weeks,
        "month_name": cal.month_name[m],
        "year": y,
        "month": m,
        "today": today,
        "first_day": first_day,
        "events_by_date": events_by_date,
        "tasks_by_date": tasks_by_date,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
    }

    return templates.TemplateResponse(request, "events/calendar.html", ctx)


# ---------------------------------------------------------------------------
# Agenda (day / week view)
# ---------------------------------------------------------------------------

@router.get("/agenda", response_class=HTMLResponse)
async def events_agenda(
    request: Request,
    date_str: str | None = Query(None, alias="date"),
    mode: str = Query("day"),
    session: AsyncSession = Depends(get_session),
):
    today = date.today()
    target = _parse_date(date_str) or today

    if mode == "week":
        start = target - timedelta(days=target.weekday())
        end = start + timedelta(days=6)
    else:
        start = target
        end = target

    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)

    events = await list_events(session, EventFilter(start_after=start_dt, start_before=end_dt))
    tasks = await list_tasks(session, TaskFilter(due_after=start_dt, due_before=end_dt))

    # Group by date
    days = []
    current = start
    while current <= end:
        day_events = [e for e in events if e.start_at and e.start_at.date() == current]
        day_tasks = [t for t in tasks if t.due_at and t.due_at.date() == current]
        days.append({"date": current, "events": day_events, "tasks": day_tasks})
        current += timedelta(days=1)

    prev_date = (start - timedelta(days=7 if mode == "week" else 1)).isoformat()
    next_date = (end + timedelta(days=1)).isoformat()

    ctx = {
        "days": days,
        "target": target,
        "mode": mode,
        "prev_date": prev_date,
        "next_date": next_date,
        "today": today,
    }

    return templates.TemplateResponse(request, "events/list.html", ctx)


# ---------------------------------------------------------------------------
# Create / Edit
# ---------------------------------------------------------------------------

@router.get("/new", response_class=HTMLResponse)
async def event_new(request: Request, session: AsyncSession = Depends(get_session)):
    user_settings = await get_settings(session)
    return templates.TemplateResponse(request, "events/form.html", {
        "event": None,
        "areas": user_settings.areas or [],
        "editing": False,
    })


@router.post("", response_class=HTMLResponse)
async def event_create(request: Request, session: AsyncSession = Depends(get_session)):
    form = await request.form()

    is_all_day = form.get("is_all_day") == "on"

    data = EventCreate(
        title=form.get("title", "").strip(),
        description=form.get("description", "").strip() or None,
        area=form.get("area", "").strip() or None,
        start_at=_parse_dt(form.get("start_at")) or datetime.now(timezone.utc),
        end_at=_parse_dt(form.get("end_at")) or datetime.now(timezone.utc),
        location=form.get("location", "").strip() or None,
        is_all_day=is_all_day,
    )

    batch_id = str(uuid.uuid4())
    await create_event(session, data, batch_id)
    await session.commit()

    return await _undo_redirect(session, "/web/events/calendar", f"Event \"{data.title}\" created")


@router.get("/{event_id}/edit", response_class=HTMLResponse)
async def event_edit(request: Request, event_id: int, session: AsyncSession = Depends(get_session)):
    event = await get_event(session, event_id)
    if not event:
        return RedirectResponse(url="/web/events/calendar", status_code=303)

    user_settings = await get_settings(session)
    return templates.TemplateResponse(request, "events/form.html", {
        "event": event,
        "areas": user_settings.areas or [],
        "editing": True,
    })


@router.post("/{event_id}", response_class=HTMLResponse)
async def event_update(request: Request, event_id: int, session: AsyncSession = Depends(get_session)):
    form = await request.form()

    is_all_day = form.get("is_all_day") == "on"

    data = EventUpdate(
        title=form.get("title", "").strip(),
        description=form.get("description", "").strip() or None,
        area=form.get("area", "").strip() or None,
        start_at=_parse_dt(form.get("start_at")),
        end_at=_parse_dt(form.get("end_at")),
        location=form.get("location", "").strip() or None,
        is_all_day=is_all_day,
    )

    batch_id = str(uuid.uuid4())
    await update_event(session, event_id, data, batch_id)
    await session.commit()

    return await _undo_redirect(session, "/web/events/calendar", f"Event \"{data.title}\" updated")


@router.post("/{event_id}/delete", response_class=HTMLResponse)
async def event_delete(request: Request, event_id: int, session: AsyncSession = Depends(get_session)):
    batch_id = str(uuid.uuid4())
    await delete_event(session, event_id, batch_id)
    await session.commit()

    if _is_htmx(request):
        return HTMLResponse("")
    return await _undo_redirect(session, "/web/events/calendar", "Event deleted")
