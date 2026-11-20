import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from app.core.config import Settings
from app.integrations.database import database_error
from app.main import create_app

OWNER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
HEADERS = {"X-Bookmark-Key": "secret"}


def client(database_url: str | None = None, **kwargs: object) -> TestClient:
    settings = {"BOOKMARK_API_KEY": "secret", **kwargs}
    if database_url:
        settings["DATABASE_URL"] = database_url
    return TestClient(create_app(Settings(**settings)))


def seed_owner(db: psycopg.Connection, owner: str = OWNER) -> None:
    db.execute(
        "insert into bookmark.sections (user_id, name) values (%s, 'Read')", [owner]
    )


def test_owner_discovery_returns_single_owner(db, app_database_url):
    seed_owner(db)
    response = client(app_database_url).get("/api/v1/auth/me", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": OWNER, "email": None}


SECOND_OWNER_SQL = {
    "items": "insert into bookmark.items (user_id, title, url)"
    " values (%s, 't', 'https://example.com')",
    "folders": "insert into bookmark.folders (user_id, name) values (%s, 'W')",
    "sections": "insert into bookmark.sections (user_id, name) values (%s, 'R')",
    "folder_sections": "with f as (insert into bookmark.folders (user_id, name)"
    " values (%s, 'W') returning id, user_id) insert into bookmark.folder_sections"
    " (id, user_id, folder_id, name) select gen_random_uuid(), user_id, id, 'S'"
    " from f",
}


@pytest.mark.parametrize("table", SECOND_OWNER_SQL)
def test_second_owner_in_any_table_fails_closed(db, app_database_url, table):
    seed_owner(db)
    db.execute(SECOND_OWNER_SQL[table], [OTHER])
    response = client(app_database_url).get("/api/v1/auth/me", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "service_identity_unavailable"


def test_empty_database_has_no_service_identity(db, app_database_url):
    response = client(app_database_url).get("/api/v1/auth/me", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "service_identity_unavailable"


def test_explicit_owner_bootstraps_empty_database(db, app_database_url):
    response = client(app_database_url, BOOKMARK_USER_ID=OWNER).get(
        "/api/v1/auth/me", headers=HEADERS
    )
    assert response.json() == {"id": OWNER, "email": None}


def test_unreachable_database_is_sanitized():
    response = client().get("/api/bookmarks", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert "127.0.0.1" not in response.text


def test_app_pools_connections_and_closes_them_at_shutdown(db, app_database_url):
    seed_owner(db)
    app = create_app(Settings(DATABASE_URL=app_database_url, BOOKMARK_API_KEY="secret"))
    with TestClient(app) as instance:
        pool = app.state.database_pool
        for _ in range(3):
            assert instance.get("/api/snapshot", headers=HEADERS).status_code == 200
        assert not pool.closed
    assert app.state.database_pool is None
    assert pool.closed


@pytest.mark.parametrize(
    "error,status,code",
    [
        (errors.InsufficientPrivilege, 403, "database_access_denied"),
        (errors.NoDataFound, 404, "resource_not_found"),
        (errors.ForeignKeyViolation, 409, "resource_conflict"),
        (errors.CheckViolation, 409, "resource_conflict"),
        (errors.UniqueViolation, 409, "resource_conflict"),
        (errors.NotNullViolation, 409, "resource_conflict"),
        (errors.InvalidTextRepresentation, 422, "validation_error"),
        (errors.NullValueNotAllowed, 422, "validation_error"),
        (errors.QueryCanceled, 503, "database_unavailable"),
        (psycopg.InterfaceError, 503, "database_unavailable"),
        (errors.SyntaxError, 502, "database_request_failed"),
    ],
)
def test_database_errors_are_sanitized(error, status, code):
    mapped = database_error(error("private detail"))
    assert (mapped.status_code, mapped.code) == (status, code)
    assert "private" not in mapped.message


def test_app_role_cannot_read_unrelated_tables(db, app_database_url):
    with (
        psycopg.connect(app_database_url) as conn,
        pytest.raises(errors.InsufficientPrivilege),
    ):
        conn.execute("select * from bookmark.audit_log")
