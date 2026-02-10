"""Local ONNX-based vision backend for board recognition (stub)."""

from __future__ import annotations

from pathlib import Path

from .base import VisionBackend, VisionError, VisionResult


class LocalVisionBackend(VisionBackend):
    """Board recognition using a local ONNX model (stub implementation)."""

    def __init__(self, *, model_path: str | None = None) -> None:
        """Initialize with an optional local model path."""
        self._model_path = model_path

    @property
    def name(self) -> str:  # noqa: D102
        return "local"

    def is_available(self) -> bool:
        """Local backend is not yet implemented."""
        return False

    def recognize(self, image_path: Path) -> VisionResult:
        """Recognize a chess position from an image using a local model."""
        raise VisionError(
            "Local vision model not yet implemented. "
            "Use 'claude' or 'openai' backend, or provide a model "
            "at experimental.local_model_path."
        )
