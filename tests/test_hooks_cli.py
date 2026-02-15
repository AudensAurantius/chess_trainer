"""Tests for F16 — CLI hooks commands and import hook emission."""

from __future__ import annotations

import stat
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


# ── hooks list ─────────────────────────────────────────────────────────────────


class TestHooksList:
    """Tests for the 'hooks list' CLI command."""

    def test_hooks_list_shows_all_events(self, tmp_path):
        from src.config import AppConfig, HooksConfig

        config = AppConfig()
        config.hooks = HooksConfig(directory=str(tmp_path / "hooks"))

        with patch("src.cli.app._get_config", return_value=config):
            result = runner.invoke(app, ["hooks", "list"])

        assert result.exit_code == 0
        assert "on_exercise_complete" in result.output
        assert "on_session_end" in result.output
        assert "on_import_complete" in result.output

    def test_hooks_list_shows_installed_status(self, tmp_path):
        from src.config import AppConfig, HooksConfig

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        script = hooks_dir / "on_exercise_complete"
        script.write_text("#!/bin/bash\nexit 0\n")

        config = AppConfig()
        config.hooks = HooksConfig(directory=str(hooks_dir))

        with patch("src.cli.app._get_config", return_value=config):
            result = runner.invoke(app, ["hooks", "list"])

        assert result.exit_code == 0
        assert "Yes" in result.output


# ── hooks init ─────────────────────────────────────────────────────────────────


class TestHooksInit:
    """Tests for the 'hooks init' CLI command."""

    def test_hooks_init_creates_directory(self, tmp_path):
        from src.config import AppConfig, HooksConfig

        hooks_dir = tmp_path / "new_hooks"
        config = AppConfig()
        config.hooks = HooksConfig(directory=str(hooks_dir))

        with patch("src.cli.app._get_config", return_value=config):
            result = runner.invoke(app, ["hooks", "init"])

        assert result.exit_code == 0
        assert hooks_dir.is_dir()
        assert "initialized" in result.output
        # Check example scripts exist
        examples = list(hooks_dir.glob("*.example"))
        assert len(examples) == 6


# ── hooks test ─────────────────────────────────────────────────────────────────


class TestHooksTest:
    """Tests for the 'hooks test' CLI command."""

    def test_hooks_test_invalid_event(self, tmp_path):
        from src.config import AppConfig, HooksConfig

        config = AppConfig()
        config.hooks = HooksConfig(directory=str(tmp_path / "hooks"))

        with patch("src.cli.app._get_config", return_value=config):
            result = runner.invoke(app, ["hooks", "test", "on_bogus_event"])

        assert result.exit_code == 1
        assert "Unknown event" in result.output

    def test_hooks_test_no_script(self, tmp_path):
        from src.config import AppConfig, HooksConfig

        config = AppConfig()
        config.hooks = HooksConfig(directory=str(tmp_path / "hooks"))

        with patch("src.cli.app._get_config", return_value=config):
            result = runner.invoke(app, ["hooks", "test", "on_exercise_complete"])

        assert result.exit_code == 1
        assert "No script installed" in result.output

    def test_hooks_test_success(self, tmp_path):
        from src.config import AppConfig, HooksConfig

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        script = hooks_dir / "on_exercise_complete"
        script.write_text("#!/bin/bash\nexit 0\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        config = AppConfig()
        config.hooks = HooksConfig(directory=str(hooks_dir))

        with patch("src.cli.app._get_config", return_value=config):
            result = runner.invoke(app, ["hooks", "test", "on_exercise_complete"])

        assert result.exit_code == 0
        assert "successfully" in result.output

    def test_hooks_test_failure(self, tmp_path):
        from src.config import AppConfig, HooksConfig

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        script = hooks_dir / "on_session_end"
        script.write_text("#!/bin/bash\nexit 1\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        config = AppConfig()
        config.hooks = HooksConfig(directory=str(hooks_dir))

        with patch("src.cli.app._get_config", return_value=config):
            result = runner.invoke(app, ["hooks", "test", "on_session_end"])

        assert result.exit_code == 1
        assert "failed" in result.output


# ── Import hooks ───────────────────────────────────────────────────────────────


class TestImportHooks:
    """Tests for _fire_import_hook from CLI import commands."""

    def test_fire_import_hook_calls_manager(self):
        from src.config import AppConfig

        config = AppConfig()
        with patch("src.cli.app._get_config", return_value=config):
            with patch("src.hooks.manager.HookManager.fire") as mock_fire:
                from src.cli.app import _fire_import_hook

                _fire_import_hook("lichess", 5, 2, 1)

                mock_fire.assert_called_once()
                payload = mock_fire.call_args[0][1]
                assert payload["source"] == "lichess"
                assert payload["added"] == 5

    def test_import_puzzles_fires_hook(self, tmp_path, monkeypatch):
        """import-puzzles should call _fire_import_hook."""
        from src.config import AppConfig

        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        mock_result = MagicMock()
        mock_result.total_added = 3
        mock_result.total_skipped = 0
        mock_result.errors = []
        mock_result.__str__ = lambda s: "3 added"

        monkeypatch.delenv("LICHESS_TOKEN", raising=False)

        with patch("src.cli.app._get_config", return_value=config):
            with patch("src.cli.app.LichessPuzzleImporter") as mock_imp:
                mock_imp.return_value.import_to.return_value = mock_result
                with patch("src.cli.app.get_repo") as mock_repo:
                    mock_repo.return_value.__enter__ = MagicMock(return_value=MagicMock())
                    mock_repo.return_value.__exit__ = MagicMock(return_value=False)
                    with patch("src.cli.app._fire_import_hook") as mock_hook:
                        result = runner.invoke(app, ["import-puzzles", "--count", "3"])

        assert result.exit_code == 0
        mock_hook.assert_called_once_with("lichess", 3, 0, 0)
