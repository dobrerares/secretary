from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from secretary.config.settings import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level.upper() == "DEBUG",
    connect_args={"timeout": 30},
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session_factory() as session:
        yield session
