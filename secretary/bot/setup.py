"""Bot and Dispatcher setup, polling lifecycle management, webhook route."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update

from secretary.bot.middleware import AuthMiddleware, DbSessionMiddleware
from secretary.bot.handlers import callbacks, chat, events, system, tasks, voice
from secretary.config.settings import settings

logger = logging.getLogger(__name__)

# --- Dispatcher (stateless, safe to create at import time) ---

dp = Dispatcher(storage=MemoryStorage())

# Register middleware (outer = first to run)
dp.message.outer_middleware(AuthMiddleware())
dp.callback_query.outer_middleware(AuthMiddleware())
dp.message.middleware(DbSessionMiddleware())
dp.callback_query.middleware(DbSessionMiddleware())

# Register routers
dp.include_router(system.router)
dp.include_router(tasks.router)
dp.include_router(events.router)
dp.include_router(callbacks.router)
dp.include_router(voice.router)
# Chat handler must be last -- catch-all for non-command messages
dp.include_router(chat.router)

# --- Bot instance (created lazily to avoid token validation at import) ---

bot: Bot | None = None


def _create_bot() -> Bot:
    """Create the Bot instance. Requires a valid token."""
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


# --- Polling task management ---

_polling_task: asyncio.Task | None = None


async def _run_polling() -> None:
    """Internal: run bot polling loop."""
    logger.info("Starting Telegram bot polling...")
    try:
        await dp.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        logger.info("Bot polling cancelled.")
    except Exception:
        logger.exception("Bot polling crashed.")


async def start_bot(app=None) -> None:
    """Start the bot as a background asyncio task.

    In ``polling`` mode (default) a background task polls Telegram for updates.
    In ``webhook`` mode the webhook URL is registered with Telegram and incoming
    updates are expected to arrive via the ``/webhook/telegram`` FastAPI route.
    """
    global _polling_task, bot

    token = settings.telegram_bot_token
    if not token or token.startswith("your-") or ":" not in token:
        logger.warning("SECRETARY_TELEGRAM_BOT_TOKEN not configured -- bot will not start.")
        return

    bot = _create_bot()

    # Register slash command hints with Telegram so they appear in the / menu
    from aiogram.types import BotCommand

    await bot.set_my_commands(
        [
            BotCommand(command="addtask", description="Add a new task"),
            BotCommand(command="tasks", description="List tasks (today, overdue, area)"),
            BotCommand(command="done", description="Mark a task complete"),
            BotCommand(command="edit", description="Edit a task"),
            BotCommand(command="delete", description="Delete a task"),
            BotCommand(command="addevent", description="Add a new event"),
            BotCommand(command="agenda", description="Today's agenda"),
            BotCommand(command="inbox", description="Pending inbox items"),
            BotCommand(command="undo", description="Undo the last action"),
            BotCommand(command="sync", description="Sync calendars now"),
            BotCommand(command="briefing", description="Get your daily briefing"),
            BotCommand(command="settings", description="View settings"),
            BotCommand(command="help", description="Show all commands"),
        ]
    )

    if settings.bot_mode == "webhook":
        webhook_url = settings.webhook_url.rstrip("/") + "/webhook/telegram"
        await bot.set_webhook(webhook_url)
        logger.info("Telegram webhook set to %s -- updates handled via FastAPI route.", webhook_url)
    else:
        _polling_task = asyncio.create_task(_run_polling())
        logger.info("Telegram bot polling task started.")


async def stop_bot() -> None:
    """Cancel the polling task and shut down the bot."""
    global _polling_task, bot

    if _polling_task is not None:
        logger.info("Stopping Telegram bot...")
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
        _polling_task = None

    # Remove webhook if we were in webhook mode
    if bot is not None and settings.bot_mode == "webhook":
        try:
            await bot.delete_webhook()
        except Exception:
            logger.warning("Failed to delete webhook on shutdown")

    # Close bot session
    if bot is not None:
        await bot.session.close()
        bot = None
    logger.info("Telegram bot stopped.")


# --- Webhook route (mounted by FastAPI when bot_mode == "webhook") ---


async def telegram_webhook_handler(request) -> dict:
    """FastAPI route handler for incoming Telegram webhook updates.

    Mount this at ``/webhook/telegram``.  Telegram POSTs JSON-encoded
    ``Update`` objects which are fed directly into the aiogram dispatcher.
    """

    if bot is None:
        return {"ok": False, "error": "bot not initialised"}

    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot=bot, update=update)
    return {"ok": True}
