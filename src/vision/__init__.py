"""Vision-based board recognition from screenshots and images."""

from .base import VisionBackend, VisionError, VisionResult, get_backend

__all__ = [
    "VisionBackend",
    "VisionError",
    "VisionResult",
    "get_backend",
]
