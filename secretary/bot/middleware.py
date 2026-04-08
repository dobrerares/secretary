"""Bot middleware: authentication and DB session injection."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from secretary.config.settings import settings
from secretary.db.session import async_session_factory

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Silently drop updates from unauthorized users."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Extract user from the update
        user = data.get("event_from_user")
        if user is None:
            # No user attached (e.g., channel posts) -- drop silently
            return None

        if settings.telegram_user_id and user.id != settings.telegram_user_id:
            logger.debug("Ignoring message from unauthorized user %s", user.id)
            return None

        return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    """Create an async DB session per update and inject into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                return result
            except Exception:
                await session.rollback()
                raise
