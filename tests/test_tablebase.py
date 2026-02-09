"""Tests for endgame tablebase module."""

from unittest.mock import MagicMock, patch

import chess
import chess.syzygy
import pytest
import requests

from src.tablebase import TablebaseError, TablebaseManager, TablebaseMove, TablebaseResult
from src.tablebase.manager import _negate_wdl, _wdl_to_category

# ── Model tests ──────────────────────────────────────────────────────────────


class TestTablebaseMove:
    """Tests for TablebaseMove dataclass."""

    def test_create_basic(self):
        m = TablebaseMove(uci="e2e4", san="e4", wdl=2)
        assert m.uci == "e2e4"
        assert m.san == "e4"
        assert m.wdl == 2

    def test_defaults(self):
        m = TablebaseMove(uci="a1a2", san="Ka2", wdl=0)
        assert m.dtz is None
        assert m.category == ""
        assert m.zeroing is False
        assert m.checkmate is False

    def test_full_construction(self):
        m = TablebaseMove(
            uci="h7h8q",
            san="h8=Q",
            wdl=2,
            dtz=1,
            category="win",
            zeroing=True,
            checkmate=False,
        )
        assert m.dtz == 1
        assert m.category == "win"
        assert m.zeroing is True

    def test_frozen(self):
        m = TablebaseMove(uci="e2e4", san="e4", wdl=2)
        with pytest.raises(AttributeError):
            m.wdl = 0  # type: ignore[misc]

    def test_checkmate_move(self):
        m = TablebaseMove(uci="d1h5", san="Qh5#", wdl=2, checkmate=True)
        assert m.checkmate is True


class TestTablebaseResult:
    """Tests for TablebaseResult dataclass."""

    def test_create_win(self):
        r = TablebaseResult(wdl=2, dtz=5, category="win")
        assert r.is_winning is True
        assert r.is_losing is False
        assert r.is_draw is False

    def test_create_loss(self):
        r = TablebaseResult(wdl=-2, dtz=-3, category="loss")
        assert r.is_winning is False
        assert r.is_losing is True
        assert r.is_draw is False

    def test_create_draw(self):
        r = TablebaseResult(wdl=0, dtz=0, category="draw")
        assert r.is_winning is False
        assert r.is_losing is False
        assert r.is_draw is True

    def test_cursed_win(self):
        r = TablebaseResult(wdl=1, category="cursed-win")
        assert r.is_winning is True
        assert r.is_losing is False

    def test_blessed_loss(self):
        r = TablebaseResult(wdl=-1, category="blessed-loss")
        assert r.is_winning is False
        assert r.is_losing is True

    def test_frozen(self):
        r = TablebaseResult(wdl=2)
        with pytest.raises(AttributeError):
            r.wdl = 0  # type: ignore[misc]

    def test_defaults(self):
        r = TablebaseResult(wdl=0)
        assert r.dtz is None
        assert r.category == ""
        assert r.checkmate is False
        assert r.stalemate is False
        assert r.moves == []

    def test_checkmate_result(self):
        r = TablebaseResult(wdl=-2, dtz=0, category="loss", checkmate=True)
        assert r.checkmate is True
        assert r.is_losing is True

    def test_stalemate_result(self):
        r = TablebaseResult(wdl=0, dtz=0, category="draw", stalemate=True)
        assert r.stalemate is True
        assert r.is_draw is True

    def test_best_moves_empty(self):
        r = TablebaseResult(wdl=2, moves=[])
        assert r.best_moves == []

    def test_best_moves_single(self):
        m = TablebaseMove(uci="e2e4", san="e4", wdl=2)
        r = TablebaseResult(wdl=2, moves=[m])
        assert r.best_moves == [m]

    def test_best_moves_multiple(self):
        m1 = TablebaseMove(uci="e2e4", san="e4", wdl=2, dtz=3)
        m2 = TablebaseMove(uci="d2d4", san="d4", wdl=2, dtz=5)
        m3 = TablebaseMove(uci="a2a3", san="a3", wdl=0, dtz=0)
        r = TablebaseResult(wdl=2, moves=[m1, m2, m3])
        assert r.best_moves == [m1, m2]

    def test_best_moves_all_same_wdl(self):
        m1 = TablebaseMove(uci="a1a2", san="Ka2", wdl=0)
        m2 = TablebaseMove(uci="a1b1", san="Kb1", wdl=0)
        r = TablebaseResult(wdl=0, moves=[m1, m2])
        assert r.best_moves == [m1, m2]


# ── Helper function tests ───────────────────────────────────────────────────


class TestHelpers:
    """Tests for module-level helper functions."""

    def test_wdl_to_category_win(self):
        assert _wdl_to_category(2) == "win"

    def test_wdl_to_category_cursed_win(self):
        assert _wdl_to_category(1) == "cursed-win"

    def test_wdl_to_category_draw(self):
        assert _wdl_to_category(0) == "draw"

    def test_wdl_to_category_blessed_loss(self):
        assert _wdl_to_category(-1) == "blessed-loss"

    def test_wdl_to_category_loss(self):
        assert _wdl_to_category(-2) == "loss"

    def test_wdl_to_category_unknown(self):
        assert _wdl_to_category(99) == "unknown"

    def test_negate_wdl(self):
        assert _negate_wdl(2) == -2
        assert _negate_wdl(-2) == 2
        assert _negate_wdl(0) == 0
        assert _negate_wdl(1) == -1
        assert _negate_wdl(-1) == 1


# ── TablebaseManager tests ──────────────────────────────────────────────────


class TestTablebaseManagerInit:
    """Tests for manager initialization and properties."""

    def test_default_init(self):
        mgr = TablebaseManager()
        assert mgr.has_local is False
        assert mgr.has_lichess is True

    def test_lichess_disabled(self):
        mgr = TablebaseManager(use_lichess_fallback=False)
        assert mgr.has_lichess is False

    def test_custom_max_pieces(self):
        mgr = TablebaseManager(max_pieces=5)
        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")  # KPK = 3 pieces
        assert mgr.is_tablebase_position(board) is True

    def test_is_tablebase_position_true(self):
        mgr = TablebaseManager(max_pieces=7)
        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")  # 3 pieces
        assert mgr.is_tablebase_position(board) is True

    def test_is_tablebase_position_false(self):
        mgr = TablebaseManager(max_pieces=3)
        board = chess.Board("8/8/8/2B5/8/5K2/4P3/4k3 w - - 0 1")  # 4 pieces
        assert mgr.is_tablebase_position(board) is False

    def test_is_tablebase_position_starting(self):
        mgr = TablebaseManager()
        board = chess.Board()
        assert mgr.is_tablebase_position(board) is False

    def test_context_manager(self):
        with TablebaseManager() as mgr:
            assert mgr is not None
        # close() should be called, no error

    @patch("src.tablebase.manager.chess.syzygy.open_tablebase")
    def test_init_with_syzygy_path(self, mock_open):
        mock_open.return_value = MagicMock()
        mgr = TablebaseManager(syzygy_path="/path/to/syzygy")
        assert mgr.has_local is True
        mock_open.assert_called_once_with("/path/to/syzygy")

    @patch("src.tablebase.manager.chess.syzygy.open_tablebase")
    def test_init_syzygy_path_fails(self, mock_open):
        mock_open.side_effect = OSError("No such directory")
        mgr = TablebaseManager(syzygy_path="/bad/path")
        assert mgr.has_local is False

    @patch("src.tablebase.manager.chess.syzygy.open_tablebase")
    def test_close_syzygy(self, mock_open):
        mock_tb = MagicMock()
        mock_open.return_value = mock_tb
        mgr = TablebaseManager(syzygy_path="/path")
        mgr.close()
        mock_tb.close.assert_called_once()
        assert mgr.has_local is False

    def test_close_without_syzygy(self):
        mgr = TablebaseManager()
        mgr.close()  # Should not raise


class TestTablebaseManagerProbe:
    """Tests for the probe() method."""

    def test_too_many_pieces(self):
        mgr = TablebaseManager(max_pieces=5, use_lichess_fallback=False)
        board = chess.Board()  # 32 pieces
        with pytest.raises(TablebaseError, match="Too many pieces"):
            mgr.probe(board)

    def test_checkmate_position(self):
        # Scholar's mate position — Black is checkmated
        board = chess.Board("r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4")
        mgr = TablebaseManager(use_lichess_fallback=False, max_pieces=32)
        result = mgr.probe(board)
        assert result.checkmate is True
        assert result.wdl == -2
        assert result.category == "loss"

    def test_stalemate_position(self):
        # Stalemate: Black king on f8, White pawn on f7 + king on f6
        board = chess.Board("5k2/5P2/5K2/8/8/8/8/8 b - - 0 1")
        assert board.is_stalemate()
        mgr = TablebaseManager(use_lichess_fallback=False, max_pieces=7)
        result = mgr.probe(board)
        assert result.stalemate is True
        assert result.wdl == 0
        assert result.category == "draw"

    def test_no_backend_available(self):
        mgr = TablebaseManager(use_lichess_fallback=False)
        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        with pytest.raises(TablebaseError, match="No tablebase backend"):
            mgr.probe(board)


class TestTablebaseManagerSyzygy:
    """Tests for local Syzygy probing (mocked)."""

    def _make_manager_with_mock_syzygy(self):
        """Create a manager with a mocked Syzygy tablebase."""
        mgr = TablebaseManager(use_lichess_fallback=False)
        mock_tb = MagicMock()
        mgr._syzygy = mock_tb
        return mgr, mock_tb

    def test_probe_syzygy_win(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        mock_tb.probe_wdl.return_value = 2
        mock_tb.get_dtz.return_value = 5

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == 2
        assert result.dtz == 5
        assert result.category == "win"

    def test_probe_syzygy_loss(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        mock_tb.probe_wdl.return_value = -2
        mock_tb.get_dtz.return_value = -3

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == -2
        assert result.category == "loss"

    def test_probe_syzygy_draw(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        mock_tb.probe_wdl.return_value = 0
        mock_tb.get_dtz.return_value = 0

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == 0
        assert result.category == "draw"

    def test_probe_syzygy_moves_generated(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        # KPK position — White king a1, pawn e2, Black king e4
        board = chess.Board("8/8/8/8/4k3/8/4P3/K7 w - - 0 1")
        legal_count = len(list(board.legal_moves))

        # Position WDL + DTZ, then one pair per legal move
        mock_tb.probe_wdl.side_effect = [2] + [0] * legal_count
        mock_tb.get_dtz.side_effect = [5] + [0] * legal_count

        result = mgr.probe(board)

        assert result.wdl == 2
        assert len(result.moves) == legal_count

    def test_probe_syzygy_missing_table_fallback_disabled(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        mock_tb.probe_wdl.side_effect = chess.syzygy.MissingTableError

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        with pytest.raises(TablebaseError, match="No tablebase backend"):
            mgr.probe(board)

    @patch("src.tablebase.manager.requests.get")
    def test_probe_syzygy_missing_falls_back_to_lichess(self, mock_get):
        """When Syzygy table is missing, fall back to Lichess API."""
        mgr = TablebaseManager(use_lichess_fallback=True)
        mock_tb = MagicMock()
        mock_tb.probe_wdl.side_effect = chess.syzygy.MissingTableError
        mgr._syzygy = mock_tb

        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "dtz": 5,
                "category": "win",
                "checkmate": False,
                "stalemate": False,
                "moves": [],
            },
        )

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == 2
        assert result.category == "win"

    def test_probe_syzygy_cursed_win(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        mock_tb.probe_wdl.return_value = 1
        mock_tb.get_dtz.return_value = 120

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == 1
        assert result.category == "cursed-win"

    def test_probe_wdl_shortcut(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        mock_tb.probe_wdl.return_value = 2
        mock_tb.get_dtz.return_value = 5

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        wdl = mgr.probe_wdl(board)
        assert wdl == 2

    def test_best_moves_shortcut(self):
        mgr, mock_tb = self._make_manager_with_mock_syzygy()
        mock_tb.probe_wdl.return_value = 0
        mock_tb.get_dtz.return_value = 0

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        moves = mgr.best_moves(board)
        assert isinstance(moves, list)


class TestTablebaseManagerLichess:
    """Tests for Lichess API probing (mocked)."""

    LICHESS_WIN_RESPONSE = {
        "dtz": 1,
        "category": "win",
        "checkmate": False,
        "stalemate": False,
        "moves": [
            {
                "uci": "h7h8q",
                "san": "h8=Q",
                "dtz": -2,
                "category": "loss",
                "zeroing": True,
                "checkmate": False,
            },
            {
                "uci": "f3f4",
                "san": "Kf4",
                "dtz": -8,
                "category": "loss",
                "zeroing": False,
                "checkmate": False,
            },
            {
                "uci": "f3e3",
                "san": "Ke3",
                "dtz": 0,
                "category": "draw",
                "zeroing": False,
                "checkmate": False,
            },
        ],
    }

    LICHESS_DRAW_RESPONSE = {
        "dtz": 0,
        "category": "draw",
        "checkmate": False,
        "stalemate": False,
        "moves": [
            {
                "uci": "e1d1",
                "san": "Kd1",
                "dtz": 0,
                "category": "draw",
                "zeroing": False,
                "checkmate": False,
            },
        ],
    }

    LICHESS_CHECKMATE_RESPONSE = {
        "dtz": None,
        "category": "loss",
        "checkmate": True,
        "stalemate": False,
        "moves": [],
    }

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_win(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: self.LICHESS_WIN_RESPONSE,
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/7P/5K2/8/8/8/4k3/8 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == 2
        assert result.category == "win"
        assert result.dtz == 1
        assert not result.checkmate
        assert not result.stalemate

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_moves_parsed(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: self.LICHESS_WIN_RESPONSE,
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/7P/5K2/8/8/8/4k3/8 w - - 0 1")
        result = mgr.probe(board)

        # Moves should be sorted: winning first
        assert len(result.moves) == 3
        # h8=Q and Kf4 are "loss" for opponent → win for us (wdl=2)
        assert result.moves[0].wdl == 2
        assert result.moves[1].wdl == 2

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_move_wdl_negation(self, mock_get):
        """Lichess move categories are opponent's POV; we negate."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: self.LICHESS_WIN_RESPONSE,
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/7P/5K2/8/8/8/4k3/8 w - - 0 1")
        result = mgr.probe(board)

        # "loss" for opponent → win for us → wdl = 2
        winning_moves = [m for m in result.moves if m.category == "win"]
        assert len(winning_moves) >= 1

        # "draw" for opponent → draw for us → wdl = 0
        draw_moves = [m for m in result.moves if m.category == "draw"]
        assert len(draw_moves) == 1

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_draw(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: self.LICHESS_DRAW_RESPONSE,
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/8/8/8/8/5K2/8/4k3 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == 0
        assert result.category == "draw"

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_zeroing_flag(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: self.LICHESS_WIN_RESPONSE,
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/7P/5K2/8/8/8/4k3/8 w - - 0 1")
        result = mgr.probe(board)

        # h8=Q is zeroing (pawn promotion)
        h8q = next(m for m in result.moves if m.uci == "h7h8q")
        assert h8q.zeroing is True

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_dtz_negated(self, mock_get):
        """DTZ should be negated from Lichess response for our perspective."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: self.LICHESS_WIN_RESPONSE,
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/7P/5K2/8/8/8/4k3/8 w - - 0 1")
        result = mgr.probe(board)

        # h8=Q has lichess dtz=-2, negated = 2
        h8q = next(m for m in result.moves if m.uci == "h7h8q")
        assert h8q.dtz == 2

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_network_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("Network error")
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        with pytest.raises(TablebaseError, match="Lichess tablebase"):
            mgr.probe(board)

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_http_error(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        mock_get.return_value = mock_resp
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        with pytest.raises(TablebaseError, match="Lichess tablebase"):
            mgr.probe(board)

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_timeout(self, mock_get):
        mock_get.side_effect = requests.Timeout("Request timed out")
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        with pytest.raises(TablebaseError, match="Lichess tablebase"):
            mgr.probe(board)

    @patch("src.tablebase.manager.requests.get")
    def test_probe_passes_fen_param(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: self.LICHESS_DRAW_RESPONSE,
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/8/8/8/8/5K2/8/4k3 w - - 0 1")
        mgr.probe(board)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["fen"] == board.fen()

    @patch("src.tablebase.manager.requests.get")
    def test_probe_lichess_insufficient_material(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "dtz": 0,
                "category": "draw",
                "checkmate": False,
                "stalemate": False,
                "insufficient_material": True,
                "moves": [],
            },
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("8/8/8/8/8/5K2/8/4k3 w - - 0 1")
        result = mgr.probe(board)

        assert result.wdl == 0
        assert result.is_draw is True


class TestTablebaseManagerCategoryToWdl:
    """Tests for _category_to_wdl static method."""

    def test_win(self):
        assert TablebaseManager._category_to_wdl("win", False, False) == 2

    def test_cursed_win(self):
        assert TablebaseManager._category_to_wdl("cursed-win", False, False) == 1

    def test_draw(self):
        assert TablebaseManager._category_to_wdl("draw", False, False) == 0

    def test_blessed_loss(self):
        assert TablebaseManager._category_to_wdl("blessed-loss", False, False) == -1

    def test_loss(self):
        assert TablebaseManager._category_to_wdl("loss", False, False) == -2

    def test_checkmate_override(self):
        assert TablebaseManager._category_to_wdl("win", True, False) == -2

    def test_stalemate_override(self):
        assert TablebaseManager._category_to_wdl("win", False, True) == 0

    def test_unknown_category(self):
        assert TablebaseManager._category_to_wdl("unknown", False, False) == 0


class TestTablebaseManagerMovesSorting:
    """Tests for move sorting in probe results."""

    @patch("src.tablebase.manager.requests.get")
    def test_moves_sorted_by_wdl_desc(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "dtz": 5,
                "category": "win",
                "checkmate": False,
                "stalemate": False,
                "moves": [
                    {
                        "uci": "a1a2",
                        "san": "Ka2",
                        "dtz": 0,
                        "category": "draw",
                        "zeroing": False,
                        "checkmate": False,
                    },
                    {
                        "uci": "a1b1",
                        "san": "Kb1",
                        "dtz": -5,
                        "category": "loss",
                        "zeroing": False,
                        "checkmate": False,
                    },
                    {
                        "uci": "a1a3",
                        "san": "Ka3",
                        "dtz": -3,
                        "category": "loss",
                        "zeroing": False,
                        "checkmate": False,
                    },
                ],
            },
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("K7/8/8/8/8/8/8/4k3 w - - 0 1")
        result = mgr.probe(board)

        # Loss for opponent → win for us (wdl=2)
        # Draw for opponent → draw for us (wdl=0)
        wdls = [m.wdl for m in result.moves]
        assert wdls == sorted(wdls, reverse=True)

    @patch("src.tablebase.manager.requests.get")
    def test_moves_sorted_by_dtz_within_same_wdl(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "dtz": 5,
                "category": "win",
                "checkmate": False,
                "stalemate": False,
                "moves": [
                    {
                        "uci": "a1b1",
                        "san": "Kb1",
                        "dtz": -10,
                        "category": "loss",
                        "zeroing": False,
                        "checkmate": False,
                    },
                    {
                        "uci": "a1a2",
                        "san": "Ka2",
                        "dtz": -3,
                        "category": "loss",
                        "zeroing": False,
                        "checkmate": False,
                    },
                ],
            },
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("K7/8/8/8/8/8/8/4k3 w - - 0 1")
        result = mgr.probe(board)

        # Both are winning (opponent loss). Smaller |DTZ| first.
        assert result.moves[0].san == "Ka2"
        assert result.moves[1].san == "Kb1"

    @patch("src.tablebase.manager.requests.get")
    def test_moves_dtz_none_sorted_last(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "dtz": 5,
                "category": "win",
                "checkmate": False,
                "stalemate": False,
                "moves": [
                    {
                        "uci": "a1a2",
                        "san": "Ka2",
                        "dtz": None,
                        "category": "loss",
                        "zeroing": False,
                        "checkmate": False,
                    },
                    {
                        "uci": "a1b1",
                        "san": "Kb1",
                        "dtz": -3,
                        "category": "loss",
                        "zeroing": False,
                        "checkmate": False,
                    },
                ],
            },
        )
        mgr = TablebaseManager(use_lichess_fallback=True)
        board = chess.Board("K7/8/8/8/8/8/8/4k3 w - - 0 1")
        result = mgr.probe(board)

        # DTZ=None should sort after DTZ=-3
        assert result.moves[0].san == "Kb1"
        assert result.moves[1].san == "Ka2"
