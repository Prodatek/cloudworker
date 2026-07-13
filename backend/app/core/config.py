from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced from environment variables / .env.

    Every tunable belongs here rather than hard-coded in application code.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CloudWorker API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://cloudworker:cloudworker@localhost:5432/cloudworker"
    database_pool_size: int = 5
    database_pool_timeout_seconds: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
