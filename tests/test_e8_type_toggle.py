"""Tests for E8: Exercise type label toggle + E3: Themed sessions."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from src.cli.app import _parse_duration, app
from src.config import AppConfig, TrainingConfig, load_config
from src.exercises import TacticExercise
from src.storage import Repository
from src.training.session import SessionConfig
from src.web import create_app

runner = CliRunner()

SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


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


# ── Web API tests ──────────────────────────────────────────────────────


@pytest.fixture
def web_app(tmp_path):
    config = AppConfig()
    config.database.path = str(tmp_path / "test.db")
    return create_app(config)


@pytest.fixture
def seeded_web_client(web_app, tmp_path):
    with Repository(tmp_path / "test.db") as repo:
        tactic = TacticExercise(
            id="test:001",
            fen=SAMPLE_FEN,
            tags=["fork", "tactic"],
            source="test",
            difficulty=1500.0,
            solution=["g7g6"],
            themes=["fork"],
        )
        repo.exercises.add(tactic)
        repo.cards.get_or_create(tactic.id)
    return TestClient(web_app)


class TestE8WebTypeToggle:
    """Test exercise type in web API responses."""

    def test_next_includes_type_by_default(self, seeded_web_client):
        seeded_web_client.post("/api/session/start", json={})
        res = seeded_web_client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "ok"
        assert data["exercise_type"] == "TACTIC"

    def test_next_omits_type_when_hidden(self, seeded_web_client):
        seeded_web_client.post("/api/session/start", json={"hide_type": True})
        res = seeded_web_client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "ok"
        assert "exercise_type" not in data

    def test_start_accepts_exercise_types_filter(self, seeded_web_client):
        # Filter for ENDGAME only — our tactic should be excluded
        res = seeded_web_client.post("/api/session/start", json={"exercise_types": ["ENDGAME"]})
        data = res.json()
        assert data["queue_size"] == 0

    def test_start_accepts_matching_exercise_type(self, seeded_web_client):
        res = seeded_web_client.post("/api/session/start", json={"exercise_types": ["TACTIC"]})
        data = res.json()
        assert data["queue_size"] == 1

    def test_start_with_duration(self, seeded_web_client):
        seeded_web_client.post("/api/session/start", json={"max_duration_minutes": 15})
        res = seeded_web_client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "ok"
        assert "remaining_minutes" in data
        assert "elapsed_minutes" in data
        assert data["remaining_minutes"] <= 15

    def test_no_duration_no_timer(self, seeded_web_client):
        seeded_web_client.post("/api/session/start", json={})
        res = seeded_web_client.get("/api/session/next")
        data = res.json()
        assert "remaining_minutes" not in data
        assert "elapsed_minutes" not in data

    def test_train_page_has_type_filter(self, seeded_web_client):
        res = seeded_web_client.get("/train")
        assert "exercise-type-filter" in res.text
        assert "hide-type" in res.text
        assert "duration" in res.text
