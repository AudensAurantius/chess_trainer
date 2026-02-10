"""Main repository class managing DuckDB connection and stores."""
# TODO: Consider adding a database migration history.

from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from .card_store import CardStore
    from .exercise_store import ExerciseStore
    from .opening_store import OpeningStore
    from .tag_store import TagStore


class Repository:
    """Central repository managing database connection and stores.

    Provides transactional access to exercises and review cards.
    """

    def __init__(self, db_path: str | Path | None = None):
        """Initialize repository with optional database path.

        Args:
            db_path: Path to database file. If None, uses in-memory database.
        """
        self.db_path = Path(db_path) if db_path else None
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._exercises: ExerciseStore | None = None
        self._cards: CardStore | None = None
        self._openings: OpeningStore | None = None
        self._tags: TagStore | None = None

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

    @property
    def openings(self) -> "OpeningStore":
        """Get opening store."""
        if self._openings is None:
            from .opening_store import OpeningStore

            self._openings = OpeningStore(self.conn)
        return self._openings

    @property
    def tags(self) -> "TagStore":
        """Get tag store."""
        if self._tags is None:
            from .tag_store import TagStore

            self._tags = TagStore(self.conn)
        return self._tags

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

        # Opening book tables
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS opening_lines (
                id VARCHAR PRIMARY KEY,
                color VARCHAR NOT NULL,
                eco_code VARCHAR,
                name VARCHAR,
                variation VARCHAR,
                moves JSON NOT NULL,
                annotations JSON,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS explorer_cache (
                cache_key VARCHAR PRIMARY KEY,
                fen VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                response_json JSON NOT NULL,
                fetched_at TIMESTAMP NOT NULL
            )
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_opening_lines_color
            ON opening_lines(color)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_explorer_cache_fetched
            ON explorer_cache(fetched_at)
        """)

        # Analytics indexes for review_history queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_review_history_reviewed_at
            ON review_history(reviewed_at)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_review_history_exercise_id
            ON review_history(exercise_id)
        """)

        # Tags table for normalized tag storage
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                entity_type VARCHAR NOT NULL,
                entity_id VARCHAR NOT NULL,
                tag VARCHAR NOT NULL,
                source VARCHAR NOT NULL DEFAULT 'user',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (entity_type, entity_id, tag)
            )
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tags_source ON tags(source)
        """)

        # One-time migration: backfill tags from exercise JSON
        self._migrate_exercise_tags()

    def _migrate_exercise_tags(self) -> None:
        """Backfill the tags table from exercise JSON data (one-time)."""
        tag_count = self.conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        if tag_count > 0:
            return  # Already populated

        exercise_count = self.conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0]
        if exercise_count == 0:
            return  # Nothing to migrate

        self.conn.execute("""
            INSERT INTO tags (entity_type, entity_id, tag, source, created_at)
            SELECT 'exercise', e.id, LOWER(TRIM(t.tag)), 'system', CURRENT_TIMESTAMP
            FROM exercises e, UNNEST(CAST(e.tags AS VARCHAR[])) AS t(tag)
            WHERE e.tags IS NOT NULL AND CAST(e.tags AS VARCHAR) != '[]'
            ON CONFLICT DO NOTHING
        """)

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._exercises = None
            self._cards = None
            self._openings = None
            self._tags = None

    def __enter__(self) -> "Repository":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
