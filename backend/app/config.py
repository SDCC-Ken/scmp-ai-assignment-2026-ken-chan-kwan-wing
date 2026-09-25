from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
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
    cors_origins: list[str] | str = ["http://localhost:9180"]

    llm_provider: str = "gemini"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.8-flash"
    gemini_thinking_level: str = "low"

    reqres_base_url: str = "https://reqres.in/api/users"
    reqres_api_key: SecretStr = SecretStr("")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
