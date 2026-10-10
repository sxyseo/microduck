"""Cross-origin browser access (Cloudflare Pages frontend -> local API) stays opt-in.

Without MICRODUCK_STUDIO_ALLOWED_ORIGINS the app behaves exactly as before: no CORS headers,
so pages from other origins cannot read responses. When configured, preflights — including
Chrome's Private Network Access preflight for public pages calling 127.0.0.1 — are answered,
and disallowed origins stay rejected.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from microduck_studio.app import add_browser_origins, allowed_browser_origins


def build_app(origins: list[str]) -> FastAPI:
    app = FastAPI()
    add_browser_origins(app, origins)

    @app.get("/api/version")
    def version():
        return {"version": "test"}

    @app.post("/api/projects")
    def create():
        return {"id": "p1"}

    return app


def test_no_origins_configured_by_default(monkeypatch):
    monkeypatch.delenv("MICRODUCK_STUDIO_ALLOWED_ORIGINS", raising=False)
    assert allowed_browser_origins() == []


def test_origins_parse_and_trim(monkeypatch):
    monkeypatch.setenv(
        "MICRODUCK_STUDIO_ALLOWED_ORIGINS",
        " https://a.pages.dev , https://b.example.com/ ",
    )
    assert allowed_browser_origins() == ["https://a.pages.dev", "https://b.example.com"]


def test_allowed_origin_gets_cors_and_private_network_headers():
    client = TestClient(build_app(["https://studio.pages.dev"]))
    preflight = client.options(
        "/api/projects",
        headers={
            "Origin": "https://studio.pages.dev",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "https://studio.pages.dev"
    assert preflight.headers["access-control-allow-private-network"] == "true"
    assert "POST" in preflight.headers["access-control-allow-methods"]

    actual = client.post(
        "/api/projects",
        json={},
        headers={"Origin": "https://studio.pages.dev"},
    )
    assert actual.status_code == 200
    assert actual.headers["access-control-allow-origin"] == "https://studio.pages.dev"


def test_disallowed_origin_gets_no_allow_header():
    client = TestClient(build_app(["https://studio.pages.dev"]))
    response = client.get("/api/version", headers={"Origin": "https://evil.pages.dev"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_lookalike_suffix_origin_is_rejected():
    # Exact-match allow-list: studio.pages.dev must not open the door to other *.pages.dev sites.
    client = TestClient(build_app(["https://studio.pages.dev"]))
    response = client.get("/api/version", headers={"Origin": "https://notstudio.pages.dev"})
    assert "access-control-allow-origin" not in response.headers


def test_default_app_has_no_cors_middleware(monkeypatch):
    monkeypatch.delenv("MICRODUCK_STUDIO_ALLOWED_ORIGINS", raising=False)
    from microduck_studio.app import app as default_app

    response = TestClient(default_app).get(
        "/api/version", headers={"Origin": "https://studio.pages.dev"}
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
