from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest

from tests.db_fakes import Connection
from tests.test_auth import HEADERS, OWNER, client

ID = "00000000-0000-0000-0000-000000000010"
FOLDER_ID = "00000000-0000-0000-0000-000000000020"
SECTION_ID = "00000000-0000-0000-0000-000000000030"
BOOKMARK = {
    "id": UUID(ID),
    "user_id": UUID(OWNER),
    "title": "Example",
    "url": "https://example.com",
    "description": None,
    "is_favorite": False,
    "color": None,
    "folder_id": None,
    "folder_section_id": None,
    "position": 0,
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
}
FOLDER = {
    "id": ID,
    "user_id": OWNER,
    "name": "Work",
    "color": None,
    "section_id": None,
    "position": 0,
}
SECTION = {"id": ID, "user_id": OWNER, "name": "Read", "color": None, "position": 0}
FOLDER_SECTION = {**SECTION, "folder_id": FOLDER_ID}
CASES = [
    (
        "bookmarks",
        "items",
        BOOKMARK,
        {"title": "Example", "url": "https://example.com"},
    ),
    ("folders", "folders", FOLDER, {"name": "Work"}),
    ("sections", "sections", SECTION, {"name": "Read"}),
    (
        "folder-sections",
        "folder_sections",
        FOLDER_SECTION,
        {"name": "Read", "folderId": FOLDER_ID},
    ),
]


def request(monkeypatch, conn, method, path, **kwargs):
    return getattr(client(monkeypatch, conn, BOOKMARK_USER_ID=OWNER), method)(
        path, headers=HEADERS, **kwargs
    )


@pytest.mark.parametrize("path,table,row,payload", CASES)
def test_crud_and_reorder_contract(monkeypatch, path, table, row, payload):
    conn = Connection([row])
    response = request(monkeypatch, conn, "get", "/api/" + path)
    assert response.status_code == 200
    assert response.json()[0]["userId"] == OWNER
    assert response.json()[0]["id"] == ID
    assert '"bookmark"."' + table + '"' in conn.queries[0][0]
    assert conn.queries[0][1] == [OWNER]

    results = ([[FOLDER]] if path == "folder-sections" else []) + [
        [{"position": 0}],
        [row],
    ]
    conn = Connection(*results)
    response = request(monkeypatch, conn, "post", "/api/" + path, json=payload)
    assert response.status_code == 201, response.text
    assert OWNER in conn.queries[-1][1]
    assert "RETURNING *" in conn.queries[-1][0]
    assert conn.committed

    conn = Connection([row])
    field = "title" if path == "bookmarks" else "name"
    response = request(
        monkeypatch,
        conn,
        "patch",
        f"/api/{path}/{ID}",
        json={field: "Changed", "color": "#fff"},
    )
    assert response.status_code == 200
    assert conn.queries[-1][1][-2:] == [ID, OWNER]

    conn = Connection([row], [row])
    response = request(
        monkeypatch,
        conn,
        "post",
        f"/api/{path}/reorder",
        json=[{"id": ID, "position": 2}, {"id": ID, "position": 3}],
    )
    assert response.status_code == 204
    assert all(query[1][-2:] == [ID, OWNER] for query in conn.queries)

    results = (
        [[row], [{"position": 0}], [], [], [row]] if path == "folders" else [[row]]
    )
    conn = Connection(*results)
    response = request(monkeypatch, conn, "delete", f"/api/{path}/{ID}")
    assert response.status_code == 204
    assert conn.queries[-1][1] == [ID, OWNER]


@pytest.mark.parametrize("path,table,row,payload", CASES)
def test_missing_resources_and_atomic_reorder(monkeypatch, path, table, row, payload):
    conn = Connection([])
    response = request(
        monkeypatch, conn, "patch", f"/api/{path}/{ID}", json={"color": "#fff"}
    )
    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert conn.rolled_back
    conn = Connection([row], [])
    response = request(
        monkeypatch,
        conn,
        "post",
        f"/api/{path}/reorder",
        json=[{"id": ID, "position": 4}, {"id": ID, "position": 9}],
    )
    assert response.status_code == 404
    assert conn.rolled_back and not conn.committed


@pytest.mark.parametrize(
    "error,status,code",
    [
        (
            psycopg.errors.InsufficientPrivilege("private"),
            403,
            "database_access_denied",
        ),
        (psycopg.errors.NoDataFound("private"), 404, "resource_not_found"),
        (psycopg.errors.ForeignKeyViolation("private"), 409, "resource_conflict"),
        (psycopg.errors.CheckViolation("private"), 409, "resource_conflict"),
        (psycopg.errors.UniqueViolation("private"), 409, "resource_conflict"),
        (psycopg.errors.NotNullViolation("private"), 409, "resource_conflict"),
        (psycopg.errors.InvalidTextRepresentation("private"), 422, "validation_error"),
        (psycopg.OperationalError("private"), 503, "database_unavailable"),
        (psycopg.ProgrammingError("private"), 502, "database_request_failed"),
    ],
)
def test_database_errors_are_sanitized(monkeypatch, error, status, code):
    response = request(monkeypatch, Connection(error), "get", "/api/bookmarks")
    assert response.status_code == status
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "request_id"}
    assert "private" not in response.text


@pytest.mark.parametrize("rows", [None, [1]])
def test_invalid_database_response(monkeypatch, rows):
    response = request(monkeypatch, Connection(rows), "get", "/api/bookmarks")
    assert response.json()["code"] == "database_response_invalid"


def test_serialization_and_injection_safe_parameters(monkeypatch):
    conn = Connection([BOOKMARK])
    response = request(monkeypatch, conn, "get", "/api/bookmarks")
    assert response.json()[0]["createdAt"] == "2026-01-01T00:00:00+00:00"
    assert response.json()[0]["isFavorite"] is False
    attack = "x' OR true; --"
    conn = Connection([])
    response = request(monkeypatch, conn, "delete", "/api/bookmarks/" + attack)
    assert response.status_code == 404
    assert attack not in conn.queries[0][0]
    assert attack in conn.queries[0][1]


@pytest.mark.parametrize("section_id", [SECTION_ID, None])
def test_folder_move_recalculates_position(monkeypatch, section_id):
    conn = Connection(
        [FOLDER],
        *([[SECTION]] if section_id else []),
        *([[{"position": 7}]] if section_id else []),
        [{**FOLDER, "section_id": section_id}],
    )
    response = request(
        monkeypatch, conn, "patch", f"/api/folders/{ID}", json={"sectionId": section_id}
    )
    assert response.status_code == 200
    if section_id:
        assert 7 in conn.queries[-1][1]


def test_create_folder_in_section_and_unknown_parent(monkeypatch):
    conn = Connection([SECTION], [{"position": 4}], [FOLDER])
    assert (
        request(
            monkeypatch,
            conn,
            "post",
            "/api/folders",
            json={"name": "New", "sectionId": SECTION_ID},
        ).status_code
        == 201
    )
    conn = Connection([])
    assert (
        request(
            monkeypatch,
            conn,
            "post",
            "/api/folders",
            json={"name": "New", "sectionId": SECTION_ID},
        ).status_code
        == 404
    )
    conn = Connection([])
    assert (
        request(
            monkeypatch,
            conn,
            "post",
            "/api/folder-sections",
            json={"name": "New", "folderId": FOLDER_ID},
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "folder_section_id,matching",
    [(SECTION_ID, True), (SECTION_ID, False), (None, True)],
)
def test_bookmark_parent_ownership_and_membership(
    monkeypatch, folder_section_id, matching
):
    results = [[FOLDER]]
    if folder_section_id:
        results += [[{**FOLDER_SECTION, "folder_id": FOLDER_ID if matching else ID}]]
    if matching:
        results += [[{"position": 3}], [BOOKMARK]]
    conn = Connection(*results)
    response = request(
        monkeypatch,
        conn,
        "post",
        "/api/bookmarks",
        json={
            "title": "New",
            "url": "https://example.com",
            "folderId": FOLDER_ID,
            "folderSectionId": folder_section_id,
        },
    )
    assert response.status_code == (201 if matching else 409)


def test_bookmark_rejects_foreign_folder(monkeypatch):
    response = request(
        monkeypatch,
        Connection([]),
        "post",
        "/api/bookmarks",
        json={"title": "New", "url": "https://example.com", "folderId": FOLDER_ID},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "updates,current,extra",
    [
        ({"folderId": FOLDER_ID}, BOOKMARK, [[FOLDER], [{"position": 3}]]),
        (
            {"folderId": None},
            {**BOOKMARK, "folder_id": FOLDER_ID, "folder_section_id": SECTION_ID},
            [[{"position": 3}]],
        ),
        (
            {"folderSectionId": SECTION_ID},
            {**BOOKMARK, "folder_id": FOLDER_ID},
            [[FOLDER], [FOLDER_SECTION], [{"position": 3}]],
        ),
        (
            {"folderSectionId": None},
            {**BOOKMARK, "folder_id": FOLDER_ID, "folder_section_id": SECTION_ID},
            [[FOLDER], [{"position": 3}]],
        ),
        ({"folderSectionId": None}, BOOKMARK, []),
    ],
)
def test_bookmark_moves_and_clears_folder_section(monkeypatch, updates, current, extra):
    conn = Connection([current], *extra, [BOOKMARK])
    response = request(monkeypatch, conn, "patch", f"/api/bookmarks/{ID}", json=updates)
    assert response.status_code == 200, response.text
    if "folderId" in updates:
        assert '"folder_section_id" = %s' in conn.queries[-1][0]


def test_folder_delete_moves_bookmarks_and_deletes_sections(monkeypatch):
    conn = Connection(
        [FOLDER], [FOLDER], [{"position": 5}], [BOOKMARK], [BOOKMARK], [], [FOLDER]
    )
    response = request(
        monkeypatch,
        conn,
        "delete",
        f"/api/folders/{ID}?destination_folder_id={FOLDER_ID}",
    )
    assert response.status_code == 204
    assert conn.queries[0][0].endswith("FOR UPDATE")
    assert conn.queries[1][0].endswith("FOR UPDATE")
    assert conn.queries[3][0].endswith("FOR UPDATE")
    assert conn.committed
    mutation = conn.queries[4]
    assert mutation[1][0:3] == [FOLDER_ID, None, 5]
    assert 'DELETE FROM "bookmark"."folder_sections"' in conn.queries[5][0]
    assert all("user_id" in query for query, _ in conn.queries)


def test_folder_delete_rejects_same_destination(monkeypatch):
    conn = Connection()
    response = request(
        monkeypatch, conn, "delete", f"/api/folders/{ID}?destination_folder_id={ID}"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "folder_destination_invalid"
    assert not conn.queries


@pytest.mark.parametrize("url", ["javascript:alert(1)", None])
def test_invalid_bookmark_url(monkeypatch, url):
    response = request(
        monkeypatch,
        Connection(),
        "post",
        "/api/bookmarks",
        json={"title": "New", "url": url},
    )
    assert response.status_code == 422


def test_folder_tree_stays_removed(monkeypatch):
    response = request(monkeypatch, Connection(), "get", "/api/folders/tree")
    assert response.status_code == 405
