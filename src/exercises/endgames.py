"""Endgame exercise implementation.

Endgame exercises test knowledge of theoretical endgame positions and
techniques. Unlike tactics, the emphasis is on demonstrating understanding
of the winning (or drawing) method rather than finding a single move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import chess

from .base import Exercise, ExerciseResult, ExerciseType

if TYPE_CHECKING:
    from ..tablebase import TablebaseManager


def _wdl_to_category(wdl: int) -> str:
    """Convert a WDL integer to a human-readable category string."""
    return {
        2: "win",
        1: "cursed-win",
        0: "draw",
        -1: "blessed-loss",
        -2: "loss",
    }.get(wdl, "unknown")


@dataclass
class EndgameExercise(Exercise):
    """A theoretical endgame exercise.

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
        """Return the challenge text for this endgame exercise."""
        if self.technique_name:
            return f"{self.side_to_move} to play. Demonstrate the {self.technique_name}."
        elif self.target_outcome == "win":
            return f"{self.side_to_move} to play and win."
        elif self.target_outcome == "draw":
            return f"{self.side_to_move} to play and draw."
        else:
            return f"{self.side_to_move} to play. Find the best continuation."

    def get_solution(self) -> list[chess.Move]:
        """Return acceptable first moves for this endgame."""
        return [chess.Move.from_uci(uci) for uci in self.acceptable_first_moves]

    def evaluate(
        self,
        moves: list[chess.Move],
        time_taken_ms: int,
        tablebase: TablebaseManager | None = None,
    ) -> ExerciseResult:
        """Evaluate user's moves against acceptable endgame continuations.

        If a TablebaseManager is provided and the played move is not in the
        static acceptable list, the tablebase is consulted to check whether
        the move maintains the required WDL outcome.

        Args:
            moves: The moves played by the user.
            time_taken_ms: Time taken to solve in milliseconds.
            tablebase: Optional tablebase manager for objective evaluation.
        """
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

        # Check if move is in acceptable list first
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

        # If tablebase is available, check if the move maintains the outcome
        if tablebase is not None:
            return self._evaluate_with_tablebase(
                board, played_move, acceptable, time_taken_ms, moves, tablebase
            )

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

    def _evaluate_with_tablebase(
        self,
        board: chess.Board,
        played_move: chess.Move,
        acceptable: list[chess.Move],
        time_taken_ms: int,
        moves: list[chess.Move],
        tablebase: TablebaseManager,
    ) -> ExerciseResult:
        """Evaluate using tablebase probing."""
        from ..tablebase import TablebaseError

        played_san = board.san(played_move)

        try:
            # Get the position WDL before the move
            before_result = tablebase.probe(board)
            before_wdl = before_result.wdl

            # Probe after the played move
            after_board = board.copy()
            after_board.push(played_move)
            after_result = tablebase.probe(after_board)
            # Negate because side to move changed
            after_wdl = -after_result.wdl

            # Check if the move maintains or improves the WDL outcome
            if after_wdl >= before_wdl:
                # Move maintains the outcome — correct
                # Partial credit based on DTZ optimality
                credit = self._compute_dtz_credit(played_move, before_result, after_wdl, before_wdl)
                return ExerciseResult(
                    correct=True,
                    partial_credit=credit,
                    time_taken_ms=time_taken_ms,
                    moves_played=moves,
                    expected_moves=acceptable,
                    feedback=f"Correct! {played_san} maintains the {_wdl_to_category(before_wdl)}.",
                )
            else:
                # Move worsens the outcome — incorrect
                return ExerciseResult(
                    correct=False,
                    partial_credit=0.0,
                    time_taken_ms=time_taken_ms,
                    moves_played=moves,
                    expected_moves=acceptable,
                    feedback=f"Incorrect. {played_san} changes the outcome from "
                    f"{_wdl_to_category(before_wdl)} to "
                    f"{_wdl_to_category(after_wdl)}.",
                )
        except TablebaseError:
            # Tablebase probe failed — fall back to static check
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

    def _compute_dtz_credit(
        self,
        played_move: chess.Move,
        before_result,
        after_wdl: int,
        before_wdl: int,
    ) -> float:
        """Compute partial credit based on DTZ optimality.

        Full credit (1.0) for the optimal DTZ move.
        Reduced credit (0.8) for suboptimal but outcome-preserving moves.
        """
        if not before_result.moves:
            return 1.0

        # Find the best DTZ among winning moves
        best_moves = before_result.best_moves
        played_uci = played_move.uci()

        for m in best_moves:
            if m.uci == played_uci:
                return 1.0  # This is one of the best moves

        # It maintains outcome but is not the optimal DTZ — still good
        if after_wdl > before_wdl:
            return 1.0  # Improved the outcome, full credit
        return 0.8

    def get_explanation(self) -> str:
        """Return the technique and key concepts as explanation."""
        parts = []

        if self.technique_name:
            parts.append(f"Technique: {self.technique_name}")

        if self.key_ideas:
            parts.append("Key ideas:\n" + "\n".join(f"  - {idea}" for idea in self.key_ideas))

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
    def from_dict(cls, data: dict[str, Any]) -> EndgameExercise:
        """Deserialize an EndgameExercise from a dictionary."""
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
