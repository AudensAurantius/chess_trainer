"""Opening explorer and personal opening book.

Provides tools for exploring opening statistics via the Lichess Explorer API
and managing a personal repertoire of opening lines for spaced-repetition training.
"""

from .book import BookError, create_line, generate_exercises, parse_pgn_file, parse_pgn_to_uci
from .explorer import ExplorerError, OpeningExplorer, filter_moves, get_repertoire_moves
from .models import (
    BookColor,
    ExplorerFilter,
    ExplorerResult,
    ExplorerSource,
    MoveStats,
    OpeningLine,
    RepertoireInfo,
)

__all__ = [
    "BookColor",
    "BookError",
    "ExplorerError",
    "ExplorerFilter",
    "ExplorerResult",
    "ExplorerSource",
    "MoveStats",
    "OpeningExplorer",
    "OpeningLine",
    "RepertoireInfo",
    "create_line",
    "filter_moves",
    "generate_exercises",
    "get_repertoire_moves",
    "parse_pgn_file",
    "parse_pgn_to_uci",
]
