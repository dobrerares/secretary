import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from secretary.config.settings import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Secretary starting up...")

    # Run Alembic migrations (handles both fresh and existing DBs)
    from secretary.db.session import engine

    try:
        from alembic.config import Config
        from alembic import command
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations applied.")
    except Exception:
        logger.warning("Alembic migration failed, falling back to create_all", exc_info=True)
        from secretary.db.base import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Seed settings row if missing
    from secretary.db.session import async_session_factory
    from secretary.db.models import Settings as SettingsModel
    from sqlalchemy import select

    async with async_session_factory() as session:
        result = await session.execute(select(SettingsModel).where(SettingsModel.id == 1))
        if result.scalar_one_or_none() is None:
            session.add(SettingsModel(id=1))
            await session.commit()

    # Start Telegram bot
    from secretary.bot.setup import start_bot, stop_bot

    await start_bot(app)

    # Start scheduler
    from secretary.scheduler.setup import start_scheduler, stop_scheduler

    await start_scheduler()

    logger.info("Secretary ready.")
    yield

    logger.info("Secretary shutting down...")
    await stop_scheduler()
    await stop_bot()
    await engine.dispose()


app = FastAPI(title="Secretary", version="0.1.0", lifespan=lifespan)

# Web UI
from secretary.web.app import router as web_router, TokenAuthMiddleware  # noqa: E402

app.add_middleware(TokenAuthMiddleware)
app.include_router(web_router, prefix="/web")


# Webhook route for Telegram (only active in webhook mode)
if settings.bot_mode == "webhook":
    from fastapi import Request

    from secretary.bot.setup import telegram_webhook_handler

    @app.post("/webhook/telegram")
    async def webhook_telegram(request: Request):
        return await telegram_webhook_handler(request)


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})
