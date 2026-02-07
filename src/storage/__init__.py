"""
Storage layer for chess trainer.

Uses DuckDB for efficient embedded storage of exercises and review state.
"""

from .repository import Repository
from .exercise_store import ExerciseStore
from .card_store import CardStore

__all__ = [
    "Repository",
    "ExerciseStore",
    "CardStore",
]
