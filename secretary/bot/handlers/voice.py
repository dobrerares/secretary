"""Voice message handler -- transcribe audio and feed it into the AI pipeline.

Registered before the catch-all chat handler so voice messages are
intercepted here rather than silently ignored. Once we have transcript
text, the inbox flow is identical to text chat: delegate to
:func:`secretary.ai.conversation.process_message` with ``source="voice"``,
then render the ProcessResult.
"""

from __future__ import annotations

import logging
import os
import tempfile

from aiogram import Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.ai.conversation import ProcessResult, process_message
from secretary.bot.formatters import format_proposal, format_status_report
from secretary.config.settings import settings
from secretary.transcription.audio import cleanup_temp_files, convert_ogg_to_wav
from secretary.transcription.base import get_transcriber

logger = logging.getLogger(__name__)

router = Router()


def _suggestion_keyboard(inbox_item_id: int, action_id: str) -> InlineKeyboardMarkup:
    """Build [Approve] [Reject] buttons keyed by Proposed action UUID."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Approve", callback_data=f"apr:{inbox_item_id}:{action_id}"),
        InlineKeyboardButton(text="Reject", callback_data=f"rej:{inbox_item_id}:{action_id}"),
    ]])


def _undo_keyboard(batch_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Undo", callback_data=f"undo:{batch_id}"),
    ]])


async def _render(message: Message, result: ProcessResult) -> None:
    """Render a ProcessResult as Telegram messages (mirror of chat.py)."""
    if result.response_text:
        await message.answer(result.response_text, parse_mode="HTML")

    for action in result.proposed:
        await message.answer(
            format_proposal(action),
            reply_markup=_suggestion_keyboard(result.item.id, action["action_id"]),
            parse_mode="HTML",
        )

    for action in result.executed:
        if action.get("silent"):
            continue
        await message.answer(
            format_status_report(action),
            reply_markup=_undo_keyboard(action["batch_id"]),
            parse_mode="HTML",
        )


@router.message(lambda msg: msg.voice is not None)
async def handle_voice_message(message: Message, session: AsyncSession) -> None:
    """Receive a voice note, transcribe it, then run the inbox flow."""
    bot = message.bot
    assert bot is not None

    voice = message.voice
    assert voice is not None

    tmp_dir = tempfile.mkdtemp(prefix="secretary_voice_")
    ogg_path = os.path.join(tmp_dir, "voice.ogg")
    wav_path: str | None = None

    try:
        # 1. Download the voice file from Telegram.
        file = await bot.get_file(voice.file_id)
        assert file.file_path is not None
        await bot.download_file(file.file_path, ogg_path)

        # 2. Convert OGG/Opus -> 16 kHz mono WAV.
        wav_path = await convert_ogg_to_wav(ogg_path)

        # 3. Transcribe.
        transcriber = get_transcriber(settings.whisper_mode)
        transcribed_text = await transcriber.transcribe(wav_path)

        if not transcribed_text.strip():
            await message.answer("I couldn't make out any words in that voice note.")
            return

        # 4. Echo transcription for transparency.
        await message.answer(f"I heard: <i>{transcribed_text}</i>", parse_mode="HTML")

        # 5. Run the inbox flow with source="voice".
        try:
            result = await process_message(session, transcribed_text, source="voice")
        except Exception:
            logger.exception(
                "AI processing failed for voice transcription: %s",
                transcribed_text[:100],
            )
            await session.commit()
            await message.answer(
                "I transcribed your voice note but couldn't process it right now. "
                "You can still use slash commands like /addtask or /help."
            )
            return

        await session.commit()
        await _render(message, result)

    except Exception:
        logger.exception("Voice message processing failed")
        await message.answer(
            "Sorry, I couldn't process that voice note. "
            "Please try again or send a text message instead."
        )
    finally:
        files_to_clean = [ogg_path]
        if wav_path is not None:
            files_to_clean.append(wav_path)
        await cleanup_temp_files(*files_to_clean)
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
