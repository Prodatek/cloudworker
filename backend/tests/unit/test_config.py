from app.core.config import Settings, get_settings


def test_settings_defaults_when_no_env_overrides() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "CloudWorker API"
    assert settings.app_env == "development"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.log_level == "INFO"


def test_settings_reads_overrides_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@example:5432/db")

    settings = Settings(_env_file=None)

    assert settings.log_level == "DEBUG"
    assert settings.database_url == "postgresql+asyncpg://u:p@example:5432/db"


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()
