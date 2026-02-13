"""Tests for F15: Import failed tactics puzzles from Lichess.

Covers:
- parse_time_horizon() utility
- LichessPuzzleImporter.fetch_failed() method
- LichessPuzzleImporter._convert_activity() method
- LichessPuzzleImporter.import_to_failed() method
- CLI import-failed-puzzles command
- ImportConfig defaults and TOML parsing
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from requests import Response

from src.config import AppConfig, _apply_toml, load_config
from src.importers.lichess_puzzles import LichessPuzzleImporter, parse_time_horizon

# ---------------------------------------------------------------------------
# Sample data matching Lichess puzzle activity format
# ---------------------------------------------------------------------------

FAILED_ACTIVITY = {
    "date": int(time.time() * 1000),  # Recent timestamp (ms)
    "win": False,
    "puzzle": {
        "id": "AbCdE",
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
        "lastMove": "g8f6",
        "rating": 1200,
        "plays": 5000,
        "solution": ["h5f7"],
        "themes": ["mateIn1", "short"],
    },
}

WON_ACTIVITY = {
    "date": int(time.time() * 1000),
    "win": True,
    "puzzle": {
        "id": "WonPz",
        "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        "lastMove": "e2e4",
        "rating": 1000,
        "plays": 100,
        "solution": ["e7e5"],
        "themes": ["opening"],
    },
}

OLD_FAILED_ACTIVITY = {
    "date": int((time.time() - 200 * 86400) * 1000),  # 200 days ago
    "win": False,
    "puzzle": {
        "id": "OldPz",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "lastMove": "e2e4",
        "rating": 800,
        "plays": 50,
        "solution": ["d2d4"],
        "themes": ["opening"],
    },
}

MULTI_THEME_FAILED = {
    "date": int(time.time() * 1000),
    "win": False,
    "puzzle": {
        "id": "ForkP",
        "fen": "r1bqkb1r/pppp1ppp/2n5/4p3/2B1n3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 4",
        "lastMove": "f6e4",
        "rating": 1600,
        "plays": 3000,
        "solution": ["d1d5", "e4f6", "d5f7"],
        "themes": ["fork", "middlegame", "short"],
    },
}


# ===========================================================================
# parse_time_horizon()
# ===========================================================================


class TestParseTimeHorizon:
    """Tests for the time horizon parser."""

    def test_iso_date(self):
        result = parse_time_horizon("2025-06-15")
        assert result == datetime(2025, 6, 15)

    def test_iso_datetime(self):
        result = parse_time_horizon("2025-06-15T10:30:00")
        assert result == datetime(2025, 6, 15, 10, 30, 0)

    def test_days(self):
        before = datetime.now()
        result = parse_time_horizon("30 days")
        after = datetime.now()
        expected = before - timedelta(days=30)
        assert (
            expected - timedelta(seconds=1)
            <= result
            <= after - timedelta(days=30) + timedelta(seconds=1)
        )

    def test_months(self):
        result = parse_time_horizon("3 months")
        expected = datetime.now() - timedelta(days=90)
        assert abs((result - expected).total_seconds()) < 2

    def test_weeks(self):
        result = parse_time_horizon("2 weeks")
        expected = datetime.now() - timedelta(days=14)
        assert abs((result - expected).total_seconds()) < 2

    def test_year(self):
        result = parse_time_horizon("1 year")
        expected = datetime.now() - timedelta(days=365)
        assert abs((result - expected).total_seconds()) < 2

    def test_short_units(self):
        result_d = parse_time_horizon("7d")
        result_w = parse_time_horizon("1w")
        result_m = parse_time_horizon("2m")
        result_y = parse_time_horizon("1y")

        assert abs((result_d - result_w).total_seconds()) < 2
        assert abs((result_m - (datetime.now() - timedelta(days=60))).total_seconds()) < 2
        assert abs((result_y - (datetime.now() - timedelta(days=365))).total_seconds()) < 2

    def test_case_insensitive(self):
        result = parse_time_horizon("3 Months")
        expected = datetime.now() - timedelta(days=90)
        assert abs((result - expected).total_seconds()) < 2

    def test_whitespace_tolerance(self):
        result = parse_time_horizon("  3  months  ")
        expected = datetime.now() - timedelta(days=90)
        assert abs((result - expected).total_seconds()) < 2

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Unrecognized time horizon"):
            parse_time_horizon("next tuesday")

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="Unrecognized time horizon"):
            parse_time_horizon("3 fortnights")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="Unrecognized time horizon"):
            parse_time_horizon("")


# ===========================================================================
# _convert_activity()
# ===========================================================================


class TestConvertActivity:
    """Tests for converting puzzle activity entries to TacticExercise."""

    def test_basic_conversion(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_activity(FAILED_ACTIVITY)

        assert exercise.id == "lichess:AbCdE"
        assert exercise.fen == FAILED_ACTIVITY["puzzle"]["fen"]
        assert exercise.source == "lichess"
        assert exercise.source_url == "https://lichess.org/training/AbCdE"
        assert exercise.difficulty == 1200
        assert exercise.solution == ["h5f7"]
        assert exercise.themes == ["mateIn1", "short"]

    def test_auto_tagging(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_activity(FAILED_ACTIVITY, auto_tag=True)

        assert "failed-puzzle" in exercise.tags
        assert "needs-review" in exercise.tags

    def test_no_auto_tagging(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_activity(FAILED_ACTIVITY, auto_tag=False)

        assert "failed-puzzle" not in exercise.tags
        assert "needs-review" not in exercise.tags

    def test_theme_mapping_preserved(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_activity(FAILED_ACTIVITY, auto_tag=False)

        # mateIn1 should trigger "mating_pattern" tag via _map_themes
        assert "mating_pattern" in exercise.tags
        assert "mateIn1" in exercise.tags

    def test_fork_theme_mapping(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_activity(MULTI_THEME_FAILED, auto_tag=False)

        assert "fork" in exercise.tags
        assert "tactic" in exercise.tags

    def test_multi_move_solution(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_activity(MULTI_THEME_FAILED)

        # Activity format: all moves are in solution (no setup move skip)
        assert exercise.solution == ["d1d5", "e4f6", "d5f7"]

    def test_missing_optional_fields(self):
        """Puzzle with minimal data should still convert."""
        data = {
            "date": int(time.time() * 1000),
            "win": False,
            "puzzle": {
                "id": "MinP",
                "fen": "8/8/8/8/8/8/8/4K3 w - - 0 1",
                "lastMove": "e1e2",
                "rating": 500,
                "plays": 1,
                "solution": [],
                "themes": [],
            },
        }
        importer = LichessPuzzleImporter()
        exercise = importer._convert_activity(data)

        assert exercise.id == "lichess:MinP"
        assert exercise.solution == []
        assert exercise.themes == []

    def test_missing_puzzle_key_raises(self):
        importer = LichessPuzzleImporter()
        with pytest.raises(KeyError):
            importer._convert_activity({"date": 123, "win": False})


# ===========================================================================
# fetch_failed()
# ===========================================================================


class TestFetchFailed:
    """Tests for LichessPuzzleImporter.fetch_failed()."""

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_filters_for_losses(self, mock_history):
        mock_history.return_value = iter([WON_ACTIVITY, FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=10))

        assert len(exercises) == 1
        assert exercises[0].id == "lichess:AbCdE"

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_respects_count_limit(self, mock_history):
        activities = [
            {**FAILED_ACTIVITY, "puzzle": {**FAILED_ACTIVITY["puzzle"], "id": f"P{i}"}}
            for i in range(5)
        ]
        mock_history.return_value = iter(activities)
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=3))

        assert len(exercises) == 3

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_time_horizon_string(self, mock_history):
        """Puzzles older than the horizon are excluded."""
        mock_history.return_value = iter([FAILED_ACTIVITY, OLD_FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=10, since="3 months"))

        # FAILED_ACTIVITY is recent, OLD_FAILED_ACTIVITY is 200 days ago (> 90 days)
        assert len(exercises) == 1
        assert exercises[0].id == "lichess:AbCdE"

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_time_horizon_datetime(self, mock_history):
        """Accept datetime objects for since parameter."""
        cutoff = datetime.now() - timedelta(days=30)
        mock_history.return_value = iter([FAILED_ACTIVITY, OLD_FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=10, since=cutoff))

        assert len(exercises) == 1

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_auto_tag_default(self, mock_history):
        mock_history.return_value = iter([FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=1))

        assert "failed-puzzle" in exercises[0].tags
        assert "needs-review" in exercises[0].tags

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_auto_tag_disabled(self, mock_history):
        mock_history.return_value = iter([FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=1, auto_tag=False))

        assert "failed-puzzle" not in exercises[0].tags
        assert "needs-review" not in exercises[0].tags

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_skips_bad_data(self, mock_history):
        bad_entry = {"date": int(time.time() * 1000), "win": False, "puzzle": {}}
        mock_history.return_value = iter([bad_entry, FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=10))

        assert len(exercises) == 1
        assert exercises[0].id == "lichess:AbCdE"

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_empty_history(self, mock_history):
        mock_history.return_value = iter([])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=10))

        assert exercises == []

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_all_wins_returns_empty(self, mock_history):
        mock_history.return_value = iter([WON_ACTIVITY, WON_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=10))

        assert exercises == []

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_batch_size_multiplied(self, mock_history):
        """Should request 3x count from the API to account for wins."""
        mock_history.return_value = iter([])
        importer = LichessPuzzleImporter()
        list(importer.fetch_failed(count=20))

        mock_history.assert_called_once_with(limit=60)

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_stops_at_horizon_boundary(self, mock_history):
        """Once we hit an entry older than since, stop immediately."""
        # Activity is reverse chronological: recent first, then old
        mock_history.return_value = iter([FAILED_ACTIVITY, OLD_FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch_failed(count=100, since="1 month"))

        # Should stop after OLD_FAILED_ACTIVITY (200 days ago) hits the cutoff
        assert len(exercises) == 1


# ===========================================================================
# import_to_failed()
# ===========================================================================


class TestImportToFailed:
    """Tests for the import_to_failed convenience method."""

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_imports_and_tracks_stats(self, mock_history, tmp_path):
        from src.storage import Repository

        mock_history.return_value = iter([FAILED_ACTIVITY, MULTI_THEME_FAILED])
        importer = LichessPuzzleImporter()

        with Repository(tmp_path / "test.db") as repo:
            result = importer.import_to_failed(repo.exercises, count=10)

        assert result.total_fetched == 2
        assert result.total_added == 2
        assert result.total_skipped == 0
        assert result.errors == []

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_deduplicates(self, mock_history, tmp_path):
        from src.storage import Repository

        mock_history.return_value = iter([FAILED_ACTIVITY])
        importer = LichessPuzzleImporter()

        with Repository(tmp_path / "test.db") as repo:
            # First import
            result1 = importer.import_to_failed(repo.exercises, count=10)
            assert result1.total_added == 1

            # Second import with same data
            mock_history.return_value = iter([FAILED_ACTIVITY])
            result2 = importer.import_to_failed(repo.exercises, count=10)
            assert result2.total_added == 0
            assert result2.total_skipped == 1


# ===========================================================================
# ImportConfig
# ===========================================================================


class TestImportConfig:
    """Tests for the import_settings config section."""

    def test_defaults(self):
        config = AppConfig()
        assert config.import_settings.failed_puzzle_default_horizon == "3 months"
        assert config.import_settings.failed_puzzle_auto_tag is True

    def test_apply_toml(self):
        config = AppConfig()
        _apply_toml(
            config,
            {
                "import_settings": {
                    "failed_puzzle_default_horizon": "6 months",
                    "failed_puzzle_auto_tag": False,
                }
            },
        )
        assert config.import_settings.failed_puzzle_default_horizon == "6 months"
        assert config.import_settings.failed_puzzle_auto_tag is False

    def test_apply_toml_partial(self):
        config = AppConfig()
        _apply_toml(
            config,
            {"import_settings": {"failed_puzzle_default_horizon": "1 year"}},
        )
        assert config.import_settings.failed_puzzle_default_horizon == "1 year"
        assert config.import_settings.failed_puzzle_auto_tag is True  # unchanged

    def test_load_from_toml_file(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            "[import_settings]\n"
            'failed_puzzle_default_horizon = "30 days"\n'
            "failed_puzzle_auto_tag = false\n"
        )
        config_file.chmod(0o600)

        config = load_config(config_file)
        assert config.import_settings.failed_puzzle_default_horizon == "30 days"
        assert config.import_settings.failed_puzzle_auto_tag is False

    def test_get_config_keys_includes_import(self):
        from src.config import get_config_keys

        keys = get_config_keys()
        assert "import_settings.failed_puzzle_default_horizon" in keys
        assert "import_settings.failed_puzzle_auto_tag" in keys


# ===========================================================================
# get_puzzle_history() before parameter
# ===========================================================================


class TestGetPuzzleHistoryBefore:
    """Tests for the before parameter on get_puzzle_history."""

    @patch("src.lichess.api.LICHESS_TOKEN", "tok")
    @patch("src.lichess.api.requests.get")
    def test_before_parameter_passed(self, mock_get):
        from src.lichess.api import get_puzzle_history

        lines = [b'{"puzzle":{"id":"P1"}}']
        mock_resp = _mock_response(content_type="application/x-ndjson", iter_lines_data=lines)
        mock_get.return_value = mock_resp

        list(get_puzzle_history(limit=5, before=1700000000000))

        _, kwargs = mock_get.call_args
        assert kwargs["params"]["before"] == "1700000000000"
        assert kwargs["params"]["max"] == "5"

    @patch("src.lichess.api.LICHESS_TOKEN", "tok")
    @patch("src.lichess.api.requests.get")
    def test_no_before_parameter(self, mock_get):
        from src.lichess.api import get_puzzle_history

        lines = [b'{"puzzle":{"id":"P1"}}']
        mock_resp = _mock_response(content_type="application/x-ndjson", iter_lines_data=lines)
        mock_get.return_value = mock_resp

        list(get_puzzle_history(limit=5))

        _, kwargs = mock_get.call_args
        assert "before" not in kwargs["params"]


# ===========================================================================
# CLI command
# ===========================================================================


class TestImportFailedPuzzlesCLI:
    """Tests for the import-failed-puzzles CLI command."""

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_basic_invocation(self, mock_history, tmp_path):
        from typer.testing import CliRunner

        from src.cli.app import app

        mock_history.return_value = iter([FAILED_ACTIVITY])
        runner = CliRunner()
        result = runner.invoke(app, ["import-failed-puzzles", "--db", str(tmp_path / "test.db")])

        assert result.exit_code == 0
        assert "1 added" in result.output

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_with_since_flag(self, mock_history, tmp_path):
        from typer.testing import CliRunner

        from src.cli.app import app

        mock_history.return_value = iter([FAILED_ACTIVITY])
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "import-failed-puzzles",
                "--since",
                "1 month",
                "--db",
                str(tmp_path / "test.db"),
            ],
        )

        assert result.exit_code == 0

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_with_count_flag(self, mock_history, tmp_path):
        from typer.testing import CliRunner

        from src.cli.app import app

        activities = [
            {**FAILED_ACTIVITY, "puzzle": {**FAILED_ACTIVITY["puzzle"], "id": f"P{i}"}}
            for i in range(5)
        ]
        mock_history.return_value = iter(activities)
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "import-failed-puzzles",
                "--count",
                "3",
                "--db",
                str(tmp_path / "test.db"),
            ],
        )

        assert result.exit_code == 0
        assert "3 added" in result.output

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_no_tag_flag(self, mock_history, tmp_path):
        from typer.testing import CliRunner

        from src.cli.app import app
        from src.storage import Repository

        mock_history.return_value = iter([FAILED_ACTIVITY])
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "import-failed-puzzles",
                "--no-tag",
                "--db",
                str(tmp_path / "test.db"),
            ],
        )

        assert result.exit_code == 0

        # Verify no auto-tags
        with Repository(tmp_path / "test.db") as repo:
            ex = repo.exercises.get("lichess:AbCdE")
            assert ex is not None
            assert "failed-puzzle" not in ex.tags

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_empty_results(self, mock_history, tmp_path):
        from typer.testing import CliRunner

        from src.cli.app import app

        mock_history.return_value = iter([WON_ACTIVITY])
        runner = CliRunner()
        result = runner.invoke(app, ["import-failed-puzzles", "--db", str(tmp_path / "test.db")])

        assert result.exit_code == 0
        assert "0 added" in result.output


# ---------------------------------------------------------------------------
# Helpers (shared with test_http.py mock patterns)
# ---------------------------------------------------------------------------


def _mock_response(
    content: bytes = b"",
    status_code: int = 200,
    content_type: str = "application/json",
    iter_lines_data: list[bytes] | None = None,
) -> MagicMock:
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = MagicMock()
    if iter_lines_data is not None:
        resp.iter_lines = MagicMock(return_value=iter(iter_lines_data))
    return resp
