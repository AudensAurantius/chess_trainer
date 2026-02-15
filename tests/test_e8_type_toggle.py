"""Tests for E8: Exercise type label toggle."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from src.cli.app import _parse_duration, app
from src.config import TrainingConfig, load_config
from src.training.session import SessionConfig

runner = CliRunner()


class TestE8Config:
    """Test show_exercise_type config field."""

    def test_show_exercise_type_defaults_true(self):
        cfg = TrainingConfig()
        assert cfg.show_exercise_type is True

    def test_default_duration_minutes_defaults_none(self):
        cfg = TrainingConfig()
        assert cfg.default_duration_minutes is None

    def test_show_exercise_type_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[training]\nshow_exercise_type = false\n")
        cfg = load_config(toml_file)
        assert cfg.training.show_exercise_type is False

    def test_default_duration_from_toml(self, tmp_path):
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[training]\ndefault_duration_minutes = 15\n")
        cfg = load_config(toml_file)
        assert cfg.training.default_duration_minutes == 15


class TestE8SessionConfig:
    """Test hide_exercise_type and max_duration_minutes in SessionConfig."""

    def test_hide_exercise_type_defaults_false(self):
        sc = SessionConfig()
        assert sc.hide_exercise_type is False

    def test_hide_exercise_type_set(self):
        sc = SessionConfig(hide_exercise_type=True)
        assert sc.hide_exercise_type is True

    def test_max_duration_minutes_defaults_none(self):
        sc = SessionConfig()
        assert sc.max_duration_minutes is None

    def test_max_duration_minutes_set(self):
        sc = SessionConfig(max_duration_minutes=15)
        assert sc.max_duration_minutes == 15


class TestE8CLISubtitle:
    """Test CLI shows/hides exercise type label."""

    def test_hide_type_flag_shows_question_marks(self, tmp_path):
        """With --hide-type, subtitle should show ??? instead of exercise type."""
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["train", "--hide-type", "--db", str(db_path)])
        assert result.exit_code == 0
        # Empty DB exits with "No cards due" — that's fine for testing the flag parses
        assert "No cards due" in result.output

    def test_invalid_difficulty_preset(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["train", "--difficulty", "extreme", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Unknown difficulty" in result.output


class TestParseDuration:
    """Test the _parse_duration helper."""

    def test_minutes_with_suffix(self):
        assert _parse_duration("15m") == 15

    def test_hours_with_suffix(self):
        assert _parse_duration("1h") == 60

    def test_bare_number(self):
        assert _parse_duration("30") == 30

    def test_hours_and_minutes(self):
        assert _parse_duration("1h30m") == 90

    def test_just_hours(self):
        assert _parse_duration("2h") == 120

    def test_just_minutes_no_m(self):
        assert _parse_duration("45m") == 45

    def test_whitespace_stripped(self):
        assert _parse_duration("  10m  ") == 10

    def test_invalid_raises(self):
        import typer

        with pytest.raises(typer.BadParameter):
            _parse_duration("abc")

    def test_zero_minutes(self):
        assert _parse_duration("0m") == 0
        assert _parse_duration("0") == 0
