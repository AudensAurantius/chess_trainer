"""Tests for F16 — Hook events, HookManager, and config."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

# ── Event payloads ─────────────────────────────────────────────────────────────


class TestEventPayloads:
    """Tests for hook event payload builder functions."""

    def test_exercise_complete_payload(self):
        from src.hooks.events import exercise_complete_payload

        p = exercise_complete_payload(
            exercise_id="ex1", exercise_type="TACTIC", rating=3, correct=True, time_ms=5000
        )
        assert p["event"] == "on_exercise_complete"
        assert p["exercise_id"] == "ex1"
        assert p["exercise_type"] == "TACTIC"
        assert p["rating"] == 3
        assert p["correct"] is True
        assert p["time_ms"] == 5000

    def test_session_end_payload(self):
        from src.hooks.events import session_end_payload

        p = session_end_payload(
            total_reviewed=10,
            correct=7,
            incorrect=2,
            partial=1,
            accuracy=0.7,
            duration_seconds=600.0,
        )
        assert p["event"] == "on_session_end"
        assert p["total_reviewed"] == 10
        assert p["accuracy"] == 0.7
        assert p["duration_seconds"] == 600.0

    def test_streak_milestone_payload(self):
        from src.hooks.events import streak_milestone_payload

        p = streak_milestone_payload(streak_days=30)
        assert p["event"] == "on_streak_milestone"
        assert p["streak_days"] == 30

    def test_bundle_cycle_complete_payload(self):
        from src.hooks.events import bundle_cycle_complete_payload

        p = bundle_cycle_complete_payload(
            bundle_id="bundle:test", cycle_number=2, accuracy=0.95, passed=True
        )
        assert p["event"] == "on_bundle_cycle_complete"
        assert p["bundle_id"] == "bundle:test"
        assert p["passed"] is True

    def test_daily_goal_met_payload(self):
        from src.hooks.events import daily_goal_met_payload

        p = daily_goal_met_payload(reviews_today=50, goal=50)
        assert p["event"] == "on_daily_goal_met"
        assert p["reviews_today"] == 50
        assert p["goal"] == 50

    def test_import_complete_payload(self):
        from src.hooks.events import import_complete_payload

        p = import_complete_payload(source="lichess", added=5, skipped=2, errors=0)
        assert p["event"] == "on_import_complete"
        assert p["source"] == "lichess"
        assert p["added"] == 5

    def test_all_payloads_are_json_serializable(self):
        from src.hooks.events import (
            bundle_cycle_complete_payload,
            daily_goal_met_payload,
            exercise_complete_payload,
            import_complete_payload,
            session_end_payload,
            streak_milestone_payload,
        )

        payloads = [
            exercise_complete_payload(exercise_id="x", exercise_type="T", rating=3, correct=True),
            session_end_payload(total_reviewed=1, correct=1, incorrect=0, partial=0, accuracy=1.0),
            streak_milestone_payload(streak_days=7),
            bundle_cycle_complete_payload(bundle_id="b", cycle_number=1, accuracy=0.9, passed=True),
            daily_goal_met_payload(reviews_today=10, goal=10),
            import_complete_payload(source="s", added=1, skipped=0, errors=0),
        ]
        for p in payloads:
            json.dumps(p)  # Should not raise


# ── HookEvent enum ─────────────────────────────────────────────────────────────


class TestHookEvent:
    """Tests for the HookEvent enum."""

    def test_all_events_are_strings(self):
        from src.hooks.events import HookEvent

        for event in HookEvent:
            assert isinstance(event, str)
            assert event.value.startswith("on_")

    def test_event_count(self):
        from src.hooks.events import HookEvent

        assert len(HookEvent) == 6

    def test_streak_milestones(self):
        from src.hooks.events import STREAK_MILESTONES

        assert STREAK_MILESTONES == [7, 30, 100, 365]


# ── HookManager ────────────────────────────────────────────────────────────────


def _make_script(path: Path, content: str = "#!/bin/bash\nexit 0\n") -> None:
    """Write an executable script."""
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class TestHookManager:
    """Tests for the HookManager class."""

    def _make_manager(self, tmp_path, enabled=True, timeout=10):
        from src.config import HooksConfig
        from src.hooks import HookManager

        config = HooksConfig(enabled=enabled, directory=str(tmp_path), timeout_seconds=timeout)
        return HookManager(config)

    def test_fire_success(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        _make_script(tmp_path / "on_exercise_complete")

        result = mgr.fire("on_exercise_complete", {"test": True})
        assert result is True

    def test_fire_disabled(self, tmp_path):
        mgr = self._make_manager(tmp_path, enabled=False)
        _make_script(tmp_path / "on_exercise_complete")

        result = mgr.fire("on_exercise_complete", {"test": True})
        assert result is False

    def test_fire_no_script(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.fire("on_exercise_complete", {"test": True})
        assert result is False

    def test_fire_not_executable(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        script = tmp_path / "on_exercise_complete"
        script.write_text("#!/bin/bash\nexit 0\n")
        # Don't set executable bit

        result = mgr.fire("on_exercise_complete", {"test": True})
        assert result is False

    def test_fire_nonzero_exit(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        _make_script(tmp_path / "on_session_end", "#!/bin/bash\nexit 1\n")

        result = mgr.fire("on_session_end", {"test": True})
        assert result is False

    def test_fire_timeout(self, tmp_path):
        mgr = self._make_manager(tmp_path, timeout=1)
        _make_script(tmp_path / "on_exercise_complete", "#!/bin/bash\nsleep 10\n")

        result = mgr.fire("on_exercise_complete", {"test": True})
        assert result is False

    def test_fire_receives_json_stdin(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        output_file = tmp_path / "output.json"
        _make_script(
            tmp_path / "on_exercise_complete",
            f"#!/bin/bash\ncat > {output_file}\n",
        )

        payload = {"exercise_id": "ex1", "rating": 3}
        mgr.fire("on_exercise_complete", payload)

        received = json.loads(output_file.read_text())
        assert received == payload

    def test_fire_with_hook_event_enum(self, tmp_path):
        from src.hooks.events import HookEvent

        mgr = self._make_manager(tmp_path)
        _make_script(tmp_path / "on_import_complete")

        result = mgr.fire(HookEvent.ON_IMPORT_COMPLETE, {"source": "test"})
        assert result is True

    def test_fire_oserror(self, tmp_path, monkeypatch):
        mgr = self._make_manager(tmp_path)
        _make_script(tmp_path / "on_exercise_complete")

        import subprocess

        def failing_run(*args, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr(subprocess, "run", failing_run)
        result = mgr.fire("on_exercise_complete", {"test": True})
        assert result is False

    def test_is_installed_true(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        _make_script(tmp_path / "on_exercise_complete")
        assert mgr.is_installed("on_exercise_complete") is True

    def test_is_installed_false(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.is_installed("on_exercise_complete") is False

    def test_is_installed_with_enum(self, tmp_path):
        from src.hooks.events import HookEvent

        mgr = self._make_manager(tmp_path)
        _make_script(tmp_path / "on_session_end")
        assert mgr.is_installed(HookEvent.ON_SESSION_END) is True

    def test_list_hooks(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        _make_script(tmp_path / "on_exercise_complete")

        hooks = mgr.list_hooks()
        assert len(hooks) == 6  # All events listed

        ex_hook = next(h for h in hooks if h["event"] == "on_exercise_complete")
        assert ex_hook["installed"] is True

        sess_hook = next(h for h in hooks if h["event"] == "on_session_end")
        assert sess_hook["installed"] is False

    def test_init_hooks_dir(self, tmp_path):
        hooks_dir = tmp_path / "new_hooks"
        from src.config import HooksConfig
        from src.hooks import HookManager

        mgr = HookManager(HooksConfig(directory=str(hooks_dir)))
        result = mgr.init_hooks_dir()

        assert result == hooks_dir
        assert hooks_dir.is_dir()
        # Example scripts created
        examples = list(hooks_dir.glob("*.example"))
        assert len(examples) == 6

    def test_init_hooks_dir_idempotent(self, tmp_path):
        hooks_dir = tmp_path / "hooks"
        from src.config import HooksConfig
        from src.hooks import HookManager

        mgr = HookManager(HooksConfig(directory=str(hooks_dir)))
        mgr.init_hooks_dir()
        mgr.init_hooks_dir()  # Should not fail
        examples = list(hooks_dir.glob("*.example"))
        assert len(examples) == 6


# ── HooksConfig ────────────────────────────────────────────────────────────────


class TestHooksConfig:
    """Tests for HooksConfig fields, TOML, env, and validation."""

    def test_defaults(self):
        from src.config import HooksConfig

        cfg = HooksConfig()
        assert cfg.enabled is True
        assert "hooks" in cfg.directory
        assert cfg.timeout_seconds == 10

    def test_toml_parsing(self, tmp_path):
        from src.config import load_config

        toml = tmp_path / "config.toml"
        toml.write_text("""\
[hooks]
enabled = false
directory = "/tmp/my-hooks"
timeout_seconds = 30
""")
        cfg = load_config(toml)
        assert cfg.hooks.enabled is False
        assert cfg.hooks.directory == "/tmp/my-hooks"
        assert cfg.hooks.timeout_seconds == 30

    def test_toml_path_expansion(self, tmp_path):
        from src.config import load_config

        toml = tmp_path / "config.toml"
        toml.write_text('[hooks]\ndirectory = "~/my-hooks"\n')
        cfg = load_config(toml)
        assert "~" not in cfg.hooks.directory

    def test_env_overrides(self, monkeypatch, tmp_path):
        from src.config import load_config

        toml = tmp_path / "empty.toml"
        toml.write_text("")
        monkeypatch.setenv("CHESS_TRAINER_HOOKS_ENABLED", "false")
        monkeypatch.setenv("CHESS_TRAINER_HOOKS_DIRECTORY", "/opt/hooks")
        monkeypatch.setenv("CHESS_TRAINER_HOOKS_TIMEOUT", "5")
        cfg = load_config(toml)
        assert cfg.hooks.enabled is False
        assert cfg.hooks.directory == "/opt/hooks"
        assert cfg.hooks.timeout_seconds == 5

    def test_validation_timeout(self):
        from src.config import _validate_value

        _validate_value("hooks.timeout_seconds", 1)
        _validate_value("hooks.timeout_seconds", 300)
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("hooks.timeout_seconds", 0)
        with pytest.raises(ValueError, match="must be between"):
            _validate_value("hooks.timeout_seconds", 301)

    def test_app_config_has_hooks(self):
        from src.config import AppConfig

        cfg = AppConfig()
        assert hasattr(cfg, "hooks")
        assert cfg.hooks.enabled is True

    def test_daily_review_goal_default(self):
        from src.config import TrainingConfig

        cfg = TrainingConfig()
        assert cfg.daily_review_goal is None

    def test_daily_review_goal_toml(self, tmp_path):
        from src.config import load_config

        toml = tmp_path / "config.toml"
        toml.write_text("[training]\ndaily_review_goal = 50\n")
        cfg = load_config(toml)
        assert cfg.training.daily_review_goal == 50

    def test_daily_review_goal_env(self, monkeypatch, tmp_path):
        from src.config import load_config

        toml = tmp_path / "empty.toml"
        toml.write_text("")
        monkeypatch.setenv("CHESS_TRAINER_DAILY_REVIEW_GOAL", "30")
        cfg = load_config(toml)
        assert cfg.training.daily_review_goal == 30

    def test_daily_review_goal_validation(self):
        from src.config import _validate_value

        _validate_value("training.daily_review_goal", 1)
        with pytest.raises(ValueError):
            _validate_value("training.daily_review_goal", 0)

    def test_generate_default_config_includes_hooks(self):
        from src.config import generate_default_config

        cfg = generate_default_config()
        assert "hooks" in cfg
        assert "timeout_seconds" in cfg
        assert "daily_review_goal" in cfg
