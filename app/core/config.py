from functools import lru_cache
from typing import ClassVar, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import SecretStr, field_validator
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

    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    DATABASE_URL: SecretStr
    BOOKMARK_API_KEY: SecretStr | None = None
    BOOKMARK_USER_ID: UUID | None = None

    app_name: ClassVar[str] = "Bookmark API"
    database_schema: ClassVar[str] = "bookmark"
    CORS_ORIGINS: ClassVar[list[str]] = [
        require_http_origin("http://localhost:3000", allow_root_path=False)
    ]
    DATABASE_TIMEOUT_SECONDS: ClassVar[int] = 5

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def require_postgres_dsn(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            raise ValueError("DATABASE_URL must be a PostgreSQL URI")  # noqa: TRY004 - Pydantic validation
        try:
            parsed = urlsplit(raw)
            valid = parsed.scheme in {"postgres", "postgresql"} and bool(
                parsed.hostname
            )
            valid = valid and parsed.path not in {"", "/"} and parsed.port != 0
        except ValueError:
            valid = False
        if not valid or any(char.isspace() or ord(char) < 32 for char in raw):
            raise ValueError("DATABASE_URL must be a PostgreSQL URI")
        return value

    @field_validator("BOOKMARK_API_KEY", "BOOKMARK_USER_ID", mode="before")
    @classmethod
    def normalize_blank_optional(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        return None if isinstance(raw, str) and not raw.strip() else value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # Loaded from the environment.


def clear_settings_cache() -> None:
    get_settings.cache_clear()
