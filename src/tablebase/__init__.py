"""Endgame tablebase probing with local Syzygy and Lichess API backends."""

from .manager import TablebaseError, TablebaseManager
from .models import TablebaseMove, TablebaseResult

__all__ = [
    "TablebaseError",
    "TablebaseManager",
    "TablebaseMove",
    "TablebaseResult",
]
