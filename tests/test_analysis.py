"""Tests for UCI engine analysis module and CLI analyze command."""

from unittest.mock import MagicMock, patch

import chess
import chess.engine
import pytest
from typer.testing import CliRunner

from src.analysis.classification import (
    MoveClassification,
    MoveEvaluation,
    classify_move,
)
from src.analysis.engine import (
    MATE_SCORE,
    AnalysisLine,
    AnalysisResult,
    EngineError,
    EngineManager,
    _find_engine,
    _parse_info,
)
from src.cli.app import _format_score, _parse_pgn_to_board, app
from src.config import AppConfig, load_config

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers for building mock engine InfoDict objects
# ---------------------------------------------------------------------------


def _make_info(
    cp: int | None = None,
    mate: int | None = None,
    pv: list[chess.Move] | None = None,
    depth: int = 20,
    seldepth: int = 22,
    nodes: int = 1_000_000,
    nps: int = 500_000,
) -> dict:
    """Build a mock InfoDict matching python-chess conventions."""
    info: dict = {
        "depth": depth,
        "seldepth": seldepth,
        "nodes": nodes,
        "nps": nps,
    }
    if cp is not None:
        info["score"] = chess.engine.PovScore(chess.engine.Cp(cp), chess.WHITE)
    elif mate is not None:
        info["score"] = chess.engine.PovScore(chess.engine.Mate(mate), chess.WHITE)
    if pv is not None:
        info["pv"] = pv
    return info


def _make_mock_engine():
    """Create a mock SimpleEngine with analyse() method."""
    engine = MagicMock(spec=chess.engine.SimpleEngine)
    engine.configure = MagicMock()
    engine.quit = MagicMock()
    return engine


# ===========================================================================
# classification.py — classify_move
# ===========================================================================


class TestClassifyMove:
    """Tests for classify_move threshold boundaries."""

    def test_zero_loss_is_best(self):
        assert classify_move(0) == MoveClassification.BEST

    def test_negative_loss_is_best(self):
        assert classify_move(-5) == MoveClassification.BEST

    def test_10cp_is_excellent(self):
        assert classify_move(10) == MoveClassification.EXCELLENT

    def test_5cp_is_excellent(self):
        assert classify_move(5) == MoveClassification.EXCELLENT

    def test_11cp_is_good(self):
        assert classify_move(11) == MoveClassification.GOOD

    def test_25cp_is_good(self):
        assert classify_move(25) == MoveClassification.GOOD

    def test_26cp_is_inaccuracy(self):
        assert classify_move(26) == MoveClassification.INACCURACY

    def test_50cp_is_inaccuracy(self):
        assert classify_move(50) == MoveClassification.INACCURACY

    def test_51cp_is_mistake(self):
        assert classify_move(51) == MoveClassification.MISTAKE

    def test_100cp_is_mistake(self):
        assert classify_move(100) == MoveClassification.MISTAKE

    def test_101cp_is_blunder(self):
        assert classify_move(101) == MoveClassification.BLUNDER

    def test_large_loss_is_blunder(self):
        assert classify_move(500) == MoveClassification.BLUNDER


# ===========================================================================
# classification.py — MoveClassification
# ===========================================================================


class TestMoveClassification:
    """Tests for the MoveClassification enum."""

    def test_ordering(self):
        assert MoveClassification.BEST < MoveClassification.BLUNDER
        assert MoveClassification.EXCELLENT < MoveClassification.MISTAKE

    def test_all_values(self):
        assert len(MoveClassification) == 6


# ===========================================================================
# classification.py — MoveEvaluation
# ===========================================================================


class TestMoveEvaluation:
    """Tests for the MoveEvaluation dataclass."""

    def test_frozen(self):
        ev = MoveEvaluation(
            move=chess.Move.from_uci("e2e4"),
            classification=MoveClassification.BEST,
            cp_loss=0,
            best_move=chess.Move.from_uci("e2e4"),
            score_before=30,
            score_after=30,
        )
        with pytest.raises(AttributeError):
            ev.cp_loss = 100  # type: ignore[misc]


# ===========================================================================
# engine.py — _find_engine
# ===========================================================================


class TestFindEngine:
    """Tests for auto-detection of UCI engines."""

    @patch("src.analysis.engine.shutil.which")
    def test_finds_stockfish(self, mock_which):
        mock_which.side_effect = lambda name: (
            "/usr/games/stockfish" if name == "stockfish" else None
        )
        assert _find_engine() == "/usr/games/stockfish"

    @patch("src.analysis.engine.shutil.which")
    def test_finds_lc0(self, mock_which):
        mock_which.side_effect = lambda name: "/usr/bin/lc0" if name == "lc0" else None
        assert _find_engine() == "/usr/bin/lc0"

    @patch("src.analysis.engine.shutil.which", return_value=None)
    def test_raises_when_not_found(self, mock_which):
        with pytest.raises(EngineError, match="No UCI engine found"):
            _find_engine()


# ===========================================================================
# engine.py — _parse_info
# ===========================================================================


class TestParseInfo:
    """Tests for converting InfoDict to AnalysisLine."""

    def test_cp_score(self):
        info = _make_info(cp=150, depth=15)
        line = _parse_info(info, multipv_rank=1)
        assert line.score_cp == 150
        assert line.score_mate is None
        assert line.depth == 15
        assert line.multipv_rank == 1

    def test_mate_score(self):
        info = _make_info(mate=3, depth=20)
        line = _parse_info(info)
        assert line.score_cp is None
        assert line.score_mate == 3

    def test_negative_mate(self):
        info = _make_info(mate=-2, depth=20)
        line = _parse_info(info)
        assert line.score_mate == -2

    def test_pv_moves(self):
        pv = [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]
        info = _make_info(cp=30, pv=pv)
        line = _parse_info(info)
        assert line.pv == pv

    def test_no_score(self):
        info = {"depth": 10, "seldepth": 12, "nodes": 100, "nps": 50}
        line = _parse_info(info)
        assert line.score_cp is None
        assert line.score_mate is None

    def test_nodes_and_nps(self):
        info = _make_info(cp=0, nodes=5_000_000, nps=1_000_000)
        line = _parse_info(info)
        assert line.nodes == 5_000_000
        assert line.nps == 1_000_000


# ===========================================================================
# engine.py — AnalysisLine
# ===========================================================================


class TestAnalysisLine:
    """Tests for AnalysisLine properties."""

    def test_score_value_cp(self):
        line = AnalysisLine(score_cp=150, score_mate=None, pv=[], depth=20)
        assert line.score_value == 150

    def test_score_value_mate_winning(self):
        line = AnalysisLine(score_cp=None, score_mate=3, pv=[], depth=20)
        assert line.score_value == MATE_SCORE

    def test_score_value_mate_losing(self):
        line = AnalysisLine(score_cp=None, score_mate=-2, pv=[], depth=20)
        assert line.score_value == -MATE_SCORE

    def test_score_value_none(self):
        line = AnalysisLine(score_cp=None, score_mate=None, pv=[], depth=20)
        assert line.score_value == 0


# ===========================================================================
# engine.py — AnalysisResult
# ===========================================================================


class TestAnalysisResult:
    """Tests for AnalysisResult properties."""

    def test_best_line(self):
        lines = [
            AnalysisLine(score_cp=150, score_mate=None, pv=[], depth=20, multipv_rank=1),
            AnalysisLine(score_cp=80, score_mate=None, pv=[], depth=20, multipv_rank=2),
        ]
        result = AnalysisResult(fen=chess.STARTING_FEN, lines=lines, depth=20)
        assert result.best_line is lines[0]

    def test_best_line_empty(self):
        result = AnalysisResult(fen=chess.STARTING_FEN, lines=[], depth=20)
        assert result.best_line is None

    def test_evaluation(self):
        lines = [AnalysisLine(score_cp=42, score_mate=None, pv=[], depth=20)]
        result = AnalysisResult(fen=chess.STARTING_FEN, lines=lines, depth=20)
        assert result.evaluation == 42

    def test_evaluation_empty(self):
        result = AnalysisResult(fen=chess.STARTING_FEN, lines=[], depth=20)
        assert result.evaluation == 0


# ===========================================================================
# engine.py — EngineManager lifecycle
# ===========================================================================


class TestEngineManagerLifecycle:
    """Tests for EngineManager open/close and context manager."""

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_open_and_close(self, mock_popen):
        mock_popen.return_value = _make_mock_engine()
        mgr = EngineManager(path="/usr/games/stockfish")
        assert not mgr.is_open
        mgr.open()
        assert mgr.is_open
        mgr.close()
        assert not mgr.is_open

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_context_manager(self, mock_popen):
        mock_popen.return_value = _make_mock_engine()
        with EngineManager(path="/usr/games/stockfish") as mgr:
            assert mgr.is_open
        assert not mgr.is_open

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_double_open_is_noop(self, mock_popen):
        mock_popen.return_value = _make_mock_engine()
        mgr = EngineManager(path="/usr/games/stockfish")
        mgr.open()
        mgr.open()  # Should not raise
        assert mock_popen.call_count == 1
        mgr.close()

    def test_close_without_open_is_noop(self):
        mgr = EngineManager(path="/usr/games/stockfish")
        mgr.close()  # Should not raise

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_configures_hash_and_threads(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_popen.return_value = mock_engine
        mgr = EngineManager(path="/usr/games/stockfish", hash_mb=512, threads=4)
        mgr.open()
        mock_engine.configure.assert_called_once_with({"Hash": 512, "Threads": 4})
        mgr.close()

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_open_file_not_found(self, mock_popen):
        mock_popen.side_effect = FileNotFoundError()
        mgr = EngineManager(path="/nonexistent/engine")
        with pytest.raises(EngineError, match="Engine not found"):
            mgr.open()

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_open_engine_terminated(self, mock_popen):
        mock_popen.side_effect = chess.engine.EngineTerminatedError()
        mgr = EngineManager(path="/usr/games/stockfish")
        with pytest.raises(EngineError, match="Engine failed to start"):
            mgr.open()

    @patch("src.analysis.engine._find_engine", return_value="/usr/games/stockfish")
    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_auto_detect_path(self, mock_popen, mock_find):
        mock_popen.return_value = _make_mock_engine()
        mgr = EngineManager()  # No path
        mgr.open()
        mock_find.assert_called_once()
        mock_popen.assert_called_once_with("/usr/games/stockfish")
        mgr.close()


# ===========================================================================
# engine.py — EngineManager.analyze
# ===========================================================================


class TestEngineManagerAnalyze:
    """Tests for EngineManager.analyze()."""

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_single_pv(self, mock_popen):
        mock_engine = _make_mock_engine()
        pv = [chess.Move.from_uci("e2e4")]
        mock_engine.analyse.return_value = [_make_info(cp=30, pv=pv, depth=20)]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            board = chess.Board()
            result = mgr.analyze(board, depth=20)

        assert len(result.lines) == 1
        assert result.best_line.score_cp == 30
        assert result.best_line.pv == pv
        assert result.fen == chess.STARTING_FEN

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_multi_pv(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20),
            _make_info(cp=20, pv=[chess.Move.from_uci("d2d4")], depth=20),
            _make_info(cp=10, pv=[chess.Move.from_uci("g1f3")], depth=20),
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            result = mgr.analyze(chess.Board(), depth=20, multipv=3)

        assert len(result.lines) == 3
        assert result.lines[0].multipv_rank == 1
        assert result.lines[1].multipv_rank == 2
        assert result.lines[2].multipv_rank == 3

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_with_time_limit(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [_make_info(cp=15, depth=12)]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            mgr.analyze(chess.Board(), time_limit=1.0)

        call_args = mock_engine.analyse.call_args
        limit = call_args[0][1]  # Second positional arg is the Limit
        assert limit.time == 1.0
        assert limit.depth is None

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_mate_score(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(mate=2, pv=[chess.Move.from_uci("h5f7")], depth=20)
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            result = mgr.analyze(chess.Board(), depth=20)

        assert result.best_line.score_mate == 2
        assert result.evaluation == MATE_SCORE

    def test_analyze_without_open_raises(self):
        mgr = EngineManager(path="/usr/games/stockfish")
        with pytest.raises(EngineError, match="Engine is not open"):
            mgr.analyze(chess.Board())

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_engine_terminated(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.side_effect = chess.engine.EngineTerminatedError()
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            with pytest.raises(EngineError, match="Engine terminated"):
                mgr.analyze(chess.Board())


# ===========================================================================
# engine.py — EngineManager.evaluate_move
# ===========================================================================


class TestEvaluateMove:
    """Tests for EngineManager.evaluate_move()."""

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_best_move(self, mock_popen):
        mock_engine = _make_mock_engine()
        best_move = chess.Move.from_uci("e2e4")
        # First call: analyze before (score +30, best move e2e4)
        # Second call: analyze after e2e4 (score -30 from black's POV = +30)
        mock_engine.analyse.side_effect = [
            [_make_info(cp=30, pv=[best_move], depth=20)],
            [_make_info(cp=-30, pv=[chess.Move.from_uci("e7e5")], depth=20)],
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            ev = mgr.evaluate_move(chess.Board(), best_move, depth=20)

        assert ev.classification == MoveClassification.BEST
        assert ev.cp_loss == 0
        assert ev.best_move == best_move

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_blunder(self, mock_popen):
        mock_engine = _make_mock_engine()
        best_move = chess.Move.from_uci("e2e4")
        played_move = chess.Move.from_uci("a2a3")
        # Before: +30, best is e2e4
        # After a2a3: +120 for black = -120 from white's perspective → cp_loss = 30 - (-120) = 150
        mock_engine.analyse.side_effect = [
            [_make_info(cp=30, pv=[best_move], depth=20)],
            [_make_info(cp=120, pv=[chess.Move.from_uci("e7e5")], depth=20)],
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            ev = mgr.evaluate_move(chess.Board(), played_move, depth=20)

        assert ev.classification == MoveClassification.BLUNDER
        assert ev.cp_loss == 150
        assert ev.best_move == best_move

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_inaccuracy(self, mock_popen):
        mock_engine = _make_mock_engine()
        best_move = chess.Move.from_uci("e2e4")
        played_move = chess.Move.from_uci("d2d4")
        # Before: +30, best is e2e4
        # After d2d4: +5 for black = -5 from white's perspective → cp_loss = 30-(-5) = 35
        mock_engine.analyse.side_effect = [
            [_make_info(cp=30, pv=[best_move], depth=20)],
            [_make_info(cp=5, pv=[chess.Move.from_uci("d7d5")], depth=20)],
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            ev = mgr.evaluate_move(chess.Board(), played_move, depth=20)

        assert ev.classification == MoveClassification.INACCURACY
        assert ev.cp_loss == 35

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_mate_missed(self, mock_popen):
        mock_engine = _make_mock_engine()
        best_move = chess.Move.from_uci("h5f7")
        played_move = chess.Move.from_uci("a2a3")
        # Before: mate in 2 (MATE_SCORE), best is Qxf7
        # After a3: -50 for black = +50 from white's perspective → cp_loss = MATE_SCORE - 50
        mock_engine.analyse.side_effect = [
            [_make_info(mate=2, pv=[best_move], depth=20)],
            [_make_info(cp=-50, pv=[chess.Move.from_uci("e7e5")], depth=20)],
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            ev = mgr.evaluate_move(chess.Board(), played_move, depth=20)

        assert ev.classification == MoveClassification.BLUNDER
        assert ev.cp_loss == MATE_SCORE - 50

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_same_mate(self, mock_popen):
        mock_engine = _make_mock_engine()
        # Scholar's mate position where Qxf7 is mate
        board = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 3")
        best_move = chess.Move.from_uci("h5f7")
        # Both before and after give mate → cp_loss = 0
        mock_engine.analyse.side_effect = [
            [_make_info(mate=1, pv=[best_move], depth=20)],
            [_make_info(mate=-1, pv=[], depth=20)],  # Mate from black's POV → +MATE for white
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            ev = mgr.evaluate_move(board, best_move, depth=20)

        assert ev.classification == MoveClassification.BEST
        assert ev.cp_loss == 0

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_no_pv_uses_played_move_as_best(self, mock_popen):
        """When the engine returns no PV, use the played move as best_move."""
        mock_engine = _make_mock_engine()
        played = chess.Move.from_uci("e2e4")
        mock_engine.analyse.side_effect = [
            [_make_info(cp=0, pv=[], depth=20)],  # No PV
            [_make_info(cp=0, pv=[], depth=20)],
        ]
        mock_popen.return_value = mock_engine

        with EngineManager(path="/usr/games/stockfish") as mgr:
            ev = mgr.evaluate_move(chess.Board(), played, depth=20)

        assert ev.best_move == played


# ===========================================================================
# config.py — EngineConfig
# ===========================================================================


class TestEngineConfig:
    """Tests for engine configuration."""

    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.engine.path is None
        assert cfg.engine.hash_mb == 256
        assert cfg.engine.threads == 2
        assert cfg.engine.default_depth == 20
        assert cfg.engine.default_multipv == 3

    def test_toml_override(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[engine]\npath = "/opt/stockfish"\nhash_mb = 512\n'
            "threads = 8\ndefault_depth = 30\ndefault_multipv = 5\n"
        )
        cfg = load_config(config_file)
        assert cfg.engine.path == "/opt/stockfish"
        assert cfg.engine.hash_mb == 512
        assert cfg.engine.threads == 8
        assert cfg.engine.default_depth == 30
        assert cfg.engine.default_multipv == 5

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CHESS_TRAINER_ENGINE_PATH", "/usr/local/bin/sf")
        monkeypatch.setenv("CHESS_TRAINER_ENGINE_HASH_MB", "1024")
        monkeypatch.setenv("CHESS_TRAINER_ENGINE_THREADS", "16")
        cfg = load_config(None)
        assert cfg.engine.path == "/usr/local/bin/sf"
        assert cfg.engine.hash_mb == 1024
        assert cfg.engine.threads == 16

    def test_generate_default_includes_engine(self):
        from src.config import generate_default_config

        text = generate_default_config()
        assert "[engine]" in text
        assert "hash_mb" in text
        assert "default_depth" in text

    def test_config_show_includes_engine(self):
        result = runner.invoke(app, ["config", "show"])
        assert "engine.path" in result.output
        assert "engine.hash_mb" in result.output
        assert "engine.default_depth" in result.output
        assert "engine.default_multipv" in result.output


# ===========================================================================
# cli/app.py — _format_score
# ===========================================================================


class TestFormatScore:
    """Tests for score formatting helper."""

    def test_positive_cp(self):
        line = AnalysisLine(score_cp=150, score_mate=None, pv=[], depth=20)
        assert _format_score(line) == "+1.50"

    def test_negative_cp(self):
        line = AnalysisLine(score_cp=-200, score_mate=None, pv=[], depth=20)
        assert _format_score(line) == "-2.00"

    def test_zero_cp(self):
        line = AnalysisLine(score_cp=0, score_mate=None, pv=[], depth=20)
        assert _format_score(line) == "+0.00"

    def test_mate_positive(self):
        line = AnalysisLine(score_cp=None, score_mate=3, pv=[], depth=20)
        assert _format_score(line) == "M3"

    def test_mate_negative(self):
        line = AnalysisLine(score_cp=None, score_mate=-2, pv=[], depth=20)
        assert _format_score(line) == "-M2"


# ===========================================================================
# cli/app.py — _parse_pgn_to_board
# ===========================================================================


class TestParsePgnToBoard:
    """Tests for PGN parsing helper."""

    def test_simple_pgn(self):
        pgn = "1. e4 e5 2. Nf3 Nc6"
        board = _parse_pgn_to_board(pgn)
        # After 2...Nc6, it's white's move
        assert board.turn == chess.WHITE
        assert board.fullmove_number == 3

    def test_pgn_file(self, tmp_path):
        pgn_file = tmp_path / "game.pgn"
        pgn_file.write_text("1. d4 d5 2. c4 e6\n")
        board = _parse_pgn_to_board(str(pgn_file))
        assert board.turn == chess.WHITE
        assert board.fullmove_number == 3

    def test_invalid_pgn_raises(self):
        import typer

        with pytest.raises(typer.BadParameter, match="Could not parse PGN"):
            _parse_pgn_to_board("")


# ===========================================================================
# cli/app.py — analyze command
# ===========================================================================


class TestAnalyzeCommand:
    """Tests for the CLI analyze command."""

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_starting_position(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20),
        ]
        mock_popen.return_value = mock_engine

        result = runner.invoke(
            app, ["analyze", "--engine", "/usr/games/stockfish", "--depth", "10"]
        )
        assert result.exit_code == 0
        assert "Analysis" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_with_fen(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=150, pv=[chess.Move.from_uci("h5f7")], depth=15),
        ]
        mock_popen.return_value = mock_engine

        fen = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 2 3"
        result = runner.invoke(app, ["analyze", fen, "--engine", "/usr/games/stockfish"])
        assert result.exit_code == 0

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_with_multipv(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20),
            _make_info(cp=20, pv=[chess.Move.from_uci("d2d4")], depth=20),
            _make_info(cp=10, pv=[chess.Move.from_uci("g1f3")], depth=20),
        ]
        mock_popen.return_value = mock_engine

        result = runner.invoke(
            app, ["analyze", "--engine", "/usr/games/stockfish", "--multipv", "3"]
        )
        assert result.exit_code == 0

    def test_analyze_invalid_fen(self):
        result = runner.invoke(
            app, ["analyze", "not-a-valid-fen", "--engine", "/usr/games/stockfish"]
        )
        assert result.exit_code == 1
        assert "Invalid FEN" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_engine_not_found(self, mock_popen):
        mock_popen.side_effect = FileNotFoundError()
        result = runner.invoke(app, ["analyze", "--engine", "/nonexistent/engine"])
        assert result.exit_code == 1
        assert "Engine not found" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_with_pgn(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=10, pv=[chess.Move.from_uci("f1c4")], depth=20),
        ]
        mock_popen.return_value = mock_engine

        result = runner.invoke(
            app, ["analyze", "--pgn", "1. e4 e5 2. Nf3 Nc6", "--engine", "/usr/games/stockfish"]
        )
        assert result.exit_code == 0

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_interactive_quit(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20),
        ]
        mock_popen.return_value = mock_engine

        result = runner.invoke(
            app,
            ["analyze", "--interactive", "--engine", "/usr/games/stockfish"],
            input="quit\n",
        )
        assert result.exit_code == 0

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_interactive_move_and_back(self, mock_popen):
        mock_engine = _make_mock_engine()
        # Return different PVs for different positions:
        # 1st call: starting pos → best is e2e4
        # 2nd call: after 1.e4 → best is e7e5 (black to move)
        # 3rd call: back to starting pos → best is e2e4 again
        mock_engine.analyse.side_effect = [
            [_make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20)],
            [_make_info(cp=-25, pv=[chess.Move.from_uci("e7e5")], depth=20)],
            [_make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20)],
        ]
        mock_popen.return_value = mock_engine

        result = runner.invoke(
            app,
            ["analyze", "--interactive", "--engine", "/usr/games/stockfish"],
            input="e4\nback\nquit\n",
        )
        assert result.exit_code == 0

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_interactive_invalid_move(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20),
        ]
        mock_popen.return_value = mock_engine

        result = runner.invoke(
            app,
            ["analyze", "--interactive", "--engine", "/usr/games/stockfish"],
            input="xyz\nquit\n",
        )
        assert result.exit_code == 0
        assert "Invalid move" in result.output

    @patch("src.analysis.engine.chess.engine.SimpleEngine.popen_uci")
    def test_analyze_interactive_back_no_moves(self, mock_popen):
        mock_engine = _make_mock_engine()
        mock_engine.analyse.return_value = [
            _make_info(cp=30, pv=[chess.Move.from_uci("e2e4")], depth=20),
        ]
        mock_popen.return_value = mock_engine

        result = runner.invoke(
            app,
            ["analyze", "--interactive", "--engine", "/usr/games/stockfish"],
            input="back\nquit\n",
        )
        assert result.exit_code == 0
        assert "No moves to undo" in result.output
