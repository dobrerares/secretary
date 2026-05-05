"""Catch-all message handler for natural language AI processing.

Lowest-priority handler — runs only when no slash command matches. The
heavy lifting lives in :mod:`secretary.ai.conversation` (LLM loop +
decide) and :mod:`secretary.core.inbox` (state machine). This module is
a thin controller: receive message → delegate → render the
ProcessResult as Telegram messages.
"""

import logging

from aiogram import Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.conversation import ProcessResult, process_message
from secretary.bot.formatters import format_proposal, format_status_report

logger = logging.getLogger(__name__)

router = Router()


def _suggestion_keyboard(inbox_item_id: int, action_id: str) -> InlineKeyboardMarkup:
    """Build [Approve] [Reject] buttons keyed by Proposed action UUID."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Approve", callback_data=f"apr:{inbox_item_id}:{action_id}"),
                InlineKeyboardButton(text="Reject", callback_data=f"rej:{inbox_item_id}:{action_id}"),
            ]
        ]
    )


def _undo_keyboard(batch_id: str) -> InlineKeyboardMarkup:
    """Build [Undo] keyboard for an auto-executed action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Undo", callback_data=f"undo:{batch_id}"),
            ]
        ]
    )


async def _render(message: Message, result: ProcessResult, *, surface_executed: bool) -> None:
    """Render a ProcessResult to the Telegram chat: AI reply, auto-executed
    status reports (unless silent mode suppressed them), and one suggestion
    card per Proposed action."""
    if result.response_text:
        await message.answer(result.response_text, parse_mode="HTML")

    for action in result.proposed:
        await message.answer(
            format_proposal(action),
            reply_markup=_suggestion_keyboard(result.item.id, action["action_id"]),
            parse_mode="HTML",
        )

    if surface_executed:
        for action in result.executed:
            if action.get("silent"):
                continue
            await message.answer(
                format_status_report(action),
                reply_markup=_undo_keyboard(action["batch_id"]),
                parse_mode="HTML",
            )


@router.message()
async def handle_chat_message(message: Message, session: AsyncSession) -> None:
    """Process a natural-language message through the inbox state machine."""
    if not message.text:
        return

    text = message.text.strip()
    if not text:
        return

    try:
        result = await process_message(session, text, source="chat")
    except Exception:
        logger.exception("AI processing failed for message: %s", text[:100])
        await session.commit()
        await message.answer(
            "Sorry, I couldn't process that right now. You can still use slash commands like /addtask or /help."
        )
        return

    await session.commit()
    await _render(message, result, surface_executed=True)
