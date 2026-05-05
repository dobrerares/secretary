"""Tests for core CRUD and undo system."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from secretary.core.actions import get_recent_actions, undo_action, undo_batch
from secretary.core.events import create_event, delete_event, get_event, update_event
from secretary.core.schemas import EventCreate, EventUpdate, TaskCreate, TaskFilter, TaskUpdate
from secretary.core.tasks import complete_task, create_task, delete_task, get_task, list_tasks, update_task


def batch() -> str:
    return str(uuid.uuid4())


# --- Task CRUD ---


@pytest.mark.asyncio
async def test_create_task(session):
    task = await create_task(session, TaskCreate(title="Test task", area="UBB", priority="high"), batch())
    await session.commit()
    assert task.id is not None
    assert task.title == "Test task"
    assert task.area == "UBB"
    assert task.priority == "high"
    assert task.status == "to_do"


@pytest.mark.asyncio
async def test_create_task_with_subtasks_and_tags(session):
    from secretary.core.schemas import SubtaskCreate

    data = TaskCreate(
        title="Complex task",
        subtasks=[SubtaskCreate(title="Step 1"), SubtaskCreate(title="Step 2")],
        tags=["exam", "urgent"],
    )
    task = await create_task(session, data, batch())
    await session.commit()

    loaded = await get_task(session, task.id)
    assert len(loaded.subtasks) == 2
    assert loaded.subtasks[0].title == "Step 1"
    assert len(loaded.tags) == 2
    assert {t.name for t in loaded.tags} == {"exam", "urgent"}


@pytest.mark.asyncio
async def test_update_task(session):
    task = await create_task(session, TaskCreate(title="Original"), batch())
    await session.commit()

    bid = batch()
    updated = await update_task(session, task.id, TaskUpdate(title="Updated", priority="urgent"), bid)
    await session.commit()

    assert updated.title == "Updated"
    assert updated.priority == "urgent"


@pytest.mark.asyncio
async def test_complete_task(session):
    task = await create_task(session, TaskCreate(title="Do it"), batch())
    await session.commit()

    completed = await complete_task(session, task.id, batch())
    await session.commit()

    assert completed.status == "done"


@pytest.mark.asyncio
async def test_delete_task(session):
    task = await create_task(session, TaskCreate(title="Delete me"), batch())
    await session.commit()

    result = await delete_task(session, task.id, batch())
    await session.commit()

    assert result is True
    assert await get_task(session, task.id) is None


@pytest.mark.asyncio
async def test_list_tasks_filters(session):
    await create_task(session, TaskCreate(title="UBB task", area="UBB"), batch())
    await create_task(session, TaskCreate(title="Personal task", area="Personal"), batch())
    await create_task(session, TaskCreate(title="Done task", status="done"), batch())
    await session.commit()

    # Default: excludes done
    all_active = await list_tasks(session)
    assert len(all_active) == 2

    # Filter by area
    ubb = await list_tasks(session, TaskFilter(area="UBB"))
    assert len(ubb) == 1
    assert ubb[0].title == "UBB task"

    # Include done
    done = await list_tasks(session, TaskFilter(status="done"))
    assert len(done) == 1


# --- Event CRUD ---


@pytest.mark.asyncio
async def test_create_event(session):
    now = datetime.now(timezone.utc)
    data = EventCreate(title="Meeting", start_at=now, end_at=now + timedelta(hours=1))
    event = await create_event(session, data, batch())
    await session.commit()

    assert event.id is not None
    assert event.title == "Meeting"
    assert event.calendar_source == "internal"


@pytest.mark.asyncio
async def test_update_event(session):
    now = datetime.now(timezone.utc)
    event = await create_event(
        session, EventCreate(title="Old title", start_at=now, end_at=now + timedelta(hours=1)), batch()
    )
    await session.commit()

    updated = await update_event(session, event.id, EventUpdate(title="New title"), batch())
    await session.commit()

    assert updated.title == "New title"


@pytest.mark.asyncio
async def test_delete_event(session):
    now = datetime.now(timezone.utc)
    event = await create_event(
        session, EventCreate(title="Delete me", start_at=now, end_at=now + timedelta(hours=1)), batch()
    )
    await session.commit()

    assert await delete_event(session, event.id, batch()) is True
    await session.commit()
    assert await get_event(session, event.id) is None


# --- Undo ---


@pytest.mark.asyncio
async def test_undo_create(session):
    bid = batch()
    task = await create_task(session, TaskCreate(title="Undo me"), bid)
    await session.commit()

    actions = await get_recent_actions(session)
    assert len(actions) == 1
    assert actions[0].action_type == "create"

    result = await undo_action(session, actions[0].id)
    await session.commit()

    assert result is True
    assert await get_task(session, task.id) is None


@pytest.mark.asyncio
async def test_undo_update(session):
    task = await create_task(session, TaskCreate(title="Original", priority="low"), batch())
    await session.commit()

    bid = batch()
    await update_task(session, task.id, TaskUpdate(title="Changed", priority="high"), bid)
    await session.commit()

    actions = await get_recent_actions(session, limit=1)
    result = await undo_action(session, actions[0].id)
    await session.commit()

    assert result is True
    task = await get_task(session, task.id)
    assert task.title == "Original"
    assert task.priority == "low"


@pytest.mark.asyncio
async def test_undo_delete(session):
    task = await create_task(session, TaskCreate(title="Restore me"), batch())
    await session.commit()
    task_id = task.id

    bid = batch()
    await delete_task(session, task_id, bid)
    await session.commit()

    assert await get_task(session, task_id) is None

    actions = await get_recent_actions(session, limit=1)
    result = await undo_action(session, actions[0].id)
    await session.commit()

    assert result is True
    restored = await get_task(session, task_id)
    assert restored is not None
    assert restored.title == "Restore me"


@pytest.mark.asyncio
async def test_undo_batch(session):
    bid = batch()
    t1 = await create_task(session, TaskCreate(title="Task 1"), bid)
    t2 = await create_task(session, TaskCreate(title="Task 2"), bid)
    await session.commit()

    count = await undo_batch(session, bid)
    await session.commit()

    assert count == 2
    assert await get_task(session, t1.id) is None
    assert await get_task(session, t2.id) is None


@pytest.mark.asyncio
async def test_undo_idempotent(session):
    bid = batch()
    await create_task(session, TaskCreate(title="Once"), bid)
    await session.commit()

    actions = await get_recent_actions(session)
    assert await undo_action(session, actions[0].id) is True
    await session.commit()
    # Second undo should fail (already undone)
    assert await undo_action(session, actions[0].id) is False
