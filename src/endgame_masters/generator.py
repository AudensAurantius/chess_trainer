"""Generate EndgameExercise items from annotated master game phases."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import chess

from ..exercises.endgames import EndgameExercise
from .models import EndgamePhase

if TYPE_CHECKING:
    from ..tablebase import TablebaseManager


def classify_endgame_type(board: chess.Board) -> str:
    """Classify the endgame type based on piece configuration.

    Args:
        board: The position to classify.

    Returns:
        Human-readable endgame type string.
    """
    white_pieces = _piece_set(board, chess.WHITE)
    black_pieces = _piece_set(board, chess.BLACK)

    has_white_rook = chess.ROOK in white_pieces
    has_black_rook = chess.ROOK in black_pieces
    has_white_bishop = chess.BISHOP in white_pieces
    has_black_bishop = chess.BISHOP in black_pieces
    has_white_knight = chess.KNIGHT in white_pieces
    has_black_knight = chess.KNIGHT in black_pieces
    has_white_queen = chess.QUEEN in white_pieces
    has_black_queen = chess.QUEEN in black_pieces
    has_white_pawns = chess.PAWN in white_pieces
    has_black_pawns = chess.PAWN in black_pieces

    # Pure pawn endgames (no pieces except kings and pawns)
    only_pawns = not any(
        [
            has_white_rook,
            has_black_rook,
            has_white_bishop,
            has_black_bishop,
            has_white_knight,
            has_black_knight,
            has_white_queen,
            has_black_queen,
        ]
    )
    if only_pawns:
        if has_white_pawns or has_black_pawns:
            return "Pawn Endgame"
        return "King vs King"

    # Queen endgames
    if has_white_queen or has_black_queen:
        return "Queen Endgame"

    # Rook endgames
    if has_white_rook or has_black_rook:
        if not any([has_white_bishop, has_black_bishop, has_white_knight, has_black_knight]):
            return "Rook Endgame"
        if has_white_bishop or has_black_bishop:
            return "Rook and Bishop Endgame"
        if has_white_knight or has_black_knight:
            return "Rook and Knight Endgame"
        return "Rook Endgame"

    # Bishop endgames
    if has_white_bishop or has_black_bishop:
        if not (has_white_knight or has_black_knight):
            # Check for opposite-color bishops
            if has_white_bishop and has_black_bishop:
                white_sq = _bishop_square_color(board, chess.WHITE)
                black_sq = _bishop_square_color(board, chess.BLACK)
                if white_sq is not None and black_sq is not None and white_sq != black_sq:
                    return "Opposite-Color Bishops"
                return "Same-Color Bishops"
            return "Bishop Endgame"
        return "Bishop and Knight Endgame"

    # Knight endgames
    if has_white_knight or has_black_knight:
        return "Knight Endgame"

    return "Endgame"


def generate_endgame_exercises(
    phase: EndgamePhase,
    tablebase: TablebaseManager,
    max_exercises: int = 5,
) -> Iterator[EndgameExercise]:
    """Generate EndgameExercise items from critical moments in an annotated phase.

    Args:
        phase: Annotated endgame phase from a master game.
        tablebase: Tablebase manager for computing best moves.
        max_exercises: Maximum exercises to generate per phase.

    Yields:
        EndgameExercise objects ready for storage and training.
    """
    from ..tablebase import TablebaseError

    critical = phase.critical_moments
    if not critical:
        return

    count = 0
    for pos in critical:
        if count >= max_exercises:
            break

        board = chess.Board(pos.fen)

        # Get best moves from tablebase
        try:
            result = tablebase.probe(board)
        except TablebaseError:
            continue

        best = result.best_moves
        if not best:
            continue

        acceptable_uci = [m.uci for m in best]
        technique = classify_endgame_type(board)
        target = _wdl_to_target(pos.wdl)

        exercise = EndgameExercise(
            id=f"masters:{phase.game_info.game_id}:p{pos.ply}",
            fen=pos.fen,
            tags=["endgame", "master-game", technique.lower().replace(" ", "-")],
            source="master-games",
            source_url=f"https://explorer.lichess.ovh/masters?fen={pos.fen}",
            metadata={
                "game_id": phase.game_info.game_id,
                "white": phase.game_info.white,
                "black": phase.game_info.black,
                "white_rating": phase.game_info.white_rating,
                "black_rating": phase.game_info.black_rating,
                "year": phase.game_info.year,
                "ply": pos.ply,
            },
            winning_side=board.turn == chess.WHITE,
            technique_name=technique,
            acceptable_first_moves=acceptable_uci,
            tablebase_eval=result.dtz,
            target_outcome=target,
        )

        yield exercise
        count += 1


def _piece_set(board: chess.Board, color: chess.Color) -> set[int]:
    """Return set of piece types present for a color (excluding king)."""
    types: set[int] = set()
    for piece_type in [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]:
        if board.pieces(piece_type, color):
            types.add(piece_type)
    return types


def _bishop_square_color(board: chess.Board, color: chess.Color) -> bool | None:
    """Return the square color of a side's bishop (True=light, False=dark).

    Returns None if no bishop found.
    """
    bishops = board.pieces(chess.BISHOP, color)
    if not bishops:
        return None
    sq = list(bishops)[0]
    return chess.square_rank(sq) % 2 == chess.square_file(sq) % 2


def _wdl_to_target(wdl: int) -> str:
    """Convert WDL to a target outcome string for exercises."""
    if wdl >= 1:
        return "win"
    elif wdl == 0:
        return "draw"
    else:
        return "hold"
