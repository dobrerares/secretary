"""Action history web routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.action_log import get_recent_actions, undo_action, undo_batch
from secretary.db.models import ActionLog
from secretary.db.session import get_session
from secretary.web.app import templates

router = APIRouter(prefix="/history", tags=["web-history"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@router.get("", response_class=HTMLResponse)
async def history_list(request: Request, session: AsyncSession = Depends(get_session)):
    # Get all recent actions (including undone) for display
    result = await session.execute(
        select(ActionLog).order_by(ActionLog.created_at.desc()).limit(50)
    )
    actions = list(result.scalars().all())

    return templates.TemplateResponse(request, "history.html", {
        "actions": actions,
    })


@router.post("/{action_id}/undo", response_class=HTMLResponse)
async def history_undo(request: Request, action_id: int, session: AsyncSession = Depends(get_session)):
    success = await undo_action(session, action_id)
    await session.commit()

    if _is_htmx(request):
        if success:
            # Re-fetch the action to show updated state
            result = await session.execute(select(ActionLog).where(ActionLog.id == action_id))
            action = result.scalar_one_or_none()
            if action:
                return templates.TemplateResponse(request, "partials/_history_row.html", {
                    "action": action,
                })
        return HTMLResponse("")

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/web/history", status_code=303)


@router.post("/batch/{batch_id}/undo", response_class=HTMLResponse)
async def history_undo_batch(request: Request, batch_id: str, session: AsyncSession = Depends(get_session)):
    count = await undo_batch(session, batch_id)
    await session.commit()

    if _is_htmx(request):
        # Return refreshed action list
        result = await session.execute(
            select(ActionLog).order_by(ActionLog.created_at.desc()).limit(50)
        )
        actions = list(result.scalars().all())
        return templates.TemplateResponse(request, "partials/_history_table.html", {
            "actions": actions,
        })

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/web/history", status_code=303)
