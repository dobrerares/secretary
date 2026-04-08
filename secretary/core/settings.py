"""User settings operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from secretary.core.schemas import SettingsUpdate
from secretary.db.models import Settings


async def get_settings(session: AsyncSession) -> Settings:
    result = await session.execute(select(Settings).where(Settings.id == 1))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = Settings(id=1)
        session.add(settings)
        await session.flush()
    return settings


async def update_settings(session: AsyncSession, data: SettingsUpdate) -> Settings:
    settings = await get_settings(session)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, key, value)
    await session.flush()
    return settings
