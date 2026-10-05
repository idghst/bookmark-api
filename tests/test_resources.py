import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from tests.test_auth import HEADERS
from tests.test_supabase import OWNER, client

ID = "00000000-0000-0000-0000-000000000010"
FOLDER_ID = "00000000-0000-0000-0000-000000000020"
SECTION_ID = "00000000-0000-0000-0000-000000000030"
BOOKMARK = {
    "id": ID,
    "user_id": OWNER,
    "title": "Example",
    "url": "https://example.com",
    "description": None,
    "is_favorite": False,
    "color": None,
    "folder_id": None,
    "folder_section_id": None,
    "position": 0,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
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


class Store:
    def __init__(self):
        self.tables = {table: [deepcopy(row)] for _, table, row, _ in CASES}
        self.tables["folders"] += [{**FOLDER, "id": FOLDER_ID}]
        self.tables["sections"] += [{**SECTION, "id": SECTION_ID}]
        self.tables["folder_sections"] += [{**FOLDER_SECTION, "id": SECTION_ID}]
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        table = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content) if request.content else None
        if "/rpc/" in request.url.path:
            assert body["p_user_id"] == OWNER
            return httpx.Response(200, json=[])
        if request.method == "POST":
            assert body["user_id"] == OWNER
            self.tables[table].append(body)
            return httpx.Response(201, json=[body])
        assert request.url.params["user_id"] == "eq." + OWNER
        rows = self.tables[table]
        for key, value in request.url.params.items():
            if value.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == value[3:]]
            elif value == "is.null":
                rows = [r for r in rows if r.get(key) is None]
        if request.method == "GET":
            rows = sorted(
                rows,
                key=lambda r: (r["position"], r["id"]),
                reverse=".desc" in request.url.params.get("order", ""),
            )
            offset = int(request.url.params.get("offset", "0"))
            limit = int(request.url.params.get("limit", "1000"))
            return httpx.Response(200, json=rows[offset : offset + limit])
        if request.method == "PATCH":
            for row in rows:
                row.update(body)
        elif request.method == "DELETE":
            self.tables[table] = [row for row in self.tables[table] if row not in rows]
        return httpx.Response(200, json=rows)


def api(monkeypatch, store):
    return client(monkeypatch, store, BOOKMARK_USER_ID=OWNER)


def test_snapshot_returns_all_resources_with_existing_serialization(monkeypatch):
    store = Store()
    instance = api(monkeypatch, store)
    response = instance.get("/api/snapshot", headers=HEADERS)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert set(snapshot) == {"bookmarks", "folders", "sections", "folderSections"}
    for path, _, _, _ in CASES:
        key = "folderSections" if path == "folder-sections" else path
        assert snapshot[key] == instance.get("/api/" + path, headers=HEADERS).json()
    assert snapshot["bookmarks"][0]["createdAt"] == BOOKMARK["created_at"]
    assert snapshot["bookmarks"][0]["isFavorite"] is False
    assert snapshot["folderSections"][0]["folderId"] == FOLDER_ID


def test_snapshot_filters_every_resource_by_owner_and_reads_latest(monkeypatch):
    store = Store()
    for rows in store.tables.values():
        rows.append({**rows[0], "id": "foreign", "user_id": "other"})
    instance = api(monkeypatch, store)
    response = instance.get("/api/snapshot?user_id=eq.other", headers=HEADERS)
    assert response.status_code == 200, response.text
    for rows in response.json().values():
        assert rows
        assert all(row["userId"] == OWNER and row["id"] != "foreign" for row in rows)
    assert {request.url.path.rsplit("/", 1)[-1] for request in store.requests} == {
        "items",
        "folders",
        "sections",
        "folder_sections",
    }
    assert all(
        request.url.params["user_id"] == "eq." + OWNER for request in store.requests
    )
    store.tables["items"][0]["title"] = "Updated outside API"
    assert (
        instance.get("/api/snapshot", headers=HEADERS).json()["bookmarks"][0]["title"]
        == "Updated outside API"
    )


@pytest.mark.parametrize(
    "headers,code",
    [({}, "authentication_required"), ({"X-Bookmark-Key": "wrong"}, "invalid_api_key")],
)
def test_snapshot_rejects_unauthorized_before_database(monkeypatch, headers, code):
    def handle(request):
        pytest.fail("Unauthenticated snapshot must not reach Supabase")

    response = api(monkeypatch, handle).get("/api/snapshot", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "request_id"}


def test_snapshot_discovers_owner_once_for_all_resources(monkeypatch):
    store = Store()
    discovery = []

    def handle(request):
        if request.url.params["select"] == "user_id":
            discovery.append(request)
            return httpx.Response(200, json=[{"user_id": OWNER}])
        return store(request)

    response = client(monkeypatch, handle).get("/api/snapshot", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert len(discovery) == 8
    for _, table, _, _ in CASES:
        assert (
            len(
                [
                    request
                    for request in discovery
                    if request.url.path.endswith("/" + table)
                ]
            )
            == 2
        )
    assert len(store.requests) == 8


def test_snapshot_reads_resources_in_parallel(monkeypatch):
    started = set()
    all_started = asyncio.Event()

    async def handle(request):
        started.add(request.url.path.rsplit("/", 1)[-1])
        if len(started) == 4:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=1)
        return httpx.Response(200, json=[])

    response = api(monkeypatch, handle).get("/api/snapshot", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "bookmarks": [],
        "folders": [],
        "sections": [],
        "folderSections": [],
    }


@pytest.mark.parametrize(
    "sqlcode,status,code",
    [
        ("42501", 403, "database_access_denied"),
        ("unexpected", 502, "database_request_failed"),
    ],
)
def test_snapshot_waits_for_all_reads_before_propagating_database_error(
    monkeypatch, sqlcode, status, code
):
    finished = set()

    async def handle(request):
        table = request.url.path.rsplit("/", 1)[-1]
        if table == "items":
            return httpx.Response(400, json={"code": sqlcode, "message": "private"})
        await asyncio.sleep(0.02)
        finished.add(table)
        return httpx.Response(200, json=[])

    response = api(monkeypatch, handle).get("/api/snapshot", headers=HEADERS)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "request_id"}
    assert "private" not in response.text
    assert finished == {"folders", "sections", "folder_sections"}


@pytest.mark.parametrize("path,table,row,payload", CASES)
def test_crud_and_reorder_contract(monkeypatch, path, table, row, payload):
    store = Store()
    instance = api(monkeypatch, store)
    response = instance.get("/api/" + path, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()[0]["userId"] == OWNER
    response = instance.post("/api/" + path, json=payload, headers=HEADERS)
    assert response.status_code == 201, response.text
    assert response.json()["position"] == 1
    field = "title" if path == "bookmarks" else "name"
    response = instance.patch(
        f"/api/{path}/{ID}", json={field: "Changed", "color": "#fff"}, headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json()[field] == "Changed"
    updates = [{"id": ID, "position": 2}, {"id": ID, "position": 3}]
    response = instance.post(f"/api/{path}/reorder", json=updates, headers=HEADERS)
    assert response.status_code == 204
    assert store.requests[-1].url.path.endswith("rpc/reorder_resources")
    assert json.loads(store.requests[-1].content) == {
        "p_table": table,
        "p_user_id": OWNER,
        "p_updates": updates,
    }
    response = instance.delete(f"/api/{path}/{ID}", headers=HEADERS)
    assert response.status_code == 204


@pytest.mark.parametrize("path,table,row,payload", CASES)
def test_missing_resources_and_failed_reorder_uses_one_rpc(
    monkeypatch, path, table, row, payload
):
    response = api(monkeypatch, lambda request: httpx.Response(200, json=[])).patch(
        f"/api/{path}/{ID}", json={"color": "#fff"}, headers=HEADERS
    )
    assert response.status_code == 404
    calls = []

    def failure(request):
        calls.append(request)
        return httpx.Response(404, json={"code": "P0002", "message": "private"})

    response = api(monkeypatch, failure).post(
        f"/api/{path}/reorder",
        json=[{"id": ID, "position": 4}, {"id": FOLDER_ID, "position": 9}],
        headers=HEADERS,
    )
    assert response.status_code == 404
    assert len(calls) == 1
    assert calls[0].url.path.endswith("/rpc/reorder_resources")


@pytest.mark.parametrize(
    "sqlcode,status,code",
    [
        ("42501", 403, "database_access_denied"),
        ("P0002", 404, "resource_not_found"),
        ("23503", 409, "resource_conflict"),
        ("23514", 409, "resource_conflict"),
        ("23505", 409, "resource_conflict"),
        ("23502", 409, "resource_conflict"),
        ("22P02", 422, "validation_error"),
        ("22004", 422, "validation_error"),
        ("unexpected", 502, "database_request_failed"),
    ],
)
def test_database_errors_are_sanitized(monkeypatch, sqlcode, status, code):
    response = api(
        monkeypatch,
        lambda request: httpx.Response(
            400, json={"code": sqlcode, "message": "private"}
        ),
    ).get("/api/bookmarks", headers=HEADERS)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message", "request_id"}
    assert "private" not in response.text


@pytest.mark.parametrize("body", [None, [1], {}])
def test_invalid_database_response(monkeypatch, body):
    response = api(monkeypatch, lambda request: httpx.Response(200, json=body)).get(
        "/api/bookmarks", headers=HEADERS
    )
    assert response.json()["code"] == "database_response_invalid"


def test_serialization_and_owner_filter_cannot_be_overridden(monkeypatch):
    store = Store()
    response = api(monkeypatch, store).get(
        "/api/bookmarks?user_id=eq.other", headers=HEADERS
    )
    assert response.json()[0]["createdAt"] == "2026-01-01T00:00:00+00:00"
    assert response.json()[0]["isFavorite"] is False
    assert store.requests[0].url.params["user_id"] == "eq." + OWNER


@pytest.mark.parametrize("section_id", [SECTION_ID, None])
def test_folder_move_recalculates_position(monkeypatch, section_id):
    store = Store()
    store.tables["folders"][0]["section_id"] = FOLDER_ID
    response = api(monkeypatch, store).patch(
        f"/api/folders/{ID}", json={"sectionId": section_id}, headers=HEADERS
    )
    assert response.status_code == 200, response.text
    assert response.json()["position"] == (0 if section_id else 1)


def test_create_folder_in_section_and_unknown_parent(monkeypatch):
    instance = api(monkeypatch, Store())
    assert (
        instance.post(
            "/api/folders",
            json={"name": "New", "sectionId": SECTION_ID},
            headers=HEADERS,
        ).status_code
        == 201
    )
    assert (
        instance.post(
            "/api/folders",
            json={"name": "New", "sectionId": "missing"},
            headers=HEADERS,
        ).status_code
        == 404
    )
    assert (
        instance.post(
            "/api/folder-sections",
            json={"name": "New", "folderId": "missing"},
            headers=HEADERS,
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
    store = Store()
    if not matching:
        store.tables["folder_sections"][-1]["folder_id"] = ID
    response = api(monkeypatch, store).post(
        "/api/bookmarks",
        json={
            "title": "New",
            "url": "https://example.com",
            "folderId": FOLDER_ID,
            "folderSectionId": folder_section_id,
        },
        headers=HEADERS,
    )
    assert response.status_code == (201 if matching else 409)


def test_bookmark_rejects_foreign_folder(monkeypatch):
    store = Store()
    store.tables["folders"][-1]["user_id"] = "other"
    response = api(monkeypatch, store).post(
        "/api/bookmarks",
        json={"title": "New", "url": "https://example.com", "folderId": FOLDER_ID},
        headers=HEADERS,
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "updates,current",
    [
        ({"folderId": FOLDER_ID}, BOOKMARK),
        (
            {"folderId": None},
            {**BOOKMARK, "folder_id": FOLDER_ID, "folder_section_id": SECTION_ID},
        ),
        ({"folderSectionId": SECTION_ID}, {**BOOKMARK, "folder_id": FOLDER_ID}),
        (
            {"folderSectionId": None},
            {**BOOKMARK, "folder_id": FOLDER_ID, "folder_section_id": SECTION_ID},
        ),
        ({"folderSectionId": None}, BOOKMARK),
    ],
)
def test_bookmark_moves_and_clears_folder_section(monkeypatch, updates, current):
    store = Store()
    store.tables["items"] = [deepcopy(current)]
    response = api(monkeypatch, store).patch(
        f"/api/bookmarks/{ID}", json=updates, headers=HEADERS
    )
    assert response.status_code == 200, response.text
    if "folderId" in updates:
        assert response.json()["folderSectionId"] is None


def test_folder_delete_delegates_atomic_movement(monkeypatch):
    store = Store()
    response = api(monkeypatch, store).delete(
        f"/api/folders/{ID}?destination_folder_id={FOLDER_ID}", headers=HEADERS
    )
    assert response.status_code == 204
    assert len(store.requests) == 1
    assert json.loads(store.requests[0].content) == {
        "p_folder_id": ID,
        "p_destination_folder_id": FOLDER_ID,
        "p_user_id": OWNER,
    }


def test_folder_delete_rejects_same_destination(monkeypatch):
    store = Store()
    response = api(monkeypatch, store).delete(
        f"/api/folders/{ID}?destination_folder_id={ID}", headers=HEADERS
    )
    assert response.status_code == 422
    assert response.json()["code"] == "folder_destination_invalid"
    assert not store.requests


@pytest.mark.parametrize("url", ["javascript:alert(1)", None])
def test_invalid_bookmark_url(monkeypatch, url):
    response = api(monkeypatch, Store()).post(
        "/api/bookmarks", json={"title": "New", "url": url}, headers=HEADERS
    )
    assert response.status_code == 422


def test_folder_tree_stays_removed(monkeypatch):
    assert (
        api(monkeypatch, Store()).get("/api/folders/tree", headers=HEADERS).status_code
        == 405
    )


def test_bookmark_move_uses_one_request_per_id_lookup(monkeypatch):
    store = Store()
    response = api(monkeypatch, store).patch(
        f"/api/bookmarks/{ID}",
        json={"folderId": FOLDER_ID, "folderSectionId": SECTION_ID},
        headers=HEADERS,
    )
    assert response.status_code == 200
    lookups = [
        request
        for request in store.requests
        if request.method == "GET" and "id" in request.url.params
    ]
    assert len(lookups) == 3
    assert all(request.url.params["limit"] == "1" for request in lookups)
    assert len(store.requests) == 5
