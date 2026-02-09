"""Opening explorer and personal opening book.

Provides tools for exploring opening statistics via the Lichess Explorer API
and managing a personal repertoire of opening lines for spaced-repetition training.
"""

from .book import BookError, create_line, generate_exercises, parse_pgn_file, parse_pgn_to_uci
from .explorer import ExplorerError, OpeningExplorer
from .models import BookColor, ExplorerResult, ExplorerSource, MoveStats, OpeningLine

__all__ = [
    "BookColor",
    "BookError",
    "ExplorerError",
    "ExplorerResult",
    "ExplorerSource",
    "MoveStats",
    "OpeningExplorer",
    "OpeningLine",
    "create_line",
    "generate_exercises",
    "parse_pgn_file",
    "parse_pgn_to_uci",
]
