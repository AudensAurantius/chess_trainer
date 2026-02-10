"""Training session management.

Coordinates exercises, scheduling, and user interaction for
spaced repetition training sessions.
"""

from .session import SessionConfig, SessionStats, TrainingSession
from .woodpecker import WoodpeckerSession, WoodpeckerStats

__all__ = [
    "TrainingSession",
    "SessionConfig",
    "SessionStats",
    "WoodpeckerSession",
    "WoodpeckerStats",
]
