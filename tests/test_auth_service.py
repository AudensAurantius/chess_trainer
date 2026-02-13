"""Tests for AuthService (business logic)."""

from datetime import UTC, datetime, timedelta

import pytest

from src.auth.service import (
    AuthService,
    InactiveAccountError,
    InvalidCredentialsError,
    InvalidInviteCodeError,
    InvalidUsernameError,
    InviteCodeAlreadyUsedError,
    UsernameAlreadyExistsError,
    WeakPasswordError,
)
from src.auth.store import AuthStore


@pytest.fixture
def store():
    with AuthStore() as s:
        yield s


@pytest.fixture
def svc(store):
    return AuthService(store, session_expiry_hours=24)


@pytest.fixture
def invite_code(svc):
    return svc.create_invite_code()


class TestRegister:
    def test_success(self, svc, invite_code):
        user = svc.register("alice", "password123", invite_code)
        assert user.username == "alice"
        assert user.is_active is True
        # Invite should be marked used
        invite = svc.store.get_invite(invite_code)
        assert invite.used_by == user.id

    def test_invalid_invite(self, svc):
        with pytest.raises(InvalidInviteCodeError):
            svc.register("alice", "password123", "bad-code")

    def test_used_invite(self, svc, invite_code):
        svc.register("alice", "password123", invite_code)
        with pytest.raises(InviteCodeAlreadyUsedError):
            svc.register("bob", "password456", invite_code)

    def test_duplicate_username(self, svc):
        code1 = svc.create_invite_code()
        code2 = svc.create_invite_code()
        svc.register("alice", "password123", code1)
        with pytest.raises(UsernameAlreadyExistsError):
            svc.register("alice", "password456", code2)

    def test_invalid_username_too_short(self, svc, invite_code):
        with pytest.raises(InvalidUsernameError):
            svc.register("a", "password123", invite_code)

    def test_invalid_username_bad_chars(self, svc, invite_code):
        with pytest.raises(InvalidUsernameError):
            svc.register("al!ce", "password123", invite_code)

    def test_weak_password(self, svc, invite_code):
        with pytest.raises(WeakPasswordError):
            svc.register("alice", "short", invite_code)

    def test_valid_username_with_hyphens_underscores(self, svc, invite_code):
        user = svc.register("my-user_01", "password123", invite_code)
        assert user.username == "my-user_01"


class TestLogin:
    def test_success(self, svc, invite_code):
        svc.register("alice", "password123", invite_code)
        session = svc.login("alice", "password123")
        assert session.token
        assert session.user_id

    def test_wrong_password(self, svc, invite_code):
        svc.register("alice", "password123", invite_code)
        with pytest.raises(InvalidCredentialsError):
            svc.login("alice", "wrong")

    def test_nonexistent_user(self, svc):
        with pytest.raises(InvalidCredentialsError):
            svc.login("nobody", "password123")

    def test_deactivated_user(self, svc, invite_code):
        user = svc.register("alice", "password123", invite_code)
        svc.store.deactivate_user(user.id)
        with pytest.raises(InactiveAccountError):
            svc.login("alice", "password123")


class TestSessionManagement:
    def test_validate_valid_session(self, svc, invite_code):
        svc.register("alice", "password123", invite_code)
        session = svc.login("alice", "password123")
        user = svc.validate_session(session.token)
        assert user is not None
        assert user.username == "alice"

    def test_validate_invalid_token(self, svc):
        assert svc.validate_session("bad-token") is None

    def test_validate_expired_session(self, svc, invite_code):
        svc.register("alice", "password123", invite_code)
        session = svc.login("alice", "password123")
        # Manually expire the session
        svc.store.conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE token = ?",
            [datetime.now(UTC) - timedelta(hours=1), session.token],
        )
        assert svc.validate_session(session.token) is None

    def test_validate_deactivated_user(self, svc, invite_code):
        user = svc.register("alice", "password123", invite_code)
        session = svc.login("alice", "password123")
        svc.store.deactivate_user(user.id)
        assert svc.validate_session(session.token) is None

    def test_logout(self, svc, invite_code):
        svc.register("alice", "password123", invite_code)
        session = svc.login("alice", "password123")
        svc.logout(session.token)
        assert svc.validate_session(session.token) is None

    def test_create_invite_code(self, svc):
        code = svc.create_invite_code()
        assert len(code) > 10
        invite = svc.store.get_invite(code)
        assert invite is not None
        assert invite.used_by is None
