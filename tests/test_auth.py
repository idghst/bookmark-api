import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_supabase import OWNER, client

HEADERS = {"X-Bookmark-Key": "secret"}


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, "authentication_required"),
        ({"Authorization": "Bearer obsolete-jwt"}, "authentication_required"),
        ({"X-Bookmark-Key": "wrong"}, "invalid_api_key"),
    ],
)
def test_auth_rejects_before_database(monkeypatch, headers, code):
    def handle(request):
        pytest.fail("Unauthenticated request must not reach Supabase")

    response = client(monkeypatch, handle).get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == code


@pytest.mark.parametrize(
    "rows", [[], [{"user_id": OWNER}, {"user_id": "other"}], [{"user_id": None}]]
)
def test_ambiguous_identity_fails_closed(monkeypatch, rows):
    response = client(monkeypatch, lambda request: httpx.Response(200, json=rows)).get(
        "/api/v1/auth/me", headers=HEADERS
    )
    assert response.status_code == 503
    assert response.json()["code"] == "service_identity_unavailable"


def test_explicit_owner_bootstraps_empty_database(monkeypatch):
    def handle(request):
        pytest.fail("Configured owner does not need discovery")

    response = client(monkeypatch, handle, BOOKMARK_USER_ID=OWNER).get(
        "/api/v1/auth/me", headers=HEADERS
    )
    assert response.json() == {"id": OWNER, "email": None}


def test_missing_configured_key_is_rejected():
    response = TestClient(create_app(Settings(BOOKMARK_API_KEY=None))).get(
        "/api/bookmarks", headers=HEADERS
    )
    assert response.json()["code"] == "invalid_api_key"
