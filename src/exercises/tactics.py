"""Tactical exercise implementation.

Tactics are positions where there's a forcing sequence that wins material
or delivers checkmate. The user must find the correct move(s).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import chess

from .base import Exercise, ExerciseResult, ExerciseType


@dataclass
class TacticExercise(Exercise):
    """A tactical puzzle exercise.

    The user must find the winning move or sequence of moves.
    """

    exercise_type: ExerciseType = field(default=ExerciseType.TACTIC, init=False)
    solution: list[str] = field(default_factory=list)  # UCI move strings
    themes: list[str] = field(default_factory=list)  # fork, pin, skewer, etc.
    game_id: str | None = None  # Source game if from a real game
    acceptable_first_moves: list[str] = field(default_factory=list)  # UCI near-optimal first moves
    best_move_eval: int | None = None  # Centipawn score of best move
    evaluate_depth: int | None = None  # User moves to evaluate (None = all)

    def get_challenge(self) -> str:
        """Return the challenge text for this tactic."""
        return f"{self.side_to_move} to play. Find the best move."

    def get_solution(self) -> list[chess.Move]:
        """Convert UCI solution strings to chess.Move objects."""
        board = self.position
        moves = []
        for uci in self.solution:
            move = chess.Move.from_uci(uci)
            moves.append(move)
            board.push(move)
        return moves

    def evaluate(self, moves: list[chess.Move], time_taken_ms: int) -> ExerciseResult:
        """Evaluate user's moves against the tactical solution."""
        solution_moves = self.get_solution()

        if not moves:
            return ExerciseResult(
                correct=False,
                partial_credit=0.0,
                time_taken_ms=time_taken_ms,
                moves_played=moves,
                expected_moves=solution_moves,
                feedback="No moves played.",
            )

        # For tactics, we typically only check the first move (user's move)
        # The solution alternates: user move, opponent response, user move, ...
        user_solution_moves = solution_moves[::2]  # Every other move starting at 0

        # Apply evaluate_depth: only check this many user moves
        if self.evaluate_depth is not None:
            user_solution_moves = user_solution_moves[: self.evaluate_depth]

        user_played = moves[: len(user_solution_moves)]

        # Check how many moves match (with acceptable first moves for move 0)
        correct_count = 0
        for i, (played, expected) in enumerate(zip(user_played, user_solution_moves)):
            if played == expected:
                correct_count += 1
            elif i == 0 and self.acceptable_first_moves:
                # First move: also accept near-optimal alternatives
                if played.uci() in self.acceptable_first_moves:
                    correct_count += 1
                else:
                    break
            else:
                break

        partial_credit = correct_count / len(user_solution_moves) if user_solution_moves else 0.0
        correct = correct_count == len(user_solution_moves)

        if correct:
            feedback = "Correct!"
            if self.themes:
                feedback += f" Themes: {', '.join(self.themes)}"
        elif correct_count > 0:
            feedback = (
                f"Partially correct. You found {correct_count} of {len(user_solution_moves)} moves."
            )
        else:
            feedback = f"Incorrect. The solution was {self._format_solution()}."

        return ExerciseResult(
            correct=correct,
            partial_credit=partial_credit,
            time_taken_ms=time_taken_ms,
            moves_played=moves,
            expected_moves=solution_moves,
            feedback=feedback,
        )

    def _format_solution(self) -> str:
        """Format solution moves in algebraic notation."""
        board = self.position.copy()
        san_moves = []
        for uci in self.solution:
            move = chess.Move.from_uci(uci)
            san_moves.append(board.san(move))
            board.push(move)
        return " ".join(san_moves)

    def get_explanation(self) -> str:
        """Return solution and themes as explanation text."""
        explanation = f"Solution: {self._format_solution()}"
        if self.themes:
            explanation += f"\n\nThemes: {', '.join(self.themes)}"
        return explanation

    def _type_specific_dict(self) -> dict[str, Any]:
        return {
            "solution": self.solution,
            "themes": self.themes,
            "game_id": self.game_id,
            "acceptable_first_moves": self.acceptable_first_moves,
            "best_move_eval": self.best_move_eval,
            "evaluate_depth": self.evaluate_depth,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TacticExercise":
        """Deserialize a TacticExercise from a dictionary."""
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
            solution=data.get("solution", []),
            themes=data.get("themes", []),
            game_id=data.get("game_id"),
            acceptable_first_moves=data.get("acceptable_first_moves", []),
            best_move_eval=data.get("best_move_eval"),
            evaluate_depth=data.get("evaluate_depth"),
        )
