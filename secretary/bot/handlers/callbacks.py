"""Callback query handlers for inline keyboard buttons."""

import logging
import uuid

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.bot.formatters import format_task
from secretary.bot.keyboards import confirm_keyboard, undo_keyboard
from secretary.core.actions import get_last_batch_id, undo_batch
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
            await callback.message.edit_text(callback.message.text + f"\n\n\u21a9 Undone ({count} action(s)).")
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
# Approve / Reject Proposed actions
#
# Callback data format (UUID-keyed, no list-index lookup):
#
#   apr:<inbox_item_id>:<action_id>     approve a single Proposed action
#   rej:<inbox_item_id>:<action_id>     reject a single Proposed action
#   rejall:<inbox_item_id>              reject every pending Proposed action
#
# Logic lives in secretary.core.inbox; these handlers are thin
# controllers that route by action_id and render the result.
# ---------------------------------------------------------------------------


def _parse_apr_rej(data: str) -> tuple[int, str] | None:
    """Parse ``apr:<inbox_id>:<action_id>`` / ``rej:...`` callback data.

    Returns ``(inbox_item_id, action_id)`` or ``None`` if malformed.
    """
    parts = data.split(":", 2)
    if len(parts) < 3 or not parts[1].isdigit():
        return None
    return int(parts[1]), parts[2]


@router.callback_query(F.data.startswith("apr:"))
async def cb_approve_action(callback: CallbackQuery, session: AsyncSession) -> None:
    """Approve a single Proposed action by its UUID action_id."""
    parsed = _parse_apr_rej(callback.data or "")
    if parsed is None:
        await callback.answer("Invalid action.", show_alert=True)
        return
    inbox_item_id, action_id = parsed

    try:
        result = await inbox_crud.approve_action(session, inbox_item_id, action_id)
    except Exception:
        logger.exception("Failed to approve action %s on item %s", action_id, inbox_item_id)
        await callback.message.edit_text("Failed to execute this action.")
        await callback.answer()
        return

    if result is None:
        await callback.message.edit_text("This suggestion has expired.")
        await callback.answer()
        return

    await session.commit()

    item = await inbox_crud.get_inbox_item(session, inbox_item_id)
    batch_id = item.batch_id if item else None

    original_text = callback.message.text or callback.message.html_text or ""
    if "error" in result.result:
        await callback.message.edit_text(
            f"{original_text}\n\n\u26a0\ufe0f <b>Error:</b> {result.result['error']}",
            parse_mode="HTML",
        )
        await callback.answer("Action failed.", show_alert=True)
        return

    keyboard = undo_keyboard(batch_id) if batch_id else None
    await callback.message.edit_text(
        f"{original_text}\n\n\u2705 <b>Approved</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer("Action approved!")


@router.callback_query(F.data.startswith("rej:"))
async def cb_reject_action(callback: CallbackQuery, session: AsyncSession) -> None:
    """Reject a single Proposed action by its UUID action_id."""
    parsed = _parse_apr_rej(callback.data or "")
    if parsed is None:
        await callback.answer("Invalid action.", show_alert=True)
        return
    inbox_item_id, action_id = parsed

    ok = await inbox_crud.reject_action(session, inbox_item_id, action_id)
    await session.commit()

    if not ok:
        await callback.message.edit_text("This suggestion has expired.")
        await callback.answer()
        return

    original_text = callback.message.text or callback.message.html_text or ""
    await callback.message.edit_text(
        f"{original_text}\n\n\u274c <b>Rejected</b>",
        parse_mode="HTML",
    )
    await callback.answer("Action rejected.")


@router.callback_query(F.data.startswith("rejall:"))
async def cb_reject_item(callback: CallbackQuery, session: AsyncSession) -> None:
    """Reject every pending Proposed action on an inbox item."""
    parts = (callback.data or "").split(":", 1)
    if len(parts) < 2 or not parts[1].isdigit():
        await callback.answer("Invalid action.", show_alert=True)
        return
    inbox_item_id = int(parts[1])

    ok = await inbox_crud.reject_item(session, inbox_item_id)
    await session.commit()

    if not ok:
        await callback.message.edit_text("This item has expired.")
        await callback.answer()
        return

    original_text = callback.message.text or callback.message.html_text or ""
    await callback.message.edit_text(
        f"{original_text}\n\n\u274c <b>All suggestions rejected</b>",
        parse_mode="HTML",
    )
    await callback.answer("Item rejected.")
