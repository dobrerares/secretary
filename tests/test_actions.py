"""Tests for the Action seam (`secretary.core.actions`).

The Action seam concentrates reversibility for Root entities (Task, Event).
Each Root entity has a Snapshot — the canonical "one card" used by both
ActionLog storage and the AI tool result. Subtasks and tags are children
that ride inside their root's Snapshot; they are not Root entities.
"""

import uuid
from datetime import datetime, timezone

import pytest


def batch() -> str:
    return str(uuid.uuid4())


# --- Public API surface ---


def test_public_api_is_importable():
    """The Action seam must expose its full public API from a single module."""
    from secretary.core.actions import (
        get_last_batch_id,
        get_recent_actions,
        log_create,
        log_delete,
        log_update,
        make_snapshot,
        undo_action,
        undo_batch,
    )

    # All must be callable
    assert callable(make_snapshot)
    assert callable(log_create)
    assert callable(log_update)
    assert callable(log_delete)
    assert callable(undo_action)
    assert callable(undo_batch)
    assert callable(get_recent_actions)
    assert callable(get_last_batch_id)


# --- Registry coverage (Root entities only) ---


def test_records_registry_lists_only_root_entities():
    """The internal `_RECORDS` registry must hold task and event only.

    Subtasks and tags are children that ride inside a Root entity's
    Snapshot; they do not get their own registry entry.
    """
    from secretary.core.actions import _RECORDS

    assert set(_RECORDS.keys()) == {"task", "event"}
    for entity_type, record in _RECORDS.items():
        # (snapshot, recreate, restore) — three callables
        assert len(record) == 3
        snapshot_fn, recreate_fn, restore_fn = record
        assert callable(snapshot_fn)
        assert callable(recreate_fn)
        assert callable(restore_fn)


@pytest.mark.asyncio
async def test_make_snapshot_unsupported_entity_raises(session):
    """Calling make_snapshot on a non-Root entity must fail loudly."""
    from secretary.core.actions import make_snapshot

    with pytest.raises((KeyError, ValueError, TypeError)):
        # subtask is not a Root entity — it rides inside a Task snapshot.
        make_snapshot("subtask", object())


# --- Snapshot round-trip property ---


@pytest.mark.asyncio
async def test_task_snapshot_round_trip(session):
    """For any Task t: recreate(snapshot(t)) yields a Task with equal
    meaningful fields, including children (subtasks, tags)."""
    from secretary.core.actions import _RECORDS, make_snapshot
    from secretary.core.schemas import SubtaskCreate, TaskCreate
    from secretary.core.tasks import create_task, get_task

    data = TaskCreate(
        title="Round-trip me",
        description="desc",
        area="UBB",
        priority="high",
        status="to_do",
        due_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        scheduled_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        time_estimate_minutes=30,
        subtasks=[SubtaskCreate(title="Step A"), SubtaskCreate(title="Step B")],
        tags=["alpha", "beta"],
    )
    original = await create_task(session, data, batch())
    await session.commit()

    snap = make_snapshot("task", original)

    # Delete the original, then recreate via the registry's recreate fn.

    await session.delete(original)
    await session.commit()

    _, recreate_fn, _ = _RECORDS["task"]
    await recreate_fn(session, snap)
    await session.commit()

    restored = await get_task(session, snap["id"])
    assert restored is not None
    assert restored.title == "Round-trip me"
    assert restored.description == "desc"
    assert restored.area == "UBB"
    assert restored.priority == "high"
    assert restored.status == "to_do"
    assert restored.due_at == datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    assert restored.time_estimate_minutes == 30
    assert {s.title for s in restored.subtasks} == {"Step A", "Step B"}
    assert {t.name for t in restored.tags} == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_event_snapshot_round_trip(session):
    """For any Event e: recreate(snapshot(e)) yields an Event with equal
    meaningful fields."""
    from secretary.core.actions import _RECORDS, make_snapshot
    from secretary.core.events import create_event, get_event
    from secretary.core.schemas import EventCreate

    start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    data = EventCreate(
        title="Round-trip event",
        description="desc",
        area="Work",
        start_at=start,
        end_at=end,
        location="Room A",
        is_all_day=False,
    )
    original = await create_event(session, data, batch())
    await session.commit()

    snap = make_snapshot("event", original)

    await session.delete(original)
    await session.commit()

    _, recreate_fn, _ = _RECORDS["event"]
    await recreate_fn(session, snap)
    await session.commit()

    restored = await get_event(session, snap["id"])
    assert restored is not None
    assert restored.title == "Round-trip event"
    assert restored.description == "desc"
    assert restored.area == "Work"
    assert restored.start_at == start
    assert restored.end_at == end
    assert restored.location == "Room A"
    assert restored.is_all_day is False


# --- Undo of update reapplies children (the latent bug fix) ---


@pytest.mark.asyncio
async def test_undo_update_restores_tags(session):
    """Undoing an update Action must restore the Snapshot's tags exactly.

    This catches the latent bug at action_log.py:240 where _restore_fields
    skipped 'tags' (and 'subtasks').
    """
    from secretary.core.actions import get_recent_actions, undo_action
    from secretary.core.schemas import TaskCreate, TaskUpdate
    from secretary.core.tasks import create_task, get_task, update_task

    # Original has two tags
    data = TaskCreate(title="Tagged", tags=["alpha", "beta"])
    task = await create_task(session, data, batch())
    await session.commit()

    # Update changes the tags entirely
    await update_task(session, task.id, TaskUpdate(tags=["gamma"]), batch())
    await session.commit()

    loaded = await get_task(session, task.id)
    assert {t.name for t in loaded.tags} == {"gamma"}

    # Undo the update — tags must roll back to {alpha, beta}
    actions = await get_recent_actions(session, limit=1)
    assert actions[0].action_type == "update"
    assert await undo_action(session, actions[0].id) is True
    await session.commit()

    restored = await get_task(session, task.id)
    assert {t.name for t in restored.tags} == {"alpha", "beta"}


@pytest.mark.asyncio
async def test_undo_update_restores_subtasks(session):
    """Undoing an update Action must restore the Snapshot's subtasks."""
    from secretary.core.actions import get_recent_actions, undo_action
    from secretary.core.schemas import SubtaskCreate, TaskCreate, TaskUpdate
    from secretary.core.tasks import create_task, get_task, update_task

    # Original has two subtasks
    data = TaskCreate(
        title="With subtasks",
        subtasks=[SubtaskCreate(title="Step 1"), SubtaskCreate(title="Step 2")],
    )
    task = await create_task(session, data, batch())
    await session.commit()

    # Update replaces them with a single subtask
    await update_task(
        session,
        task.id,
        TaskUpdate(subtasks=[SubtaskCreate(title="Replacement")]),
        batch(),
    )
    await session.commit()

    loaded = await get_task(session, task.id)
    assert [s.title for s in loaded.subtasks] == ["Replacement"]

    # Undo — must restore Step 1 and Step 2
    actions = await get_recent_actions(session, limit=1)
    assert actions[0].action_type == "update"
    assert await undo_action(session, actions[0].id) is True
    await session.commit()

    restored = await get_task(session, task.id)
    assert {s.title for s in restored.subtasks} == {"Step 1", "Step 2"}


# --- log_create / log_update / log_delete behaviour through the seam ---


@pytest.mark.asyncio
async def test_log_create_records_after_snapshot(session):
    """log_create persists an Action with after_state=Snapshot, before_state=None."""
    from secretary.core.actions import get_recent_actions
    from secretary.core.schemas import TaskCreate
    from secretary.core.tasks import create_task

    bid = batch()
    task = await create_task(session, TaskCreate(title="Logged"), bid)
    await session.commit()

    actions = await get_recent_actions(session, limit=1)
    assert len(actions) == 1
    a = actions[0]
    assert a.action_type == "create"
    assert a.entity_type == "task"
    assert a.entity_id == task.id
    assert a.before_state is None
    assert a.after_state is not None
    assert a.after_state["title"] == "Logged"
    assert a.batch_id == bid


@pytest.mark.asyncio
async def test_log_delete_records_before_snapshot(session):
    """log_delete persists an Action with before_state=Snapshot, after_state=None."""
    from secretary.core.actions import get_recent_actions
    from secretary.core.schemas import TaskCreate
    from secretary.core.tasks import create_task, delete_task

    task = await create_task(session, TaskCreate(title="Doomed", tags=["x"]), batch())
    await session.commit()

    bid = batch()
    await delete_task(session, task.id, bid)
    await session.commit()

    actions = await get_recent_actions(session, limit=1)
    a = actions[0]
    assert a.action_type == "delete"
    assert a.entity_type == "task"
    assert a.entity_id == task.id
    assert a.after_state is None
    assert a.before_state is not None
    assert a.before_state["title"] == "Doomed"
    assert a.before_state["tags"] == ["x"]


@pytest.mark.asyncio
async def test_make_snapshot_returns_serializable_dict(session):
    """The Snapshot is "one shape, two jobs" — JSON-storable for ActionLog
    and consumable as the AI tool result. It must be a dict with the
    entity's id."""
    from secretary.core.actions import make_snapshot
    from secretary.core.schemas import TaskCreate
    from secretary.core.tasks import create_task, get_task

    task = await create_task(session, TaskCreate(title="Snap"), batch())
    await session.commit()
    loaded = await get_task(session, task.id)

    snap = make_snapshot("task", loaded)
    assert isinstance(snap, dict)
    assert snap["id"] == task.id
    assert snap["title"] == "Snap"
