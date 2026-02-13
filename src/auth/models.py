"""Auth domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class User:
    """A registered user."""

    id: str
    username: str
    password_hash: str
    created_at: datetime
    is_active: bool = True


@dataclass
class InviteCode:
    """A single-use invite code for registration."""

    code: str
    created_at: datetime
    used_by: str | None = None
    used_at: datetime | None = None


@dataclass
class Session:
    """An authenticated session tied to a user."""

    token: str
    user_id: str
    created_at: datetime
    expires_at: datetime
