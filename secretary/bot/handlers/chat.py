"""Catch-all message handler for natural language AI processing.

This is the lowest-priority handler — runs only when no slash command matches.
Routes messages through the AI layer and presents suggestions via inline keyboards.
"""

import logging
import uuid

from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.conversation import process_message
from secretary.core.inbox import create_inbox_item
from secretary.core.schemas import InboxItemCreate
from secretary.core.settings import get_settings

logger = logging.getLogger(__name__)

router = Router()


def _suggestion_keyboard(inbox_item_id: int, action_index: int) -> InlineKeyboardMarkup:
    """Build [Approve] [Reject] keyboard for a proposed action."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Approve", callback_data=f"apr:{inbox_item_id}:{action_index}"),
        InlineKeyboardButton(text="Edit", callback_data=f"edt:{inbox_item_id}:{action_index}"),
        InlineKeyboardButton(text="Reject", callback_data=f"rej:{inbox_item_id}:{action_index}"),
    ]])


def _undo_keyboard(batch_id: str) -> InlineKeyboardMarkup:
    """Build [Undo] keyboard for an auto-executed action."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Undo", callback_data=f"undo:{batch_id}"),
    ]])


def _format_status_report(action: dict) -> str:
    """Format an auto-executed action as a status report line."""
    tool = action.get("tool", "unknown")
    args = action.get("args", {})

    labels = {
        "create_task": "Created task",
        "update_task": "Updated task",
        "complete_task": "Completed task",
        "delete_task": "Deleted task",
        "create_event": "Created event",
        "update_event": "Updated event",
        "delete_event": "Deleted event",
        "update_memory": "Remembered",
    }
    label = labels.get(tool, tool)

    parts = [f"\u2705 Auto-approved: {label}"]

    title = args.get("title") or args.get("fact")
    if title:
        parts[0] += f" '{title}'"

    if "due_at" in args:
        parts.append(f"Due: {args['due_at']}")
    if "start_at" in args:
        parts.append(f"Start: {args['start_at']}")
    if "area" in args:
        parts.append(f"Area: {args['area']}")

    return " \u2014 ".join(parts)


def _format_proposal(action: dict) -> str:
    """Format a proposed action as a readable suggestion card."""
    tool = action.get("tool", "unknown")
    args = action.get("args", {})

    # Determine emoji and action label
    labels = {
        "create_task": ("Create task", "\U0001f4cb"),
        "update_task": ("Update task", "\u270f\ufe0f"),
        "complete_task": ("Complete task", "\u2705"),
        "delete_task": ("Delete task", "\U0001f5d1"),
        "create_event": ("Create event", "\U0001f4c5"),
        "update_event": ("Update event", "\u270f\ufe0f"),
        "delete_event": ("Delete event", "\U0001f5d1"),
        "update_memory": ("Remember", "\U0001f9e0"),
    }
    label, emoji = labels.get(tool, (tool, "\u2753"))

    lines = [f"{emoji} <b>Suggestion: {label}</b>"]

    # Format key fields based on tool type
    if "title" in args:
        lines.append(f"  Title: {args['title']}")
    if "area" in args:
        lines.append(f"  Area: {args['area']}")
    if "priority" in args and args["priority"] != "none":
        lines.append(f"  Priority: {args['priority'].title()}")
    if "due_at" in args:
        lines.append(f"  Due: {args['due_at']}")
    if "start_at" in args:
        lines.append(f"  Start: {args['start_at']}")
    if "end_at" in args:
        lines.append(f"  End: {args['end_at']}")
    if "location" in args:
        lines.append(f"  Location: {args['location']}")
    if "description" in args and args["description"]:
        desc = args["description"][:100]
        lines.append(f"  Description: {desc}")
    if "fact" in args:
        lines.append(f"  Fact: {args['fact']}")
    if "task_id" in args:
        lines.append(f"  Task ID: {args['task_id']}")
    if "event_id" in args:
        lines.append(f"  Event ID: {args['event_id']}")

    return "\n".join(lines)


@router.message()
async def handle_chat_message(message: Message, session: AsyncSession) -> None:
    """Process natural language messages through the AI layer."""
    if not message.text:
        return

    text = message.text.strip()
    if not text:
        return

    # Create inbox item
    batch_id = str(uuid.uuid4())
    inbox_item = await create_inbox_item(
        session,
        InboxItemCreate(raw_text=text, source="chat"),
        batch_id=batch_id,
    )
    await session.flush()

    # Process through AI
    try:
        result = await process_message(session, text)
    except Exception:
        logger.exception("AI processing failed for message: %s", text[:100])
        await message.answer(
            "Sorry, I couldn't process that right now. "
            "You can still use slash commands like /addtask or /help."
        )
        await session.commit()
        return

    # Store proposed actions on the inbox item
    if result.proposed_actions:
        from secretary.core.inbox import update_proposed_actions
        await update_proposed_actions(session, inbox_item.id, result.proposed_actions)

    await session.commit()

    # Send the AI's text response (if any)
    if result.response_text:
        await message.answer(result.response_text, parse_mode="HTML")

    # Send suggestion cards for each proposed action
    for i, action in enumerate(result.proposed_actions):
        card_text = _format_proposal(action)
        keyboard = _suggestion_keyboard(inbox_item.id, i)
        await message.answer(card_text, reply_markup=keyboard, parse_mode="HTML")

    # Send status reports for auto-executed actions (unless silent mode)
    if result.executed_actions:
        user_settings = await get_settings(session)
        if user_settings.auto_approve_mode != "silent":
            for action in result.executed_actions:
                report_text = _format_status_report(action)
                keyboard = _undo_keyboard(action["batch_id"])
                await message.answer(report_text, reply_markup=keyboard, parse_mode="HTML")
