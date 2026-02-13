"""Integration tests for web authentication."""

import pytest
from fastapi.testclient import TestClient

from src.auth.service import AuthService
from src.auth.store import AuthStore
from src.config import AppConfig
from src.web import create_app


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
    return TestClient(auth_app)


@pytest.fixture
def no_auth_app(tmp_path):
    """Create a FastAPI app with auth disabled (default)."""
    config = AppConfig()
    config.database.path = str(tmp_path / "test.db")
    return create_app(config)


@pytest.fixture
def no_auth_client(no_auth_app):
    return TestClient(no_auth_app)


@pytest.fixture
def seeded_auth(auth_app):
    """Pre-create an invite code and registered user."""
    svc: AuthService = auth_app.state.auth_service
    invite_code = svc.create_invite_code()
    user = svc.register("testuser", "password123", invite_code)
    return {"user": user, "invite_code": invite_code}


@pytest.fixture
def seeded_auth_client(auth_app, seeded_auth):
    """Client with a pre-registered user (not logged in)."""
    return TestClient(auth_app)


@pytest.fixture
def logged_in_client(auth_app, seeded_auth):
    """Client that is already logged in."""
    client = TestClient(auth_app)
    resp = client.post(
        "/login",
        data={"username": "testuser", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return client


# ── Backward compatibility (auth disabled) ───────────────────────────────────


class TestAuthDisabled:
    def test_dashboard_accessible(self, no_auth_client):
        resp = no_auth_client.get("/")
        assert resp.status_code == 200
        assert "Chess Trainer" in resp.text

    def test_api_accessible(self, no_auth_client):
        resp = no_auth_client.get("/api/stats")
        assert resp.status_code == 200

    def test_login_page_accessible(self, no_auth_client):
        resp = no_auth_client.get("/login")
        assert resp.status_code == 200

    def test_register_page_accessible(self, no_auth_client):
        resp = no_auth_client.get("/register")
        assert resp.status_code == 200


# ── Middleware (auth enabled, not logged in) ─────────────────────────────────


class TestMiddleware:
    def test_html_redirects_to_login(self, auth_client):
        resp = auth_client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_api_returns_401(self, auth_client):
        resp = auth_client.get("/api/stats")
        assert resp.status_code == 401
        assert resp.json()["error"] == "Authentication required"

    def test_login_page_exempt(self, auth_client):
        resp = auth_client.get("/login")
        assert resp.status_code == 200
        assert "Login" in resp.text

    def test_register_page_exempt(self, auth_client):
        resp = auth_client.get("/register")
        assert resp.status_code == 200
        assert "Register" in resp.text

    def test_static_exempt(self, auth_client):
        resp = auth_client.get("/static/css/style.css")
        assert resp.status_code == 200

    def test_favicon_exempt(self, auth_client):
        resp = auth_client.get("/favicon.ico")
        # 404 is fine, just shouldn't be 302/401
        assert resp.status_code != 302
        assert resp.status_code != 401


# ── Registration flow ────────────────────────────────────────────────────────


class TestRegistration:
    def test_valid_registration(self, auth_app, auth_client):
        svc: AuthService = auth_app.state.auth_service
        code = svc.create_invite_code()

        resp = auth_client.post(
            "/register",
            data={
                "invite_code": code,
                "username": "newuser",
                "password": "password123",
                "confirm_password": "password123",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
        assert "session_token" in resp.cookies

    def test_invalid_invite(self, auth_client):
        resp = auth_client.post(
            "/register",
            data={
                "invite_code": "bad-code",
                "username": "user",
                "password": "password123",
                "confirm_password": "password123",
            },
        )
        assert resp.status_code == 400
        assert "Invalid invite code" in resp.text

    def test_used_invite(self, auth_app, seeded_auth_client, seeded_auth):
        # The invite from seeded_auth is already used
        svc: AuthService = auth_app.state.auth_service
        code = svc.create_invite_code()
        # Use it first
        svc.register("first", "password123", code)

        resp = seeded_auth_client.post(
            "/register",
            data={
                "invite_code": code,
                "username": "second",
                "password": "password123",
                "confirm_password": "password123",
            },
        )
        assert resp.status_code == 400
        assert "already used" in resp.text

    def test_duplicate_username(self, auth_app, seeded_auth_client, seeded_auth):
        svc: AuthService = auth_app.state.auth_service
        code = svc.create_invite_code()

        resp = seeded_auth_client.post(
            "/register",
            data={
                "invite_code": code,
                "username": "testuser",  # already exists
                "password": "password123",
                "confirm_password": "password123",
            },
        )
        assert resp.status_code == 400
        assert "already taken" in resp.text

    def test_weak_password(self, auth_app, auth_client):
        svc: AuthService = auth_app.state.auth_service
        code = svc.create_invite_code()

        resp = auth_client.post(
            "/register",
            data={
                "invite_code": code,
                "username": "user",
                "password": "short",
                "confirm_password": "short",
            },
        )
        assert resp.status_code == 400
        assert "at least 8" in resp.text

    def test_password_mismatch(self, auth_app, auth_client):
        svc: AuthService = auth_app.state.auth_service
        code = svc.create_invite_code()

        resp = auth_client.post(
            "/register",
            data={
                "invite_code": code,
                "username": "user",
                "password": "password123",
                "confirm_password": "password456",
            },
        )
        assert resp.status_code == 400
        assert "do not match" in resp.text


# ── Login flow ───────────────────────────────────────────────────────────────


class TestLogin:
    def test_valid_login(self, seeded_auth_client, seeded_auth):
        resp = seeded_auth_client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/"
        assert "session_token" in resp.cookies

    def test_wrong_password(self, seeded_auth_client, seeded_auth):
        resp = seeded_auth_client.post(
            "/login",
            data={"username": "testuser", "password": "wrong"},
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.text

    def test_nonexistent_user(self, auth_client):
        resp = auth_client.post(
            "/login",
            data={"username": "nobody", "password": "password123"},
        )
        assert resp.status_code == 400

    def test_deactivated_user(self, auth_app, seeded_auth_client, seeded_auth):
        store: AuthStore = auth_app.state.auth_store
        store.deactivate_user(seeded_auth["user"].id)

        resp = seeded_auth_client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
        )
        assert resp.status_code == 400
        assert "deactivated" in resp.text.lower()


# ── Session flow ─────────────────────────────────────────────────────────────


class TestSessionFlow:
    def test_authenticated_request(self, logged_in_client):
        resp = logged_in_client.get("/")
        assert resp.status_code == 200
        assert "Chess Trainer" in resp.text

    def test_authenticated_api(self, logged_in_client):
        resp = logged_in_client.get("/api/stats")
        assert resp.status_code == 200

    def test_logout_clears_session(self, logged_in_client):
        resp = logged_in_client.post("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

        # After logout, should redirect
        resp = logged_in_client.get("/", follow_redirects=False)
        assert resp.status_code == 302

    def test_expired_session_redirects(self, auth_app, seeded_auth):
        """Manually expire a session and verify redirect."""
        from datetime import UTC, datetime, timedelta

        svc: AuthService = auth_app.state.auth_service
        session = svc.login("testuser", "password123")

        # Expire the session
        svc.store.conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?",
            [datetime.now(UTC) - timedelta(hours=1), session.token],
        )

        client = TestClient(auth_app, cookies={"session_token": session.token})
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    def test_navbar_shows_username(self, logged_in_client):
        resp = logged_in_client.get("/")
        assert "testuser" in resp.text
        assert "Logout" in resp.text
