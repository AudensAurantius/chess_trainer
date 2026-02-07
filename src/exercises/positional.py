"""Positional exercise implementation.

Positional exercises test understanding of strategic concepts: weak squares,
piece activity, pawn structure, prophylaxis, etc. Unlike tactics, the focus
is on understanding the "why" rather than calculating forcing lines.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import chess

from .base import Exercise, ExerciseResult, ExerciseType


@dataclass
class PositionalExercise(Exercise):
    """A positional/strategic exercise.

    The user must identify the key positional idea and execute it.
    Multiple moves may be acceptable if they achieve the same goal.
    """

    exercise_type: ExerciseType = field(default=ExerciseType.POSITIONAL, init=False)
    concept: str = ""  # "weak square", "minority attack", "piece activity"
    question: str = ""  # Specific question about the position
    correct_moves: list[str] = field(default_factory=list)  # UCI moves
    explanation_text: str = ""  # Why these moves are correct
    key_features: list[str] = field(default_factory=list)  # What to notice
    wrong_ideas: list[str] = field(default_factory=list)  # Common mistakes

    def get_challenge(self) -> str:
        """Return the challenge text for this positional exercise."""
        if self.question:
            return self.question
        elif self.concept:
            return f"{self.side_to_move} to play. Demonstrate the concept: {self.concept}."
        else:
            return f"{self.side_to_move} to play. Find the best plan."

    def get_solution(self) -> list[chess.Move]:
        """Return the correct positional moves."""
        return [chess.Move.from_uci(uci) for uci in self.correct_moves]

    def evaluate(self, moves: list[chess.Move], time_taken_ms: int) -> ExerciseResult:
        """Evaluate user's moves against correct positional concepts."""
        correct_move_objs = self.get_solution()

        if not moves:
            return ExerciseResult(
                correct=False,
                partial_credit=0.0,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=correct_move_objs,
                feedback="No move played.",
            )

        played_move = moves[0]
        board = self.position

        # Check if the move is in the correct list
        if played_move in correct_move_objs:
            played_san = board.san(played_move)
            return ExerciseResult(
                correct=True,
                partial_credit=1.0,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=correct_move_objs,
                feedback=f"Correct! {played_san} demonstrates the concept.",
            )

        # For positional exercises, we could add partial credit for moves
        # that achieve similar goals (would require engine evaluation)
        # For now, just mark as incorrect

        played_san = board.san(played_move)
        correct_san = [board.san(m) for m in correct_move_objs]

        return ExerciseResult(
            correct=False,
            partial_credit=0.0,
            time_taken_ms=time_taken_ms,
            moves_played=moves,
            expected_moves=correct_move_objs,
            feedback=f"Incorrect. {played_san} doesn't demonstrate the concept. "
            f"Try: {', '.join(correct_san)}",
        )

    def get_explanation(self) -> str:
        """Return the positional concept and key ideas as explanation."""
        parts = []

        if self.concept:
            parts.append(f"Concept: {self.concept}")

        if self.key_features:
            parts.append(
                "Key features to notice:\n" + "\n".join(f"  - {f}" for f in self.key_features)
            )

        if self.correct_moves:
            board = self.position
            moves_san = [board.san(chess.Move.from_uci(uci)) for uci in self.correct_moves]
            parts.append(f"Correct moves: {', '.join(moves_san)}")

        if self.explanation_text:
            parts.append(f"Explanation: {self.explanation_text}")

        if self.wrong_ideas:
            parts.append(
                "Common mistakes:\n" + "\n".join(f"  - {idea}" for idea in self.wrong_ideas)
            )

        return "\n\n".join(parts) if parts else "No explanation available."

    def _type_specific_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "question": self.question,
            "correct_moves": self.correct_moves,
            "explanation_text": self.explanation_text,
            "key_features": self.key_features,
            "wrong_ideas": self.wrong_ideas,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PositionalExercise":
        """Deserialize a PositionalExercise from a dictionary."""
        return cls(
            id=data["id"],
            fen=data["fen"],
            tags=data.get("tags", []),
            source=data.get("source", ""),
            source_url=data.get("source_url"),
            difficulty=data.get("difficulty"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
            metadata=data.get("metadata", {}),
            concept=data.get("concept", ""),
            question=data.get("question", ""),
            correct_moves=data.get("correct_moves", []),
            explanation_text=data.get("explanation_text", ""),
            key_features=data.get("key_features", []),
            wrong_ideas=data.get("wrong_ideas", []),
        )
