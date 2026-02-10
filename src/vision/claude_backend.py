"""Claude (Anthropic) vision backend for board recognition."""

from __future__ import annotations

from pathlib import Path

from .base import VisionBackend, VisionResult


class ClaudeVisionBackend(VisionBackend):
    """Board recognition using the Anthropic Claude API with vision."""

    def __init__(self, *, api_key: str | None = None) -> None:
        """Initialize with an optional Anthropic API key."""
        self._api_key = api_key

    @property
    def name(self) -> str:  # noqa: D102
        return "claude"

    def is_available(self) -> bool:
        """Check that the anthropic SDK is installed and API key is set."""
        if not self._api_key:
            return False
        try:
            import anthropic  # noqa: F401

            return True
        except ImportError:
            return False

    def recognize(self, image_path: Path) -> VisionResult:
        """Recognize a chess position from an image using Claude vision."""
        raise NotImplementedError
