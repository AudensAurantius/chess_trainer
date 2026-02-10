"""Chess training exercise domain model.

This module defines the core abstractions for all exercise types:
- Exercise: Base class for all training exercises
- ExerciseResult: Result of attempting an exercise
- ExerciseType: Enumeration of exercise categories
"""

from .base import Exercise, ExerciseResult, ExerciseType
from .bundle import (
    BundleConfig,
    BundleProgress,
    CycleResult,
    ExerciseBundle,
    WoodpeckerCycle,
)
from .endgames import EndgameExercise
from .openings import OpeningExercise
from .positional import PositionalExercise
from .tactics import TacticExercise

__all__ = [
    "Exercise",
    "ExerciseResult",
    "ExerciseType",
    "TacticExercise",
    "OpeningExercise",
    "EndgameExercise",
    "PositionalExercise",
    "ExerciseBundle",
    "BundleConfig",
    "WoodpeckerCycle",
    "BundleProgress",
    "CycleResult",
]
