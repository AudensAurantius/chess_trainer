"""
Endgame exercise implementation.

Endgame exercises test knowledge of theoretical endgame positions and
techniques. Unlike tactics, the emphasis is on demonstrating understanding
of the winning (or drawing) method rather than finding a single move.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import chess

from .base import Exercise, ExerciseResult, ExerciseType


@dataclass
class EndgameExercise(Exercise):
    """
    A theoretical endgame exercise.

    The user must demonstrate the winning (or drawing) technique.
    Evaluation can use tablebases for objective assessment.
    """

    exercise_type: ExerciseType = field(default=ExerciseType.ENDGAME, init=False)
    winning_side: bool = True  # True = White wins, False = Black wins, None = draw
    technique_name: str = ""  # "Lucena Position", "Philidor Defense"
    key_ideas: list[str] = field(default_factory=list)
    key_squares: list[str] = field(default_factory=list)  # Important squares
    acceptable_first_moves: list[str] = field(default_factory=list)  # UCI moves
    tablebase_eval: int | None = None  # DTZ (distance to zeroing) if available
    target_outcome: str = "win"  # "win", "draw", "hold"

    def get_challenge(self) -> str:
        if self.technique_name:
            return f"{self.side_to_move} to play. Demonstrate the {self.technique_name}."
        elif self.target_outcome == "win":
            return f"{self.side_to_move} to play and win."
        elif self.target_outcome == "draw":
            return f"{self.side_to_move} to play and draw."
        else:
            return f"{self.side_to_move} to play. Find the best continuation."

    def get_solution(self) -> list[chess.Move]:
        return [chess.Move.from_uci(uci) for uci in self.acceptable_first_moves]

    def evaluate(self, moves: list[chess.Move], time_taken_ms: int) -> ExerciseResult:
        acceptable = self.get_solution()

        if not moves:
            return ExerciseResult(
                correct=False,
                partial_credit=0.0,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=acceptable,
                feedback="No move played.",
            )

        played_move = moves[0]
        board = self.position

        # Check if move is in acceptable list
        if played_move in acceptable:
            played_san = board.san(played_move)
            return ExerciseResult(
                correct=True,
                partial_credit=1.0,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=acceptable,
                feedback=f"Correct! {played_san} demonstrates the technique.",
            )

        # For endgames, we might want to check if the move maintains the evaluation
        # This would require tablebase integration
        # For now, we'll just check against the acceptable moves list

        played_san = board.san(played_move)
        acceptable_san = [board.san(m) for m in acceptable]

        return ExerciseResult(
            correct=False,
            partial_credit=0.0,
            time_taken_ms=time_taken_ms,
            moves_played=moves,
            expected_moves=acceptable,
            feedback=f"Incorrect. {played_san} doesn't demonstrate the technique. "
            f"Try: {', '.join(acceptable_san)}",
        )

    def get_explanation(self) -> str:
        parts = []

        if self.technique_name:
            parts.append(f"Technique: {self.technique_name}")

        if self.key_ideas:
            parts.append(f"Key ideas:\n" + "\n".join(f"  - {idea}" for idea in self.key_ideas))

        if self.key_squares:
            parts.append(f"Key squares: {', '.join(self.key_squares)}")

        if self.acceptable_first_moves:
            board = self.position
            moves_san = [board.san(chess.Move.from_uci(uci)) for uci in self.acceptable_first_moves]
            parts.append(f"Correct moves: {', '.join(moves_san)}")

        if self.tablebase_eval is not None:
            parts.append(f"Tablebase DTZ: {self.tablebase_eval}")

        return "\n\n".join(parts) if parts else "No explanation available."

    def _type_specific_dict(self) -> dict[str, Any]:
        return {
            "winning_side": self.winning_side,
            "technique_name": self.technique_name,
            "key_ideas": self.key_ideas,
            "key_squares": self.key_squares,
            "acceptable_first_moves": self.acceptable_first_moves,
            "tablebase_eval": self.tablebase_eval,
            "target_outcome": self.target_outcome,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EndgameExercise":
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
            winning_side=data.get("winning_side", True),
            technique_name=data.get("technique_name", ""),
            key_ideas=data.get("key_ideas", []),
            key_squares=data.get("key_squares", []),
            acceptable_first_moves=data.get("acceptable_first_moves", []),
            tablebase_eval=data.get("tablebase_eval"),
            target_outcome=data.get("target_outcome", "win"),
        )
