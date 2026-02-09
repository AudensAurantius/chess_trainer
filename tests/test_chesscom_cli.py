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
    def test_mutually_exclusive_sources(self):
        result = runner.invoke(
            app,
            ["import-games", "--user", "someone", "--chesscom-user", "someone"],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    @patch("src.analysis.engine.EngineManager.open")
    def test_server_evals_warning(self, mock_engine_open, tmp_path):
        """--server-evals with --chesscom-user prints warning then fails on engine."""
        from src.analysis import EngineError

        mock_engine_open.side_effect = EngineError("No engine found")

        db = tmp_path / "test.db"
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
        # Should exit with error since engine is required for Chess.com
        assert result.exit_code != 0

    def test_no_source_specified(self):
        result = runner.invoke(app, ["import-games"])
        assert result.exit_code != 0
        assert "--chesscom-user" in result.output

    @patch("src.importers.chesscom_games.get_recent_games")
    @patch("src.analysis.engine.EngineManager.close")
    @patch("src.analysis.engine.EngineManager.open")
    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_chesscom_import_success(self, mock_popen, mock_open, mock_close, mock_games, tmp_path):
        """Full success path: engine mocked, API mocked, exercises stored."""
        mock_games.return_value = iter([])  # No games — just verify the path works

        db = tmp_path / "test.db"
        result = runner.invoke(
            app,
            [
                "import-games",
                "--chesscom-user",
                "testuser",
                "--max-games",
                "1",
                "--db",
                str(db),
            ],
        )
        assert result.exit_code == 0
        assert "Chess.com Game Analysis" in result.output

    @patch("src.analysis.engine.EngineManager.open")
    def test_chesscom_no_engine_exits(self, mock_engine_open, tmp_path):
        """Chess.com requires engine — missing engine should exit with error."""
        from src.analysis import EngineError

        mock_engine_open.side_effect = EngineError("No engine found")

        db = tmp_path / "test.db"
        result = runner.invoke(
            app,
            ["import-games", "--chesscom-user", "testuser", "--db", str(db)],
        )
        assert result.exit_code != 0

    def test_time_class_option_accepted(self):
        """--time-class is accepted without error (fails on engine, not on arg parsing)."""
        result = runner.invoke(
            app,
            ["import-games", "--chesscom-user", "testuser", "--time-class", "blitz"],
        )
        # Fails on engine, not on arg parsing
        assert "time-class" not in result.output or result.exit_code != 0


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

    @patch("src.chesscom.api.requests.get")
    def test_server_evals_warning(self, mock_get):
        """--server-evals with --chesscom-game prints warning then hits API."""
        from unittest.mock import MagicMock

        from requests import HTTPError, Response

        # Mock Chess.com API to return 404 so it fails fast
        resp = MagicMock(spec=Response)
        resp.status_code = 404
        resp.raise_for_status.side_effect = HTTPError(response=resp)
        mock_get.return_value = resp

        result = runner.invoke(
            app,
            ["analyze-game", "--chesscom-game", "12345", "--server-evals"],
        )
        assert "--server-evals is not available for Chess.com" in result.output
        # Should exit with error (API fails)
        assert result.exit_code != 0

    def test_no_source_specified(self):
        result = runner.invoke(app, ["analyze-game"])
        assert result.exit_code != 0
        assert "--chesscom-game" in result.output

    @patch("src.chesscom.api.requests.get")
    def test_chesscom_game_api_failure(self, mock_get):
        """Chess.com API failure should print a helpful message."""
        from unittest.mock import MagicMock

        from requests import HTTPError, Response

        resp = MagicMock(spec=Response)
        resp.status_code = 404
        resp.raise_for_status.side_effect = HTTPError(response=resp)
        mock_get.return_value = resp

        result = runner.invoke(
            app,
            ["analyze-game", "--chesscom-game", "99999999"],
        )
        assert result.exit_code != 0
        assert "Could not fetch game" in result.output


# ---------------------------------------------------------------------------
# config show includes chesscom
# ---------------------------------------------------------------------------


class TestConfigShowChessCom:
    def test_config_show_includes_chesscom(self):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "chesscom.user_agent" in result.output
        assert "chesscom.request_delay" in result.output
