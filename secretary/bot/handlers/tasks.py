"""Task-related command handlers: /addtask, /tasks, /done, /edit, /delete."""

import uuid
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.bot.formatters import format_task, format_task_list
from secretary.bot.keyboards import (
    area_keyboard,
    confirm_create_task_keyboard,
    edit_field_keyboard,
    priority_keyboard,
    undo_keyboard,
)
from secretary.bot.states import AddTaskStates, EditTaskStates
from secretary.core.schemas import TaskCreate, TaskFilter, TaskUpdate
from secretary.core.settings import get_settings as get_db_settings
from secretary.core import tasks as task_crud

router = Router()


# ---------------------------------------------------------------------------
# Date parsing helper
# ---------------------------------------------------------------------------


def _parse_date(text: str) -> datetime | None:
    """Parse natural date strings into UTC datetimes."""
    text = text.strip().lower()
    now = datetime.now(timezone.utc)
    today = now.replace(hour=23, minute=59, second=0, microsecond=0)

    if text in ("today",):
        return today
    if text in ("tomorrow", "tmr"):
        return today + timedelta(days=1)

    day_names = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }
    if text in day_names:
        target = day_names[text]
        current = now.weekday()
        delta = (target - current) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)

    # Try ISO-like formats
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# /addtask  -- FSM flow
# ---------------------------------------------------------------------------


@router.message(Command("addtask"))
async def cmd_addtask(message: Message, state: FSMContext, session: AsyncSession) -> None:
    # Check if title was provided inline:  /addtask Buy groceries
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        title = args[1].strip()
        await state.update_data(title=title)
        # Jump straight to area selection
        db_settings = await get_db_settings(session)
        areas = db_settings.areas or []
        if areas:
            await message.answer(
                f"Task: <b>{title}</b>\n\nSelect an area:",
                reply_markup=area_keyboard(areas),
                parse_mode="HTML",
            )
        else:
            await state.update_data(area=None)
            await message.answer(
                f"Task: <b>{title}</b>\n\nSelect priority:",
                reply_markup=priority_keyboard(),
                parse_mode="HTML",
            )
        await state.set_state(AddTaskStates.waiting_for_area)
        return

    await message.answer("What's the task title?")
    await state.set_state(AddTaskStates.waiting_for_title)


@router.message(AddTaskStates.waiting_for_title)
async def addtask_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    title = message.text.strip()
    if not title:
        await message.answer("Please enter a non-empty title.")
        return
    await state.update_data(title=title)

    db_settings = await get_db_settings(session)
    areas = db_settings.areas or []
    if areas:
        await message.answer(
            f"Task: <b>{title}</b>\n\nSelect an area:",
            reply_markup=area_keyboard(areas),
            parse_mode="HTML",
        )
        await state.set_state(AddTaskStates.waiting_for_area)
    else:
        await state.update_data(area=None)
        await message.answer("Select priority:", reply_markup=priority_keyboard())
        await state.set_state(AddTaskStates.waiting_for_priority)


@router.callback_query(AddTaskStates.waiting_for_area, F.data.startswith("area:"))
async def addtask_area_cb(callback: CallbackQuery, state: FSMContext) -> None:
    area = callback.data.split(":", 1)[1]
    if area == "__skip__":
        area = None
    await state.update_data(area=area)
    await callback.message.edit_text("Select priority:", reply_markup=priority_keyboard())
    await state.set_state(AddTaskStates.waiting_for_priority)
    await callback.answer()


@router.callback_query(AddTaskStates.waiting_for_priority, F.data.startswith("pri:"))
async def addtask_priority_cb(callback: CallbackQuery, state: FSMContext) -> None:
    priority = callback.data.split(":", 1)[1]
    if priority == "__skip__":
        priority = "none"
    await state.update_data(priority=priority)
    await callback.message.edit_text(
        "Enter a due date (e.g. <code>tomorrow</code>, <code>Friday</code>, <code>2026-04-15</code>) or /skip:",
        parse_mode="HTML",
    )
    await state.set_state(AddTaskStates.waiting_for_due)
    await callback.answer()


@router.message(AddTaskStates.waiting_for_due)
async def addtask_due(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if text.lower() in ("/skip", "skip", "-"):
        due_at = None
    else:
        due_at = _parse_date(text)
        if due_at is None:
            await message.answer(
                "Could not parse that date. Try formats like <code>tomorrow</code>, "
                "<code>Friday</code>, <code>2026-04-15</code>, or /skip.",
                parse_mode="HTML",
            )
            return

    await state.update_data(due_at=due_at.isoformat() if due_at else None)

    data = await state.get_data()
    due_str = due_at.strftime("%b %d, %Y") if due_at else "None"
    summary = (
        f"<b>New Task</b>\n"
        f"Title: {data['title']}\n"
        f"Area: {data.get('area') or 'None'}\n"
        f"Priority: {data.get('priority', 'none')}\n"
        f"Due: {due_str}\n\n"
        f"Create this task?"
    )
    await message.answer(summary, reply_markup=confirm_create_task_keyboard(), parse_mode="HTML")
    await state.set_state(AddTaskStates.waiting_for_confirm)


@router.callback_query(AddTaskStates.waiting_for_confirm, F.data == "tcr:yes")
async def addtask_confirm_yes(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    due_at = datetime.fromisoformat(data["due_at"]) if data.get("due_at") else None

    task_data = TaskCreate(
        title=data["title"],
        area=data.get("area"),
        priority=data.get("priority", "none"),
        due_at=due_at,
        source="chat",
    )
    batch_id = str(uuid.uuid4())
    task = await task_crud.create_task(session, task_data, batch_id)
    await session.commit()

    await callback.message.edit_text(
        f"\u2705 Task created!\n\n{format_task(task)}",
        reply_markup=undo_keyboard(batch_id),
        parse_mode="HTML",
    )
    await state.clear()
    await callback.answer()


@router.callback_query(AddTaskStates.waiting_for_confirm, F.data == "tcr:no")
async def addtask_confirm_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("\u274c Task creation cancelled.")
    await state.clear()
    await callback.answer()


# ---------------------------------------------------------------------------
# /tasks  -- list / filter
# ---------------------------------------------------------------------------


@router.message(Command("tasks"))
async def cmd_tasks(message: Message, session: AsyncSession) -> None:
    args = message.text.split(maxsplit=1)
    arg = args[1].strip().lower() if len(args) > 1 else ""

    filters = TaskFilter()
    label = "All active tasks"

    if arg in ("today",):
        now = datetime.now(timezone.utc)
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
        filters.due_before = end_of_day
        filters.due_after = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "Tasks due today"
    elif arg in ("overdue",):
        filters.overdue = True
        label = "Overdue tasks"
    elif arg in ("done", "completed"):
        filters.status = "done"
        label = "Completed tasks"
    elif arg in ("all",):
        # Show everything including done
        filters.status = None
        # But we need to override the default exclusion --
        # pass a status that includes everything by searching without filter
        filters = None
        label = "All tasks (including done)"
    elif arg:
        # Try as area name first, then as search term
        filters.area = arg
        label = f"Tasks in '{arg}'"

    task_list = await task_crud.list_tasks(session, filters)

    if not task_list and arg and arg not in ("today", "overdue", "done", "completed", "all"):
        # Retry as search term
        filters2 = TaskFilter(search=arg)
        task_list = await task_crud.list_tasks(session, filters2)
        if task_list:
            label = f"Tasks matching '{arg}'"

    text = f"<b>{label}</b>\n\n{format_task_list(task_list)}"
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# /done  -- mark task complete
# ---------------------------------------------------------------------------


@router.message(Command("done"))
async def cmd_done(message: Message, session: AsyncSession) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/done &lt;id or keyword&gt;</code>", parse_mode="HTML")
        return

    query = args[1].strip()

    # Try as numeric ID
    task = None
    if query.lstrip("#").isdigit():
        task_id = int(query.lstrip("#"))
        task = await task_crud.get_task(session, task_id)

    if task:
        batch_id = str(uuid.uuid4())
        task = await task_crud.complete_task(session, task.id, batch_id)
        await session.commit()
        await message.answer(
            f"\u2705 Task completed!\n\n{format_task(task)}",
            reply_markup=undo_keyboard(batch_id),
            parse_mode="HTML",
        )
        return

    # Try keyword search
    matches = await task_crud.list_tasks(session, TaskFilter(search=query))
    if not matches:
        await message.answer(f"No task found matching '{query}'.")
        return

    if len(matches) == 1:
        batch_id = str(uuid.uuid4())
        task = await task_crud.complete_task(session, matches[0].id, batch_id)
        await session.commit()
        await message.answer(
            f"\u2705 Task completed!\n\n{format_task(task)}",
            reply_markup=undo_keyboard(batch_id),
            parse_mode="HTML",
        )
        return

    # Multiple matches -- show disambiguation
    lines = ["Multiple tasks match. Use the exact ID:\n"]
    for t in matches[:10]:
        lines.append(f"  <code>/done {t.id}</code> - {t.title}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ---------------------------------------------------------------------------
# /edit  -- edit a task
# ---------------------------------------------------------------------------


@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().lstrip("#").isdigit():
        await message.answer("Usage: <code>/edit &lt;task_id&gt;</code>", parse_mode="HTML")
        return

    task_id = int(args[1].strip().lstrip("#"))
    task = await task_crud.get_task(session, task_id)
    if not task:
        await message.answer(f"Task #{task_id} not found.")
        return

    await state.update_data(edit_task_id=task_id)
    await message.answer(
        f"Editing: {format_task(task)}\n\nWhich field to edit?",
        reply_markup=edit_field_keyboard(task_id),
        parse_mode="HTML",
    )
    await state.set_state(EditTaskStates.waiting_for_field)


@router.callback_query(EditTaskStates.waiting_for_field, F.data.startswith("edf:"))
async def edit_field_cb(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    field = parts[1]

    if field == "cancel":
        await callback.message.edit_text("Edit cancelled.")
        await state.clear()
        await callback.answer()
        return

    field_map = {
        "title": "title",
        "area": "area",
        "pri": "priority",
        "due": "due_at",
        "desc": "description",
    }
    actual_field = field_map.get(field, field)
    await state.update_data(edit_field=actual_field)

    prompts = {
        "title": "Enter the new title:",
        "area": "Enter the new area (or 'none' to clear):",
        "priority": "Enter new priority (none/low/medium/high/urgent):",
        "due_at": "Enter new due date (e.g. tomorrow, 2026-04-15, or 'none' to clear):",
        "description": "Enter the new description (or 'none' to clear):",
    }
    await callback.message.edit_text(prompts.get(actual_field, f"Enter new value for {actual_field}:"))
    await state.set_state(EditTaskStates.waiting_for_value)
    await callback.answer()


@router.message(EditTaskStates.waiting_for_value)
async def edit_value(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    task_id = data["edit_task_id"]
    field = data["edit_field"]
    value = message.text.strip()

    update_data = {}
    if field == "due_at":
        if value.lower() in ("none", "clear", "-"):
            update_data["due_at"] = None
        else:
            parsed = _parse_date(value)
            if parsed is None:
                await message.answer("Could not parse date. Try again or send 'none'.")
                return
            update_data["due_at"] = parsed
    elif field == "priority":
        if value.lower() not in ("none", "low", "medium", "high", "urgent"):
            await message.answer("Priority must be one of: none, low, medium, high, urgent")
            return
        update_data["priority"] = value.lower()
    elif field in ("area", "description"):
        if value.lower() in ("none", "clear", "-"):
            update_data[field] = None
        else:
            update_data[field] = value
    else:
        update_data[field] = value

    batch_id = str(uuid.uuid4())
    task = await task_crud.update_task(session, task_id, TaskUpdate(**update_data), batch_id)
    await session.commit()

    if task:
        await message.answer(
            f"\u2705 Task updated!\n\n{format_task(task)}",
            reply_markup=undo_keyboard(batch_id),
            parse_mode="HTML",
        )
    else:
        await message.answer(f"Task #{task_id} not found.")

    await state.clear()


# ---------------------------------------------------------------------------
# /delete  -- delete a task
# ---------------------------------------------------------------------------


@router.message(Command("delete"))
async def cmd_delete(message: Message, session: AsyncSession) -> None:
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().lstrip("#").isdigit():
        await message.answer("Usage: <code>/delete &lt;task_id&gt;</code>", parse_mode="HTML")
        return

    task_id = int(args[1].strip().lstrip("#"))
    task = await task_crud.get_task(session, task_id)
    if not task:
        await message.answer(f"Task #{task_id} not found.")
        return

    from secretary.bot.keyboards import confirm_keyboard

    await message.answer(
        f"\u26a0\ufe0f Delete this task?\n\n{format_task(task)}",
        reply_markup=confirm_keyboard("del", task_id),
        parse_mode="HTML",
    )
