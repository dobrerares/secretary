from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "SECRETARY_", "env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Telegram
    telegram_bot_token: str = ""
    telegram_user_id: int = 0

    # Database
    database_url: str = "sqlite+aiosqlite:///data/secretary.db"

    # LLM
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""

    # Web UI
    web_auth_token: str = ""
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    # Whisper
    whisper_mode: str = "local"  # "local" or "cloud"
    whisper_model_size: str = "small"  # tiny/small/medium/large
    openai_api_key: str = ""  # for cloud whisper

    # Logging
    log_level: str = "INFO"

    # Bot mode
    bot_mode: str = "polling"  # "polling" or "webhook"
    webhook_url: str = ""

    # Calendar sync
    google_calendar_enabled: bool = False
    google_client_id: str = ""
    google_client_secret: str = ""
    caldav_url: str = ""
    caldav_username: str = ""
    caldav_password: str = ""
    calendar_sync_interval_minutes: int = 15


settings = Settings()


def reload_settings() -> None:
    """Re-read .env and update the global settings singleton in-place."""
    fresh = Settings()
    for field_name in Settings.model_fields:
        setattr(settings, field_name, getattr(fresh, field_name))
