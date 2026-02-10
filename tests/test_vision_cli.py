"""Tests for the scan CLI command."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.cli.app import app
from src.config import AppConfig
from src.vision.base import VisionError

runner = CliRunner()

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def _make_config(*, enabled=False, vision=False, backend="claude", api_key=None):
    """Create an AppConfig with experimental settings."""
    cfg = AppConfig()
    cfg.experimental.enabled = enabled
    cfg.experimental.vision = vision
    cfg.experimental.vision_backend = backend
    cfg.experimental.claude_api_key = api_key
    return cfg


class TestScanGateCheck:
    """Tests for the experimental feature gate."""

    def test_disabled_by_default(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        with patch("src.cli.app._get_config", return_value=_make_config()):
            result = runner.invoke(app, ["scan", str(img)])
        assert result.exit_code == 1
        assert "experimental feature" in result.output

    def test_master_only_not_enough(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=False)
        with patch("src.cli.app._get_config", return_value=cfg):
            result = runner.invoke(app, ["scan", str(img)])
        assert result.exit_code == 1
        assert "experimental feature" in result.output

    def test_vision_only_not_enough(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=False, vision=True)
        with patch("src.cli.app._get_config", return_value=cfg):
            result = runner.invoke(app, ["scan", str(img)])
        assert result.exit_code == 1

    def test_setup_instructions_shown(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        with patch("src.cli.app._get_config", return_value=_make_config()):
            result = runner.invoke(app, ["scan", str(img)])
        assert "config set experimental.enabled true" in result.output
        assert "config set experimental.vision true" in result.output


class TestScanImageValidation:
    """Tests for image file validation."""

    def test_nonexistent_image(self, tmp_path):
        cfg = _make_config(enabled=True, vision=True, api_key="sk-test")
        with patch("src.cli.app._get_config", return_value=cfg):
            result = runner.invoke(app, ["scan", str(tmp_path / "nope.png")])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestScanBackendErrors:
    """Tests for backend initialization and recognition errors."""

    def test_backend_unavailable(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=True, backend="claude")
        with patch("src.cli.app._get_config", return_value=cfg):
            result = runner.invoke(app, ["scan", str(img)])
        assert result.exit_code == 1
        assert "not available" in result.output

    def test_recognition_failure(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=True, api_key="sk-test")

        mock_backend = MagicMock()
        mock_backend.name = "claude"
        mock_backend.recognize.side_effect = VisionError("API timeout")

        with (
            patch("src.cli.app._get_config", return_value=cfg),
            patch("src.vision.base.get_backend", return_value=mock_backend),
            patch("src.vision.get_backend", return_value=mock_backend),
        ):
            result = runner.invoke(app, ["scan", str(img)])
        assert result.exit_code == 1
        assert "Recognition failed" in result.output


class TestScanSuccess:
    """Tests for successful scan flow."""

    def test_scan_displays_board_and_fen(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=True, api_key="sk-test")

        mock_result = SimpleNamespace(fen=STARTING_FEN, confidence=0.95, backend="claude")
        mock_backend = MagicMock()
        mock_backend.name = "claude"
        mock_backend.recognize.return_value = mock_result

        with (
            patch("src.cli.app._get_config", return_value=cfg),
            patch("src.vision.get_backend", return_value=mock_backend),
        ):
            result = runner.invoke(app, ["scan", str(img)], input="y\n")

        assert result.exit_code == 0
        assert STARTING_FEN in result.output
        assert "95%" in result.output

    def test_scan_with_backend_override(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=True, backend="claude", api_key="sk-test")

        mock_result = SimpleNamespace(fen=STARTING_FEN, confidence=0.80, backend="openai")
        mock_backend = MagicMock()
        mock_backend.name = "openai"
        mock_backend.recognize.return_value = mock_result

        with (
            patch("src.cli.app._get_config", return_value=cfg),
            patch("src.vision.get_backend", return_value=mock_backend),
        ):
            result = runner.invoke(
                app, ["scan", str(img), "--backend", "openai"], input="y\n"
            )

        assert result.exit_code == 0
        assert "openai" in result.output

    def test_scan_user_corrects_fen(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=True, api_key="sk-test")

        wrong_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        mock_result = SimpleNamespace(fen=wrong_fen, confidence=0.70, backend="claude")
        mock_backend = MagicMock()
        mock_backend.name = "claude"
        mock_backend.recognize.return_value = mock_result

        with (
            patch("src.cli.app._get_config", return_value=cfg),
            patch("src.vision.get_backend", return_value=mock_backend),
        ):
            result = runner.invoke(
                app,
                ["scan", str(img)],
                input=f"n\n{STARTING_FEN}\n",
            )

        assert result.exit_code == 0
        assert STARTING_FEN in result.output

    def test_scan_with_analyze(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=True, api_key="sk-test")

        mock_result = SimpleNamespace(fen=STARTING_FEN, confidence=0.95, backend="claude")
        mock_backend = MagicMock()
        mock_backend.name = "claude"
        mock_backend.recognize.return_value = mock_result

        # Mock engine analysis
        mock_line = SimpleNamespace(
            multipv_rank=1,
            score_cp=30,
            score_mate=None,
            pv=[],
        )
        mock_analysis = SimpleNamespace(depth=20, lines=[mock_line])
        mock_engine_instance = MagicMock()
        mock_engine_instance.__enter__ = MagicMock(return_value=mock_engine_instance)
        mock_engine_instance.__exit__ = MagicMock(return_value=False)
        mock_engine_instance.analyze.return_value = mock_analysis

        with (
            patch("src.cli.app._get_config", return_value=cfg),
            patch("src.vision.get_backend", return_value=mock_backend),
            patch("src.analysis.EngineManager", return_value=mock_engine_instance),
            patch("src.analysis.engine.EngineManager", return_value=mock_engine_instance),
        ):
            result = runner.invoke(
                app,
                ["scan", str(img), "--analyze"],
                input="y\n",
            )

        assert STARTING_FEN in result.output

    def test_scan_invalid_fen_from_backend(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG")

        cfg = _make_config(enabled=True, vision=True, api_key="sk-test")

        mock_result = SimpleNamespace(fen="not-valid", confidence=0.5, backend="claude")
        mock_backend = MagicMock()
        mock_backend.name = "claude"
        mock_backend.recognize.return_value = mock_result

        with (
            patch("src.cli.app._get_config", return_value=cfg),
            patch("src.vision.get_backend", return_value=mock_backend),
        ):
            result = runner.invoke(app, ["scan", str(img)])

        assert result.exit_code == 1
        assert "Invalid FEN" in result.output
