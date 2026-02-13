"""Per-user SessionManager pool for multi-tenant web access."""

from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from .session_manager import SessionManager


def resolve_db_path(config: AppConfig, user_id: str | None) -> Path:
    """Determine the database path for a user.

    Args:
        config: Application configuration.
        user_id: Authenticated user ID, or None when auth is disabled.

    Returns:
        Path to the user's DuckDB file:
        - auth enabled + user_id: ``{data_dir}/{user_id}/trainer.db``
        - auth disabled / no user: ``config.database.path`` (unchanged default)
    """
    if config.auth.enabled and user_id is not None:
        return Path(config.database.data_dir) / user_id / "trainer.db"
    return Path(config.database.path)


class ManagerPool:
    """Maps user IDs to SessionManager instances.

    Lazily creates managers on first access. Designed for the single-process
    async FastAPI model (no concurrent mutations).
    """

    def __init__(self, config: AppConfig) -> None:
        """Initialize pool with the application config."""
        self._config = config
        self._managers: dict[str, SessionManager] = {}

    def get(self, user_id: str | None) -> SessionManager:
        """Get or create a SessionManager for the given user.

        Args:
            user_id: Authenticated user ID, or None for the default manager.

        Returns:
            SessionManager backed by the user's database file.
        """
        key = user_id or "_default"
        if key not in self._managers:
            db_path = resolve_db_path(self._config, user_id)
            self._managers[key] = SessionManager(self._config, db_path=db_path)
        return self._managers[key]

    def close_all(self) -> None:
        """Close all managers. Called on app shutdown."""
        for manager in self._managers.values():
            manager.end_session()
        self._managers.clear()

    def remove(self, user_id: str) -> None:
        """Remove and close a specific user's manager (e.g. on logout)."""
        key = user_id or "_default"
        if key in self._managers:
            self._managers[key].end_session()
            del self._managers[key]
