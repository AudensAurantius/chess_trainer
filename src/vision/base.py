"""Vision backend abstraction for board recognition from images."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class VisionError(Exception):
    """Raised when vision recognition fails or is unavailable."""


@dataclass(frozen=True)
class VisionResult:
    """Result of board recognition from an image.

    Attributes:
        fen: FEN string representing the recognized board position.
        confidence: Confidence score between 0.0 and 1.0 (if available).
        backend: Name of the backend that produced the result.
    """

    fen: str
    confidence: float
    backend: str


class VisionBackend(ABC):
    """Abstract base class for vision-based board recognition backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this backend (e.g. 'claude', 'openai', 'local')."""

    @abstractmethod
    def recognize(self, image_path: Path) -> VisionResult:
        """Recognize a chess board position from an image file.

        Args:
            image_path: Path to the image file (PNG, JPG, etc.).

        Returns:
            VisionResult with the detected FEN and confidence.

        Raises:
            VisionError: If recognition fails.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this backend is ready (deps installed, API key set, etc.)."""


def get_backend(config) -> VisionBackend:
    """Factory: instantiate the configured vision backend.

    Args:
        config: AppConfig instance.

    Returns:
        A ready VisionBackend.

    Raises:
        VisionError: If the backend is unavailable.
    """
    backend_name = config.experimental.vision_backend

    if backend_name == "claude":
        from .claude_backend import ClaudeVisionBackend

        backend = ClaudeVisionBackend(api_key=config.experimental.claude_api_key)
    elif backend_name == "openai":
        from .openai_backend import OpenAIVisionBackend

        backend = OpenAIVisionBackend(api_key=config.experimental.openai_api_key)
    elif backend_name == "local":
        from .local_backend import LocalVisionBackend

        backend = LocalVisionBackend(model_path=config.experimental.local_model_path)
    else:
        raise VisionError(
            f"Unknown vision backend: {backend_name!r}. "
            "Use 'claude', 'openai', or 'local'."
        )

    if not backend.is_available():
        raise VisionError(
            f"Vision backend {backend_name!r} is not available. "
            f"{_install_hint(backend_name)}"
        )

    return backend


def _install_hint(backend_name: str) -> str:
    """Return install instructions for a vision backend."""
    hints = {
        "claude": (
            "Install with: pip install chess-trainer[vision-claude]\n"
            "Then set experimental.claude_api_key or ANTHROPIC_API_KEY."
        ),
        "openai": (
            "Install with: pip install chess-trainer[vision-openai]\n"
            "Then set experimental.openai_api_key or OPENAI_API_KEY."
        ),
        "local": (
            "Install with: pip install chess-trainer[vision-local]\n"
            "Then set experimental.local_model_path to the ONNX model file."
        ),
    }
    return hints.get(backend_name, "")
