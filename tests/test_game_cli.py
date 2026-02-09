"""Tests for import-games and analyze-game CLI commands."""

from unittest.mock import MagicMock, patch

import chess
import chess.engine
from typer.testing import CliRunner

from src.cli.app import _parse_date_to_ms, app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Test PGN data
# ---------------------------------------------------------------------------

SIMPLE_PGN = """[Event "Test"]
[Site "https://lichess.org/AbCdEfGh"]
[White "Player1"]
[Black "Player2"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0"""


def _make_mock_engine():
    """Create a mock SimpleEngine that returns reasonable analysis results."""
    mock = MagicMock(spec=chess.engine.SimpleEngine)

    def analyse_fn(board, limit, multipv=1):
        e2e4 = chess.Move.from_uci("e2e4")
        info = {
            "score": chess.engine.PovScore(chess.engine.Cp(20), chess.WHITE),
            "depth": 20,
            "seldepth": 22,
            "nodes": 1_000_000,
            "nps": 500_000,
            "pv": [e2e4],
        }
        return [info]

    mock.analyse.side_effect = analyse_fn
    return mock


# ---------------------------------------------------------------------------
# _parse_date_to_ms tests
# ---------------------------------------------------------------------------


class TestParseDateToMs:
    def test_valid_date(self):
        ms = _parse_date_to_ms("2024-01-15")
        assert ms > 0

    def test_invalid_date(self):
        ms = _parse_date_to_ms("not-a-date")
        assert ms == 0

    def test_epoch(self):
        ms = _parse_date_to_ms("1970-01-01")
        assert ms == 0


# ---------------------------------------------------------------------------
# import-games CLI tests
# ---------------------------------------------------------------------------


class TestImportGamesCommand:
    def test_no_args(self):
        result = runner.invoke(app, ["import-games"])
        assert result.exit_code != 0
        assert "Specify --pgn, --user (Lichess), or --chesscom-user" in result.output

    def test_invalid_severity(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SIMPLE_PGN)

        result = runner.invoke(
            app,
            ["import-games", "--pgn", str(pgn_file), "--min-severity", "HORRIBLE"],
        )
        assert result.exit_code != 0
        assert "Invalid severity" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_pgn_import_with_engine(self, mock_popen, tmp_path):
        mock_popen.return_value = _make_mock_engine()
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SIMPLE_PGN)
        db_path = tmp_path / "test.db"

        result = runner.invoke(
            app,
            ["import-games", "--pgn", str(pgn_file), "--db", str(db_path)],
        )
        assert result.exit_code == 0
        assert "Import from Game Analysis" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_pgn_with_color_filter(self, mock_popen, tmp_path):
        mock_popen.return_value = _make_mock_engine()
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SIMPLE_PGN)
        db_path = tmp_path / "test.db"

        result = runner.invoke(
            app,
            [
                "import-games",
                "--pgn",
                str(pgn_file),
                "--color",
                "white",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 0

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_pgn_with_depth_and_max_exercises(self, mock_popen, tmp_path):
        mock_popen.return_value = _make_mock_engine()
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SIMPLE_PGN)
        db_path = tmp_path / "test.db"

        result = runner.invoke(
            app,
            [
                "import-games",
                "--pgn",
                str(pgn_file),
                "--depth",
                "15",
                "--max-exercises",
                "3",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 0

    @patch("src.importers.games.get_user_games")
    def test_lichess_server_evals(self, mock_get_games, tmp_path):
        db_path = tmp_path / "test.db"
        mock_get_games.return_value = iter(
            [
                {
                    "id": "TestGame1",
                    "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
                    "analysis": [
                        {"eval": {"cp": 20}},
                        {"eval": {"cp": -15}},
                        {"eval": {"cp": 30}},
                        {"eval": {"cp": -25}},
                        {"eval": {"cp": 20}},
                        {"eval": {"cp": -10}},
                    ],
                }
            ]
        )

        result = runner.invoke(
            app,
            [
                "import-games",
                "--user",
                "testplayer",
                "--server-evals",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 0
        assert "Import from Game Analysis" in result.output

    @patch("src.importers.games.get_user_games")
    def test_lichess_with_date_filters(self, mock_get_games, tmp_path):
        db_path = tmp_path / "test.db"
        mock_get_games.return_value = iter([])

        result = runner.invoke(
            app,
            [
                "import-games",
                "--user",
                "testplayer",
                "--server-evals",
                "--since",
                "2024-01-01",
                "--until",
                "2024-12-31",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 0

    @patch("src.importers.games.get_user_games")
    def test_lichess_with_max_games(self, mock_get_games, tmp_path):
        db_path = tmp_path / "test.db"
        mock_get_games.return_value = iter([])

        result = runner.invoke(
            app,
            [
                "import-games",
                "--user",
                "testplayer",
                "--server-evals",
                "--max-games",
                "5",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# analyze-game CLI tests
# ---------------------------------------------------------------------------


class TestAnalyzeGameCommand:
    def test_no_args(self):
        result = runner.invoke(app, ["analyze-game"])
        assert result.exit_code != 0
        assert "Specify --pgn, --game-id (Lichess), or --chesscom-game" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_pgn(self, mock_popen, tmp_path):
        mock_popen.return_value = _make_mock_engine()
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SIMPLE_PGN)

        result = runner.invoke(app, ["analyze-game", "--pgn", str(pgn_file)])
        assert result.exit_code == 0
        assert "Player1" in result.output
        assert "Player2" in result.output
        assert "Summary" in result.output

    def test_analyze_pgn_empty_file(self, tmp_path):
        pgn_file = tmp_path / "empty.pgn"
        pgn_file.write_text("")

        result = runner.invoke(app, ["analyze-game", "--pgn", str(pgn_file)])
        assert result.exit_code != 0
        assert "No games found" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_with_color_filter(self, mock_popen, tmp_path):
        mock_popen.return_value = _make_mock_engine()
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SIMPLE_PGN)

        result = runner.invoke(app, ["analyze-game", "--pgn", str(pgn_file), "--color", "white"])
        assert result.exit_code == 0

    @patch("src.lichess.api.get_game")
    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_by_game_id(self, mock_popen, mock_get_game):
        mock_popen.return_value = _make_mock_engine()
        mock_get_game.return_value = {
            "id": "TestId",
            "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
        }

        result = runner.invoke(app, ["analyze-game", "--game-id", "TestId"])
        assert result.exit_code == 0
        assert "Summary" in result.output
