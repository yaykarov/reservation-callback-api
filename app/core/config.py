"""Настройки приложения. Единственная точка чтения окружения (никаких os.getenv по коду)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://reserve:reserve@localhost:5439/reserve"
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_echo: bool = False

    reservation_ttl_seconds: int = 900


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Кэшированный синглтон настроек (создаётся при первом обращении, не при импорте)."""
    return Settings()
