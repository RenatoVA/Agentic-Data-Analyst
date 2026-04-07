from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    OPENROUTER_MODEL_NAME: str
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    PROVIDER:str = "azure"  # or "openrouter"

    AZURE_OPENAI_API_KEY: str | None = None
    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_API_VERSION: str = "2025-04-01-preview"
    AZURE_DEPLOYMENT: str | None = None

    ROOT_DIR: Path
    USERS_DIR: Path | None = None

    CORS_ALLOW_ORIGINS: str = "*"
    LOG_LEVEL: str = "INFO"
    CHAT_TEMPERATURE: float = 0.2
    FILE_SIGNING_SECRET: str | None = None

    GROQ_API_KEY: str | None = None
    GROQ_STT_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_STT_MODEL: str = "whisper-large-v3-turbo"
    GROQ_STT_TEMPERATURE: float = 0.0
    GROQ_STT_RESPONSE_FORMAT: str = "verbose_json"
    GROQ_STT_TIMESTAMP_GRANULARITIES: str = "[\"word\"]"
    GROQ_STT_LANGUAGE: str = "en"
    STT_TIMEOUT_SECONDS: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("ROOT_DIR", mode="before")
    @classmethod
    def _expand_root_dir(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @model_validator(mode="after")
    def _set_path_defaults(self) -> "Settings":
        self.ROOT_DIR = self.ROOT_DIR.resolve()
        if self.USERS_DIR is None:
            self.USERS_DIR = (self.ROOT_DIR / "users").resolve()
        else:
            self.USERS_DIR = self.USERS_DIR.expanduser().resolve()
        if not self.FILE_SIGNING_SECRET:
            self.FILE_SIGNING_SECRET = secrets.token_hex(32)
        return self

    @property
    def cors_origins(self) -> list[str]:
        raw = self.CORS_ALLOW_ORIGINS.strip()
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
