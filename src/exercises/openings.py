"""
Opening exercise implementation.

Opening exercises test knowledge of opening theory by presenting positions
from opening lines and asking the user to find the main line move.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import chess

from .base import Exercise, ExerciseResult, ExerciseType


@dataclass
class OpeningExercise(Exercise):
    """
    An opening theory exercise.

    The user must find the main line move in an opening position.
    Alternative acceptable moves can be specified for partial credit.
    """

    exercise_type: ExerciseType = field(default=ExerciseType.OPENING, init=False)
    line: list[str] = field(default_factory=list)  # Full opening line (UCI)
    current_move_index: int = 0  # Which move we're testing
    eco_code: str = ""  # E.g., "B90"
    opening_name: str = ""  # E.g., "Sicilian Najdorf"
    variation_name: str = ""  # E.g., "English Attack"
    alternative_moves: list[str] = field(default_factory=list)  # Also acceptable

    def get_challenge(self) -> str:
        name = self.opening_name
        if self.variation_name:
            name += f", {self.variation_name}"
        return f"{self.side_to_move} to play. What is the main line in the {name}?"

    def get_solution(self) -> list[chess.Move]:
        if self.current_move_index < len(self.line):
            return [chess.Move.from_uci(self.line[self.current_move_index])]
        return []

    def evaluate(self, moves: list[chess.Move], time_taken_ms: int) -> ExerciseResult:
        solution = self.get_solution()

        if not moves:
            return ExerciseResult(
                correct=False,
                partial_credit=0.0,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=solution,
                feedback="No move played.",
            )

        played_move = moves[0]
        expected_move = solution[0] if solution else None

        if expected_move and played_move == expected_move:
            return ExerciseResult(
                correct=True,
                partial_credit=1.0,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=solution,
                feedback="Correct! That's the main line.",
            )

        # Check alternatives
        alt_moves = [chess.Move.from_uci(uci) for uci in self.alternative_moves]
        if played_move in alt_moves:
            board = self.position
            played_san = board.san(played_move)
            expected_san = board.san(expected_move) if expected_move else "?"
            return ExerciseResult(
                correct=False,
                partial_credit=0.7,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=solution,
                feedback=f"{played_san} is playable, but the main line is {expected_san}.",
            )

        # Wrong move
        board = self.position
        played_san = board.san(played_move)
        expected_san = board.san(expected_move) if expected_move else "?"
        return ExerciseResult(
            correct=False,
            partial_credit=0.0,
            time_taken_ms=time_taken_ms,
            moves_played=moves,
            expected_moves=solution,
            feedback=f"Incorrect. {played_san} is not theory here. The main line is {expected_san}.",
        )

    def get_explanation(self) -> str:
        if not self.line:
            return "No line available."

        board = chess.Board()
        san_line = []
        for i, uci in enumerate(self.line):
            move = chess.Move.from_uci(uci)
            if i == self.current_move_index:
                san_line.append(f"**{board.san(move)}**")
            else:
                san_line.append(board.san(move))
            board.push(move)

        explanation = f"Opening: {self.opening_name}"
        if self.variation_name:
            explanation += f", {self.variation_name}"
        if self.eco_code:
            explanation += f" ({self.eco_code})"
        explanation += f"\n\nLine: {' '.join(san_line)}"

        if self.alternative_moves:
            board = self.position
            alts = [board.san(chess.Move.from_uci(uci)) for uci in self.alternative_moves]
            explanation += f"\n\nAlternatives: {', '.join(alts)}"

        return explanation

    def _type_specific_dict(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "current_move_index": self.current_move_index,
            "eco_code": self.eco_code,
            "opening_name": self.opening_name,
            "variation_name": self.variation_name,
            "alternative_moves": self.alternative_moves,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpeningExercise":
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
            line=data.get("line", []),
            current_move_index=data.get("current_move_index", 0),
            eco_code=data.get("eco_code", ""),
            opening_name=data.get("opening_name", ""),
            variation_name=data.get("variation_name", ""),
            alternative_moves=data.get("alternative_moves", []),
        )
