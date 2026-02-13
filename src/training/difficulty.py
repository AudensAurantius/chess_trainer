"""Automatic difficulty adaptation for training sessions.

Tracks accuracy over recent reviews and adjusts the target difficulty
range so users work at an appropriate challenge level. FSRS handles
*when* to review; this module handles *what* difficulty to serve.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from ..config import DifficultyConfig


@dataclass
class DifficultyRange:
    """A range of exercise difficulty ratings to serve."""

    min_difficulty: float
    max_difficulty: float


class DifficultyAdapter:
    """Computes an appropriate difficulty range from recent review performance.

    Queries the last N reviews (joined with exercises for their difficulty
    field), computes accuracy, and shifts the target up or down accordingly.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection, config: DifficultyConfig) -> None:
        """Initialize with a database connection and difficulty config."""
        self.conn = conn
        self.config = config

    def compute_range(self) -> DifficultyRange | None:
        """Compute the difficulty range based on recent review performance.

        Returns:
            A DifficultyRange if enough data exists, or None if there are
            too few reviews with difficulty ratings to adapt.
        """
        rows = self.conn.execute(
            """
            SELECT rh.correct, e.difficulty
            FROM review_history rh
            JOIN exercises e ON rh.exercise_id = e.id
            WHERE e.difficulty IS NOT NULL
            ORDER BY rh.reviewed_at DESC
            LIMIT ?
            """,
            [self.config.window],
        ).fetchall()

        if len(rows) < self.config.min_reviews:
            return None

        correct_count = sum(1 for correct, _ in rows if correct)
        accuracy = correct_count / len(rows)
        avg_difficulty = sum(d for _, d in rows) / len(rows)

        if accuracy >= self.config.promote_accuracy:
            target = avg_difficulty + self.config.step
        elif accuracy <= self.config.demote_accuracy:
            target = avg_difficulty - self.config.step
        else:
            target = avg_difficulty

        half_range = self.config.difficulty_range / 2
        return DifficultyRange(
            min_difficulty=target - half_range,
            max_difficulty=target + half_range,
        )
