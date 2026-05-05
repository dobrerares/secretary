"""Task tools — the five Tool entries that operate on Task root entities."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.tools._types import Tool, ToolCategory
from secretary.core.actions import make_snapshot
from secretary.core.schemas import (
    ListTasksArgs,
    TaskCompleteArgs,
    TaskCreate,
    TaskCreateArgs,
    TaskDeleteArgs,
    TaskFilter,
    TaskUpdate,
    TaskUpdateArgs,
)
from secretary.core.tasks import (
    complete_task,
    create_task,
    delete_task,
    list_tasks,
    update_task,
)


def _serialize_task(task) -> dict:
    return make_snapshot("task", task)


# ---------------------------------------------------------------------------
# Executors — each takes (session, validated args, batch_id) and returns
# either {"result": ...} or {"error": ...}.
# ---------------------------------------------------------------------------


async def _create_task(session: AsyncSession, args: TaskCreateArgs, batch_id: str) -> dict:
    # TaskCreateArgs is an alias for TaskCreate, but the LLM never sets
    # `source` — pin it to "ai_suggested" so the provenance is clear.
    data = TaskCreate(**{**args.model_dump(), "source": "ai_suggested"})
    task = await create_task(session, data, batch_id)
    return {"result": _serialize_task(task)}


async def _update_task(session: AsyncSession, args: TaskUpdateArgs, batch_id: str) -> dict:
    payload = args.model_dump(exclude_unset=True, exclude={"task_id"})
    data = TaskUpdate(**payload)
    task = await update_task(session, args.task_id, data, batch_id)
    if task is None:
        return {"error": f"Task {args.task_id} not found"}
    return {"result": _serialize_task(task)}


async def _complete_task(session: AsyncSession, args: TaskCompleteArgs, batch_id: str) -> dict:
    task = await complete_task(session, args.task_id, batch_id)
    if task is None:
        return {"error": f"Task {args.task_id} not found"}
    return {"result": _serialize_task(task)}


async def _delete_task(session: AsyncSession, args: TaskDeleteArgs, batch_id: str) -> dict:
    deleted = await delete_task(session, args.task_id, batch_id)
    if not deleted:
        return {"error": f"Task {args.task_id} not found"}
    return {"result": {"deleted": True, "task_id": args.task_id}}


async def _list_tasks(session: AsyncSession, args: ListTasksArgs, batch_id: str) -> dict:
    payload = args.model_dump(exclude_unset=True)
    # Pydantic's `overdue: bool | None` may surface as None — drop it so
    # TaskFilter's default (False) wins.
    if payload.get("overdue") is None:
        payload.pop("overdue", None)
    filters = TaskFilter(**payload) if payload else None
    tasks = await list_tasks(session, filters)
    return {"result": [_serialize_task(t) for t in tasks]}


# ---------------------------------------------------------------------------
# Tool registrations
# ---------------------------------------------------------------------------


TASK_TOOLS = [
    Tool(
        name="create_task",
        description="Create a new task for the user.",
        args_schema=TaskCreateArgs,
        execute=_create_task,
        category=ToolCategory.WRITE,
    ),
    Tool(
        name="update_task",
        description="Update an existing task's fields.",
        args_schema=TaskUpdateArgs,
        execute=_update_task,
        category=ToolCategory.WRITE,
    ),
    Tool(
        name="complete_task",
        description="Mark a task as done.",
        args_schema=TaskCompleteArgs,
        execute=_complete_task,
        category=ToolCategory.WRITE,
    ),
    Tool(
        name="delete_task",
        description="Permanently delete a task.",
        args_schema=TaskDeleteArgs,
        execute=_delete_task,
        category=ToolCategory.DESTRUCTIVE_WRITE,
    ),
    Tool(
        name="list_tasks",
        description="List tasks with optional filters. Returns active tasks by default.",
        args_schema=ListTasksArgs,
        execute=_list_tasks,
        category=ToolCategory.READ,
    ),
]
