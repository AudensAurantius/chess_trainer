"""Auth business logic: registration, login, session management."""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta

from .models import InviteCode, Session, User
from .passwords import hash_password, verify_password
from .store import AuthStore

# ── Exceptions ────────────────────────────────────────────────────────────────

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{2,32}$")
_MIN_PASSWORD_LENGTH = 8


class AuthError(Exception):
    """Base auth error."""


class InvalidInviteCodeError(AuthError):
    """Invite code does not exist."""


class InviteCodeAlreadyUsedError(AuthError):
    """Invite code has already been redeemed."""


class UsernameAlreadyExistsError(AuthError):
    """Username is taken."""


class InvalidUsernameError(AuthError):
    """Username doesn't match requirements."""


class WeakPasswordError(AuthError):
    """Password is too short or weak."""


class InvalidCredentialsError(AuthError):
    """Wrong username or password."""


class InactiveAccountError(AuthError):
    """Account has been deactivated."""


# ── Service ───────────────────────────────────────────────────────────────────


class AuthService:
    """Orchestrates registration, login, and session lifecycle."""

    def __init__(self, store: AuthStore, session_expiry_hours: int = 720):
        """Initialize with an auth store and session expiry duration."""
        self.store = store
        self.session_expiry_hours = session_expiry_hours

    def register(self, username: str, password: str, invite_code: str) -> User:
        """Register a new user with an invite code.

        Raises:
            InvalidInviteCodeError: Code does not exist.
            InviteCodeAlreadyUsedError: Code already redeemed.
            InvalidUsernameError: Bad format.
            UsernameAlreadyExistsError: Username taken.
            WeakPasswordError: Password too short.
        """
        # Validate invite
        invite = self.store.get_invite(invite_code)
        if invite is None:
            raise InvalidInviteCodeError("Invalid invite code")
        if invite.used_by is not None:
            raise InviteCodeAlreadyUsedError("Invite code already used")

        # Validate username
        if not _USERNAME_RE.match(username):
            raise InvalidUsernameError(
                "Username must be 2-32 characters: letters, digits, hyphens, underscores"
            )
        if self.store.get_user_by_username(username) is not None:
            raise UsernameAlreadyExistsError(f"Username '{username}' is already taken")

        # Validate password
        if len(password) < _MIN_PASSWORD_LENGTH:
            raise WeakPasswordError(f"Password must be at least {_MIN_PASSWORD_LENGTH} characters")

        now = datetime.now(UTC)
        user = User(
            id=secrets.token_urlsafe(16),
            username=username,
            password_hash=hash_password(password),
            created_at=now,
        )
        self.store.create_user(user)
        self.store.mark_invite_used(invite_code, user.id, now)
        return user

    def login(self, username: str, password: str) -> Session:
        """Authenticate and create a session.

        Raises:
            InvalidCredentialsError: Wrong username or password.
            InactiveAccountError: Account deactivated.
        """
        user = self.store.get_user_by_username(username)
        if user is None:
            raise InvalidCredentialsError("Invalid username or password")
        if not user.is_active:
            raise InactiveAccountError("Account is deactivated")
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Invalid username or password")

        now = datetime.now(UTC)
        session = Session(
            token=secrets.token_urlsafe(32),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(hours=self.session_expiry_hours),
        )
        self.store.create_session(session)
        return session

    def logout(self, session_token: str) -> None:
        """Delete a session."""
        self.store.delete_session(session_token)

    def validate_session(self, session_token: str) -> User | None:
        """Check a session token and return the user, or None if invalid/expired."""
        session = self.store.get_session(session_token)
        if session is None:
            return None
        # DuckDB returns naive datetimes; compare in naive UTC
        now = datetime.now(UTC).replace(tzinfo=None)
        if session.expires_at.replace(tzinfo=None) < now:
            self.store.delete_session(session_token)
            return None
        user = self.store.get_user(session.user_id)
        if user is None or not user.is_active:
            return None
        return user

    def create_invite_code(self) -> str:
        """Generate and store a new invite code."""
        code = secrets.token_urlsafe(16)
        self.store.create_invite(InviteCode(code=code, created_at=datetime.now(UTC)))
        return code
