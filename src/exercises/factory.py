"""Exercise creation factory with validation.

Centralizes validation and construction of custom exercises so that
CLI and web surfaces don't duplicate logic.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import chess

from .base import ExerciseType
from .endgames import EndgameExercise
from .openings import OpeningExercise
from .positional import PositionalExercise
from .tactics import TacticExercise

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")
_VALID_TYPES = {"tactic", "opening", "endgame", "positional"}
_TYPE_MAP: dict[str, ExerciseType] = {
    "tactic": ExerciseType.TACTIC,
    "opening": ExerciseType.OPENING,
    "endgame": ExerciseType.ENDGAME,
    "positional": ExerciseType.POSITIONAL,
}


class ExerciseCreationError(ValueError):
    """Raised when exercise creation inputs are invalid."""


def validate_fen(fen: str) -> chess.Board:
    """Parse and validate a FEN string.

    Returns the resulting Board on success.
    Raises ExerciseCreationError on invalid FEN.
    """
    try:
        board = chess.Board(fen)
    except ValueError as e:
        raise ExerciseCreationError(f"Invalid FEN: {e}") from e
    return board


def validate_moves(board: chess.Board, moves_uci: list[str]) -> list[str]:
    """Validate that each UCI move is legal in sequence from the given board.

    Returns the validated list of UCI strings.
    Raises ExerciseCreationError if any move is illegal.
    """
    if not moves_uci:
        raise ExerciseCreationError("At least one move is required")
    test_board = board.copy()
    validated: list[str] = []
    for i, uci in enumerate(moves_uci):
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise ExerciseCreationError(f"Invalid UCI notation at move {i + 1}: {uci}")
        if move not in test_board.legal_moves:
            raise ExerciseCreationError(
                f"Illegal move at position {i + 1}: {uci} "
                f"(legal: {', '.join(m.uci() for m in test_board.legal_moves)})"
            )
        test_board.push(move)
        validated.append(uci)
    return validated


def validate_single_moves(board: chess.Board, moves_uci: list[str]) -> list[str]:
    """Validate that each UCI move is independently legal from the given board.

    Unlike validate_moves, this does not push moves sequentially — each move
    is checked against the same starting position. Used for fields like
    acceptable_first_moves and correct_moves.
    """
    if not moves_uci:
        raise ExerciseCreationError("At least one move is required")
    validated: list[str] = []
    for uci in moves_uci:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            raise ExerciseCreationError(f"Invalid UCI notation: {uci}")
        if move not in board.legal_moves:
            raise ExerciseCreationError(f"Illegal move from this position: {uci}")
        validated.append(uci)
    return validated


def generate_exercise_id(slug: str | None = None) -> str:
    """Generate a custom exercise ID.

    If slug is provided, validates format and returns ``custom:{slug}``.
    Otherwise returns ``custom:{uuid4}``.
    """
    if slug is None:
        return f"custom:{uuid.uuid4()}"
    if not _SLUG_RE.match(slug):
        raise ExerciseCreationError(
            "Slug must be 2-64 chars, lowercase alphanumeric and hyphens, "
            "cannot start or end with a hyphen"
        )
    return f"custom:{slug}"


def create_exercise(
    exercise_type: str,
    fen: str,
    *,
    moves: list[str] | None = None,
    slug: str | None = None,
    tags: list[str] | None = None,
    difficulty: float | None = None,
    notes: str | None = None,
    # Tactic-specific
    themes: list[str] | None = None,
    # Endgame-specific
    technique: str | None = None,
    target_outcome: str | None = None,
    # Positional-specific
    concept: str | None = None,
    question: str | None = None,
    explanation: str | None = None,
    # Opening-specific
    opening_name: str | None = None,
    eco: str | None = None,
    move_index: int | None = None,
) -> TacticExercise | EndgameExercise | PositionalExercise | OpeningExercise:
    """Create a validated exercise from user inputs.

    Args:
        exercise_type: One of "tactic", "opening", "endgame", "positional".
        fen: Starting position as a FEN string.
        moves: Solution/line moves in UCI notation.
        slug: Optional human-readable ID slug.
        tags: Optional exercise tags.
        difficulty: Optional Elo-like difficulty rating.
        notes: Optional study notes.
        themes: Tactic themes (fork, pin, etc.).
        technique: Endgame technique name.
        target_outcome: Endgame target ("win", "draw", "hold").
        concept: Positional concept name.
        question: Positional question text.
        explanation: Positional explanation text.
        opening_name: Opening name.
        eco: ECO code.
        move_index: Opening move index to test.

    Returns:
        A fully constructed Exercise subclass instance.

    Raises:
        ExerciseCreationError: If any input is invalid.
    """
    exercise_type_lower = exercise_type.lower()
    if exercise_type_lower not in _VALID_TYPES:
        raise ExerciseCreationError(
            f"Invalid exercise type: {exercise_type}. "
            f"Must be one of: {', '.join(sorted(_VALID_TYPES))}"
        )

    board = validate_fen(fen)
    exercise_id = generate_exercise_id(slug)
    metadata: dict[str, Any] = {}
    if notes:
        metadata["notes"] = notes

    if exercise_type_lower == "tactic":
        return _create_tactic(board, fen, exercise_id, moves, tags, difficulty, metadata, themes)
    elif exercise_type_lower == "endgame":
        return _create_endgame(
            board, fen, exercise_id, moves, tags, difficulty, metadata, technique, target_outcome
        )
    elif exercise_type_lower == "positional":
        return _create_positional(
            board,
            fen,
            exercise_id,
            moves,
            tags,
            difficulty,
            metadata,
            concept,
            question,
            explanation,
        )
    else:  # opening
        return _create_opening(
            board,
            fen,
            exercise_id,
            moves,
            tags,
            difficulty,
            metadata,
            opening_name,
            eco,
            move_index,
        )


def _create_tactic(
    board: chess.Board,
    fen: str,
    exercise_id: str,
    moves: list[str] | None,
    tags: list[str] | None,
    difficulty: float | None,
    metadata: dict[str, Any],
    themes: list[str] | None,
) -> TacticExercise:
    if not moves:
        raise ExerciseCreationError("Tactic exercises require solution moves (--moves)")
    solution = validate_moves(board, moves)
    return TacticExercise(
        id=exercise_id,
        fen=fen,
        tags=tags or [],
        source="custom",
        difficulty=difficulty,
        metadata=metadata,
        solution=solution,
        themes=themes or [],
    )


def _create_endgame(
    board: chess.Board,
    fen: str,
    exercise_id: str,
    moves: list[str] | None,
    tags: list[str] | None,
    difficulty: float | None,
    metadata: dict[str, Any],
    technique: str | None,
    target_outcome: str | None,
) -> EndgameExercise:
    if not moves:
        raise ExerciseCreationError("Endgame exercises require acceptable first moves (--moves)")
    acceptable = validate_single_moves(board, moves)
    winning_side = board.turn == chess.WHITE
    return EndgameExercise(
        id=exercise_id,
        fen=fen,
        tags=tags or [],
        source="custom",
        difficulty=difficulty,
        metadata=metadata,
        acceptable_first_moves=acceptable,
        technique_name=technique or "",
        target_outcome=target_outcome or "win",
        winning_side=winning_side,
    )


def _create_positional(
    board: chess.Board,
    fen: str,
    exercise_id: str,
    moves: list[str] | None,
    tags: list[str] | None,
    difficulty: float | None,
    metadata: dict[str, Any],
    concept: str | None,
    question: str | None,
    explanation: str | None,
) -> PositionalExercise:
    if not moves:
        raise ExerciseCreationError("Positional exercises require correct moves (--moves)")
    correct = validate_single_moves(board, moves)
    return PositionalExercise(
        id=exercise_id,
        fen=fen,
        tags=tags or [],
        source="custom",
        difficulty=difficulty,
        metadata=metadata,
        correct_moves=correct,
        concept=concept or "",
        question=question or "",
        explanation_text=explanation or "",
    )


def _create_opening(
    board: chess.Board,
    fen: str,
    exercise_id: str,
    moves: list[str] | None,
    tags: list[str] | None,
    difficulty: float | None,
    metadata: dict[str, Any],
    opening_name: str | None,
    eco: str | None,
    move_index: int | None,
) -> OpeningExercise:
    if not moves:
        raise ExerciseCreationError("Opening exercises require line moves (--moves)")
    line = validate_moves(board, moves)
    idx = move_index if move_index is not None else 0
    if idx < 0 or idx >= len(line):
        raise ExerciseCreationError(f"Move index {idx} out of range for line of length {len(line)}")
    return OpeningExercise(
        id=exercise_id,
        fen=fen,
        tags=tags or [],
        source="custom",
        difficulty=difficulty,
        metadata=metadata,
        line=line,
        current_move_index=idx,
        opening_name=opening_name or "",
        eco_code=eco or "",
    )
