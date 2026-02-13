"""Tests for the per-user ManagerPool and resolve_db_path."""

from pathlib import Path

import pytest

from src.config import AppConfig
from src.web.manager_pool import ManagerPool, resolve_db_path


@pytest.fixture
def config(tmp_path):
    """AppConfig with auth disabled (default)."""
    cfg = AppConfig()
    cfg.database.path = str(tmp_path / "trainer.db")
    cfg.database.data_dir = str(tmp_path / "data")
    return cfg


@pytest.fixture
def auth_config(tmp_path):
    """AppConfig with auth enabled."""
    cfg = AppConfig()
    cfg.database.path = str(tmp_path / "trainer.db")
    cfg.database.data_dir = str(tmp_path / "data")
    cfg.auth.enabled = True
    cfg.auth.database_path = str(tmp_path / "auth.db")
    return cfg


# ── resolve_db_path ──────────────────────────────────────────────────────────


class TestResolveDbPath:
    def test_auth_disabled_returns_default_path(self, config, tmp_path):
        result = resolve_db_path(config, user_id=None)
        assert result == Path(tmp_path / "trainer.db")

    def test_auth_disabled_ignores_user_id(self, config, tmp_path):
        """Even if a user_id is passed, auth-disabled → default path."""
        result = resolve_db_path(config, user_id="user-123")
        assert result == Path(tmp_path / "trainer.db")

    def test_auth_enabled_no_user(self, auth_config, tmp_path):
        """Auth enabled but no user → default path."""
        result = resolve_db_path(auth_config, user_id=None)
        assert result == Path(tmp_path / "trainer.db")

    def test_auth_enabled_with_user(self, auth_config, tmp_path):
        result = resolve_db_path(auth_config, user_id="abc-123")
        assert result == Path(tmp_path / "data" / "abc-123" / "trainer.db")

    def test_different_users_get_different_paths(self, auth_config):
        path_a = resolve_db_path(auth_config, user_id="user-a")
        path_b = resolve_db_path(auth_config, user_id="user-b")
        assert path_a != path_b
        assert "user-a" in str(path_a)
        assert "user-b" in str(path_b)


# ── ManagerPool ──────────────────────────────────────────────────────────────


class TestManagerPool:
    def test_get_creates_manager(self, config):
        pool = ManagerPool(config)
        mgr = pool.get(None)
        assert mgr is not None
        pool.close_all()

    def test_get_reuses_manager(self, config):
        pool = ManagerPool(config)
        mgr1 = pool.get(None)
        mgr2 = pool.get(None)
        assert mgr1 is mgr2
        pool.close_all()

    def test_default_key_for_none_user(self, config):
        pool = ManagerPool(config)
        pool.get(None)
        assert "_default" in pool._managers
        pool.close_all()

    def test_different_users_get_different_managers(self, auth_config):
        pool = ManagerPool(auth_config)
        mgr_a = pool.get("user-a")
        mgr_b = pool.get("user-b")
        assert mgr_a is not mgr_b
        pool.close_all()

    def test_different_users_get_different_db_paths(self, auth_config):
        pool = ManagerPool(auth_config)
        mgr_a = pool.get("user-a")
        mgr_b = pool.get("user-b")
        assert mgr_a._db_path != mgr_b._db_path
        assert "user-a" in str(mgr_a._db_path)
        assert "user-b" in str(mgr_b._db_path)
        pool.close_all()

    def test_close_all_clears_pool(self, config):
        pool = ManagerPool(config)
        pool.get(None)
        pool.get("user-x")
        assert len(pool._managers) == 2
        pool.close_all()
        assert len(pool._managers) == 0

    def test_remove_specific_user(self, auth_config):
        pool = ManagerPool(auth_config)
        pool.get("user-a")
        pool.get("user-b")
        assert len(pool._managers) == 2
        pool.remove("user-a")
        assert len(pool._managers) == 1
        assert "user-a" not in pool._managers
        assert "user-b" in pool._managers
        pool.close_all()

    def test_remove_nonexistent_user_is_noop(self, config):
        pool = ManagerPool(config)
        pool.remove("nonexistent")  # Should not raise
        pool.close_all()

    def test_data_dir_created_on_repo_access(self, auth_config, tmp_path):
        """Verify that parent dirs are created when the manager opens a repo."""
        pool = ManagerPool(auth_config)
        mgr = pool.get("new-user")
        # Force a store access to trigger lazy connection + directory creation
        mgr.get_stats()
        user_dir = tmp_path / "data" / "new-user"
        assert user_dir.exists()
        assert (user_dir / "trainer.db").exists()
        pool.close_all()
