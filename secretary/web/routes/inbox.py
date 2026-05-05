"""Inbox web routes — mirror the bot handler shape over the inbox state machine."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.inbox import (
    approve_action,
    list_pending,
    reject_action,
    reject_item,
)
from secretary.db.session import get_session
from secretary.web.app import templates

router = APIRouter(prefix="/inbox", tags=["web-inbox"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _redirect_or_empty(request: Request) -> HTMLResponse | RedirectResponse:
    """HTMX requests want an empty body so the swap removes the row;
    classic form posts want a redirect back to the list view."""
    if _is_htmx(request):
        return HTMLResponse("")
    return RedirectResponse(url="/web/inbox", status_code=303)


@router.get("", response_class=HTMLResponse)
async def inbox_list(request: Request, session: AsyncSession = Depends(get_session)):
    """Render the list of inbox items still awaiting attention."""
    items = await list_pending(session)
    return templates.TemplateResponse(request, "inbox.html", {"items": items})


# ---------------------------------------------------------------------------
# Single-action endpoints (UUID action_id)
# ---------------------------------------------------------------------------


@router.post("/{item_id}/actions/{action_id}/approve", response_class=HTMLResponse)
async def inbox_approve_action(
    request: Request,
    item_id: int,
    action_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Approve a single Proposed action by its UUID."""
    await approve_action(session, item_id, action_id)
    await session.commit()
    return _redirect_or_empty(request)


@router.post("/{item_id}/actions/{action_id}/reject", response_class=HTMLResponse)
async def inbox_reject_action(
    request: Request,
    item_id: int,
    action_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Reject a single Proposed action by its UUID."""
    await reject_action(session, item_id, action_id)
    await session.commit()
    return _redirect_or_empty(request)


# ---------------------------------------------------------------------------
# Whole-item endpoints
# ---------------------------------------------------------------------------


@router.post("/{item_id}/approve", response_class=HTMLResponse)
async def inbox_approve_item(
    request: Request,
    item_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Approve every still-pending Proposed action on the item.

    Iterates the item's Proposed actions and approves each pending
    entry. Auto-resolution flips the item to processed once the last
    pending action runs.
    """
    from secretary.core.inbox import get_inbox_item  # local import to keep API stable

    item = await get_inbox_item(session, item_id)
    if item and item.proposed_actions:
        # Snapshot ids first so mutating proposed_actions during the
        # loop doesn't trip iteration.
        ids = [a.get("action_id") for a in item.proposed_actions if a.get("action_id")]
        for action_id in ids:
            await approve_action(session, item_id, action_id)
    await session.commit()
    return _redirect_or_empty(request)


@router.post("/{item_id}/reject", response_class=HTMLResponse)
async def inbox_reject_item(
    request: Request,
    item_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Reject every still-pending Proposed action on the item."""
    await reject_item(session, item_id)
    await session.commit()
    return _redirect_or_empty(request)
