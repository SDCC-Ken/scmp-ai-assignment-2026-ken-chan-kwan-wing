import pytest

from app.config import Settings

ENV_VARS = [
    "API_PORT",
    "APP_ENV",
    "DATABASE_URL",
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
