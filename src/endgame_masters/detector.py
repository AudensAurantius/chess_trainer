"""Endgame detection, tablebase annotation, and critical moment identification."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import chess
import chess.pgn

from .models import AnnotatedPosition, EndgamePhase, MasterGameInfo

if TYPE_CHECKING:
    from ..tablebase import TablebaseManager

logger = logging.getLogger(__name__)

# Material values for endgame detection (standard piece values)
_MATERIAL_VALUES = {
    chess.QUEEN: 9,
    chess.ROOK: 5,
    chess.BISHOP: 3,
    chess.KNIGHT: 3,
}

_WDL_CATEGORIES = {
    2: "win",
    1: "cursed-win",
    0: "draw",
    -1: "blessed-loss",
    -2: "loss",
}


def is_endgame(board: chess.Board) -> bool:
    """Determine if a position is an endgame.

    An endgame is detected when:
    - No queens remain on the board, OR
    - Total non-pawn material (for both sides) is <= 13 points even with queens.

    Args:
        board: The position to evaluate.

    Returns:
        True if the position qualifies as an endgame.
    """
    white_queens = len(board.pieces(chess.QUEEN, chess.WHITE))
    black_queens = len(board.pieces(chess.QUEEN, chess.BLACK))
    has_queens = (white_queens + black_queens) > 0

    if not has_queens:
        return True

    # Queens present — check total non-pawn material
    total_material = 0
    for piece_type, value in _MATERIAL_VALUES.items():
        white_count = len(board.pieces(piece_type, chess.WHITE))
        black_count = len(board.pieces(piece_type, chess.BLACK))
        total_material += (white_count + black_count) * value

    return total_material <= 13


def find_endgame_start(game: chess.pgn.Game) -> int | None:
    """Find the ply at which the endgame phase begins in a game.

    Walks through the game mainline and returns the ply of the first
    position that qualifies as an endgame.

    Args:
        game: A parsed chess game.

    Returns:
        The ply number (0-indexed half-moves) of the endgame start,
        or None if the game never reaches an endgame.
    """
    board = game.board()
    for ply, move in enumerate(game.mainline_moves()):
        board.push(move)
        if is_endgame(board):
            return ply + 1  # ply after the move that creates the endgame
    return None


def annotate_endgame(
    game: chess.pgn.Game,
    start_ply: int,
    tablebase: TablebaseManager,
) -> list[AnnotatedPosition]:
    """Annotate endgame positions with tablebase evaluations.

    Probes the tablebase at each position from ``start_ply`` onward where
    the piece count is within tablebase limits. Marks positions as critical
    when:
    1. The played move worsened the WDL outcome, OR
    2. Only <= 2 moves maintain the best WDL (narrow winning window).

    Args:
        game: The parsed chess game.
        start_ply: The ply at which to begin annotation.
        tablebase: Tablebase manager for probing.

    Returns:
        List of annotated positions with WDL/DTZ data.
    """
    from ..tablebase import TablebaseError

    board = game.board()
    moves = list(game.mainline_moves())
    positions: list[AnnotatedPosition] = []

    # Advance board to start_ply
    for i in range(min(start_ply, len(moves))):
        board.push(moves[i])

    # Annotate from start_ply onward
    for ply_idx in range(start_ply, len(moves)):
        if not tablebase.is_tablebase_position(board):
            board.push(moves[ply_idx])
            continue

        try:
            result = tablebase.probe(board)
        except TablebaseError:
            board.push(moves[ply_idx])
            continue

        wdl_before = result.wdl
        category = _WDL_CATEGORIES.get(wdl_before, "unknown")
        move_played = moves[ply_idx]
        move_san = board.san(move_played)
        pre_move_fen = board.fen()

        # Probe after the move to get wdl_after
        wdl_after = None
        is_critical = False

        board.push(move_played)

        if tablebase.is_tablebase_position(board):
            try:
                after_result = tablebase.probe(board)
                wdl_after = -after_result.wdl  # Negate for perspective

                # Critical: move worsened WDL
                if wdl_after < wdl_before:
                    is_critical = True
            except TablebaseError:
                pass

        # Critical: narrow winning window (<=2 moves maintain best WDL)
        if not is_critical and result.moves:
            best_wdl = result.moves[0].wdl if result.moves else wdl_before
            maintaining_moves = [m for m in result.moves if m.wdl == best_wdl]
            if len(maintaining_moves) <= 2:
                is_critical = True

        positions.append(
            AnnotatedPosition(
                fen=pre_move_fen,
                ply=ply_idx,
                move_played=move_played,
                move_san=move_san,
                wdl=wdl_before,
                dtz=result.dtz,
                category=category,
                is_critical=is_critical,
                wdl_after=wdl_after,
            )
        )

    return positions


def build_endgame_phase(
    game_info: MasterGameInfo,
    pgn_text: str,
    game: chess.pgn.Game,
    tablebase: TablebaseManager,
) -> EndgamePhase | None:
    """Build a fully annotated endgame phase from a master game.

    Orchestrates endgame detection and tablebase annotation.

    Args:
        game_info: Metadata about the game.
        pgn_text: Full PGN text.
        game: Parsed chess game.
        tablebase: Tablebase manager for probing.

    Returns:
        An EndgamePhase with annotated positions, or None if the game
        has no endgame or no TB-eligible positions.
    """
    start = find_endgame_start(game)
    if start is None:
        return None

    positions = annotate_endgame(game, start, tablebase)
    if not positions:
        return None

    return EndgamePhase(
        game_info=game_info,
        pgn_text=pgn_text,
        endgame_start_ply=start,
        positions=positions,
    )
