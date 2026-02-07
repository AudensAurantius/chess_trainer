"""
Content importers for populating the exercise database.

Each importer knows how to fetch exercises from a specific source
and convert them to the internal Exercise format.
"""

from .base import Importer, ImportResult
from .lichess_puzzles import LichessPuzzleImporter

__all__ = [
    "Importer",
    "ImportResult",
    "LichessPuzzleImporter",
]
