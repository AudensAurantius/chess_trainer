"""
Spaced repetition scheduling module.

This module implements the FSRS (Free Spaced Repetition Scheduler) algorithm
for optimal review scheduling based on memory research.
"""

from .card import ReviewCard, CardState
from .fsrs import FSRSScheduler, FSRSParameters, SchedulingResult

__all__ = [
    "ReviewCard",
    "CardState",
    "FSRSScheduler",
    "FSRSParameters",
    "SchedulingResult",
]
