"""Tests for the vision module: backend abstraction, factory, and implementations."""

from unittest.mock import patch

import pytest

from src.config import AppConfig
from src.vision.base import VisionError, VisionResult, _install_hint, get_backend


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
