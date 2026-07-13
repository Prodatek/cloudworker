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

    aws_region: str = "us-east-1"
    launch_template_id: str = ""
    # Comma-separated private subnet ids (from Phase 3's networking module outputs). Kept as a
    # plain string rather than list[str] to avoid fighting pydantic-settings' env-var parsing
    # for complex types; split via worker_subnet_id_list below.
    worker_subnet_ids: str = ""
    ssm_ready_timeout_seconds: float = 120.0
    worker_poll_interval_seconds: float = 5.0

    # Phase 3's storage module bucket outputs — logs is where SSM writes full command
    # output, artifacts is where Phase 6's Playwright runner uploads screenshots/video.
    logs_bucket_name: str = ""
    artifacts_bucket_name: str = ""
    job_execution_timeout_seconds: float = 900.0
    max_concurrent_jobs: int = 5
    artifact_url_expiry_seconds: int = 900

    # SECURITY: jwt_secret_key defaults to an insecure placeholder for local dev only —
    # every deployment beyond a laptop MUST override this via the JWT_SECRET_KEY env var.
    jwt_secret_key: str = "dev-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expiry_minutes: int = 60

    # Comma-separated allowed browser origins for CORS (the dashboard's dev server by default).
    cors_allowed_origins: str = "http://localhost:5173"

    @property
    def worker_subnet_id_list(self) -> list[str]:
        return [s.strip() for s in self.worker_subnet_ids.split(",") if s.strip()]

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [s.strip() for s in self.cors_allowed_origins.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
