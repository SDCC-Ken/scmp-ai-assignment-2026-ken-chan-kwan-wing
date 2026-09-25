from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env (backend/app/config.py -> repo root is two levels above backend/).
# A missing file is tolerated by pydantic-settings.
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ROOT_ENV,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_port: int = 9181
    app_env: str = "development"
    database_url: str = "sqlite:///./data/app.db"
    # Create tables and load fictional demo data on startup when the users table is empty.
    db_auto_seed: bool = True

    # Real JWT auth (HS256). Empty secret: random per-process secret outside production.
    jwt_secret_key: SecretStr = SecretStr("")
    jwt_expire_minutes: int = Field(default=60, gt=0)
    jwt_issuer: str = "scmp-ai-assignment"
    # Mock Google SSO (fictional seed users, no password). Disable to hide the endpoints.
    mock_sso_enabled: bool = True
    cors_origins: list[str] | str = ["http://localhost:9180"]
    # The JWT travels only in this httpOnly cookie (never in a response body). Set
    # AUTH_COOKIE_SECURE=true whenever the app is served over HTTPS; APP_ENV=production
    # forces Secure regardless.
    auth_cookie_name: str = Field(default="scmp_session", min_length=1)
    auth_cookie_secure: bool = False

    llm_provider: str = "gemini"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.8-flash"
    gemini_thinking_level: str = "low"

    reqres_base_url: str = "https://reqres.in/api/users"
    reqres_api_key: SecretStr = SecretStr("")

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def cookie_secure(self) -> bool:
        """Effective ``Secure`` attribute of the session cookie."""
        return self.auth_cookie_secure or self.is_production

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
