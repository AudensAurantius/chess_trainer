"""Move quality classification based on centipawn loss."""

from dataclasses import dataclass
from enum import IntEnum

import chess
import chess.engine


class MoveClassification(IntEnum):
    """Move quality classification based on centipawn loss.

    Thresholds follow standard chess analysis conventions:
    - BEST: 0cp loss (the engine's top choice)
    - EXCELLENT: ≤10cp loss
    - GOOD: ≤25cp loss
    - INACCURACY: ≤50cp loss
    - MISTAKE: ≤100cp loss
    - BLUNDER: >100cp loss
    """

    BEST = 0
    EXCELLENT = 1
    GOOD = 2
    INACCURACY = 3
    MISTAKE = 4
    BLUNDER = 5


@dataclass(frozen=True)
class MoveEvaluation:
    """Evaluation of a single move's quality.

    Attributes:
        move: The move that was played.
        classification: Quality classification based on cp loss.
        cp_loss: Centipawn loss relative to the best move.
        best_move: The engine's best move for comparison.
        score_before: Position score before the move (from side to move's POV).
        score_after: Position score after the move (from side to move's POV).
    """

    move: chess.Move
    classification: MoveClassification
    cp_loss: int
    best_move: chess.Move
    score_before: int
    score_after: int


def classify_move(cp_loss: int) -> MoveClassification:
    """Classify a move based on centipawn loss.

    Args:
        cp_loss: Centipawn loss relative to the best move. Must be ≥ 0.

    Returns:
        MoveClassification based on threshold boundaries.
    """
    if cp_loss <= 0:
        return MoveClassification.BEST
    elif cp_loss <= 10:
        return MoveClassification.EXCELLENT
    elif cp_loss <= 25:
        return MoveClassification.GOOD
    elif cp_loss <= 50:
        return MoveClassification.INACCURACY
    elif cp_loss <= 100:
        return MoveClassification.MISTAKE
    else:
        return MoveClassification.BLUNDER
