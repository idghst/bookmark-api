import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.test_database import client


@pytest.mark.parametrize("path", ["/health", "/health/live"])
def test_liveness(path):
    assert TestClient(create_app()).get(path).json() == {"status": "ok"}


def test_readiness_queries_database(db, app_database_url):
    assert client(app_database_url).get("/health/ready").json() == {"status": "ok"}


def test_readiness_hides_database_failure():
    response = client().get("/health/ready")
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"
    assert "127.0.0.1" not in response.text


def test_factory_and_cors():
    client = TestClient(create_app(Settings()))
    assert client.get("/").json() == {"message": "Bookmark API"}
    response = client.options(
        "/api/bookmarks",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_hidden_on_production_hosts(path):
    assert (
        TestClient(create_app(), base_url="https://api.example.com")
        .get(path)
        .status_code
        == 404
    )
    assert TestClient(create_app()).get(path).status_code == 200


def test_production_serves_liveness_without_database():
    assert (
        TestClient(create_app(), base_url="https://api.example.com")
        .get("/health/live")
        .status_code
        == 200
    )
