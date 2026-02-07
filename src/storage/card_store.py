"""Review card storage operations."""

from datetime import datetime

import duckdb

from ..scheduling import CardState, ReviewCard
from ..scheduling.fsrs import Rating


class CardStore:
    """Store for review card CRUD and scheduling queries."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        """Initialize card store with database connection."""
        self.conn = conn

    def get(self, exercise_id: str) -> ReviewCard | None:
        """Get a review card by exercise ID."""
        result = self.conn.execute(
            """
            SELECT exercise_id, state, difficulty, stability, retrievability,
                   due, last_review, reps, lapses, step_index, created_at
            FROM review_cards WHERE exercise_id = ?
            """,
            [exercise_id],
        ).fetchone()

        if not result:
            return None

        return self._row_to_card(result)

    def get_or_create(self, exercise_id: str) -> ReviewCard:
        """Get existing card or create a new one for the exercise."""
        card = self.get(exercise_id)
        if card:
            return card

        card = ReviewCard(exercise_id=exercise_id)
        self.save(card)
        return card

    def save(self, card: ReviewCard) -> None:
        """Save (insert or update) a review card."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO review_cards (
                exercise_id, state, difficulty, stability, retrievability,
                due, last_review, reps, lapses, step_index, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                card.exercise_id,
                card.state.name,
                card.difficulty,
                card.stability,
                card.retrievability,
                card.due,
                card.last_review,
                card.reps,
                card.lapses,
                card.step_index,
                card.created_at,
            ],
        )

    def get_due(
        self,
        limit: int = 50,
        now: datetime | None = None,
        include_new: bool = True,
    ) -> list[ReviewCard]:
        """Get cards due for review.

        Args:
            limit: Maximum number of cards to return
            now: Current time (defaults to datetime.now())
            include_new: Whether to include NEW cards

        Returns:
            List of due cards, ordered by urgency
        """
        now = now or datetime.now()

        state_filter = ""
        if not include_new:
            state_filter = "AND state != 'NEW'"

        results = self.conn.execute(
            f"""
            SELECT exercise_id, state, difficulty, stability, retrievability,
                   due, last_review, reps, lapses, step_index, created_at
            FROM review_cards
            WHERE due <= ? {state_filter}
            ORDER BY
                CASE state
                    WHEN 'RELEARNING' THEN 1
                    WHEN 'LEARNING' THEN 2
                    WHEN 'REVIEW' THEN 3
                    WHEN 'NEW' THEN 4
                END,
                due ASC
            LIMIT ?
            """,
            [now, limit],
        ).fetchall()

        return [self._row_to_card(row) for row in results]

    def get_new(self, limit: int = 20) -> list[ReviewCard]:
        """Get cards that have never been reviewed."""
        results = self.conn.execute(
            """
            SELECT exercise_id, state, difficulty, stability, retrievability,
                   due, last_review, reps, lapses, step_index, created_at
            FROM review_cards
            WHERE state = 'NEW'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

        return [self._row_to_card(row) for row in results]

    def get_learning(self) -> list[ReviewCard]:
        """Get cards currently in learning/relearning state."""
        results = self.conn.execute(
            """
            SELECT exercise_id, state, difficulty, stability, retrievability,
                   due, last_review, reps, lapses, step_index, created_at
            FROM review_cards
            WHERE state IN ('LEARNING', 'RELEARNING')
            ORDER BY due ASC
            """
        ).fetchall()

        return [self._row_to_card(row) for row in results]

    def count_by_state(self) -> dict[str, int]:
        """Get counts of cards in each state."""
        results = self.conn.execute(
            """
            SELECT state, COUNT(*) as count
            FROM review_cards
            GROUP BY state
            """
        ).fetchall()

        return {row[0]: row[1] for row in results}

    def count_due(self, now: datetime | None = None) -> int:
        """Count cards due for review."""
        now = now or datetime.now()
        result = self.conn.execute(
            "SELECT COUNT(*) FROM review_cards WHERE due <= ?", [now]
        ).fetchone()
        return result[0] if result else 0

    def get_stats(self) -> dict:
        """Get overall statistics about the card collection."""
        state_counts = self.count_by_state()

        total = self.conn.execute("SELECT COUNT(*) FROM review_cards").fetchone()[0]
        due_count = self.count_due()

        avg_stability = self.conn.execute(
            "SELECT AVG(stability) FROM review_cards WHERE state = 'REVIEW'"
        ).fetchone()[0]

        total_reviews = self.conn.execute("SELECT SUM(reps) FROM review_cards").fetchone()[0]

        return {
            "total_cards": total,
            "due_count": due_count,
            "state_counts": state_counts,
            "average_stability_days": avg_stability or 0,
            "total_reviews": total_reviews or 0,
        }

    def record_review(
        self,
        card: ReviewCard,
        rating: Rating,
        time_taken_ms: int,
        correct: bool,
        stability_before: float,
        stability_after: float,
    ) -> None:
        """Record a review in the history table."""
        self.conn.execute(
            """
            INSERT INTO review_history (
                id, exercise_id, reviewed_at, rating, time_taken_ms,
                correct, stability_before, stability_after
            ) VALUES (nextval('review_history_seq'), ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                card.exercise_id,
                datetime.now(),
                rating.value,
                time_taken_ms,
                correct,
                stability_before,
                stability_after,
            ],
        )

    def delete(self, exercise_id: str) -> bool:
        """Delete a review card. Returns True if deleted."""
        result = self.conn.execute(
            "DELETE FROM review_cards WHERE exercise_id = ? RETURNING exercise_id",
            [exercise_id],
        ).fetchone()
        return result is not None

    def _row_to_card(self, row: tuple) -> ReviewCard:
        """Convert database row to ReviewCard object."""
        (
            exercise_id,
            state,
            difficulty,
            stability,
            retrievability,
            due,
            last_review,
            reps,
            lapses,
            step_index,
            created_at,
        ) = row

        return ReviewCard(
            exercise_id=exercise_id,
            state=CardState[state],
            difficulty=difficulty,
            stability=stability,
            retrievability=retrievability,
            due=due,
            last_review=last_review,
            reps=reps,
            lapses=lapses,
            step_index=step_index,
            created_at=created_at,
        )
