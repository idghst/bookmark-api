import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_database import HEADERS, client


@pytest.mark.parametrize(
    "headers,code",
    [
        ({}, "authentication_required"),
        ({"Authorization": "Bearer obsolete-jwt"}, "authentication_required"),
        ({"X-Bookmark-Key": "wrong"}, "invalid_api_key"),
    ],
)
def test_auth_rejects_before_database(headers, code):
    # The configured database is unreachable: a 401 proves no connection was made.
    response = client().get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == code


def test_missing_configured_key_is_rejected():
    response = TestClient(create_app(Settings(BOOKMARK_API_KEY=None))).get(
        "/api/bookmarks", headers=HEADERS
    )
    assert response.json()["code"] == "invalid_api_key"
