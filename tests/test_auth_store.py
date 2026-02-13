"""Tests for AuthStore (DuckDB auth database)."""

from datetime import UTC, datetime, timedelta

import pytest

from src.auth.models import InviteCode, Session, User
from src.auth.store import AuthStore


@pytest.fixture
def store():
    with AuthStore() as s:
        yield s


def _make_user(username: str = "alice", user_id: str = "uid-1") -> User:
    return User(
        id=user_id,
        username=username,
        password_hash="pbkdf2_sha256$600000$aabb$ccdd",
        created_at=datetime.now(UTC),
    )


class TestUsers:
    def test_create_and_get(self, store):
        user = _make_user()
        store.create_user(user)
        got = store.get_user("uid-1")
        assert got is not None
        assert got.username == "alice"
        assert got.is_active is True

    def test_get_nonexistent(self, store):
        assert store.get_user("nope") is None

    def test_get_by_username(self, store):
        store.create_user(_make_user())
        got = store.get_user_by_username("alice")
        assert got is not None
        assert got.id == "uid-1"

    def test_get_by_username_nonexistent(self, store):
        assert store.get_user_by_username("nope") is None

    def test_unique_username(self, store):
        store.create_user(_make_user("alice", "uid-1"))
        with pytest.raises(Exception):  # DuckDB constraint violation
            store.create_user(_make_user("alice", "uid-2"))

    def test_list_users(self, store):
        store.create_user(_make_user("alice", "uid-1"))
        store.create_user(_make_user("bob", "uid-2"))
        users = store.list_users()
        assert len(users) == 2
        assert users[0].username == "alice"

    def test_deactivate_user(self, store):
        store.create_user(_make_user())
        assert store.deactivate_user("uid-1") is True
        user = store.get_user("uid-1")
        assert user.is_active is False

    def test_deactivate_nonexistent(self, store):
        assert store.deactivate_user("nope") is False


class TestInviteCodes:
    def test_create_and_get(self, store):
        invite = InviteCode(code="abc123", created_at=datetime.now(UTC))
        store.create_invite(invite)
        got = store.get_invite("abc123")
        assert got is not None
        assert got.used_by is None

    def test_get_nonexistent(self, store):
        assert store.get_invite("nope") is None

    def test_list_invites(self, store):
        store.create_invite(InviteCode(code="a", created_at=datetime.now(UTC)))
        store.create_invite(InviteCode(code="b", created_at=datetime.now(UTC)))
        assert len(store.list_invites()) == 2

    def test_mark_used(self, store):
        now = datetime.now(UTC)
        store.create_invite(InviteCode(code="inv1", created_at=now))
        store.mark_invite_used("inv1", "uid-1", now)
        got = store.get_invite("inv1")
        assert got.used_by == "uid-1"
        assert got.used_at is not None


class TestSessions:
    def _make_session(self, store, user_id: str = "uid-1") -> Session:
        store.create_user(_make_user(user_id=user_id))
        now = datetime.now(UTC)
        session = Session(
            token="tok123",
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        store.create_session(session)
        return session

    def test_create_and_get(self, store):
        self._make_session(store)
        got = store.get_session("tok123")
        assert got is not None
        assert got.user_id == "uid-1"

    def test_get_nonexistent(self, store):
        assert store.get_session("nope") is None

    def test_delete_session(self, store):
        self._make_session(store)
        store.delete_session("tok123")
        assert store.get_session("tok123") is None

    def test_delete_user_sessions(self, store):
        self._make_session(store)
        count = store.delete_user_sessions("uid-1")
        assert count == 1
        assert store.get_session("tok123") is None

    def test_cleanup_expired(self, store):
        store.create_user(_make_user())
        now = datetime.now(UTC)
        expired = Session(
            token="old",
            user_id="uid-1",
            created_at=now - timedelta(hours=48),
            expires_at=now - timedelta(hours=24),
        )
        valid = Session(
            token="new",
            user_id="uid-1",
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        store.create_session(expired)
        store.create_session(valid)
        cleaned = store.cleanup_expired(now)
        assert cleaned == 1
        assert store.get_session("old") is None
        assert store.get_session("new") is not None
