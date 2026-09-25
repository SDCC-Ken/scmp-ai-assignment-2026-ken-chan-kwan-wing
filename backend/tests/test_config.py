import pytest

from app.config import Settings

ENV_VARS = [
    "API_PORT",
    "APP_ENV",
    "DATABASE_URL",
    "DB_AUTO_SEED",
    "JWT_SECRET_KEY",
    "JWT_EXPIRE_MINUTES",
    "JWT_ISSUER",
    "MOCK_SSO_ENABLED",
    "CORS_ORIGINS",
    "LLM_PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_THINKING_LEVEL",
    "REQRES_BASE_URL",
    "REQRES_API_KEY",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults(clean_env: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None)
    assert s.api_port == 9181
    assert s.app_env == "development"
    assert s.database_url == "sqlite:///./data/app.db"
    assert s.cors_origins == ["http://localhost:9180"]
    assert s.llm_provider == "gemini"
    assert s.gemini_model == "gemini-3.8-flash"
    assert s.gemini_thinking_level == "low"
    assert s.reqres_base_url == "https://reqres.in/api/users"
    assert s.gemini_api_key.get_secret_value() == ""


def test_cors_origins_comma_separated(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings(_env_file=None).cors_origins == ["http://a.test", "http://b.test"]


def test_secrets_not_in_repr(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("GEMINI_API_KEY", "fake-gemini-secret")
    clean_env.setenv("REQRES_API_KEY", "fake-reqres-secret")
    s = Settings(_env_file=None)
    text = repr(s) + str(s)
    assert "fake-gemini-secret" not in text
    assert "fake-reqres-secret" not in text
    assert s.gemini_api_key.get_secret_value() == "fake-gemini-secret"


def test_auth_and_db_defaults(clean_env: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None)
    assert s.db_auto_seed is True
    assert s.jwt_secret_key.get_secret_value() == ""
    assert s.jwt_expire_minutes == 60
    assert s.jwt_issuer == "scmp-ai-assignment"
    assert s.mock_sso_enabled is True
    assert s.is_production is False


def test_auth_settings_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DB_AUTO_SEED", "false")
    clean_env.setenv("JWT_SECRET_KEY", "fake-jwt-secret")
    clean_env.setenv("JWT_EXPIRE_MINUTES", "15")
    clean_env.setenv("MOCK_SSO_ENABLED", "false")
    clean_env.setenv("APP_ENV", "Production")
    s = Settings(_env_file=None)
    assert (s.db_auto_seed, s.jwt_expire_minutes, s.mock_sso_enabled) == (False, 15, False)
    assert s.is_production is True
    assert "fake-jwt-secret" not in repr(s) + str(s)
