"""Inbox web routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.inbox import list_pending, process_inbox_item, reject_inbox_item
from secretary.db.session import get_session
from secretary.web.app import templates

router = APIRouter(prefix="/inbox", tags=["web-inbox"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@router.get("", response_class=HTMLResponse)
async def inbox_list(request: Request, session: AsyncSession = Depends(get_session)):
    items = await list_pending(session)
    return templates.TemplateResponse(request, "inbox.html", {
        "items": items,
    })


@router.post("/{item_id}/approve", response_class=HTMLResponse)
async def inbox_approve(request: Request, item_id: int, session: AsyncSession = Depends(get_session)):
    await process_inbox_item(session, item_id)
    await session.commit()

    if _is_htmx(request):
        return HTMLResponse("")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/web/inbox", status_code=303)


@router.post("/{item_id}/reject", response_class=HTMLResponse)
async def inbox_reject(request: Request, item_id: int, session: AsyncSession = Depends(get_session)):
    await reject_inbox_item(session, item_id)
    await session.commit()

    if _is_htmx(request):
        return HTMLResponse("")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/web/inbox", status_code=303)
