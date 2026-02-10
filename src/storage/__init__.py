"""Storage layer for chess trainer.

Uses DuckDB for efficient embedded storage of exercises and review state.
"""

from .bundle_store import BundleStore
from .card_store import CardStore
from .exercise_store import ExerciseStore
from .opening_store import OpeningStore
from .repository import Repository
from .tag_store import TagStore

__all__ = [
    "Repository",
    "ExerciseStore",
    "CardStore",
    "OpeningStore",
    "TagStore",
    "BundleStore",
]
