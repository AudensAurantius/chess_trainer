"""OpenAI vision backend for board recognition."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import chess

from .base import VisionBackend, VisionError, VisionResult

_PROMPT = """\
You are analyzing a screenshot of a chess board. Your task:

1. Determine the board orientation (is white on the bottom or the top?).
2. Identify every piece on every square, using standard chess notation.
3. Infer castling rights: if a king and its rook are on their starting squares, \
assume castling is available for that side.
4. Default en passant to "-" (not inferrable from a static image).
5. Default the halfmove clock to 0 and fullmove number to 1.

Return ONLY a single valid FEN string, nothing else. No explanation, no markdown.

Example output:
rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"""


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
        """Recognize a chess position from an image using OpenAI vision.

        Args:
            image_path: Path to the image file.

        Returns:
            VisionResult with detected FEN.

        Raises:
            VisionError: If the API call fails or FEN is invalid.
        """
        try:
            import openai
        except ImportError:
            raise VisionError(
                "openai SDK not installed. "
                "Install with: pip install chess-trainer[vision-openai]"
            )

        if not image_path.is_file():
            raise VisionError(f"Image file not found: {image_path}")

        # Read and encode the image
        image_data = base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")
        media_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
        data_url = f"data:{media_type};base64,{image_data}"

        try:
            client = openai.OpenAI(api_key=self._api_key)
            response = client.chat.completions.create(
                model="gpt-4o",
                max_tokens=256,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                            {"type": "text", "text": _PROMPT},
                        ],
                    }
                ],
            )
        except Exception as e:
            raise VisionError(f"OpenAI API error: {e}")

        fen = response.choices[0].message.content.strip()

        # Validate FEN
        try:
            chess.Board(fen)
        except ValueError:
            raise VisionError(
                f"OpenAI returned invalid FEN: {fen!r}. "
                "The position could not be parsed."
            )

        return VisionResult(fen=fen, confidence=0.80, backend="openai")
