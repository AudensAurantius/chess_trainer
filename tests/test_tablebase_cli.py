"""Tests for tablebase CLI command."""

from unittest.mock import MagicMock, patch

import chess
from typer.testing import CliRunner

from src.cli.app import app
from src.tablebase import TablebaseError, TablebaseMove, TablebaseResult

runner = CliRunner()


def _mock_tb_context(mock_mgr):
    """Create a mock context manager wrapping mock_mgr."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_mgr)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestTablebaseCommand:
    """Tests for the tablebase CLI command."""

    def test_no_args_exits(self):
        result = runner.invoke(app, ["tablebase"])
        assert result.exit_code != 0
        assert "Provide a FEN" in result.output

    def test_invalid_fen(self):
        result = runner.invoke(app, ["tablebase", "not-a-fen"])
        assert result.exit_code != 0
        assert "Invalid FEN" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_static_probe_win(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=2,
            dtz=5,
            category="win",
            moves=[
                TablebaseMove(uci="e2e4", san="e4", wdl=2, dtz=3, category="win"),
                TablebaseMove(uci="a2a3", san="a3", wdl=0, dtz=0, category="draw"),
            ],
        )

        result = runner.invoke(app, ["tablebase", "8/8/8/8/8/5K2/4P3/4k3 w - - 0 1"])
        assert result.exit_code == 0
        assert "WIN" in result.output
        assert "e4" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_static_probe_draw(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=0,
            dtz=0,
            category="draw",
            moves=[],
        )

        result = runner.invoke(app, ["tablebase", "8/8/8/8/8/5K2/8/4k3 w - - 0 1"])
        assert result.exit_code == 0
        assert "DRAW" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_static_probe_checkmate(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=-2,
            dtz=0,
            category="loss",
            checkmate=True,
        )

        result = runner.invoke(
            app,
            [
                "tablebase",
                "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4",
            ],
        )
        assert result.exit_code == 0
        assert "Checkmate" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_static_probe_stalemate(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=0,
            dtz=0,
            category="draw",
            stalemate=True,
        )

        result = runner.invoke(
            app,
            [
                "tablebase",
                "5k2/5P2/5K2/8/8/8/8/8 b - - 0 1",
            ],
        )
        assert result.exit_code == 0
        assert "Stalemate" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_probe_error_exits(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.side_effect = TablebaseError("Too many pieces")

        result = runner.invoke(app, ["tablebase", "8/8/8/8/8/5K2/4P3/4k3 w - - 0 1"])
        assert "Too many pieces" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_static_probe_shows_dtz(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=2,
            dtz=7,
            category="win",
            moves=[],
        )

        result = runner.invoke(app, ["tablebase", "8/8/8/8/8/5K2/4P3/4k3 w - - 0 1"])
        assert result.exit_code == 0
        assert "DTZ: 7" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_static_probe_zeroing_flag(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=2,
            dtz=1,
            category="win",
            moves=[
                TablebaseMove(
                    uci="e2e4",
                    san="e4",
                    wdl=2,
                    dtz=2,
                    category="win",
                    zeroing=True,
                ),
            ],
        )

        result = runner.invoke(app, ["tablebase", "8/8/8/8/8/5K2/4P3/4k3 w - - 0 1"])
        assert result.exit_code == 0
        assert "*" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_syzygy_path_passed(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(wdl=0, category="draw", moves=[])

        runner.invoke(
            app,
            ["tablebase", "8/8/8/8/8/5K2/8/4k3 w - - 0 1", "--syzygy", "/my/syzygy"],
        )
        mock_tb_class.assert_called_once()
        call_kwargs = mock_tb_class.call_args[1]
        assert call_kwargs["syzygy_path"] == "/my/syzygy"

    @patch("src.tablebase.TablebaseManager")
    def test_interactive_mode_quit(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=0,
            category="draw",
            moves=[],
        )

        result = runner.invoke(
            app,
            ["tablebase", "8/8/8/8/8/5K2/8/4k3 w - - 0 1", "--interactive"],
            input="quit\n",
        )
        assert result.exit_code == 0

    @patch("src.tablebase.TablebaseManager")
    def test_interactive_mode_back_no_moves(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=0,
            category="draw",
            moves=[],
        )

        result = runner.invoke(
            app,
            ["tablebase", "8/8/8/8/8/5K2/8/4k3 w - - 0 1", "--interactive"],
            input="back\nquit\n",
        )
        assert result.exit_code == 0
        assert "No moves to undo" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_interactive_mode_invalid_move(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=0,
            category="draw",
            moves=[],
        )

        result = runner.invoke(
            app,
            ["tablebase", "8/8/8/8/8/5K2/8/4k3 w - - 0 1", "--interactive"],
            input="xyz\nquit\n",
        )
        assert result.exit_code == 0
        assert "Invalid move" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_interactive_plays_move_and_back(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=0,
            category="draw",
            moves=[],
        )

        result = runner.invoke(
            app,
            ["tablebase", "8/8/8/8/8/5K2/8/4k3 w - - 0 1", "--interactive"],
            input="Ke3\nback\nquit\n",
        )
        assert result.exit_code == 0
        assert "Move undone" in result.output

    @patch("src.tablebase.TablebaseManager")
    def test_interactive_fen_command(self, mock_tb_class):
        mock_mgr = MagicMock()
        mock_tb_class.return_value = _mock_tb_context(mock_mgr)
        mock_mgr.probe.return_value = TablebaseResult(
            wdl=0,
            category="draw",
            moves=[],
        )

        result = runner.invoke(
            app,
            ["tablebase", "8/8/8/8/8/5K2/8/4k3 w - - 0 1", "--interactive"],
            input="fen\nquit\n",
        )
        assert result.exit_code == 0
        assert "5K2" in result.output


class TestPieceDescription:
    """Tests for _piece_description helper."""

    def test_kpk(self):
        from src.cli.app import _piece_description

        board = chess.Board("8/8/8/8/8/5K2/4P3/4k3 w - - 0 1")
        assert _piece_description(board) == "KPvK"

    def test_kqk(self):
        from src.cli.app import _piece_description

        board = chess.Board("8/8/8/8/8/5K2/4Q3/4k3 w - - 0 1")
        assert _piece_description(board) == "KQvK"

    def test_krnvkb(self):
        from src.cli.app import _piece_description

        board = chess.Board("8/8/8/8/8/2R2K2/4N3/2b1k3 w - - 0 1")
        assert _piece_description(board) == "KRNvKB"


class TestWdlStyle:
    """Tests for _wdl_style helper."""

    def test_win(self):
        from src.cli.app import _wdl_style

        assert _wdl_style(2) == "green bold"

    def test_cursed_win(self):
        from src.cli.app import _wdl_style

        assert _wdl_style(1) == "green"

    def test_draw(self):
        from src.cli.app import _wdl_style

        assert _wdl_style(0) == "yellow"

    def test_blessed_loss(self):
        from src.cli.app import _wdl_style

        assert _wdl_style(-1) == "red"

    def test_loss(self):
        from src.cli.app import _wdl_style

        assert _wdl_style(-2) == "red bold"
