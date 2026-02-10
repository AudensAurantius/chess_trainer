"""Tests for CLI application and board rendering."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import chess
from rich.text import Text
from typer.testing import CliRunner

from src.cli.app import _format_next_review, _parse_move, app
from src.config import AppConfig
from src.cli.board import (
    PIECE_SYMBOLS,
    format_move_san,
    format_solution_line,
    render_board,
    render_board_simple,
)
from src.exercises import TacticExercise
from src.importers.base import ImportResult

runner = CliRunner()

# Reusable FENs
STARTING_FEN = chess.STARTING_FEN
SCHOLARS_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


# ---------------------------------------------------------------------------
# board.py — render_board
# ---------------------------------------------------------------------------


class TestRenderBoard:
    """Tests for the Rich board renderer."""

    def test_returns_text_object(self):
        board = chess.Board()
        result = render_board(board)
        assert isinstance(result, Text)

    def test_contains_rank_labels(self):
        board = chess.Board()
        text = render_board(board)
        plain = text.plain
        for r in range(1, 9):
            assert f" {r} " in plain

    def test_contains_file_labels(self):
        board = chess.Board()
        text = render_board(board)
        plain = text.plain
        for f in "abcdefgh":
            assert f" {f} " in plain

    def test_contains_piece_symbols(self):
        board = chess.Board()
        text = render_board(board)
        plain = text.plain
        # White king symbol
        assert PIECE_SYMBOLS[(chess.KING, chess.WHITE)] in plain
        # Black king symbol
        assert PIECE_SYMBOLS[(chess.KING, chess.BLACK)] in plain

    def test_flipped_reverses_ranks(self):
        board = chess.Board()
        normal = render_board(board, flipped=False).plain
        flipped = render_board(board, flipped=True).plain
        # In normal view rank 8 comes first; in flipped view rank 1 comes first
        normal_lines = normal.strip().split("\n")
        flipped_lines = flipped.strip().split("\n")
        assert normal_lines[0].strip().startswith("8")
        assert flipped_lines[0].strip().startswith("1")

    def test_highlight_squares(self):
        board = chess.Board()
        # highlight e4 (square 28)
        text = render_board(board, highlight_squares={chess.E4})
        # We can't easily test the style, but verify it doesn't crash
        assert isinstance(text, Text)

    def test_last_move_highlights(self):
        board = chess.Board()
        board.push_san("e4")
        move = chess.Move.from_uci("e2e4")
        text = render_board(board, last_move=move)
        assert isinstance(text, Text)

    def test_empty_board(self):
        board = chess.Board(fen=None)  # Empty board
        text = render_board(board)
        assert isinstance(text, Text)


class TestRenderBoardSimple:
    """Tests for the plain-text board renderer."""

    def test_returns_string(self):
        board = chess.Board()
        result = render_board_simple(board)
        assert isinstance(result, str)

    def test_contains_piece_symbols(self):
        board = chess.Board()
        result = render_board_simple(board)
        assert "K" in result  # White king
        assert "k" in result  # Black king
        assert "P" in result  # White pawn
        assert "p" in result  # Black pawn

    def test_flipped_reverses_ranks(self):
        board = chess.Board()
        normal = render_board_simple(board, flipped=False)
        flipped = render_board_simple(board, flipped=True)
        normal_lines = normal.strip().split("\n")
        flipped_lines = flipped.strip().split("\n")
        assert normal_lines[0].strip().startswith("8")
        assert flipped_lines[0].strip().startswith("1")

    def test_empty_squares_marked(self):
        board = chess.Board()
        result = render_board_simple(board)
        # Empty squares show dots
        assert "·" in result or "." in result


class TestFormatMoveSan:
    """Tests for SAN move formatting."""

    def test_basic_move(self):
        board = chess.Board()
        move = chess.Move.from_uci("e2e4")
        assert format_move_san(board, move) == "e4"

    def test_knight_move(self):
        board = chess.Board()
        move = chess.Move.from_uci("g1f3")
        assert format_move_san(board, move) == "Nf3"


class TestFormatSolutionLine:
    """Tests for solution line formatting."""

    def test_white_to_move(self):
        board = chess.Board()
        moves = [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]
        result = format_solution_line(board, moves)
        assert "1. e4" in result
        assert "e5" in result

    def test_black_to_move(self):
        # Position after 1. e4
        board = chess.Board()
        board.push_san("e4")
        moves = [chess.Move.from_uci("e7e5")]
        result = format_solution_line(board, moves)
        assert "1..." in result
        assert "e5" in result

    def test_multi_move_sequence(self):
        board = chess.Board()
        moves = [
            chess.Move.from_uci("e2e4"),
            chess.Move.from_uci("e7e5"),
            chess.Move.from_uci("g1f3"),
        ]
        result = format_solution_line(board, moves)
        assert "1. e4" in result
        assert "2. Nf3" in result

    def test_empty_moves(self):
        board = chess.Board()
        result = format_solution_line(board, [])
        assert result == ""


# ---------------------------------------------------------------------------
# app.py — utility functions
# ---------------------------------------------------------------------------


class TestParseMove:
    """Tests for _parse_move."""

    def test_san_move(self):
        board = chess.Board()
        move = _parse_move(board, "e4")
        assert move == chess.Move.from_uci("e2e4")

    def test_uci_move(self):
        board = chess.Board()
        move = _parse_move(board, "e2e4")
        assert move == chess.Move.from_uci("e2e4")

    def test_knight_san(self):
        board = chess.Board()
        move = _parse_move(board, "Nf3")
        assert move == chess.Move.from_uci("g1f3")

    def test_castling_san(self):
        # Position where castling is legal
        board = chess.Board("r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4")
        move = _parse_move(board, "O-O")
        assert move is not None
        assert move == chess.Move.from_uci("e1g1")

    def test_invalid_text(self):
        board = chess.Board()
        assert _parse_move(board, "xyz") is None

    def test_empty_string(self):
        board = chess.Board()
        assert _parse_move(board, "") is None

    def test_whitespace_only(self):
        board = chess.Board()
        assert _parse_move(board, "   ") is None

    def test_illegal_uci(self):
        board = chess.Board()
        # e1e8 is not legal from starting position
        assert _parse_move(board, "e1e8") is None


class TestFormatNextReview:
    """Tests for _format_next_review."""

    def test_past_due(self):
        past = datetime.now() - timedelta(hours=1)
        assert _format_next_review(past) == "now"

    def test_minutes(self):
        future = datetime.now() + timedelta(minutes=30)
        result = _format_next_review(future)
        assert "minutes" in result

    def test_hours(self):
        future = datetime.now() + timedelta(hours=3)
        result = _format_next_review(future)
        assert "hours" in result

    def test_days(self):
        future = datetime.now() + timedelta(days=5)
        result = _format_next_review(future)
        assert "days" in result

    def test_one_minute_minimum(self):
        # Just a few seconds from now should show "1 minutes"
        future = datetime.now() + timedelta(seconds=30)
        result = _format_next_review(future)
        assert "1 minutes" in result


# ---------------------------------------------------------------------------
# app.py — CLI commands via CliRunner
# ---------------------------------------------------------------------------


class TestVersionFlag:
    """Test --version flag."""

    def test_version_shows_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "chess-trainer" in result.output


class TestStatsCommand:
    """Tests for the stats command."""

    def test_stats_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["stats", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Exercise Library" in result.output
        assert "Total" in result.output

    def test_stats_with_exercises(self, tmp_path):
        db_path = tmp_path / "test.db"
        from src.storage import Repository

        # Seed the db
        with Repository(db_path) as repo:
            ex = TacticExercise(
                id="stats:t1",
                fen=SCHOLARS_FEN,
                tags=["fork"],
                source="test",
                solution=["g7g6"],
                themes=["fork"],
            )
            repo.exercises.add(ex)

        result = runner.invoke(app, ["stats", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Tactic" in result.output


class TestImportPuzzlesCommand:
    """Tests for the import-puzzles command."""

    @patch("src.cli.app.LichessPuzzleImporter")
    def test_import_success(self, mock_importer_cls, tmp_path):
        db_path = tmp_path / "test.db"
        mock_importer = MagicMock()
        mock_importer.import_to.return_value = ImportResult(
            source="lichess", total_fetched=5, total_added=5
        )
        mock_importer_cls.return_value = mock_importer

        result = runner.invoke(app, ["import-puzzles", "--count", "5", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "\u2713" in result.output
        mock_importer.import_to.assert_called_once()

    @patch("src.cli.app.LichessPuzzleImporter")
    def test_import_with_errors(self, mock_importer_cls, tmp_path):
        db_path = tmp_path / "test.db"
        mock_importer = MagicMock()
        mock_importer.import_to.return_value = ImportResult(
            source="lichess", total_fetched=5, total_added=3, errors=["parse error 1"]
        )
        mock_importer_cls.return_value = mock_importer

        result = runner.invoke(app, ["import-puzzles", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Errors" in result.output

    @patch("src.cli.app.LichessPuzzleImporter")
    def test_import_with_theme(self, mock_importer_cls, tmp_path):
        db_path = tmp_path / "test.db"
        mock_importer = MagicMock()
        mock_importer.import_to.return_value = ImportResult(
            source="lichess", total_fetched=3, total_added=3
        )
        mock_importer_cls.return_value = mock_importer

        result = runner.invoke(app, ["import-puzzles", "--theme", "fork", "--db", str(db_path)])
        assert result.exit_code == 0
        # Verify themes passed through
        call_kwargs = mock_importer.import_to.call_args
        assert call_kwargs[1]["themes"] == ["fork"]


class TestInitCardsCommand:
    """Tests for the init-cards command."""

    def test_init_cards_creates_cards(self, tmp_path):
        db_path = tmp_path / "test.db"
        from src.storage import Repository

        # Seed exercises
        with Repository(db_path) as repo:
            for i in range(3):
                ex = TacticExercise(
                    id=f"init:t{i}",
                    fen=SCHOLARS_FEN,
                    tags=[],
                    source="test",
                    solution=["g7g6"],
                )
                repo.exercises.add(ex)

        result = runner.invoke(app, ["init-cards", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "3" in result.output

    def test_init_cards_empty_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["init-cards", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "0" in result.output


class TestConfigCommands:
    """Tests for config subcommands."""

    def test_config_show(self):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "database.path" in result.output
        assert "lichess.api_url" in result.output

    def test_config_init_creates_file(self, tmp_path):
        config_path = tmp_path / "config.toml"
        with patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        assert config_path.exists()

    def test_config_init_existing_no_overwrite(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("# existing")
        with patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path):
            # User says 'n' to overwrite
            result = runner.invoke(app, ["config", "init"], input="n\n")
        assert result.exit_code != 0  # Abort

    def test_config_init_secures_file(self, tmp_path):
        config_path = tmp_path / "config.toml"
        with patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        mode = config_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_config_init_secures_parent_directory(self, tmp_path):
        config_dir = tmp_path / "chess-trainer"
        config_dir.mkdir(mode=0o755)
        config_path = config_dir / "config.toml"
        with patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "init"])
        assert result.exit_code == 0
        dir_mode = config_dir.stat().st_mode & 0o777
        assert dir_mode == 0o700


class TestTrainCommand:
    """Tests for the train command (basic scenarios only)."""

    def test_train_empty_db(self, tmp_path):
        """With no exercises, train should exit immediately."""
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["train", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "No cards due" in result.output

    def test_train_invalid_type(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["train", "--type", "nonexistent", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Unknown exercise type" in result.output


class TestWebCommand:
    """Tests for the web command."""

    def test_web_missing_uvicorn(self):
        with patch.dict("sys.modules", {"uvicorn": None}):
            result = runner.invoke(app, ["web"])
            # When uvicorn import fails, should show error
            assert result.exit_code != 0 or "not installed" in result.output


class TestConfigGetCommand:
    """Tests for config get command."""

    def test_valid_key(self):
        with patch("src.cli.app.load_config", return_value=AppConfig()):
            result = runner.invoke(app, ["config", "get", "web.port"])
        assert result.exit_code == 0
        assert "web.port" in result.output
        assert "8000" in result.output

    def test_invalid_key_shows_valid_keys(self):
        result = runner.invoke(app, ["config", "get", "bogus.key"])
        assert result.exit_code == 1
        assert "Unknown key" in result.output
        assert "Valid keys" in result.output
        assert "web.port" in result.output

    def test_token_masked(self, monkeypatch):
        monkeypatch.setenv("CHESS_TRAINER_LICHESS_TOKEN", "secret123")
        result = runner.invoke(app, ["config", "get", "lichess.token"])
        assert result.exit_code == 0
        assert "***" in result.output
        assert "secret123" not in result.output

    def test_none_value_shows_not_set(self, monkeypatch):
        monkeypatch.delenv("CHESS_TRAINER_LICHESS_TOKEN", raising=False)
        monkeypatch.delenv("LICHESS_TOKEN", raising=False)
        result = runner.invoke(app, ["config", "get", "lichess.token"])
        assert result.exit_code == 0
        assert "(not set)" in result.output


class TestConfigSetCommand:
    """Tests for config set command."""

    def test_valid_set(self, tmp_path):
        config_path = tmp_path / "config.toml"
        with patch("src.config.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "set", "web.port", "9000"])
        assert result.exit_code == 0
        assert "9000" in result.output

    def test_invalid_key(self):
        result = runner.invoke(app, ["config", "set", "bogus.key", "val"])
        assert result.exit_code == 1
        assert "Unknown" in result.output

    def test_invalid_value(self, tmp_path):
        config_path = tmp_path / "config.toml"
        with patch("src.config.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "set", "web.port", "abc"])
        assert result.exit_code == 1

    def test_out_of_range(self, tmp_path):
        config_path = tmp_path / "config.toml"
        with patch("src.config.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "set", "web.port", "99999"])
        assert result.exit_code == 1
        assert "must be between" in result.output


class TestConfigResetCommand:
    """Tests for config reset command."""

    def test_reset_single_key(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[web]\nport = 9000\n")
        with patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "reset", "web.port"])
        assert result.exit_code == 0
        assert "reset to default" in result.output

    def test_reset_all_confirms(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[web]\nport = 9000\n")
        with patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "reset"], input="y\n")
        assert result.exit_code == 0
        assert "reset to defaults" in result.output

    def test_reset_all_aborts(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[web]\nport = 9000\n")
        with patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path):
            result = runner.invoke(app, ["config", "reset"], input="n\n")
        assert result.exit_code != 0  # Abort


class TestConfigInitInteractive:
    """Tests for config init --interactive."""

    def test_wizard_with_defaults(self, tmp_path):
        config_path = tmp_path / "config.toml"
        # Respond with defaults (just Enter 5 times)
        with (
            patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path),
            patch("src.config.DEFAULT_CONFIG_PATH", config_path),
        ):
            result = runner.invoke(
                app, ["config", "init", "--interactive"], input="\n\n\n\n\n"
            )
        assert result.exit_code == 0
        assert "Setup complete" in result.output
        assert config_path.exists()

    def test_wizard_with_custom_values(self, tmp_path):
        config_path = tmp_path / "config.toml"
        # Provide custom max_new_cards and max_reviews
        answers = (
            "~/.chess-trainer/trainer.db\n"  # db path (default)
            "\n"  # token (skip)
            "\n"  # engine (skip)
            "30\n"  # max_new_cards
            "200\n"  # max_reviews
        )
        with (
            patch("src.cli.app.DEFAULT_CONFIG_PATH", config_path),
            patch("src.config.DEFAULT_CONFIG_PATH", config_path),
        ):
            result = runner.invoke(app, ["config", "init", "--interactive"], input=answers)
        assert result.exit_code == 0
        assert "Setup complete" in result.output
