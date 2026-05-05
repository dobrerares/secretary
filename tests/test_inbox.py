"""Tests for the Inbox state machine (`secretary.core.inbox`).

The inbox owns capture, attachment of executed and proposed actions,
individual approval and rejection of proposed actions, and auto-resolution
when every action has been decided. Each Proposed action carries a stable
UUID `action_id` so callbacks can refer to it without depending on list
index.

Vocabulary (from CONTEXT.md):

- **Proposed action** — a single tool call awaiting user decision,
  identified by a stable UUID `action_id`. Lifecycle:
  ``pending → approved | rejected``. When all proposed actions for an
  inbox item are decided, the item auto-resolves to ``processed`` (or
  ``rejected`` if all were rejected). Approval triggers execution under
  the inbox item's original ``batch_id``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from secretary.core.inbox import (
    ApprovalResult,
    approve_action,
    attach_actions,
    capture,
    reject_action,
    reject_item,
)
from secretary.db.models import ActionLog, Task


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


def test_public_api_is_importable():
    """The Inbox state machine must expose its full public API from one module."""
    from secretary.core.inbox import (
        ApprovalResult,
        approve_action,
        attach_actions,
        capture,
        reject_action,
        reject_item,
    )

    assert callable(capture)
    assert callable(attach_actions)
    assert callable(approve_action)
    assert callable(reject_action)
    assert callable(reject_item)
    # ApprovalResult is a dataclass — instances should be constructible.
    result = ApprovalResult(action_id="x", tool="t", result={}, item_status="processed")
    assert result.action_id == "x"


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_creates_pending_item(session):
    """capture() persists a new InboxItem with status='pending'."""
    item = await capture(session, raw_text="Buy milk tomorrow", source="chat")

    assert item.id is not None
    assert item.raw_text == "Buy milk tomorrow"
    assert item.source == "chat"
    assert item.status == "pending"


@pytest.mark.asyncio
async def test_capture_supports_voice_and_quick_add_sources(session):
    """capture() accepts the canonical inbox sources."""
    voice = await capture(session, raw_text="hello", source="voice")
    quick = await capture(session, raw_text="note", source="quick_add")

    assert voice.source == "voice"
    assert quick.source == "quick_add"


# ---------------------------------------------------------------------------
# attach_actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_actions_with_no_proposed_marks_processed(session):
    """An item with executed actions only and no proposed flips to processed."""
    item = await capture(session, raw_text="auto stuff", source="chat")
    batch_id = str(uuid.uuid4())

    item = await attach_actions(
        session,
        item,
        executed=[{"tool": "create_task", "args": {"title": "x"}}],
        proposed=[],
        batch_id=batch_id,
    )

    assert item.status == "processed"
    assert item.batch_id == batch_id
    # No proposed actions stored when none were proposed.
    assert not item.proposed_actions


@pytest.mark.asyncio
async def test_attach_actions_with_proposed_marks_proposed_and_assigns_uuids(session):
    """An item with proposed actions flips to proposed; each proposed action
    gets a fresh UUID action_id and starts in the pending state."""
    item = await capture(session, raw_text="ask first", source="chat")
    batch_id = str(uuid.uuid4())

    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[
            {"tool": "create_task", "args": {"title": "A"}},
            {"tool": "create_task", "args": {"title": "B"}},
        ],
        batch_id=batch_id,
    )

    assert item.status == "proposed"
    assert item.batch_id == batch_id
    assert isinstance(item.proposed_actions, list)
    assert len(item.proposed_actions) == 2

    ids: set[str] = set()
    for entry in item.proposed_actions:
        assert _is_uuid(entry["action_id"])
        assert entry["status"] == "pending"
        assert entry["tool"] == "create_task"
        assert "args" in entry
        ids.add(entry["action_id"])
    # action_ids must be unique per item.
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_attach_actions_preserves_proposed_metadata(session):
    """attach_actions() preserves caller-provided metadata (e.g. reason) on
    each proposed action so the suggestion card can render the explanation
    from the approval policy."""
    item = await capture(session, raw_text="needs reason", source="chat")
    batch_id = str(uuid.uuid4())

    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "X"}, "reason": "auto-approve off"}],
        batch_id=batch_id,
    )

    assert item.proposed_actions[0]["reason"] == "auto-approve off"


# ---------------------------------------------------------------------------
# approve_action — happy path + batch_id continuity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_action_runs_tool_under_item_batch_id(session):
    """Approving a Proposed action must run the tool through the dispatcher
    under the inbox item's stored batch_id, so undo-batch reverts the
    whole proposal as one unit."""
    item = await capture(session, raw_text="x", source="chat")
    batch_id = str(uuid.uuid4())

    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "Buy milk"}}],
        batch_id=batch_id,
    )
    action_id = item.proposed_actions[0]["action_id"]

    result = await approve_action(session, item.id, action_id)

    # Returns an ApprovalResult reflecting the tool result + new item status.
    assert isinstance(result, ApprovalResult)
    assert result.action_id == action_id
    assert result.tool == "create_task"
    assert "result" in result.result  # dispatcher wraps in {"result": ...}

    # The Action seam logged the create under the item's batch_id.
    rows = (await session.execute(select(ActionLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].batch_id == item.batch_id == batch_id

    # The proposed action is now approved; the item auto-resolved.
    refreshed = item.proposed_actions[0]
    assert refreshed["status"] == "approved"
    assert result.item_status == "processed"
    assert item.status == "processed"


@pytest.mark.asyncio
async def test_approve_action_returns_none_for_unknown_id(session):
    """Looking up a missing action_id returns None — caller renders 'expired'."""
    item = await capture(session, raw_text="x", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "X"}}],
        batch_id=str(uuid.uuid4()),
    )

    result = await approve_action(session, item.id, str(uuid.uuid4()))
    assert result is None


@pytest.mark.asyncio
async def test_approve_action_returns_none_for_unknown_item(session):
    """Looking up an unknown inbox_item returns None."""
    result = await approve_action(session, 9999, str(uuid.uuid4()))
    assert result is None


# ---------------------------------------------------------------------------
# reject_action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_action_marks_status_rejected(session):
    """reject_action() flips the matching proposed action to rejected and
    returns True. The Action seam stays untouched (rejection is workflow
    state, not a Root-entity operation)."""
    item = await capture(session, raw_text="nope", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "drop me"}}],
        batch_id=str(uuid.uuid4()),
    )
    action_id = item.proposed_actions[0]["action_id"]

    ok = await reject_action(session, item.id, action_id)
    assert ok is True

    assert item.proposed_actions[0]["status"] == "rejected"

    # No Tasks were created.
    tasks = (await session.execute(select(Task))).scalars().all()
    assert tasks == []

    # No Actions were logged.
    rows = (await session.execute(select(ActionLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_reject_action_returns_false_for_unknown_id(session):
    """Rejecting a missing action_id is a no-op returning False."""
    item = await capture(session, raw_text="x", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "X"}}],
        batch_id=str(uuid.uuid4()),
    )
    ok = await reject_action(session, item.id, str(uuid.uuid4()))
    assert ok is False


# ---------------------------------------------------------------------------
# Auto-resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_resolution_when_last_proposed_decided(session):
    """When the last pending proposed action is decided, the inbox item
    auto-resolves: processed if any approved, rejected if all rejected."""
    item = await capture(session, raw_text="multi", source="chat")
    batch_id = str(uuid.uuid4())

    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[
            {"tool": "create_task", "args": {"title": "A"}},
            {"tool": "create_task", "args": {"title": "B"}},
        ],
        batch_id=batch_id,
    )
    a_id = item.proposed_actions[0]["action_id"]
    b_id = item.proposed_actions[1]["action_id"]

    # First decision: still proposed (one pending remains).
    result = await approve_action(session, item.id, a_id)
    assert result is not None
    assert item.status == "proposed"
    assert result.item_status == "proposed"

    # Last decision: auto-resolves to processed (one approved).
    result = await approve_action(session, item.id, b_id)
    assert result is not None
    assert result.item_status == "processed"
    assert item.status == "processed"


@pytest.mark.asyncio
async def test_auto_resolution_all_rejected_marks_item_rejected(session):
    """If every proposed action is rejected, the item resolves to rejected."""
    item = await capture(session, raw_text="all bad", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[
            {"tool": "create_task", "args": {"title": "A"}},
            {"tool": "create_task", "args": {"title": "B"}},
        ],
        batch_id=str(uuid.uuid4()),
    )
    a_id = item.proposed_actions[0]["action_id"]
    b_id = item.proposed_actions[1]["action_id"]

    await reject_action(session, item.id, a_id)
    assert item.status == "proposed"  # one still pending

    await reject_action(session, item.id, b_id)
    assert item.status == "rejected"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_action_is_idempotent(session):
    """Approving an already-decided action is a no-op: no second tool run,
    no extra ActionLog row, and the returned ApprovalResult reflects current
    state."""
    item = await capture(session, raw_text="idem", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "Once"}}],
        batch_id=str(uuid.uuid4()),
    )
    action_id = item.proposed_actions[0]["action_id"]

    first = await approve_action(session, item.id, action_id)
    assert first is not None
    assert item.proposed_actions[0]["status"] == "approved"

    rows_before = (await session.execute(select(ActionLog))).scalars().all()
    tasks_before = (await session.execute(select(Task))).scalars().all()

    second = await approve_action(session, item.id, action_id)
    # Idempotent: still returns an ApprovalResult, not None.
    assert second is not None
    assert second.action_id == action_id

    rows_after = (await session.execute(select(ActionLog))).scalars().all()
    tasks_after = (await session.execute(select(Task))).scalars().all()
    assert len(rows_after) == len(rows_before)
    assert len(tasks_after) == len(tasks_before)


@pytest.mark.asyncio
async def test_reject_action_is_idempotent(session):
    """Rejecting an already-decided action is a no-op returning True."""
    item = await capture(session, raw_text="idem rej", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "Once"}}],
        batch_id=str(uuid.uuid4()),
    )
    action_id = item.proposed_actions[0]["action_id"]

    assert await reject_action(session, item.id, action_id) is True
    assert await reject_action(session, item.id, action_id) is True
    assert item.proposed_actions[0]["status"] == "rejected"


# ---------------------------------------------------------------------------
# reject_item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_item_marks_all_pending_actions_rejected(session):
    """reject_item() rejects every pending proposed action and flips the
    item to rejected."""
    item = await capture(session, raw_text="all", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[
            {"tool": "create_task", "args": {"title": "A"}},
            {"tool": "create_task", "args": {"title": "B"}},
        ],
        batch_id=str(uuid.uuid4()),
    )

    ok = await reject_item(session, item.id)
    assert ok is True
    assert item.status == "rejected"
    for entry in item.proposed_actions:
        assert entry["status"] == "rejected"


@pytest.mark.asyncio
async def test_reject_item_is_idempotent_when_already_decided(session):
    """reject_item() leaves already-decided actions alone; calling it again
    on a fully decided item still returns without error."""
    item = await capture(session, raw_text="settled", source="chat")
    item = await attach_actions(
        session,
        item,
        executed=[],
        proposed=[{"tool": "create_task", "args": {"title": "A"}}],
        batch_id=str(uuid.uuid4()),
    )
    action_id = item.proposed_actions[0]["action_id"]

    # Approve the only action — item auto-resolves to processed.
    await approve_action(session, item.id, action_id)
    assert item.status == "processed"

    # reject_item on a processed item changes nothing structurally; the
    # already-approved action stays approved.
    await reject_item(session, item.id)
    assert item.proposed_actions[0]["status"] == "approved"


@pytest.mark.asyncio
async def test_reject_item_returns_false_for_unknown_item(session):
    """Unknown item_id returns False."""
    assert await reject_item(session, 9999) is False
