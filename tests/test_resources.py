import re

import pytest

from tests.test_database import HEADERS, OTHER, OWNER, client

ID = "00000000-0000-0000-0000-000000000010"
FOLDER_ID = "00000000-0000-0000-0000-000000000020"
SECTION_ID = "00000000-0000-0000-0000-000000000030"
MISSING = "00000000-0000-0000-0000-0000000000ff"
TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$")
CASES = [
    ("bookmarks", "items", ID, {"title": "Example", "url": "https://example.com"}),
    ("folders", "folders", FOLDER_ID, {"name": "Work"}),
    ("sections", "sections", SECTION_ID, {"name": "Read"}),
    (
        "folder-sections",
        "folder_sections",
        SECTION_ID,
        {"name": "Read", "folderId": FOLDER_ID},
    ),
]


@pytest.fixture
def api(db, app_database_url):
    """Owner data plus one foreign row per table; the API must never see OTHER."""
    for owner, folder, section, item in (
        (OWNER, FOLDER_ID, SECTION_ID, ID),
        (OTHER, None, None, None),
    ):
        db.execute(
            "insert into bookmark.sections (id, user_id, name)"
            " values (coalesce(%s, gen_random_uuid()), %s, 'Read')",
            [section, owner],
        )
        db.execute(
            "insert into bookmark.folders (id, user_id, name)"
            " values (coalesce(%s, gen_random_uuid()), %s, 'Base')",
            [folder, owner],
        )
        db.execute(
            "insert into bookmark.folder_sections (id, user_id, folder_id, name)"
            " select coalesce(%s, gen_random_uuid()), %s, id, 'Read'"
            " from bookmark.folders where user_id = %s",
            [section, owner, owner],
        )
        db.execute(
            "insert into bookmark.items (id, user_id, title, url)"
            " values (coalesce(%s, gen_random_uuid()), %s, 'Example',"
            " 'https://example.com')",
            [item, owner],
        )
    return client(app_database_url, BOOKMARK_USER_ID=OWNER)


def test_snapshot_returns_owner_resources_with_existing_serialization(api):
    response = api.get("/api/snapshot?user_id=eq." + OTHER, headers=HEADERS)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert set(snapshot) == {"bookmarks", "folders", "sections", "folderSections"}
    for path, *_ in CASES:
        key = "folderSections" if path == "folder-sections" else path
        assert snapshot[key] == api.get("/api/" + path, headers=HEADERS).json()
        assert [row["userId"] for row in snapshot[key]] == [OWNER]
    bookmark = snapshot["bookmarks"][0]
    assert TIMESTAMP.match(bookmark["createdAt"]), bookmark["createdAt"]
    assert TIMESTAMP.match(bookmark["updatedAt"])
    assert bookmark["isFavorite"] is False
    assert bookmark["folderId"] is None
    assert snapshot["folderSections"][0]["folderId"] == FOLDER_ID


@pytest.mark.parametrize(
    "headers,code",
    [({}, "authentication_required"), ({"X-Bookmark-Key": "wrong"}, "invalid_api_key")],
)
def test_snapshot_rejects_unauthorized_before_database(headers, code):
    response = client().get("/api/snapshot", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "request_id"}


@pytest.mark.parametrize("path,table,existing,payload", CASES)
def test_crud_and_reorder_contract(api, path, table, existing, payload):
    response = api.post("/api/" + path, json=payload, headers=HEADERS)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["position"] == 1
    assert created["userId"] == OWNER
    field = "title" if path == "bookmarks" else "name"
    response = api.patch(
        f"/api/{path}/{created['id']}",
        json={field: "Changed", "color": "#fff"},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()[field] == "Changed"
    assert response.json()["color"] == "#fff"

    updates = [
        {"id": existing, "position": 5},
        {"id": created["id"], "position": 0},
    ]
    response = api.post(f"/api/{path}/reorder", json=updates, headers=HEADERS)
    assert response.status_code == 204, response.text
    rows = api.get("/api/" + path, headers=HEADERS).json()
    assert [(row["id"], row["position"]) for row in rows] == [
        (created["id"], 0),
        (existing, 5),
    ]

    response = api.delete(f"/api/{path}/{created['id']}", headers=HEADERS)
    assert response.status_code == 204
    assert api.delete(f"/api/{path}/{created['id']}", headers=HEADERS).status_code == (
        404
    )


@pytest.mark.parametrize("path,table,existing,payload", CASES)
def test_foreign_and_missing_rows_are_not_found(
    api, db, path, table, existing, payload
):
    foreign = db.execute(
        f"select id::text from bookmark.{table} where user_id = %s", [OTHER]
    ).fetchone()[0]
    for target in (foreign, MISSING):
        response = api.patch(
            f"/api/{path}/{target}", json={"color": "#fff"}, headers=HEADERS
        )
        assert response.status_code == 404
        assert api.delete(f"/api/{path}/{target}", headers=HEADERS).status_code == 404

    # A failed reorder rolls back the positions it already changed.
    response = api.post(
        f"/api/{path}/reorder",
        json=[{"id": existing, "position": 4}, {"id": foreign, "position": 9}],
        headers=HEADERS,
    )
    assert response.status_code == 404
    assert db.execute(
        f"select position from bookmark.{table} where id = %s", [existing]
    ).fetchone() == (0,)
    assert db.execute(
        f"select position from bookmark.{table} where id = %s", [foreign]
    ).fetchone() == (0,)


def test_invalid_identifier_and_conflict_are_sanitized(api):
    response = api.patch("/api/bookmarks/not-a-uuid", json={}, headers=HEADERS)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    response = api.post("/api/folders", json={"name": " base "}, headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["code"] == "resource_conflict"
    assert set(response.json()) == {"code", "message", "request_id"}


@pytest.mark.parametrize("section_id", [SECTION_ID, None])
def test_folder_move_recalculates_position(api, db, section_id):
    db.execute(
        "update bookmark.folders set section_id = %s where id = %s",
        [None if section_id else SECTION_ID, FOLDER_ID],
    )
    response = api.patch(
        f"/api/folders/{FOLDER_ID}", json={"sectionId": section_id}, headers=HEADERS
    )
    assert response.status_code == 200, response.text
    assert response.json()["sectionId"] == section_id
    assert response.json()["position"] == 0


def test_create_folder_in_section_and_unknown_parent(api):
    response = api.post(
        "/api/folders", json={"name": "New", "sectionId": SECTION_ID}, headers=HEADERS
    )
    assert response.status_code == 201
    assert response.json()["sectionId"] == SECTION_ID
    for path, payload in (
        ("folders", {"name": "Other", "sectionId": MISSING}),
        ("folder-sections", {"name": "New", "folderId": MISSING}),
    ):
        assert api.post("/api/" + path, json=payload, headers=HEADERS).status_code == (
            404
        )


@pytest.mark.parametrize("matching", [True, False])
def test_bookmark_folder_section_must_match_folder(api, db, matching):
    folder = FOLDER_ID
    if not matching:
        folder = api.post("/api/folders", json={"name": "Else"}, headers=HEADERS)
        folder = folder.json()["id"]
    response = api.post(
        "/api/bookmarks",
        json={
            "title": "New",
            "url": "https://example.com",
            "folderId": folder,
            "folderSectionId": SECTION_ID,
        },
        headers=HEADERS,
    )
    assert response.status_code == (201 if matching else 409)


def test_bookmark_rejects_foreign_folder(api, db):
    foreign = db.execute(
        "select id::text from bookmark.folders where user_id = %s", [OTHER]
    ).fetchone()[0]
    response = api.post(
        "/api/bookmarks",
        json={"title": "New", "url": "https://example.com", "folderId": foreign},
        headers=HEADERS,
    )
    assert response.status_code == 404


def test_bookmark_moves_and_clears_folder_section(api):
    response = api.patch(
        f"/api/bookmarks/{ID}",
        json={"folderId": FOLDER_ID, "folderSectionId": SECTION_ID},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    assert response.json()["folderSectionId"] == SECTION_ID
    response = api.patch(
        f"/api/bookmarks/{ID}", json={"folderId": None}, headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()["folderId"] is None
    assert response.json()["folderSectionId"] is None


def test_folder_delete_moves_bookmarks_atomically(api, db):
    api.patch(f"/api/bookmarks/{ID}", json={"folderId": FOLDER_ID}, headers=HEADERS)
    target = api.post("/api/folders", json={"name": "Target"}, headers=HEADERS)
    target_id = target.json()["id"]
    response = api.delete(
        f"/api/folders/{FOLDER_ID}?destination_folder_id={target_id}", headers=HEADERS
    )
    assert response.status_code == 204, response.text
    bookmark = api.get("/api/bookmarks", headers=HEADERS).json()[0]
    assert bookmark["folderId"] == target_id
    assert bookmark["folderSectionId"] is None
    assert api.get("/api/folder-sections", headers=HEADERS).json() == []
    response = api.delete(f"/api/folders/{FOLDER_ID}", headers=HEADERS)
    assert response.status_code == 404


def test_folder_delete_rejects_same_destination(api):
    response = api.delete(
        f"/api/folders/{FOLDER_ID}?destination_folder_id={FOLDER_ID}", headers=HEADERS
    )
    assert response.status_code == 422
    assert response.json()["code"] == "folder_destination_invalid"


@pytest.mark.parametrize("url", ["javascript:alert(1)", None])
def test_invalid_bookmark_url(api, url):
    response = api.post(
        "/api/bookmarks", json={"title": "New", "url": url}, headers=HEADERS
    )
    assert response.status_code == 422


def test_folder_tree_stays_removed():
    assert client().get("/api/folders/tree", headers=HEADERS).status_code == 405
