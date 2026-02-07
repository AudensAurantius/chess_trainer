"""Web interface for chess trainer.

Provides a Lichess-inspired browser UI using FastAPI, Jinja2, and HTMX
with chessboard.js for interactive board display.
"""

from .app import create_app

__all__ = ["create_app"]
