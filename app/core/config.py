from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.url_validation import require_http_origin

type AppEnv = Literal["development", "test", "production"]


def resolve_app_env(host: str = "", url: str = "") -> AppEnv:
    """Host/URL hostname에 test → test, dev|localhost|127.0.0.1 → development, 그 외 production."""

    parts = [host]
    if url:
        parsed = urlsplit(url)
        if parsed.hostname:
            parts.append(parsed.hostname)
        if parsed.netloc:
            parts.append(parsed.netloc)
    haystack = " ".join(parts).lower()
    if "test" in haystack:
        return "test"
    if "dev" in haystack or "localhost" in haystack or "127.0.0.1" in haystack:
        return "development"
    return "production"


class Settings(BaseSettings):
    """Validated runtime configuration loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=tuple(
            Path(__file__).resolve().parents[2] / name
            for name in (".env", ".env.local")
        ),
        extra="ignore",
        hide_input_in_errors=True,
    )

    SUPABASE_URL: str
    SUPABASE_SECRET_KEY: SecretStr
    SUPABASE_TIMEOUT_SECONDS: float = Field(default=10, gt=0, le=60)
    BOOKMARK_API_KEY: SecretStr | None = None
    BOOKMARK_USER_ID: UUID | None = None

    app_name: ClassVar[str] = "Bookmark API"
    database_schema: ClassVar[str] = "bookmark"
    CORS_ORIGINS: ClassVar[list[str]] = [
        require_http_origin("http://localhost:3000", allow_root_path=False)
    ]

    @field_validator(
        "BOOKMARK_API_KEY", "BOOKMARK_USER_ID", "SUPABASE_SECRET_KEY", mode="before"
    )
    @classmethod
    def normalize_blank_optional(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        return None if isinstance(raw, str) and not raw.strip() else value

    @field_validator("SUPABASE_URL", mode="before")
    @classmethod
    def validate_supabase_origin(cls, value: object) -> str:
        return require_http_origin(value, allow_root_path=True).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # Loaded from the environment.


def clear_settings_cache() -> None:
    get_settings.cache_clear()
