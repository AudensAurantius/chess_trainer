"""
Review card model for spaced repetition.

A ReviewCard links an Exercise to its scheduling state, tracking memory
strength and review history.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class CardState(Enum):
    """States a card can be in within the SR system."""

    NEW = auto()       # Never reviewed
    LEARNING = auto()  # In initial learning phase
    REVIEW = auto()    # Graduated to review queue
    RELEARNING = auto()  # Failed review, back in learning


@dataclass
class ReviewCard:
    """
    Tracks the spaced repetition state for a single exercise.

    The card contains all FSRS parameters needed to schedule the next review
    and predict memory retention.
    """

    exercise_id: str
    state: CardState = CardState.NEW

    # FSRS parameters (using FSRS-4.5 defaults)
    difficulty: float = 0.3  # D: difficulty, range [0,1], lower = easier
    stability: float = 0.0   # S: memory stability in days
    retrievability: float = 1.0  # R: probability of recall

    # Scheduling state
    due: datetime = field(default_factory=datetime.now)
    last_review: datetime | None = None
    reps: int = 0  # Total successful reviews
    lapses: int = 0  # Times forgotten after learning

    # Learning step tracking (for NEW/LEARNING/RELEARNING states)
    step_index: int = 0  # Current position in learning steps

    # History
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_due(self) -> bool:
        """Check if the card is due for review."""
        return datetime.now() >= self.due

    @property
    def days_overdue(self) -> float:
        """How many days past due (negative if not yet due)."""
        delta = datetime.now() - self.due
        return delta.total_seconds() / 86400

    def to_dict(self) -> dict[str, Any]:
        """Serialize card to dictionary for storage."""
        return {
            "exercise_id": self.exercise_id,
            "state": self.state.name,
            "difficulty": self.difficulty,
            "stability": self.stability,
            "retrievability": self.retrievability,
            "due": self.due.isoformat(),
            "last_review": self.last_review.isoformat() if self.last_review else None,
            "reps": self.reps,
            "lapses": self.lapses,
            "step_index": self.step_index,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewCard":
        """Deserialize card from dictionary."""
        return cls(
            exercise_id=data["exercise_id"],
            state=CardState[data["state"]],
            difficulty=data.get("difficulty", 0.3),
            stability=data.get("stability", 0.0),
            retrievability=data.get("retrievability", 1.0),
            due=datetime.fromisoformat(data["due"]),
            last_review=datetime.fromisoformat(data["last_review"])
            if data.get("last_review")
            else None,
            reps=data.get("reps", 0),
            lapses=data.get("lapses", 0),
            step_index=data.get("step_index", 0),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
        )
