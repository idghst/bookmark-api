from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.integrations import postgres
from app.main import create_app
from tests.db_fakes import Connection

OWNER = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Bookmark-Key": "secret"}


def client(monkeypatch, connection, **kwargs):
    async def connect(_):
        return connection

    monkeypatch.setattr(postgres, "connect", connect)
    return TestClient(create_app(Settings(BOOKMARK_API_KEY="secret", **kwargs)))


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, "authentication_required"),
        ({"Authorization": "Bearer obsolete-jwt"}, "authentication_required"),
        ({"X-Bookmark-Key": "wrong"}, "invalid_api_key"),
    ],
)
def test_auth_rejects_before_database(monkeypatch, headers, code):
    conn = Connection()
    response = client(monkeypatch, conn).get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == code
    assert not conn.queries


def test_auth_discovers_owner_across_all_four_tables(monkeypatch):
    conn = Connection([{"user_id": UUID(OWNER)}])
    response = client(monkeypatch, conn).get("/api/v1/auth/me", headers=HEADERS)
    assert response.json() == {"id": OWNER, "email": None}
    assert conn.committed and conn.closed
    assert all(
        "bookmark." + name in conn.queries[0][0]
        for name in ("items", "folders", "sections", "folder_sections")
    )


@pytest.mark.parametrize(
    "rows", [[], [{"user_id": OWNER}, {"user_id": "other"}], [{"user_id": None}]]
)
def test_ambiguous_identity_fails_closed(monkeypatch, rows):
    conn = Connection(rows)
    response = client(monkeypatch, conn).get("/api/v1/auth/me", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "service_identity_unavailable"
    assert conn.rolled_back and conn.closed


def test_explicit_owner_bootstraps_empty_database(monkeypatch):
    conn = Connection()
    response = client(monkeypatch, conn, BOOKMARK_USER_ID=OWNER).get(
        "/api/v1/auth/me", headers=HEADERS
    )
    assert response.status_code == 200
    assert not conn.queries


def test_missing_configured_key_is_rejected(monkeypatch):
    response = TestClient(create_app(Settings(BOOKMARK_API_KEY=None))).get(
        "/api/bookmarks", headers=HEADERS
    )
    assert response.json()["code"] == "invalid_api_key"


def test_commit_failure_is_reported_before_success(monkeypatch):
    conn = Connection(commit_error=psycopg.OperationalError("private host"))
    response = client(monkeypatch, conn, BOOKMARK_USER_ID=OWNER).get(
        "/api/v1/auth/me", headers=HEADERS
    )
    assert response.status_code == 503
    assert "private" not in response.text


async def test_connect_uses_secret_and_bounded_timeout(monkeypatch):
    captured = {}

    async def connect(dsn, **kwargs):
        captured.update(dsn=dsn, **kwargs)
        return Connection()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    settings = Settings()
    await postgres.connect(settings)
    assert captured["dsn"] == settings.DATABASE_URL.get_secret_value()
    assert captured["connect_timeout"] == 5
    assert captured["options"] == "-c statement_timeout=5000"
