import pytest
from pydantic import ValidationError

from app.core.config import (
    Settings,
    clear_settings_cache,
    get_settings,
    resolve_app_env,
)
from app.core.url_validation import require_http_origin, require_http_url


@pytest.mark.parametrize(
    ("host", "url", "expected"),
    [
        ("testserver", "http://testserver/docs", "test"),
        ("api-test.vercel.app", "", "test"),
        ("", "https://bookmark-test.example.com/health", "test"),
        ("dev.example.com", "", "development"),
        ("localhost:8000", "http://localhost:8000/", "development"),
        ("127.0.0.1:8000", "", "development"),
        ("api.example.com", "https://api.example.com/docs", "production"),
        ("fastapi-bookmark.vercel.app", "", "production"),
        ("test-dev.example.com", "", "test"),
    ],
)
def test_resolve_app_env_from_host_and_url(host: str, url: str, expected: str) -> None:
    assert resolve_app_env(host, url) == expected


def test_removed_env_fields_are_not_settings() -> None:
    assert "APP_ENV" not in Settings.model_fields
    assert "LOG_LEVEL" not in Settings.model_fields
    assert "ENABLE_DOCS" not in Settings.model_fields
    assert "CORS_ORIGINS" not in Settings.model_fields
    assert "SUPABASE_TIMEOUT_SECONDS" not in Settings.model_fields


def test_cors_origins_are_fixed() -> None:
    settings = Settings()

    assert settings.CORS_ORIGINS == ["http://localhost:3000"]
    assert "*" not in settings.CORS_ORIGINS


def test_cors_rejects_wildcard() -> None:
    with pytest.raises(ValueError):
        require_http_origin("*", allow_root_path=False)


@pytest.mark.parametrize(
    "cors_origin",
    [
        "null",
        "ftp://localhost:3000",
        "http://user:password@localhost:3000",
        "http://localhost:3000/api",
        "http://localhost:3000/",
        "http://localhost:3000?preview=true",
        "http://localhost:3000#section",
        "http:///missing-host",
        "http://localhost\\evil.com",
        "http://localhost:",
        "http://.",
        " http://localhost:3000",
        "http://localhost:3000 ",
        "http://localhost:3000\n",
        "http://localhost:3000\x00",
        "",
    ],
)
def test_cors_rejects_non_origin_values(cors_origin: str) -> None:
    with pytest.raises(ValueError):
        require_http_origin(cors_origin, allow_root_path=False)


@pytest.mark.parametrize(
    "cors_origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "https://api.example.com:8443",
    ],
)
def test_cors_allows_concrete_origins(cors_origin: str) -> None:
    assert require_http_origin(cors_origin, allow_root_path=False) == cors_origin


@pytest.mark.parametrize(
    "bookmark_url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:pass@example.com",
        "example.com",
        "https://",
    ],
)
def test_bookmark_url_rejects_non_http_values(bookmark_url: str) -> None:
    with pytest.raises(ValueError):
        require_http_url(bookmark_url)


def test_bookmark_url_allows_http_path_and_query() -> None:
    assert (
        require_http_url("https://example.com/docs?q=1#section")
        == "https://example.com/docs?q=1#section"
    )


def test_database_configuration_and_secret_redaction():
    settings = Settings(
        DATABASE_URL="postgresql://user:private@localhost/bookmark",
        BOOKMARK_API_KEY="secret",
        BOOKMARK_USER_ID="00000000-0000-0000-0000-000000000001",
    )
    assert settings.database_schema == "bookmark"
    assert "private" not in repr(settings)
    assert "secret" not in repr(settings)
    assert str(settings.BOOKMARK_USER_ID).endswith("0001")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://localhost/db",
        "postgresql://localhost",
        "postgresql://localhost:bad/db",
        "postgresql://localhost/db\n",
        123,
    ],
)
def test_database_url_validation(value):
    with pytest.raises(ValidationError):
        Settings(DATABASE_URL=value)


def test_optional_credentials_and_cache(monkeypatch):
    settings = Settings(BOOKMARK_API_KEY=" ", BOOKMARK_USER_ID="")
    assert settings.BOOKMARK_API_KEY is None
    assert settings.BOOKMARK_USER_ID is None
    first = get_settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/other")
    assert get_settings() is first
    clear_settings_cache()
    assert get_settings().DATABASE_URL.get_secret_value().endswith("/other")
