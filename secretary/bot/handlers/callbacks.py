"""Callback query handlers for inline keyboard buttons."""

import json
import logging
import uuid

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.bot.formatters import format_task
from secretary.bot.keyboards import (
    confirm_keyboard,
    edit_field_keyboard,
    undo_keyboard,
)
from secretary.bot.states import EditTaskStates
from secretary.core.action_log import get_last_batch_id, undo_batch
from secretary.core import tasks as task_crud
from secretary.core import inbox as inbox_crud

logger = logging.getLogger(__name__)

router = Router()


# ---------------------------------------------------------------------------
# Confirm Yes/No  (callback data: cfm:y:<action>:<id> / cfm:n:<action>:<id>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("cfm:y:"))
async def cb_confirm_yes(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":")
    # cfm:y:action:entity_id
    action = parts[2] if len(parts) > 2 else ""
    entity_ref = parts[3] if len(parts) > 3 else ""

    if action == "del" and entity_ref.isdigit():
        task_id = int(entity_ref)
        batch_id = str(uuid.uuid4())
        deleted = await task_crud.delete_task(session, task_id, batch_id)
        await session.commit()
        if deleted:
            await callback.message.edit_text(
                "\ud83d\uddd1 Task deleted.",
                reply_markup=undo_keyboard(batch_id),
            )
        else:
            await callback.message.edit_text("Task not found or already deleted.")

    elif action == "undo":
        # entity_ref is the truncated batch_id -- find the actual batch
        last_batch = await get_last_batch_id(session)
        if last_batch and last_batch.startswith(entity_ref):
            count = await undo_batch(session, last_batch)
            await session.commit()
            if count > 0:
                await callback.message.edit_text(f"\u21a9 Undone {count} action(s).")
            else:
                await callback.message.edit_text("Nothing to undo (may have expired).")
        else:
            await callback.message.edit_text("Could not find the action to undo.")

    await callback.answer()


@router.callback_query(F.data.startswith("cfm:n:"))
async def cb_confirm_no(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Cancelled.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Undo button  (callback data: undo:<short_batch_id>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("undo:"))
async def cb_undo(callback: CallbackQuery, session: AsyncSession) -> None:
    short_id = callback.data.split(":", 1)[1]

    # Find the matching batch
    last_batch = await get_last_batch_id(session)
    if last_batch and last_batch.startswith(short_id):
        count = await undo_batch(session, last_batch)
        await session.commit()
        if count > 0:
            await callback.message.edit_text(
                callback.message.text + f"\n\n\u21a9 Undone ({count} action(s))."
            )
        else:
            await callback.answer("Nothing to undo (may have expired).", show_alert=True)
    else:
        await callback.answer("Could not find the action to undo.", show_alert=True)

    await callback.answer()


# ---------------------------------------------------------------------------
# Task quick actions  (done:<id>, del:<id>, edit:<id>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("done:"))
async def cb_task_done(callback: CallbackQuery, session: AsyncSession) -> None:
    task_id_str = callback.data.split(":", 1)[1]
    if not task_id_str.isdigit():
        await callback.answer("Invalid task ID.", show_alert=True)
        return

    task_id = int(task_id_str)
    batch_id = str(uuid.uuid4())
    task = await task_crud.complete_task(session, task_id, batch_id)
    await session.commit()

    if task:
        await callback.message.edit_text(
            f"\u2705 Task completed!\n\n{format_task(task)}",
            reply_markup=undo_keyboard(batch_id),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text("Task not found.")

    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def cb_task_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    task_id_str = callback.data.split(":", 1)[1]
    if not task_id_str.isdigit():
        await callback.answer("Invalid task ID.", show_alert=True)
        return

    task_id = int(task_id_str)
    task = await task_crud.get_task(session, task_id)
    if not task:
        await callback.message.edit_text("Task not found.")
        await callback.answer()
        return

    await callback.message.edit_text(
        f"\u26a0\ufe0f Delete this task?\n\n{format_task(task)}",
        reply_markup=confirm_keyboard("del", task_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit:"))
async def cb_task_edit(callback: CallbackQuery, session: AsyncSession) -> None:
    from aiogram.fsm.context import FSMContext

    task_id_str = callback.data.split(":", 1)[1]
    if not task_id_str.isdigit():
        await callback.answer("Invalid task ID.", show_alert=True)
        return

    task_id = int(task_id_str)
    task = await task_crud.get_task(session, task_id)
    if not task:
        await callback.message.edit_text("Task not found.")
        await callback.answer()
        return

    # We cannot directly set FSM state from a callback without the state object.
    # Instead, show the edit keyboard and tell the user to use /edit <id>.
    await callback.message.edit_text(
        f"To edit this task, use:\n<code>/edit {task_id}</code>",
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Approve / Reject proposed actions  (apr:<inbox_id>:<idx>, rej:<inbox_id>:<idx>)
# ---------------------------------------------------------------------------

@router.callback_query(F.data.startswith("apr:"))
async def cb_approve_action(callback: CallbackQuery, session: AsyncSession) -> None:
    """Approve a proposed action from a suggestion card."""
    parts = callback.data.split(":")
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Invalid action.", show_alert=True)
        return

    inbox_item_id = int(parts[1])
    action_index = int(parts[2])

    item = await inbox_crud.get_inbox_item(session, inbox_item_id)
    if not item or not item.proposed_actions:
        await callback.message.edit_text("This suggestion has expired.")
        await callback.answer()
        return

    actions = item.proposed_actions
    if action_index >= len(actions):
        await callback.message.edit_text("Invalid action index.")
        await callback.answer()
        return

    action = actions[action_index]
    tool_name = action.get("tool", "")
    arguments = action.get("args", {})

    # Execute the action
    batch_id = str(uuid.uuid4())
    try:
        from secretary.ai.executor import execute_tool
        result = await execute_tool(session, tool_name, arguments, batch_id)
    except Exception:
        logger.exception("Failed to execute approved action: %s", tool_name)
        await callback.message.edit_text("Failed to execute this action.")
        await callback.answer()
        return

    # Mark inbox item as processed
    await inbox_crud.process_inbox_item(session, inbox_item_id)
    await session.commit()

    # Update the suggestion card to show approval
    original_text = callback.message.text or callback.message.html_text or ""
    await callback.message.edit_text(
        f"{original_text}\n\n\u2705 <b>Approved</b>",
        reply_markup=undo_keyboard(batch_id),
        parse_mode="HTML",
    )
    await callback.answer("Action approved!")


@router.callback_query(F.data.startswith("edt:"))
async def cb_edit_action(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show proposed action details so the user can edit before approving."""
    parts = callback.data.split(":")
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await callback.answer("Invalid action.", show_alert=True)
        return

    inbox_item_id = int(parts[1])
    action_index = int(parts[2])

    item = await inbox_crud.get_inbox_item(session, inbox_item_id)
    if not item or not item.proposed_actions:
        await callback.message.edit_text("This suggestion has expired.")
        await callback.answer()
        return

    actions = item.proposed_actions
    if action_index >= len(actions):
        await callback.message.edit_text("Invalid action index.")
        await callback.answer()
        return

    action = actions[action_index]
    tool_name = action.get("tool", "unknown")
    arguments = action.get("args", {})

    # Format the action fields for editing review
    lines = [f"\u270f\ufe0f <b>Edit suggestion: {tool_name}</b>\n"]
    lines.append("<b>Current fields:</b>")
    for key, value in arguments.items():
        lines.append(f"  <b>{key}:</b> {value}")

    lines.append(
        "\nReply with changes, or use /addtask to create manually. "
        "The suggestion has been saved \u2014 use [Approve] when ready."
    )

    # Re-show the approve/reject keyboard so the user can approve after editing
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Approve", callback_data=f"apr:{inbox_item_id}:{action_index}"),
        InlineKeyboardButton(text="Reject", callback_data=f"rej:{inbox_item_id}:{action_index}"),
    ]])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rej:"))
async def cb_reject_action(callback: CallbackQuery, session: AsyncSession) -> None:
    """Reject a proposed action from a suggestion card."""
    parts = callback.data.split(":")
    if len(parts) < 3 or not parts[1].isdigit():
        await callback.answer("Invalid action.", show_alert=True)
        return

    inbox_item_id = int(parts[1])
    await inbox_crud.reject_inbox_item(session, inbox_item_id)
    await session.commit()

    original_text = callback.message.text or callback.message.html_text or ""
    await callback.message.edit_text(
        f"{original_text}\n\n\u274c <b>Rejected</b>",
        parse_mode="HTML",
    )
    await callback.answer("Action rejected.")
