"""Inbox state machine — capture, attach actions, approve / reject, auto-resolve.

This module owns the lifecycle of an InboxItem (PRD §5.1, §6.4, §7.4):

1. **capture** — persist a new InboxItem in ``pending``.
2. **attach_actions** — record what the AI did or proposed; flip the item
   to ``processed`` (no proposed actions) or ``proposed`` (something
   awaits user approval). Each Proposed action gets a stable UUID
   ``action_id`` here, so callbacks never refer to it by list index.
3. **approve_action / reject_action** — operate on a single Proposed
   action by ``action_id``. Approval runs the tool through the
   dispatcher under the inbox item's stored ``batch_id`` (so undo-batch
   reverts the whole proposal as one unit even when approved in pieces).
4. **reject_item** — bulk-reject every still-pending Proposed action.

Auto-resolution: whenever the last pending Proposed action is decided,
the item flips to ``processed`` (any approval) or ``rejected`` (none
approved) without explicit caller intervention.

Vocabulary (CONTEXT.md):

- **Proposed action** — a tool call awaiting user decision, identified
  by a UUID ``action_id``. Lifecycle: ``pending → approved | rejected``.
- **Batch** — a UUID grouping Actions that should undo together.
- **Tool**, **Tool category**, **Decision** — building blocks the
  approval gate works with; this module only consumes the result.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from secretary.ai.executor import execute_tool
from secretary.db.models import InboxItem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    """The outcome of approving a Proposed action.

    Returned by :func:`approve_action`. Bot and web controllers consume
    this to render feedback to the user — what happened, and where the
    parent inbox item now stands.
    """

    action_id: str
    tool: str
    # The dispatcher's return value: ``{"result": ...}`` on success or
    # ``{"error": ...}`` on failure / unknown tool.
    result: dict
    # The inbox item's status AFTER this approval — ``processed`` if any
    # action was approved and no pending remain, ``rejected`` if every
    # proposed action ended up rejected, ``proposed`` if more pending
    # actions remain on the item.
    item_status: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _proposed_actions(item: InboxItem) -> list[dict]:
    """Return the proposed_actions list (handles None / unexpected shapes)."""
    raw = item.proposed_actions
    if isinstance(raw, list):
        return raw
    return []


def _find_action(item: InboxItem, action_id: str) -> dict | None:
    """Return the Proposed action dict matching ``action_id`` (or None)."""
    for entry in _proposed_actions(item):
        if entry.get("action_id") == action_id:
            return entry
    return None


def _all_decided(actions: list[dict]) -> bool:
    return all(a.get("status") != "pending" for a in actions)


def _resolved_status(actions: list[dict]) -> str:
    """If at least one Proposed action was approved, the item is processed;
    otherwise (every action rejected) it is rejected."""
    if any(a.get("status") == "approved" for a in actions):
        return "processed"
    return "rejected"


async def _maybe_auto_resolve(session: AsyncSession, item: InboxItem) -> None:
    """If every Proposed action is decided, flip the item to its resolved
    status. No-op while any action is still pending."""
    actions = _proposed_actions(item)
    if not actions:
        return
    if not _all_decided(actions):
        return
    item.status = _resolved_status(actions)
    await session.flush()


def _mark_modified(item: InboxItem) -> None:
    """Tell SQLAlchemy the JSON column was mutated in place.

    The proposed_actions column is a JSON list; when we mutate a dict
    inside it, SQLAlchemy's change detection won't notice without help.
    """
    flag_modified(item, "proposed_actions")


# ---------------------------------------------------------------------------
# Public state-machine surface
# ---------------------------------------------------------------------------


async def capture(
    session: AsyncSession,
    raw_text: str,
    source: str = "chat",
) -> InboxItem:
    """Capture a new InboxItem in the ``pending`` state.

    The item carries no batch_id yet — :func:`attach_actions` records the
    AI run's batch_id once parsing is done.
    """
    item = InboxItem(raw_text=raw_text, source=source, status="pending")
    session.add(item)
    await session.flush()
    return item


async def attach_actions(
    session: AsyncSession,
    item: InboxItem,
    executed: list[dict],
    proposed: list[dict],
    batch_id: str,
) -> InboxItem:
    """Record what the AI did and what it wants the user to approve.

    ``executed`` lists actions that already ran (auto-execute mode); they
    are not stored on the item — their effects already exist in the
    ActionLog. ``proposed`` lists pending tool calls; each ``{tool, args,
    ...}`` entry is augmented with a fresh UUID ``action_id`` and a
    ``status="pending"`` field.

    Status transitions:
      - ``proposed`` non-empty → item.status = ``proposed``
      - ``proposed`` empty (only executed, or nothing at all) →
        item.status = ``processed``

    The item's ``batch_id`` is set if not already, so subsequent
    approvals (which run the tool fresh) share the original AI run's
    batch — undo-batch reverts auto-executed and approved actions
    together.
    """
    enriched: list[dict] = []
    for entry in proposed:
        action: dict = {
            "action_id": str(uuid.uuid4()),
            "tool": entry.get("tool", ""),
            "args": entry.get("args", {}) or {},
            "status": "pending",
        }
        # Preserve any extra metadata the caller wants on the suggestion
        # card — typically the ``reason`` from the approval Decision.
        for key, value in entry.items():
            if key not in action:
                action[key] = value
        enriched.append(action)

    item.proposed_actions = enriched if enriched else None
    if not item.batch_id:
        item.batch_id = batch_id
    item.status = "proposed" if enriched else "processed"
    await session.flush()
    return item


async def approve_action(
    session: AsyncSession,
    item_id: int,
    action_id: str,
) -> ApprovalResult | None:
    """Approve a single Proposed action.

    Looks up the inbox item and the Proposed action by ``action_id``,
    runs the tool through the dispatcher under the item's stored
    ``batch_id`` (so undo-batch can revert the whole proposal as one
    unit), and marks the Proposed action ``approved``. If every Proposed
    action is now decided, the item auto-resolves.

    Returns:
      - ``None`` if the inbox item or the action_id can't be found.
      - ``ApprovalResult`` reflecting the dispatcher's return value and
        the item's resulting status. If the action was already decided
        (no-op idempotency), ``result`` is empty and ``item_status`` is
        the current status.
    """
    item = await _get_item(session, item_id)
    if item is None:
        return None

    action = _find_action(item, action_id)
    if action is None:
        return None

    tool_name = action.get("tool", "")

    # Idempotency: already-decided actions are a no-op.
    if action.get("status") != "pending":
        return ApprovalResult(
            action_id=action_id,
            tool=tool_name,
            result={},
            item_status=item.status,
        )

    # Run the tool under the item's batch_id so the resulting Action(s)
    # share the original AI run's batch.
    arguments = action.get("args", {}) or {}
    batch_id = item.batch_id or str(uuid.uuid4())
    if not item.batch_id:
        # Defensive: every captured item should have had a batch_id
        # attached by attach_actions, but if a caller skipped that step
        # we still want a stable batch for the resulting Action seam.
        item.batch_id = batch_id
    result = await execute_tool(session, tool_name, arguments, batch_id)

    action["status"] = "approved"
    _mark_modified(item)
    await session.flush()

    await _maybe_auto_resolve(session, item)

    return ApprovalResult(
        action_id=action_id,
        tool=tool_name,
        result=result,
        item_status=item.status,
    )


async def reject_action(
    session: AsyncSession,
    item_id: int,
    action_id: str,
) -> bool:
    """Reject a single Proposed action.

    Returns ``True`` if the action exists (whether or not it changed
    state — already-decided actions are idempotent); ``False`` if the
    item or action_id is not found.
    """
    item = await _get_item(session, item_id)
    if item is None:
        return False

    action = _find_action(item, action_id)
    if action is None:
        return False

    if action.get("status") == "pending":
        action["status"] = "rejected"
        _mark_modified(item)
        await session.flush()
        await _maybe_auto_resolve(session, item)
    return True


async def reject_item(session: AsyncSession, item_id: int) -> bool:
    """Reject every still-pending Proposed action on an item.

    Returns ``True`` if the item exists (regardless of whether any
    action changed state); ``False`` if the item is not found.
    """
    item = await _get_item(session, item_id)
    if item is None:
        return False

    actions = _proposed_actions(item)
    changed = False
    for action in actions:
        if action.get("status") == "pending":
            action["status"] = "rejected"
            changed = True

    if actions:
        if changed:
            _mark_modified(item)
        # The item's own status reflects the resolved set: anything
        # approved keeps it processed, otherwise rejected.
        item.status = _resolved_status(actions)
    else:
        # Bare item with no proposed actions — explicit reject still
        # marks the item rejected (matches the legacy behavior).
        item.status = "rejected"

    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Read helpers (still used by /inbox command and the web list view)
# ---------------------------------------------------------------------------


async def list_pending(session: AsyncSession) -> list[InboxItem]:
    """Return inbox items still awaiting attention (``pending`` or
    ``proposed``), oldest first."""
    result = await session.execute(
        select(InboxItem)
        .where(InboxItem.status.in_(["pending", "proposed"]))
        .order_by(InboxItem.created_at.asc())
    )
    return list(result.scalars().all())


async def get_inbox_item(session: AsyncSession, item_id: int) -> InboxItem | None:
    """Fetch an inbox item by id (or None)."""
    return await _get_item(session, item_id)


async def _get_item(session: AsyncSession, item_id: int) -> InboxItem | None:
    result = await session.execute(select(InboxItem).where(InboxItem.id == item_id))
    return result.scalar_one_or_none()


__all__ = [
    "ApprovalResult",
    "approve_action",
    "attach_actions",
    "capture",
    "get_inbox_item",
    "list_pending",
    "reject_action",
    "reject_item",
]
