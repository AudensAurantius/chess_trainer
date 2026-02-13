"""DuckDB-backed auth storage (separate auth.db)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb

from .models import InviteCode, Session, User


class AuthStore:
    """Manages users, invite codes, and sessions in a dedicated auth database."""

    def __init__(self, db_path: str | Path | None = None):
        """Initialize with optional database path (in-memory if None)."""
        self.db_path = Path(db_path) if db_path else None
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection, initializing schema on first access."""
        if self._conn is None:
            if self.db_path:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = duckdb.connect(str(self.db_path))
            else:
                self._conn = duckdb.connect(":memory:")
            self._init_schema()
        return self._conn

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id VARCHAR PRIMARY KEY,
                username VARCHAR NOT NULL UNIQUE,
                password_hash VARCHAR NOT NULL,
                created_at TIMESTAMP NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS invite_codes (
                code VARCHAR PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                used_by VARCHAR,
                used_at TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL REFERENCES users(id),
                created_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)
        """)

    # ── Users ─────────────────────────────────────────────────────────────

    def create_user(self, user: User) -> None:
        """Insert a new user record."""
        self.conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            [user.id, user.username, user.password_hash, user.created_at, user.is_active],
        )

    def get_user(self, user_id: str) -> User | None:
        """Look up a user by ID."""
        row = self.conn.execute(
            "SELECT id, username, password_hash, created_at, is_active FROM users WHERE id = ?",
            [user_id],
        ).fetchone()
        return self._row_to_user(row) if row else None

    def get_user_by_username(self, username: str) -> User | None:
        """Look up a user by username."""
        row = self.conn.execute(
            "SELECT id, username, password_hash, created_at, is_active "
            "FROM users WHERE username = ?",
            [username],
        ).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        """Return all users ordered by creation time."""
        rows = self.conn.execute(
            "SELECT id, username, password_hash, created_at, is_active "
            "FROM users ORDER BY created_at"
        ).fetchall()
        return [self._row_to_user(r) for r in rows]

    def deactivate_user(self, user_id: str) -> bool:
        """Mark a user as inactive. Returns True if user was found."""
        self.conn.execute("UPDATE users SET is_active = FALSE WHERE id = ?", [user_id])
        return (
            self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE id = ? AND is_active = FALSE", [user_id]
            ).fetchone()[0]
            > 0
        )

    @staticmethod
    def _row_to_user(row: tuple) -> User:
        return User(
            id=row[0],
            username=row[1],
            password_hash=row[2],
            created_at=row[3],
            is_active=row[4],
        )

    # ── Invite codes ──────────────────────────────────────────────────────

    def create_invite(self, invite: InviteCode) -> None:
        """Insert a new invite code."""
        self.conn.execute(
            "INSERT INTO invite_codes (code, created_at, used_by, used_at) VALUES (?, ?, ?, ?)",
            [invite.code, invite.created_at, invite.used_by, invite.used_at],
        )

    def get_invite(self, code: str) -> InviteCode | None:
        """Look up an invite code."""
        row = self.conn.execute(
            "SELECT code, created_at, used_by, used_at FROM invite_codes WHERE code = ?",
            [code],
        ).fetchone()
        if not row:
            return None
        return InviteCode(code=row[0], created_at=row[1], used_by=row[2], used_at=row[3])

    def list_invites(self) -> list[InviteCode]:
        """Return all invite codes ordered by creation time."""
        rows = self.conn.execute(
            "SELECT code, created_at, used_by, used_at FROM invite_codes ORDER BY created_at"
        ).fetchall()
        return [InviteCode(code=r[0], created_at=r[1], used_by=r[2], used_at=r[3]) for r in rows]

    def mark_invite_used(self, code: str, user_id: str, used_at: datetime) -> None:
        """Record that an invite code was redeemed."""
        self.conn.execute(
            "UPDATE invite_codes SET used_by = ?, used_at = ? WHERE code = ?",
            [user_id, used_at, code],
        )

    # ── Sessions ──────────────────────────────────────────────────────────

    def create_session(self, session: Session) -> None:
        """Insert a new session record."""
        self.conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            [session.token, session.user_id, session.created_at, session.expires_at],
        )

    def get_session(self, token: str) -> Session | None:
        """Look up a session by token."""
        row = self.conn.execute(
            "SELECT token, user_id, created_at, expires_at FROM sessions WHERE token = ?",
            [token],
        ).fetchone()
        if not row:
            return None
        return Session(token=row[0], user_id=row[1], created_at=row[2], expires_at=row[3])

    def delete_session(self, token: str) -> None:
        """Delete a single session by token."""
        self.conn.execute("DELETE FROM sessions WHERE token = ?", [token])

    def delete_user_sessions(self, user_id: str) -> int:
        """Delete all sessions for a user. Returns previous count."""
        before = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", [user_id]
        ).fetchone()[0]
        self.conn.execute("DELETE FROM sessions WHERE user_id = ?", [user_id])
        return before

    def cleanup_expired(self, now: datetime) -> int:
        """Remove expired sessions. Returns count deleted."""
        count = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE expires_at < ?", [now]
        ).fetchone()[0]
        self.conn.execute("DELETE FROM sessions WHERE expires_at < ?", [now])
        return count

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> AuthStore:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
