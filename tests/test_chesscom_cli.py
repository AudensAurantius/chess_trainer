"""Tests for Chess.com CLI commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# import-chesscom-puzzles
# ---------------------------------------------------------------------------


class TestImportChessComPuzzles:
    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    @patch("src.importers.chesscom_puzzles.get_daily_puzzle")
    def test_basic_import(self, mock_daily, mock_random, tmp_path):
        mock_daily.return_value = {
            "title": "Daily",
            "url": "https://chess.com/puzzle/1",
            "publish_time": 1700000000,
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            "pgn": "1... e5",
            "image": "",
        }
        mock_random.return_value = {
            "title": "Random",
            "url": "https://chess.com/puzzle/2",
            "publish_time": 1700001000,
            "fen": "rnbqkb1r/pppppppp/5n2/4P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2",
            "pgn": "1... Nd5",
            "image": "",
        }

        db = tmp_path / "test.db"
        result = runner.invoke(app, ["import-chesscom-puzzles", "--count", "1", "--db", str(db)])
        assert result.exit_code == 0
        assert "Import from Chess.com Puzzles" in result.output

    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    def test_no_daily_flag(self, mock_random, tmp_path):
        mock_random.return_value = {
            "title": "Random",
            "url": "",
            "publish_time": 1700001000,
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            "pgn": "1... e5",
            "image": "",
        }

        db = tmp_path / "test.db"
        result = runner.invoke(
            app, ["import-chesscom-puzzles", "--count", "1", "--no-daily", "--db", str(db)]
        )
        assert result.exit_code == 0

    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    @patch("src.importers.chesscom_puzzles.get_daily_puzzle")
    def test_creates_review_cards(self, mock_daily, mock_random, tmp_path):
        mock_daily.return_value = {
            "title": "Daily",
            "url": "",
            "publish_time": 1700000000,
            "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            "pgn": "1... e5",
            "image": "",
        }
        mock_random.return_value = {
            "title": "Random",
            "url": "",
            "publish_time": 1700001000,
            "fen": "rnbqkb1r/pppppppp/5n2/4P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2",
            "pgn": "1... Nd5",
            "image": "",
        }

        db = tmp_path / "test.db"
        result = runner.invoke(app, ["import-chesscom-puzzles", "--count", "1", "--db", str(db)])
        assert result.exit_code == 0
        # Verify cards were created by checking stats
        result2 = runner.invoke(app, ["stats", "--db", str(db)])
        assert "Tactic" in result2.output


# ---------------------------------------------------------------------------
# import-games --chesscom-user
# ---------------------------------------------------------------------------


class TestImportGamesChessCom:
    def test_mutually_exclusive_sources(self, tmp_path):
        db = tmp_path / "test.db"
        result = runner.invoke(
            app,
            [
                "import-games",
                "--user",
                "someone",
                "--chesscom-user",
                "someone",
                "--db",
                str(db),
            ],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_server_evals_warning(self, tmp_path):
        """--server-evals with --chesscom-user should warn and continue."""
        db = tmp_path / "test.db"
        # This will fail due to no engine but should still print the warning
        result = runner.invoke(
            app,
            [
                "import-games",
                "--chesscom-user",
                "testuser",
                "--server-evals",
                "--db",
                str(db),
            ],
        )
        assert "--server-evals is not available for Chess.com" in result.output

    def test_no_source_specified(self):
        result = runner.invoke(app, ["import-games"])
        assert result.exit_code != 0
        assert "--chesscom-user" in result.output


# ---------------------------------------------------------------------------
# analyze-game --chesscom-game
# ---------------------------------------------------------------------------


class TestAnalyzeGameChessCom:
    def test_mutually_exclusive_sources(self):
        result = runner.invoke(
            app,
            ["analyze-game", "--pgn", "test.pgn", "--chesscom-game", "12345"],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_server_evals_warning(self):
        result = runner.invoke(
            app,
            ["analyze-game", "--chesscom-game", "12345", "--server-evals"],
        )
        assert "--server-evals is not available for Chess.com" in result.output

    def test_no_source_specified(self):
        result = runner.invoke(app, ["analyze-game"])
        assert result.exit_code != 0
        assert "--chesscom-game" in result.output


# ---------------------------------------------------------------------------
# config show includes chesscom
# ---------------------------------------------------------------------------


class TestConfigShowChessCom:
    def test_config_show_includes_chesscom(self):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "chesscom.user_agent" in result.output
        assert "chesscom.request_delay" in result.output
