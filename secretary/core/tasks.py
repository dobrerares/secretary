"""Task CRUD operations.

CRUD here is thin: it persists the change and routes the
before/after bookkeeping through the Action seam in `core/actions`.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from secretary.core.actions import log_create, log_delete, log_update, make_snapshot
from secretary.core.schemas import TaskCreate, TaskFilter, TaskUpdate
from secretary.db.models import Subtask, Tag, Task, task_tags


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    result = await session.execute(
        select(Task).options(selectinload(Task.subtasks), selectinload(Task.tags)).where(Task.id == task_id)
    )
    return result.scalar_one_or_none()


async def list_tasks(session: AsyncSession, filters: TaskFilter | None = None) -> list[Task]:
    query = select(Task).options(selectinload(Task.subtasks), selectinload(Task.tags))

    if filters:
        if filters.area:
            query = query.where(Task.area == filters.area)
        if filters.priority:
            query = query.where(Task.priority == filters.priority)
        if filters.status:
            query = query.where(Task.status == filters.status)
        else:
            # By default, exclude done/cancelled
            query = query.where(Task.status.notin_(["done", "cancelled"]))
        if filters.due_before:
            query = query.where(Task.due_at <= filters.due_before)
        if filters.due_after:
            query = query.where(Task.due_at >= filters.due_after)
        if filters.overdue:
            now = datetime.now(timezone.utc)
            query = query.where(Task.due_at < now, Task.status.notin_(["done", "cancelled"]))
        if filters.tag:
            query = query.join(task_tags).join(Tag).where(Tag.name == filters.tag)
        if filters.search:
            query = query.where(Task.title.ilike(f"%{filters.search}%"))
    else:
        query = query.where(Task.status.notin_(["done", "cancelled"]))

    query = query.order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_task(session: AsyncSession, data: TaskCreate, batch_id: str) -> Task:
    task = Task(
        title=data.title,
        description=data.description,
        area=data.area,
        priority=data.priority,
        status=data.status,
        due_at=data.due_at,
        scheduled_at=data.scheduled_at,
        time_estimate_minutes=data.time_estimate_minutes,
        recurrence_rule=data.recurrence_rule,
        source=data.source,
        inbox_item_id=data.inbox_item_id,
    )
    session.add(task)
    await session.flush()

    # Add subtasks
    for i, st in enumerate(data.subtasks):
        subtask = Subtask(task_id=task.id, title=st.title, is_complete=st.is_complete, position=st.position or i)
        session.add(subtask)

    # Add tags via association table directly to avoid lazy load
    if data.tags:
        await session.flush()
        for tag_name in data.tags:
            tag = await _get_or_create_tag(session, tag_name)
            await session.execute(task_tags.insert().values(task_id=task.id, tag_id=tag.id))

    await session.flush()
    # Reload to get subtasks/tags with eager loading
    task = await get_task(session, task.id)

    await log_create(session, "task", task, batch_id)
    return task


async def update_task(session: AsyncSession, task_id: int, data: TaskUpdate, batch_id: str) -> Task | None:
    task = await get_task(session, task_id)
    if not task:
        return None

    before = make_snapshot("task", task)

    update_fields = data.model_dump(exclude_unset=True, exclude={"tags", "subtasks"})
    for key, value in update_fields.items():
        setattr(task, key, value)

    # Update tags if provided. We rewrite the association table directly
    # then expire the relationship so the next load is fresh — without this
    # the session's identity map shadows the raw write.
    if data.tags is not None:
        await session.execute(task_tags.delete().where(task_tags.c.task_id == task.id))
        for tag_name in data.tags:
            tag = await _get_or_create_tag(session, tag_name)
            await session.execute(task_tags.insert().values(task_id=task.id, tag_id=tag.id))
        session.expire(task, ["tags"])

    # Update subtasks if provided
    if data.subtasks is not None:
        for st in list(task.subtasks):
            await session.delete(st)
        await session.flush()
        for i, st in enumerate(data.subtasks):
            subtask = Subtask(task_id=task.id, title=st.title, is_complete=st.is_complete, position=st.position or i)
            session.add(subtask)
        session.expire(task, ["subtasks"])

    await session.flush()
    task = await get_task(session, task.id)

    await log_update(session, "task", before, task, batch_id)
    return task


async def complete_task(session: AsyncSession, task_id: int, batch_id: str) -> Task | None:
    task = await get_task(session, task_id)
    if not task:
        return None

    before = make_snapshot("task", task)
    task.status = "done"
    await session.flush()
    task = await get_task(session, task.id)

    await log_update(session, "task", before, task, batch_id)
    return task


async def delete_task(session: AsyncSession, task_id: int, batch_id: str) -> bool:
    task = await get_task(session, task_id)
    if not task:
        return False

    await log_delete(session, "task", task, batch_id)
    await session.delete(task)
    await session.flush()
    return True


async def _get_or_create_tag(session: AsyncSession, name: str) -> Tag:
    normalized = name.strip().lower()
    result = await session.execute(select(Tag).where(Tag.name == normalized))
    tag = result.scalar_one_or_none()
    if not tag:
        tag = Tag(name=normalized)
        session.add(tag)
        await session.flush()
    return tag
