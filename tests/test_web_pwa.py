"""Tests for responsive CSS and PWA features."""

import pytest
from fastapi.testclient import TestClient

from src.config import AppConfig
from src.web import create_app


@pytest.fixture
def app(tmp_path):
    config = AppConfig()
    config.database.path = str(tmp_path / "test.db")
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_app(tmp_path):
    """Create a FastAPI app with auth enabled."""
    config = AppConfig()
    config.database.path = str(tmp_path / "test.db")
    config.auth.enabled = True
    config.auth.database_path = str(tmp_path / "auth.db")
    config.auth.session_expiry_hours = 24
    return create_app(config)


@pytest.fixture
def auth_client(auth_app):
    return TestClient(auth_app, base_url="https://testserver")


# ── PWA Manifest ──────────────────────────────────────────────────────────────


class TestPWAManifest:
    def test_manifest_served(self, client):
        res = client.get("/manifest.json")
        assert res.status_code == 200

    def test_manifest_content_type(self, client):
        res = client.get("/manifest.json")
        assert "application/manifest+json" in res.headers["content-type"]

    def test_manifest_valid_json(self, client):
        res = client.get("/manifest.json")
        data = res.json()
        assert isinstance(data, dict)

    def test_manifest_required_fields(self, client):
        data = client.get("/manifest.json").json()
        assert data["name"] == "Chess Trainer"
        assert data["short_name"] == "Chess Trainer"
        assert data["start_url"] == "/"
        assert data["display"] == "standalone"
        assert data["theme_color"] == "#161512"
        assert data["background_color"] == "#161512"

    def test_manifest_has_icons(self, client):
        data = client.get("/manifest.json").json()
        icons = data["icons"]
        assert len(icons) >= 2
        sizes = {icon["sizes"] for icon in icons}
        assert "192x192" in sizes
        assert "512x512" in sizes


# ── Service Worker ────────────────────────────────────────────────────────────


class TestServiceWorker:
    def test_sw_served(self, client):
        res = client.get("/sw.js")
        assert res.status_code == 200

    def test_sw_content_type(self, client):
        res = client.get("/sw.js")
        assert "application/javascript" in res.headers["content-type"]

    def test_sw_allowed_header(self, client):
        res = client.get("/sw.js")
        assert res.headers["service-worker-allowed"] == "/"

    def test_sw_no_cache(self, client):
        res = client.get("/sw.js")
        assert "no-cache" in res.headers.get("cache-control", "")

    def test_sw_has_caching_logic(self, client):
        res = client.get("/sw.js")
        body = res.text
        assert "CACHE_NAME" in body
        assert "caches.open" in body
        assert "install" in body
        assert "activate" in body
        assert "fetch" in body


# ── Responsive CSS ────────────────────────────────────────────────────────────


class TestResponsiveCSS:
    def test_css_has_media_queries(self, client):
        res = client.get("/static/css/style.css")
        assert res.status_code == 200
        css = res.text
        assert "@media" in css
        assert "max-width: 767px" in css

    def test_css_has_hamburger_styles(self, client):
        css = client.get("/static/css/style.css").text
        assert ".nav-toggle-checkbox" in css
        assert ".nav-toggle-label" in css
        assert ".nav-toggle-icon" in css

    def test_css_has_touch_targets(self, client):
        css = client.get("/static/css/style.css").text
        assert "min-height: 44px" in css

    def test_css_has_tablet_breakpoint(self, client):
        css = client.get("/static/css/style.css").text
        assert "min-width: 768px" in css
        assert "max-width: 959px" in css


# ── Base Template ─────────────────────────────────────────────────────────────


class TestBaseTemplate:
    def test_has_manifest_link(self, client):
        html = client.get("/").text
        assert 'rel="manifest"' in html
        assert "/manifest.json" in html

    def test_has_theme_color(self, client):
        html = client.get("/").text
        assert 'name="theme-color"' in html
        assert "#161512" in html

    def test_has_apple_touch_icon(self, client):
        html = client.get("/").text
        assert 'rel="apple-touch-icon"' in html
        assert "/static/icons/icon-192.png" in html

    def test_has_sw_registration(self, client):
        html = client.get("/").text
        assert "serviceWorker" in html
        assert "register" in html
        assert "/sw.js" in html

    def test_has_hamburger_toggle(self, client):
        html = client.get("/").text
        assert 'id="nav-toggle"' in html
        assert 'class="nav-toggle-checkbox"' in html
        assert 'class="nav-toggle-label"' in html

    def test_has_viewport_meta(self, client):
        html = client.get("/").text
        assert 'name="viewport"' in html
        assert "width=device-width" in html

    def test_has_resize_handler(self, client):
        res = client.get("/static/js/training.js")
        assert "resize" in res.text
        assert "board.resize" in res.text


# ── Icons ─────────────────────────────────────────────────────────────────────


class TestIconsExist:
    def test_svg_icon_served(self, client):
        res = client.get("/static/icons/icon.svg")
        assert res.status_code == 200
        assert "svg" in res.headers["content-type"]

    def test_png_192_served(self, client):
        res = client.get("/static/icons/icon-192.png")
        assert res.status_code == 200
        assert "image/png" in res.headers["content-type"]

    def test_png_512_served(self, client):
        res = client.get("/static/icons/icon-512.png")
        assert res.status_code == 200
        assert "image/png" in res.headers["content-type"]


# ── Auth exemption ────────────────────────────────────────────────────────────


class TestPWAAuthExemption:
    def test_sw_accessible_without_auth(self, auth_client):
        res = auth_client.get("/sw.js")
        assert res.status_code == 200
        assert "application/javascript" in res.headers["content-type"]

    def test_manifest_accessible_without_auth(self, auth_client):
        res = auth_client.get("/manifest.json")
        assert res.status_code == 200
        assert "application/manifest+json" in res.headers["content-type"]

    def test_icons_accessible_without_auth(self, auth_client):
        res = auth_client.get("/static/icons/icon.svg")
        assert res.status_code == 200
