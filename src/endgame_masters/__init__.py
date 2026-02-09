"""Endgame master games: discover, annotate, and train on GM endgame play."""

from .catalog import ENDGAME_TYPES, EndgameCategory, get_category
from .detector import annotate_endgame, build_endgame_phase, find_endgame_start, is_endgame
from .fetcher import (
    FetcherError,
    explore_masters_with_games,
    fetch_master_pgn,
    find_endgame_games,
)
from .generator import classify_endgame_type, generate_endgame_exercises
from .models import AnnotatedPosition, EndgamePhase, MasterGameInfo

__all__ = [
    "ENDGAME_TYPES",
    "AnnotatedPosition",
    "EndgameCategory",
    "EndgamePhase",
    "FetcherError",
    "MasterGameInfo",
    "annotate_endgame",
    "build_endgame_phase",
    "classify_endgame_type",
    "explore_masters_with_games",
    "fetch_master_pgn",
    "find_endgame_games",
    "find_endgame_start",
    "generate_endgame_exercises",
    "get_category",
    "is_endgame",
]
