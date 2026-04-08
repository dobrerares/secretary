"""Voice message handler -- transcribes audio and feeds it into the AI pipeline.

Registered *before* the catch-all chat handler so voice messages are intercepted
here rather than silently ignored.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid

from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.conversation import process_message
from secretary.config.settings import settings
from secretary.core.inbox import create_inbox_item
from secretary.core.schemas import InboxItemCreate
from secretary.transcription.audio import cleanup_temp_files, convert_ogg_to_wav
from secretary.transcription.base import get_transcriber

logger = logging.getLogger(__name__)

router = Router()


# --------------------------------------------------------------------------- #
# Helpers (mirrors chat.py for suggestion cards)
# --------------------------------------------------------------------------- #


def _suggestion_keyboard(inbox_item_id: int, action_index: int) -> InlineKeyboardMarkup:
    """Build [Approve] [Reject] keyboard for a proposed action."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Approve", callback_data=f"apr:{inbox_item_id}:{action_index}"),
        InlineKeyboardButton(text="Edit", callback_data=f"edt:{inbox_item_id}:{action_index}"),
        InlineKeyboardButton(text="Reject", callback_data=f"rej:{inbox_item_id}:{action_index}"),
    ]])


def _format_proposal(action: dict) -> str:
    """Format a proposed action as a readable suggestion card."""
    tool = action.get("tool", "unknown")
    args = action.get("args", {})

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


# --------------------------------------------------------------------------- #
# Voice handler
# --------------------------------------------------------------------------- #


@router.message(lambda msg: msg.voice is not None)
async def handle_voice_message(message: Message, session: AsyncSession) -> None:
    """Receive a voice note, transcribe it, then process through the AI layer."""
    bot = message.bot
    assert bot is not None

    voice = message.voice
    assert voice is not None

    # Prepare temp directory for audio files
    tmp_dir = tempfile.mkdtemp(prefix="secretary_voice_")
    ogg_path = os.path.join(tmp_dir, "voice.ogg")
    wav_path: str | None = None

    try:
        # 1. Download the voice file from Telegram
        file = await bot.get_file(voice.file_id)
        assert file.file_path is not None
        await bot.download_file(file.file_path, ogg_path)

        # 2. Convert OGG/Opus -> 16 kHz mono WAV
        wav_path = await convert_ogg_to_wav(ogg_path)

        # 3. Transcribe
        transcriber = get_transcriber(settings.whisper_mode)
        transcribed_text = await transcriber.transcribe(wav_path)

        if not transcribed_text.strip():
            await message.answer("I couldn't make out any words in that voice note.")
            return

        # 4. Echo transcription for transparency
        await message.answer(f"I heard: <i>{transcribed_text}</i>", parse_mode="HTML")

        # 5. Create inbox item with source="voice"
        batch_id = str(uuid.uuid4())
        inbox_item = await create_inbox_item(
            session,
            InboxItemCreate(raw_text=transcribed_text, source="voice"),
            batch_id=batch_id,
        )
        await session.flush()

        # 6. Feed transcribed text into the AI pipeline
        try:
            result = await process_message(session, transcribed_text)
        except Exception:
            logger.exception("AI processing failed for voice transcription: %s", transcribed_text[:100])
            await message.answer(
                "I transcribed your voice note but couldn't process it right now. "
                "You can still use slash commands like /addtask or /help."
            )
            await session.commit()
            return

        # 7. Store proposed actions on the inbox item
        if result.proposed_actions:
            from secretary.core.inbox import update_proposed_actions
            await update_proposed_actions(session, inbox_item.id, result.proposed_actions)

        await session.commit()

        # 8. Send the AI's text response
        if result.response_text:
            await message.answer(result.response_text, parse_mode="HTML")

        # 9. Send suggestion cards
        for i, action in enumerate(result.proposed_actions):
            card_text = _format_proposal(action)
            keyboard = _suggestion_keyboard(inbox_item.id, i)
            await message.answer(card_text, reply_markup=keyboard, parse_mode="HTML")

    except Exception:
        logger.exception("Voice message processing failed")
        await message.answer(
            "Sorry, I couldn't process that voice note. "
            "Please try again or send a text message instead."
        )
    finally:
        # 10. Clean up temp files
        files_to_clean = [ogg_path]
        if wav_path is not None:
            files_to_clean.append(wav_path)
        await cleanup_temp_files(*files_to_clean)
        # Remove the temp directory itself
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
