"""
Chess training exercise domain model.

This module defines the core abstractions for all exercise types:
- Exercise: Base class for all training exercises
- ExerciseResult: Result of attempting an exercise
- ExerciseType: Enumeration of exercise categories
"""

from .base import Exercise, ExerciseResult, ExerciseType
from .tactics import TacticExercise
from .openings import OpeningExercise
from .endgames import EndgameExercise
from .positional import PositionalExercise

__all__ = [
    "Exercise",
    "ExerciseResult",
    "ExerciseType",
    "TacticExercise",
    "OpeningExercise",
    "EndgameExercise",
    "PositionalExercise",
]
