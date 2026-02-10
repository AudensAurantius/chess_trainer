"""OpenAI vision backend for board recognition."""

from __future__ import annotations

from pathlib import Path

from .base import VisionBackend, VisionResult


class OpenAIVisionBackend(VisionBackend):
    """Board recognition using the OpenAI API with vision."""

    def __init__(self, *, api_key: str | None = None) -> None:
        """Initialize with an optional OpenAI API key."""
        self._api_key = api_key

    @property
    def name(self) -> str:  # noqa: D102
        return "openai"

    def is_available(self) -> bool:
        """Check that the openai SDK is installed and API key is set."""
        if not self._api_key:
            return False
        try:
            import openai  # noqa: F401

            return True
        except ImportError:
            return False

    def recognize(self, image_path: Path) -> VisionResult:
        """Recognize a chess position from an image using OpenAI vision."""
        raise NotImplementedError
