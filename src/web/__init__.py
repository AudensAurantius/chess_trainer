"""Web interface for chess trainer.

Provides a Lichess-inspired browser UI using FastAPI, Jinja2, and HTMX
with chessboard.js for interactive board display.
"""

from .app import create_app
from .manager_pool import ManagerPool

__all__ = ["ManagerPool", "create_app"]
