import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

OWNER = "00000000-0000-0000-0000-000000000001"


def client(monkeypatch, handler, **kwargs):
    from app.integrations import supabase

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        supabase,
        "create_client",
        lambda settings: original(
            base_url="https://db.example.com/rest/v1/",
            transport=transport,
            headers={"Accept-Profile": "bookmark", "Content-Profile": "bookmark"},
        ),
    )
    return TestClient(
        create_app(
            Settings(
                SUPABASE_URL="https://db.example.com",
                SUPABASE_SECRET_KEY="private",
                BOOKMARK_API_KEY="secret",
                **kwargs,
            )
        )
    )


def test_http_owner_discovery_checks_every_table(monkeypatch):
    paths = []

    def handle(request):
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json=[{"user_id": OWNER}] if request.url.params["offset"] == "0" else [],
        )

    response = client(monkeypatch, handle).get(
        "/api/v1/auth/me", headers={"X-Bookmark-Key": "secret"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == OWNER
    assert set(paths) == {
        "/rest/v1/" + name
        for name in ("items", "folders", "sections", "folder_sections")
    }


def test_http_read_is_owner_scoped(monkeypatch):
    def handle(request):
        assert request.url.params["user_id"] == "eq." + OWNER
        return httpx.Response(200, json=[])

    response = client(monkeypatch, handle, BOOKMARK_USER_ID=OWNER).get(
        "/api/bookmarks", headers={"X-Bookmark-Key": "secret"}
    )
    assert response.status_code == 200
    assert response.json() == []


async def test_transport_profiles_credentials_and_timeout():
    from app.integrations.supabase import create_client

    async with create_client(
        Settings(SUPABASE_SECRET_KEY="test-only", SUPABASE_TIMEOUT_SECONDS=7)
    ) as transport:
        assert transport.headers["apikey"] == "test-only"
        assert transport.headers["Authorization"] == "Bearer test-only"
        assert transport.headers["Accept-Profile"] == "bookmark"
        assert transport.headers["Content-Profile"] == "bookmark"
        assert transport.headers["Prefer"] == "return=representation"
        assert transport.timeout.read == 7


async def test_pagination_continues_beyond_server_cap():
    from app.integrations.supabase import select

    offsets = []

    def handle(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        return httpx.Response(
            200, json=[{"id": str(i)} for i in range(offset, min(offset + 500, 1205))]
        )

    async with httpx.AsyncClient(
        base_url="https://db.example.com/", transport=httpx.MockTransport(handle)
    ) as transport:
        rows = await select(transport, "items", {"order": "position,id"})
    assert len(rows) == 1205
    assert offsets == [0, 500, 1000, 1205]


def test_owner_discovery_rejects_foreign_owner_on_later_page(monkeypatch):
    def handle(request):
        owner = OWNER if request.url.params["offset"] == "0" else "other"
        return httpx.Response(200, json=[{"user_id": owner}])

    response = client(monkeypatch, handle).get(
        "/api/v1/auth/me", headers={"X-Bookmark-Key": "secret"}
    )
    assert response.status_code == 503


@pytest.mark.parametrize("status", [401, 403])
def test_http_credentials_errors_are_sanitized(monkeypatch, status):
    response = client(
        monkeypatch,
        lambda request: httpx.Response(status, text="private"),
        BOOKMARK_USER_ID=OWNER,
    ).get("/api/bookmarks", headers={"X-Bookmark-Key": "secret"})
    assert response.status_code == 403
    assert response.json()["code"] == "database_access_denied"
    assert "private" not in response.text


def test_network_error_is_sanitized(monkeypatch):
    def handle(request):
        raise httpx.ReadTimeout("private upstream credentials", request=request)

    response = client(monkeypatch, handle, BOOKMARK_USER_ID=OWNER).get(
        "/api/bookmarks", headers={"X-Bookmark-Key": "secret"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert "private" not in response.text
