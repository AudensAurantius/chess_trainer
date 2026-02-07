"""
Main repository class managing DuckDB connection and stores.
"""

from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from .exercise_store import ExerciseStore
    from .card_store import CardStore


class Repository:
    """
    Central repository managing database connection and stores.

    Provides transactional access to exercises and review cards.
    """

    def __init__(self, db_path: str | Path | None = None):
        """
        Initialize repository with optional database path.

        Args:
            db_path: Path to database file. If None, uses in-memory database.
        """
        self.db_path = Path(db_path) if db_path else None
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._exercises: "ExerciseStore | None" = None
        self._cards: "CardStore | None" = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Get or create database connection."""
        if self._conn is None:
            if self.db_path:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = duckdb.connect(str(self.db_path))
            else:
                self._conn = duckdb.connect(":memory:")
            self._init_schema()
        return self._conn

    @property
    def exercises(self) -> "ExerciseStore":
        """Get exercise store."""
        if self._exercises is None:
            from .exercise_store import ExerciseStore

            self._exercises = ExerciseStore(self.conn)
        return self._exercises

    @property
    def cards(self) -> "CardStore":
        """Get card store."""
        if self._cards is None:
            from .card_store import CardStore

            self._cards = CardStore(self.conn)
        return self._cards

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS exercises (
                id VARCHAR PRIMARY KEY,
                exercise_type VARCHAR NOT NULL,
                fen VARCHAR NOT NULL,
                tags JSON,
                source VARCHAR,
                source_url VARCHAR,
                difficulty DOUBLE,
                created_at TIMESTAMP,
                metadata JSON,
                type_data JSON
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS review_cards (
                exercise_id VARCHAR PRIMARY KEY REFERENCES exercises(id),
                state VARCHAR NOT NULL,
                difficulty DOUBLE NOT NULL,
                stability DOUBLE NOT NULL,
                retrievability DOUBLE NOT NULL,
                due TIMESTAMP NOT NULL,
                last_review TIMESTAMP,
                reps INTEGER NOT NULL DEFAULT 0,
                lapses INTEGER NOT NULL DEFAULT 0,
                step_index INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS review_history (
                id INTEGER PRIMARY KEY,
                exercise_id VARCHAR NOT NULL REFERENCES exercises(id),
                reviewed_at TIMESTAMP NOT NULL,
                rating INTEGER NOT NULL,
                time_taken_ms INTEGER NOT NULL,
                correct BOOLEAN NOT NULL,
                stability_before DOUBLE,
                stability_after DOUBLE
            )
        """)

        # Create sequence for review_history if it doesn't exist
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS review_history_seq
        """)

        # Indexes for common queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cards_due ON review_cards(due)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cards_state ON review_cards(state)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_exercises_type ON exercises(exercise_type)
        """)

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._exercises = None
            self._cards = None

    def __enter__(self) -> "Repository":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
