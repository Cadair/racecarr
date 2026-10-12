import pytest
from fastapi.testclient import TestClient
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.fixture
def base_path_client(monkeypatch):
    monkeypatch.setenv("BASE_PATH", "/racecarr")
    from app.core.config import get_settings
    get_settings.cache_clear()
    from app.main import create_app
    app = create_app()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_api_routes_under_base_path(base_path_client: TestClient) -> None:
    resp = base_path_client.get("/racecarr/api/healthz")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


def test_api_routes_not_at_root(base_path_client: TestClient) -> None:
    resp = base_path_client.get("/api/healthz")
    assert resp.status_code == 404


def test_openapi_under_base_path(base_path_client: TestClient) -> None:
    resp = base_path_client.get("/racecarr/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["paths"]["/racecarr/api/healthz"]


@pytest.mark.skipif(not STATIC_DIR.exists(), reason="frontend not built")
def test_spa_index_serves_base_path_script(base_path_client: TestClient) -> None:
    resp = base_path_client.get("/racecarr/")
    assert resp.status_code == 200
    assert "window.__BASE_PATH__" in resp.text
    assert '"/racecarr"' in resp.text


def test_cookie_path_scoped(base_path_client: TestClient) -> None:
    resp = base_path_client.post(
        "/racecarr/api/auth/login",
        json={"password": "admin", "remember_me": False},
    )
    assert resp.status_code == 200
    cookie_header = resp.headers.get("set-cookie", "")
    assert "path=/racecarr" in cookie_header.lower()
