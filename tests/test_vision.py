"""Tests for the vision module: backend abstraction, factory, and implementations."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig
from src.vision.base import VisionError, VisionResult, _install_hint, get_backend
from src.vision.claude_backend import ClaudeVisionBackend
from src.vision.local_backend import LocalVisionBackend
from src.vision.openai_backend import OpenAIVisionBackend


class TestVisionResult:
    """Tests for VisionResult dataclass."""

    def test_creation(self):
        result = VisionResult(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            confidence=0.95,
            backend="claude",
        )
        assert result.fen == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        assert result.confidence == 0.95
        assert result.backend == "claude"

    def test_frozen(self):
        result = VisionResult(fen="8/8/8/8/8/8/8/8 w - - 0 1", confidence=0.5, backend="test")
        with pytest.raises(AttributeError):
            result.fen = "changed"


class TestVisionError:
    """Tests for VisionError exception."""

    def test_is_exception(self):
        assert issubclass(VisionError, Exception)

    def test_message(self):
        err = VisionError("test message")
        assert str(err) == "test message"


class TestGetBackend:
    """Tests for the get_backend factory function."""

    def test_unknown_backend_raises(self):
        cfg = AppConfig()
        cfg.experimental.vision_backend = "gemini"
        with pytest.raises(VisionError, match="Unknown vision backend"):
            get_backend(cfg)

    def test_claude_backend_unavailable(self):
        cfg = AppConfig()
        cfg.experimental.vision_backend = "claude"
        cfg.experimental.claude_api_key = None
        with pytest.raises(VisionError, match="not available"):
            get_backend(cfg)

    def test_openai_backend_unavailable(self):
        cfg = AppConfig()
        cfg.experimental.vision_backend = "openai"
        cfg.experimental.openai_api_key = None
        with pytest.raises(VisionError, match="not available"):
            get_backend(cfg)

    def test_local_backend_unavailable(self):
        cfg = AppConfig()
        cfg.experimental.vision_backend = "local"
        with pytest.raises(VisionError, match="not available"):
            get_backend(cfg)

    def test_claude_backend_with_key(self):
        cfg = AppConfig()
        cfg.experimental.vision_backend = "claude"
        cfg.experimental.claude_api_key = "sk-ant-test"
        # Mock the anthropic SDK availability
        with patch("src.vision.claude_backend.ClaudeVisionBackend.is_available", return_value=True):
            backend = get_backend(cfg)
            assert backend.name == "claude"

    def test_openai_backend_with_key(self):
        cfg = AppConfig()
        cfg.experimental.vision_backend = "openai"
        cfg.experimental.openai_api_key = "sk-test"
        with patch("src.vision.openai_backend.OpenAIVisionBackend.is_available", return_value=True):
            backend = get_backend(cfg)
            assert backend.name == "openai"


class TestInstallHint:
    """Tests for _install_hint helper."""

    def test_claude_hint(self):
        hint = _install_hint("claude")
        assert "vision-claude" in hint
        assert "ANTHROPIC_API_KEY" in hint

    def test_openai_hint(self):
        hint = _install_hint("openai")
        assert "vision-openai" in hint
        assert "OPENAI_API_KEY" in hint

    def test_local_hint(self):
        hint = _install_hint("local")
        assert "vision-local" in hint

    def test_unknown_hint(self):
        assert _install_hint("unknown") == ""


# Valid starting position FEN for mocking
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class TestClaudeBackend:
    """Tests for ClaudeVisionBackend."""

    def test_name(self):
        b = ClaudeVisionBackend(api_key="sk-ant-test")
        assert b.name == "claude"

    def test_unavailable_no_key(self):
        b = ClaudeVisionBackend(api_key=None)
        assert b.is_available() is False

    def test_unavailable_no_sdk(self):
        b = ClaudeVisionBackend(api_key="sk-ant-test")
        with patch.dict("sys.modules", {"anthropic": None}):
            assert b.is_available() is False

    def test_available_with_key_and_sdk(self):
        b = ClaudeVisionBackend(api_key="sk-ant-test")
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            assert b.is_available() is True

    def test_recognize_file_not_found(self, tmp_path):
        b = ClaudeVisionBackend(api_key="sk-ant-test")
        with patch.dict("sys.modules", {"anthropic": MagicMock()}):
            with pytest.raises(VisionError, match="not found"):
                b.recognize(tmp_path / "nonexistent.png")

    def test_recognize_success(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")  # Minimal PNG header

        # Mock the anthropic module
        mock_anthropic = MagicMock()
        mock_response = SimpleNamespace(content=[SimpleNamespace(text=STARTING_FEN)])
        mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

        b = ClaudeVisionBackend(api_key="sk-ant-test")
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = b.recognize(img)

        assert result.fen == STARTING_FEN
        assert result.backend == "claude"
        assert result.confidence == 0.85

    def test_recognize_invalid_fen(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_anthropic = MagicMock()
        mock_response = SimpleNamespace(content=[SimpleNamespace(text="not a valid fen")])
        mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

        b = ClaudeVisionBackend(api_key="sk-ant-test")
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            with pytest.raises(VisionError, match="invalid FEN"):
                b.recognize(img)

    def test_recognize_api_error(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_anthropic = MagicMock()
        mock_anthropic.Anthropic.return_value.messages.create.side_effect = RuntimeError("timeout")

        b = ClaudeVisionBackend(api_key="sk-ant-test")
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            with pytest.raises(VisionError, match="Claude API error"):
                b.recognize(img)

    def test_recognize_no_sdk(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        b = ClaudeVisionBackend(api_key="sk-ant-test")
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(VisionError, match="anthropic SDK not installed"):
                b.recognize(img)


class TestOpenAIBackend:
    """Tests for OpenAIVisionBackend."""

    def test_name(self):
        b = OpenAIVisionBackend(api_key="sk-test")
        assert b.name == "openai"

    def test_unavailable_no_key(self):
        b = OpenAIVisionBackend(api_key=None)
        assert b.is_available() is False

    def test_unavailable_no_sdk(self):
        b = OpenAIVisionBackend(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": None}):
            assert b.is_available() is False

    def test_available_with_key_and_sdk(self):
        b = OpenAIVisionBackend(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            assert b.is_available() is True

    def test_recognize_file_not_found(self, tmp_path):
        b = OpenAIVisionBackend(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": MagicMock()}):
            with pytest.raises(VisionError, match="not found"):
                b.recognize(tmp_path / "nonexistent.png")

    def test_recognize_success(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_openai = MagicMock()
        mock_choice = SimpleNamespace(message=SimpleNamespace(content=STARTING_FEN))
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = mock_response

        b = OpenAIVisionBackend(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = b.recognize(img)

        assert result.fen == STARTING_FEN
        assert result.backend == "openai"
        assert result.confidence == 0.80

    def test_recognize_invalid_fen(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_openai = MagicMock()
        mock_choice = SimpleNamespace(message=SimpleNamespace(content="garbage"))
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_openai.OpenAI.return_value.chat.completions.create.return_value = mock_response

        b = OpenAIVisionBackend(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": mock_openai}):
            with pytest.raises(VisionError, match="invalid FEN"):
                b.recognize(img)

    def test_recognize_api_error(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value.chat.completions.create.side_effect = RuntimeError("500")

        b = OpenAIVisionBackend(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": mock_openai}):
            with pytest.raises(VisionError, match="OpenAI API error"):
                b.recognize(img)

    def test_recognize_no_sdk(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        b = OpenAIVisionBackend(api_key="sk-test")
        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(VisionError, match="openai SDK not installed"):
                b.recognize(img)


class TestLocalBackend:
    """Tests for LocalVisionBackend stub."""

    def test_name(self):
        b = LocalVisionBackend()
        assert b.name == "local"

    def test_always_unavailable(self):
        b = LocalVisionBackend()
        assert b.is_available() is False

    def test_with_model_path_still_unavailable(self):
        b = LocalVisionBackend(model_path="/some/path")
        assert b.is_available() is False

    def test_recognize_raises(self, tmp_path):
        img = tmp_path / "board.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")
        b = LocalVisionBackend()
        with pytest.raises(VisionError, match="not yet implemented"):
            b.recognize(img)
