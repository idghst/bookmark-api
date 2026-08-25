import pytest
from pydantic import ValidationError

from app.core.config import (
    Settings,
    clear_settings_cache,
    get_settings,
    resolve_app_env,
)
from app.core.url_validation import require_http_origin, require_http_url


def test_schema_cannot_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_SCHEMA", "public")

    settings = Settings(
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
    )

    assert settings.supabase_schema == "bookmark"


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


def test_app_name_is_fixed() -> None:
    settings = Settings(
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
    )

    assert settings.app_name == "Bookmark API"


def test_timeout_is_fixed() -> None:
    settings = Settings(
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
    )

    assert settings.SUPABASE_TIMEOUT_SECONDS == 5.0


def test_local_allows_http_supabase_url() -> None:
    settings = Settings(
        SUPABASE_URL="http://localhost:54321",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
    )

    assert str(settings.SUPABASE_URL) == "http://localhost:54321/"


@pytest.mark.parametrize("supabase_url", ["not-a-url", "ftp://test.supabase.co"])
def test_supabase_url_must_be_http_url(supabase_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            SUPABASE_URL=supabase_url,
            SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
        )


def test_cors_origins_are_fixed() -> None:
    settings = Settings(
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
    )

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


@pytest.mark.parametrize(
    "supabase_url",
    [
        "https://user:password@test.supabase.co",
        "https://test.supabase.co/rest/v1",
        "https://test.supabase.co?preview=true",
        "https://test.supabase.co#section",
        "https://test.supabase.co\\evil.com",
        "https://test.supabase.co:",
        "https://.",
        "https://test.supabase.co\n",
        "https://test.supabase.co\x00",
    ],
)
def test_supabase_url_rejects_non_origin_values(supabase_url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            SUPABASE_URL=supabase_url,
            SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
        )


def test_https_supabase_origin_is_allowed() -> None:
    settings = Settings(
        SUPABASE_URL="https://api.example.com:8443",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
        SUPABASE_SECRET_KEY="sb_secret_test",
        BOOKMARK_API_KEY="bookmark-api-secret",
    )

    assert str(settings.SUPABASE_URL) == "https://api.example.com:8443/"


def test_publishable_key_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        Settings(
            SUPABASE_URL="https://test.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="   ",
        )


def test_blank_optional_secret_becomes_none() -> None:
    settings = Settings(
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
        SUPABASE_SECRET_KEY="   ",
        BOOKMARK_API_KEY="   ",
    )

    assert settings.SUPABASE_SECRET_KEY is None
    assert settings.BOOKMARK_API_KEY is None


def test_publishable_key_cannot_be_used_as_server_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(
            SUPABASE_URL="https://test.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
            SUPABASE_SECRET_KEY="sb_publishable_test",
        )


def test_secret_key_must_not_equal_publishable_key() -> None:
    with pytest.raises(ValidationError):
        Settings(
            SUPABASE_URL="https://test.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="shared-key",
            SUPABASE_SECRET_KEY="shared-key",
        )


def test_optional_credentials_are_optional_at_settings_time() -> None:
    settings = Settings(
        SUPABASE_URL="https://test.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
    )

    assert settings.SUPABASE_SECRET_KEY is None
    assert settings.BOOKMARK_API_KEY is None


def test_settings_cache_can_be_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    first = get_settings()
    monkeypatch.setenv("SUPABASE_URL", "https://other.supabase.co")
    assert get_settings() is first

    clear_settings_cache()
    assert str(get_settings().SUPABASE_URL) == "https://other.supabase.co/"
