import asyncio

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
            json=[{"user_id": OWNER}],
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


def test_owner_discovery_rejects_foreign_owner_at_other_bound(monkeypatch):
    def handle(request):
        owner = OWNER if request.url.params["order"] == "user_id.asc" else "other"
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


def test_app_reuses_transport_and_closes_it_at_shutdown(monkeypatch):
    from app.integrations import supabase

    created = []
    factory = supabase.create_client

    def track(settings):
        transport = factory(settings)
        created.append(transport)
        return transport

    instance = client(
        monkeypatch,
        lambda request: httpx.Response(200, json=[]),
        BOOKMARK_USER_ID=OWNER,
    )
    factory = supabase.create_client
    monkeypatch.setattr(supabase, "create_client", track)
    with instance:
        for path in (
            "/api/bookmarks",
            "/api/folders",
            "/api/sections",
            "/api/folder-sections",
            "/health/ready",
        ):
            assert (
                instance.get(path, headers={"X-Bookmark-Key": "secret"}).status_code
                == 200
            )
        assert len(created) == 1
        assert not created[0].is_closed
    assert created[0].is_closed


async def test_owner_discovery_is_bounded_and_parallel():
    from app.integrations.supabase import service_user_id

    requests = []
    active = 0
    peak = 0

    async def handle(request):
        nonlocal active, peak
        requests.append(request)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        offset = int(request.url.params.get("offset", "0"))
        limit = min(int(request.url.params["limit"]), 500)
        return httpx.Response(
            200,
            json=[{"user_id": OWNER} for _ in range(min(limit, max(0, 2500 - offset)))],
        )

    async with httpx.AsyncClient(
        base_url="https://db.example.com/", transport=httpx.MockTransport(handle)
    ) as transport:
        assert (
            await service_user_id(transport, Settings(BOOKMARK_USER_ID=None)) == OWNER
        )
    assert len(requests) == 8
    assert all(request.url.params["limit"] == "1" for request in requests)
    assert peak == 4


@pytest.mark.parametrize("foreign", ["00000000-0000-0000-0000-000000000002", None])
def test_owner_bounds_detect_invalid_owner_beyond_server_page_cap(monkeypatch, foreign):
    # Honor the actual PostgREST ordering/limit: the bad row is far beyond the
    # old first page, but is visible at the descending bound.
    data = [{"user_id": OWNER}] * 1500 + [{"user_id": foreign}]

    def handle(request):
        rows = data if request.url.path.endswith("items") else [{"user_id": OWNER}]
        descending = request.url.params["order"] == "user_id.desc"
        rows = sorted(
            rows,
            key=lambda row: (row["user_id"] is None, row["user_id"] or ""),
            reverse=descending,
        )
        return httpx.Response(200, json=rows[: int(request.url.params["limit"])])

    response = client(monkeypatch, handle).get(
        "/api/v1/auth/me", headers={"X-Bookmark-Key": "secret"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "service_identity_unavailable"


def test_owner_discovery_rechecks_after_database_owner_changes(monkeypatch):
    owner = OWNER

    def handle(request):
        value = owner if request.url.path.endswith("folder_sections") else OWNER
        return httpx.Response(200, json=[{"user_id": value}])

    with client(monkeypatch, handle) as instance:
        assert (
            instance.get(
                "/api/v1/auth/me", headers={"X-Bookmark-Key": "secret"}
            ).status_code
            == 200
        )
        owner = "00000000-0000-0000-0000-000000000002"
        assert (
            instance.get(
                "/api/v1/auth/me", headers={"X-Bookmark-Key": "secret"}
            ).status_code
            == 503
        )


async def test_discovery_error_waits_for_other_reads():
    from app.core.errors import ApiError
    from app.integrations.supabase import service_user_id

    active = 0

    async def handle(request):
        nonlocal active
        if request.url.path.endswith("items"):
            raise httpx.ReadTimeout("test-only", request=request)
        active += 1
        try:
            await asyncio.sleep(0.01)
            return httpx.Response(200, json=[])
        finally:
            active -= 1

    async with httpx.AsyncClient(
        base_url="https://db.example.com/", transport=httpx.MockTransport(handle)
    ) as transport:
        with pytest.raises(ApiError) as error:
            await service_user_id(transport, Settings(BOOKMARK_USER_ID=None))
        assert error.value.code == "database_unavailable"
        assert active == 0


async def test_concurrent_requests_keep_shared_transport_open(monkeypatch):
    instance = client(
        monkeypatch,
        lambda request: httpx.Response(200, json=[]),
        BOOKMARK_USER_ID=OWNER,
    )
    app = instance.app
    async with app.router.lifespan_context(app):
        shared = app.state.database_client
        async with httpx.AsyncClient(
            base_url="http://test", transport=httpx.ASGITransport(app=app)
        ) as api:
            responses = await asyncio.gather(
                *(
                    api.get("/api/bookmarks", headers={"X-Bookmark-Key": "secret"})
                    for _ in range(8)
                )
            )
        assert all(response.status_code == 200 for response in responses)
        assert not shared.is_closed
    assert shared.is_closed


def test_ambiguous_owner_keeps_priority_over_later_database_error(monkeypatch):
    def handle(request):
        if request.url.path.endswith("items"):
            owner = (
                OWNER
                if request.url.params["order"] == "user_id.asc"
                else "00000000-0000-0000-0000-000000000002"
            )
            return httpx.Response(200, json=[{"user_id": owner}])
        return httpx.Response(403, json={"code": "42501"})

    response = client(monkeypatch, handle).get(
        "/api/v1/auth/me", headers={"X-Bookmark-Key": "secret"}
    )
    assert response.status_code == 503
    assert response.json()["code"] == "service_identity_unavailable"
