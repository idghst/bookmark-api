import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from app.core.config import Settings
from app.integrations.postgres import AuthContext, ServiceUser
from app.main import create_app
from app.services import folders

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def dsn():
    value = os.getenv("DATABASE_TEST_URL", "")
    if not value:
        pytest.skip("DATABASE_TEST_URL is not set")
    parsed = urlsplit(value)
    if parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    } or not parsed.path.endswith("_test"):
        pytest.fail("Integration tests require a local disposable *_test database")
    with psycopg.connect(value) as conn:
        conn.execute(Path(__file__).with_name("schema.sql").read_text())
    return value


@pytest.fixture
def clients(dsn):
    owners = [str(uuid4()), str(uuid4())]
    result = [
        TestClient(
            create_app(
                Settings(
                    DATABASE_URL=dsn,
                    BOOKMARK_API_KEY="integration",
                    BOOKMARK_USER_ID=owner,
                )
            ),
            headers={"X-Bookmark-Key": "integration"},
        )
        for owner in owners
    ]
    yield result
    with psycopg.connect(dsn) as conn:
        for table in ("items", "folder_sections", "folders", "sections"):
            conn.execute(
                sql.SQL("DELETE FROM {} WHERE user_id = ANY(%s::uuid[])").format(
                    sql.Identifier("bookmark", table)
                ),
                (owners,),
            )
    for client in result:
        client.close()


def create(client, path, **payload):
    response = client.post("/api/" + path, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_roundtrip_move_delete_and_foreign_owner_isolation(clients):
    first, other = clients
    section = create(first, "sections", name="Sidebar", color="#00ff00")
    folder = create(first, "folders", name="Source", sectionId=section["id"])
    destination = create(first, "folders", name="Destination")
    inside = create(first, "folder-sections", name="Read", folderId=folder["id"])
    item = create(
        first,
        "bookmarks",
        title="Example",
        url="https://example.com",
        folderId=folder["id"],
        folderSectionId=inside["id"],
    )
    existing = create(
        first,
        "bookmarks",
        title="Existing",
        url="https://example.com",
        folderId=destination["id"],
    )
    assert item["folderSectionId"] == inside["id"]
    assert item["createdAt"] and item["userId"]
    assert other.get("/api/bookmarks").json() == []
    assert (
        other.patch(
            "/api/bookmarks/" + item["id"], json={"title": "stolen"}
        ).status_code
        == 404
    )
    assert (
        other.post(
            "/api/bookmarks",
            json={
                "title": "bad",
                "url": "https://example.com",
                "folderId": folder["id"],
            },
        ).status_code
        == 404
    )
    assert (
        other.post(
            "/api/folders", json={"name": "bad", "sectionId": section["id"]}
        ).status_code
        == 404
    )
    assert other.delete("/api/folders/" + folder["id"]).status_code == 404
    assert (
        first.delete(
            "/api/folders/" + folder["id"],
            params={"destination_folder_id": destination["id"]},
        ).status_code
        == 204
    )
    moved = next(
        row for row in first.get("/api/bookmarks").json() if row["id"] == item["id"]
    )
    assert moved["folderId"] == destination["id"]
    assert moved["folderSectionId"] is None
    assert moved["position"] == existing["position"] + 1
    assert first.get("/api/folder-sections").json() == []
    assert first.delete("/api/sections/" + section["id"]).status_code == 204


def test_reorder_failure_rolls_back_prior_updates(clients):
    first, _ = clients
    one = create(first, "sections", name="One")
    two = create(first, "sections", name="Two")
    response = first.post(
        "/api/sections/reorder",
        json=[{"id": one["id"], "position": 9}, {"id": str(uuid4()), "position": 7}],
    )
    assert response.status_code == 404
    rows = first.get("/api/sections").json()
    assert (
        next(row["position"] for row in rows if row["id"] == one["id"])
        == one["position"]
    )
    response = first.post(
        "/api/sections/reorder",
        json=[{"id": one["id"], "position": 9}, {"id": two["id"], "position": -1}],
    )
    assert response.status_code == 409
    rows = first.get("/api/sections").json()
    assert (
        next(row["position"] for row in rows if row["id"] == one["id"])
        == one["position"]
    )


def test_section_delete_unassigns_folders_and_folder_section_delete_unassigns_items(
    clients,
):
    first, _ = clients
    section = create(first, "sections", name="Sidebar")
    folder = create(first, "folders", name="Folder", sectionId=section["id"])
    inside = create(first, "folder-sections", name="Inside", folderId=folder["id"])
    item = create(
        first,
        "bookmarks",
        title="Example",
        url="https://example.com",
        folderId=folder["id"],
        folderSectionId=inside["id"],
    )
    assert first.delete("/api/sections/" + section["id"]).status_code == 204
    assert first.get("/api/folders").json()[0]["sectionId"] is None
    assert first.delete("/api/folder-sections/" + inside["id"]).status_code == 204
    assert first.get("/api/bookmarks").json()[0]["folderSectionId"] is None
    assert first.delete("/api/folders/" + folder["id"]).status_code == 204
    assert first.get("/api/bookmarks").json()[0]["folderId"] is None
    assert first.delete("/api/bookmarks/" + item["id"]).status_code == 204


@pytest.mark.parametrize("operation", ["create", "move"])
async def test_folder_deletion_serializes_concurrent_item_changes(
    clients, dsn, monkeypatch, operation
):
    first, _ = clients
    owner = first.get("/api/v1/auth/me").json()["id"]
    source = create(first, "folders", name="Source")
    destination = create(first, "folders", name="Destination")
    third = create(first, "folders", name="Third")
    item = create(
        first,
        "bookmarks",
        title="Existing",
        url="https://example.com",
        folderId=source["id"],
    )
    paused, resume = asyncio.Event(), asyncio.Event()
    hook_name = "next_position" if operation == "create" else "update"
    original = getattr(folders, hook_name)

    async def pause(*args, **kwargs):
        paused.set()
        await resume.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(folders, hook_name, pause)
    async with (
        await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as deleting,
        await psycopg.AsyncConnection.connect(dsn) as concurrent,
    ):
        auth = AuthContext(ServiceUser(owner), deleting)
        deletion = asyncio.create_task(
            folders.delete_folder(source["id"], auth, destination["id"])
        )
        await asyncio.wait_for(paused.wait(), 2)
        if operation == "create":
            changing = asyncio.create_task(
                concurrent.execute(
                    "INSERT INTO bookmark.items(id,user_id,title,url,folder_id) VALUES (%s,%s,'Concurrent','https://example.com',%s)",
                    (uuid4(), owner, source["id"]),
                )
            )
        else:
            changing = asyncio.create_task(
                concurrent.execute(
                    "UPDATE bookmark.items SET folder_id=%s WHERE id=%s AND user_id=%s",
                    (third["id"], item["id"], owner),
                )
            )
        try:
            done, _ = await asyncio.wait({changing}, timeout=0.15)
            assert not done, "Concurrent change bypassed deletion row locks"
        finally:
            resume.set()
            await asyncio.wait_for(deletion, 2)
            await deleting.commit()
        if operation == "create":
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                await asyncio.wait_for(changing, 2)
            await concurrent.rollback()
        else:
            await asyncio.wait_for(changing, 2)
            await concurrent.commit()
    rows = first.get("/api/bookmarks").json()
    assert len(rows) == 1
    assert (
        rows[0]["folderId"] == (destination if operation == "create" else third)["id"]
    )
