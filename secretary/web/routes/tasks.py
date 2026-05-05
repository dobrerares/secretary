"""Task web routes."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.actions import get_recent_actions
from secretary.core.schemas import SubtaskCreate, TaskCreate, TaskFilter, TaskUpdate
from secretary.core.settings import get_settings
from secretary.core.tasks import complete_task, create_task, delete_task, get_task, list_tasks, update_task
from secretary.db.session import get_session
from secretary.web.app import templates

router = APIRouter(prefix="/tasks", tags=["web-tasks"])


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
# List
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def task_list(
    request: Request,
    area: str | None = Query(None),
    priority: str | None = Query(None),
    status: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    filters = TaskFilter(area=area or None, priority=priority or None, status=status or None)
    tasks = await list_tasks(session, filters)
    user_settings = await get_settings(session)

    ctx = {
        "tasks": tasks,
        "areas": user_settings.areas or [],
        "current_area": area or "",
        "current_priority": priority or "",
        "current_status": status or "",
    }
    if _is_htmx(request):
        return templates.TemplateResponse(request, "tasks/_task_list.html", ctx)
    return templates.TemplateResponse(request, "tasks/list.html", ctx)


@router.get("/_list", response_class=HTMLResponse)
async def task_list_partial(
    request: Request,
    area: str | None = Query(None),
    priority: str | None = Query(None),
    status: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    filters = TaskFilter(area=area or None, priority=priority or None, status=status or None)
    tasks = await list_tasks(session, filters)
    user_settings = await get_settings(session)

    return templates.TemplateResponse(
        request,
        "tasks/_task_list.html",
        {
            "tasks": tasks,
            "areas": user_settings.areas or [],
            "current_area": area or "",
            "current_priority": priority or "",
            "current_status": status or "",
        },
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
async def task_new(request: Request, session: AsyncSession = Depends(get_session)):
    user_settings = await get_settings(session)
    return templates.TemplateResponse(
        request,
        "tasks/form.html",
        {
            "task": None,
            "areas": user_settings.areas or [],
            "editing": False,
        },
    )


@router.post("", response_class=HTMLResponse)
async def task_create(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    tags_raw = form.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    # Collect subtasks
    subtasks = []
    i = 0
    while True:
        key = f"subtask_{i}"
        val = form.get(key)
        if val is None:
            break
        if val.strip():
            subtasks.append(SubtaskCreate(title=val.strip(), position=i))
        i += 1

    data = TaskCreate(
        title=form.get("title", "").strip(),
        description=form.get("description", "").strip() or None,
        area=form.get("area", "").strip() or None,
        priority=form.get("priority", "none"),
        due_at=_parse_dt(form.get("due_at")),
        scheduled_at=_parse_dt(form.get("scheduled_at")),
        time_estimate_minutes=int(form.get("time_estimate_minutes")) if form.get("time_estimate_minutes") else None,
        tags=tags,
        subtasks=subtasks,
        source="manual",
    )

    batch_id = str(uuid.uuid4())
    await create_task(session, data, batch_id)
    await session.commit()

    return await _undo_redirect(session, "/web/tasks", f'Task "{data.title}" created')


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


@router.get("/{task_id}/edit", response_class=HTMLResponse)
async def task_edit(request: Request, task_id: int, session: AsyncSession = Depends(get_session)):
    task = await get_task(session, task_id)
    if not task:
        return RedirectResponse(url="/web/tasks", status_code=303)

    user_settings = await get_settings(session)
    return templates.TemplateResponse(
        request,
        "tasks/form.html",
        {
            "task": task,
            "areas": user_settings.areas or [],
            "editing": True,
        },
    )


@router.post("/{task_id}", response_class=HTMLResponse)
async def task_update(
    request: Request,
    task_id: int,
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    tags_raw = form.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    subtasks = []
    i = 0
    while True:
        key = f"subtask_{i}"
        val = form.get(key)
        if val is None:
            break
        if val.strip():
            subtasks.append(SubtaskCreate(title=val.strip(), position=i))
        i += 1

    data = TaskUpdate(
        title=form.get("title", "").strip(),
        description=form.get("description", "").strip() or None,
        area=form.get("area", "").strip() or None,
        priority=form.get("priority", "none"),
        status=form.get("status", "to_do"),
        due_at=_parse_dt(form.get("due_at")),
        scheduled_at=_parse_dt(form.get("scheduled_at")),
        time_estimate_minutes=int(form.get("time_estimate_minutes")) if form.get("time_estimate_minutes") else None,
        tags=tags,
        subtasks=subtasks,
    )

    batch_id = str(uuid.uuid4())
    await update_task(session, task_id, data, batch_id)
    await session.commit()

    return await _undo_redirect(session, "/web/tasks", f'Task "{data.title}" updated')


# ---------------------------------------------------------------------------
# Quick actions (HTMX)
# ---------------------------------------------------------------------------


@router.post("/{task_id}/complete", response_class=HTMLResponse)
async def task_complete(request: Request, task_id: int, session: AsyncSession = Depends(get_session)):
    batch_id = str(uuid.uuid4())
    task = await complete_task(session, task_id, batch_id)
    await session.commit()

    if task and _is_htmx(request):
        return templates.TemplateResponse(request, "tasks/_task_row.html", {"task": task})
    return await _undo_redirect(session, "/web/tasks", "Task completed")


@router.post("/{task_id}/delete", response_class=HTMLResponse)
async def task_delete(request: Request, task_id: int, session: AsyncSession = Depends(get_session)):
    batch_id = str(uuid.uuid4())
    await delete_task(session, task_id, batch_id)
    await session.commit()

    if _is_htmx(request):
        return HTMLResponse("")
    return await _undo_redirect(session, "/web/tasks", "Task deleted")
