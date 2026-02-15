"""Base classes for the exercise domain model."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any

import chess


class ExerciseType(Enum):
    """Categories of chess training exercises."""

    TACTIC = auto()  # Find the winning move(s)
    OPENING = auto()  # Play the theory move
    ENDGAME = auto()  # Execute the winning technique
    POSITIONAL = auto()  # Identify/execute the key idea


@dataclass
class ExerciseResult:
    """Result of attempting an exercise."""

    correct: bool
    partial_credit: float  # 0.0 to 1.0
    time_taken_ms: int
    moves_played: list[chess.Move]
    expected_moves: list[chess.Move]
    feedback: str

    @property
    def grade(self) -> int:
        """Convert result to SR grade (1-4 scale).

        1 = forgot/wrong
        2 = hard (correct but slow or with mistakes)
        3 = good (correct, normal time)
        4 = easy (correct, fast)
        """
        if not self.correct and self.partial_credit < 0.5:
            return 1
        elif not self.correct or self.partial_credit < 0.8:
            return 2
        elif self.time_taken_ms > 30000:  # > 30 seconds
            return 3
        else:
            return 4 if self.time_taken_ms < 10000 else 3


@dataclass
class Exercise(ABC):
    """Base class for all training exercises.

    An exercise represents a single training item: a position plus a challenge
    that tests the user's understanding or pattern recognition.
    """

    id: str
    exercise_type: ExerciseType
    fen: str  # Position as FEN string
    tags: list[str] = field(default_factory=list)
    source: str = ""
    source_url: str | None = None
    difficulty: float | None = None  # Elo-like rating
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def notes(self) -> str | None:
        """Get user-provided notes for this exercise."""
        return self.metadata.get("notes")

    @notes.setter
    def notes(self, value: str | None) -> None:
        """Set or clear user-provided notes."""
        if value is None:
            self.metadata.pop("notes", None)
        else:
            self.metadata["notes"] = value

    @property
    def position(self) -> chess.Board:
        """Get the chess.Board for this exercise's position."""
        return chess.Board(self.fen)

    @property
    def side_to_move(self) -> str:
        """Human-readable side to move."""
        return "White" if self.position.turn == chess.WHITE else "Black"

    @abstractmethod
    def get_challenge(self) -> str:
        """Get the challenge text shown to the user.

        Returns:
            A string describing what the user should do.
        """
        ...

    @abstractmethod
    def get_solution(self) -> list[chess.Move]:
        """Get the solution move(s) for this exercise.

        Returns:
            List of moves constituting the solution.
        """
        ...

    @abstractmethod
    def evaluate(self, moves: list[chess.Move], time_taken_ms: int) -> ExerciseResult:
        """Evaluate the user's response.

        Args:
            moves: The moves played by the user.
            time_taken_ms: Time taken to solve in milliseconds.

        Returns:
            An ExerciseResult with feedback.
        """
        ...

    @abstractmethod
    def get_explanation(self) -> str:
        """Get the explanation shown after the attempt.

        Returns:
            A string explaining the solution.
        """
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize exercise to dictionary for storage."""
        return {
            "id": self.id,
            "exercise_type": self.exercise_type.name,
            "fen": self.fen,
            "tags": self.tags,
            "source": self.source,
            "source_url": self.source_url,
            "difficulty": self.difficulty,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            **self._type_specific_dict(),
        }

    @abstractmethod
    def _type_specific_dict(self) -> dict[str, Any]:
        """Return type-specific fields for serialization."""
        ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> "Exercise":
        """Deserialize exercise from dictionary."""
        ...
