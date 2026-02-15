"""Exercise storage operations."""

import json
from collections.abc import Iterator
from datetime import datetime

import duckdb

from ..exercises import (
    EndgameExercise,
    Exercise,
    ExerciseType,
    OpeningExercise,
    PositionalExercise,
    TacticExercise,
)

# Mapping from type enum to class
EXERCISE_CLASSES = {
    ExerciseType.TACTIC: TacticExercise,
    ExerciseType.OPENING: OpeningExercise,
    ExerciseType.ENDGAME: EndgameExercise,
    ExerciseType.POSITIONAL: PositionalExercise,
}


class ExerciseStore:
    """Store for exercise CRUD operations."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        """Initialize exercise store with database connection."""
        self.conn = conn

    def add(self, exercise: Exercise) -> None:
        """Add a new exercise to the store."""
        data = exercise.to_dict()
        type_data = exercise._type_specific_dict()

        self.conn.execute(
            """
            INSERT INTO exercises (
                id, exercise_type, fen, tags, source, source_url,
                difficulty, created_at, metadata, type_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                data["id"],
                data["exercise_type"],
                data["fen"],
                json.dumps(data["tags"]),
                data["source"],
                data["source_url"],
                data["difficulty"],
                data["created_at"],
                json.dumps(data["metadata"]),
                json.dumps(type_data),
            ],
        )

    def add_many(self, exercises: list[Exercise]) -> int:
        """Add multiple exercises efficiently.

        Returns number of exercises added (skips duplicates).
        """
        added = 0
        for exercise in exercises:
            try:
                self.add(exercise)
                added += 1
            except duckdb.ConstraintException:
                # Skip duplicates
                pass
        return added

    def get(self, exercise_id: str) -> Exercise | None:
        """Get an exercise by ID."""
        result = self.conn.execute(
            """
            SELECT id, exercise_type, fen, tags, source, source_url,
                   difficulty, created_at, metadata, type_data
            FROM exercises WHERE id = ?
            """,
            [exercise_id],
        ).fetchone()

        if not result:
            return None

        return self._row_to_exercise(result)

    def get_by_type(self, exercise_type: ExerciseType, limit: int | None = None) -> list[Exercise]:
        """Get exercises of a specific type."""
        query = """
            SELECT id, exercise_type, fen, tags, source, source_url,
                   difficulty, created_at, metadata, type_data
            FROM exercises WHERE exercise_type = ?
            ORDER BY created_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"

        results = self.conn.execute(query, [exercise_type.name]).fetchall()
        return [self._row_to_exercise(row) for row in results]

    def get_by_tags(self, tags: list[str], match_all: bool = False) -> list[Exercise]:
        """Get exercises matching tags.

        Args:
            tags: Tags to match
            match_all: If True, exercise must have all tags. If False, any tag.
        """
        if match_all:
            # Exercise must contain all specified tags
            conditions = " AND ".join(f"list_contains(tags::VARCHAR[], '{tag}')" for tag in tags)
        else:
            # Exercise must contain at least one tag
            conditions = " OR ".join(f"list_contains(tags::VARCHAR[], '{tag}')" for tag in tags)

        results = self.conn.execute(
            f"""
            SELECT id, exercise_type, fen, tags, source, source_url,
                   difficulty, created_at, metadata, type_data
            FROM exercises WHERE {conditions}
            ORDER BY created_at DESC
            """
        ).fetchall()

        return [self._row_to_exercise(row) for row in results]

    def search(
        self,
        exercise_type: ExerciseType | None = None,
        tags: list[str] | None = None,
        min_difficulty: float | None = None,
        max_difficulty: float | None = None,
        source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Exercise]:
        """Search exercises with multiple filters."""
        conditions = []
        params = []

        if exercise_type:
            conditions.append("exercise_type = ?")
            params.append(exercise_type.name)

        if tags:
            tag_conditions = " OR ".join(f"list_contains(tags::VARCHAR[], '{tag}')" for tag in tags)
            conditions.append(f"({tag_conditions})")

        if min_difficulty is not None:
            conditions.append("difficulty >= ?")
            params.append(min_difficulty)

        if max_difficulty is not None:
            conditions.append("difficulty <= ?")
            params.append(max_difficulty)

        if source:
            conditions.append("source = ?")
            params.append(source)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        results = self.conn.execute(
            f"""
            SELECT id, exercise_type, fen, tags, source, source_url,
                   difficulty, created_at, metadata, type_data
            FROM exercises
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT {limit} OFFSET {offset}
            """,
            params,
        ).fetchall()

        return [self._row_to_exercise(row) for row in results]

    def count(self, exercise_type: ExerciseType | None = None) -> int:
        """Count exercises, optionally filtered by type."""
        if exercise_type:
            result = self.conn.execute(
                "SELECT COUNT(*) FROM exercises WHERE exercise_type = ?",
                [exercise_type.name],
            ).fetchone()
        else:
            result = self.conn.execute("SELECT COUNT(*) FROM exercises").fetchone()
        return result[0] if result else 0

    def delete(self, exercise_id: str) -> bool:
        """Delete an exercise by ID. Returns True if deleted."""
        result = self.conn.execute(
            "DELETE FROM exercises WHERE id = ? RETURNING id", [exercise_id]
        ).fetchone()
        return result is not None

    def update_metadata(self, exercise_id: str, updates: dict) -> bool:
        """Atomically merge updates into an exercise's metadata JSON.

        Args:
            exercise_id: The exercise ID to update.
            updates: Dict of keys to merge. Use ``None`` values to remove keys.

        Returns:
            True if the exercise was found and updated.
        """
        # Read current metadata
        row = self.conn.execute(
            "SELECT metadata FROM exercises WHERE id = ?", [exercise_id]
        ).fetchone()
        if row is None:
            return False

        current = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
        for key, value in updates.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value

        self.conn.execute(
            "UPDATE exercises SET metadata = ? WHERE id = ?",
            [json.dumps(current), exercise_id],
        )
        return True

    def update_notes(self, exercise_id: str, notes: str | None) -> bool:
        """Set or clear notes on an exercise.

        Args:
            exercise_id: The exercise ID.
            notes: Notes text, or ``None`` to clear.

        Returns:
            True if the exercise was found and updated.
        """
        return self.update_metadata(exercise_id, {"notes": notes})

    def iterate_all(self) -> Iterator[Exercise]:
        """Iterate over all exercises (memory efficient for large datasets)."""
        cursor = self.conn.execute(
            """
            SELECT id, exercise_type, fen, tags, source, source_url,
                   difficulty, created_at, metadata, type_data
            FROM exercises
            ORDER BY id
            """
        )

        while True:
            rows = cursor.fetchmany(100)
            if not rows:
                break
            for row in rows:
                yield self._row_to_exercise(row)

    def _row_to_exercise(self, row: tuple) -> Exercise:
        """Convert database row to Exercise object."""
        (
            id_,
            exercise_type,
            fen,
            tags,
            source,
            source_url,
            difficulty,
            created_at,
            metadata,
            type_data,
        ) = row

        # Parse JSON fields
        tags = json.loads(tags) if isinstance(tags, str) else tags
        metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
        type_data = json.loads(type_data) if isinstance(type_data, str) else type_data

        # Get exercise type
        ex_type = ExerciseType[exercise_type]
        cls = EXERCISE_CLASSES[ex_type]

        # Build data dict for from_dict
        data = {
            "id": id_,
            "fen": fen,
            "tags": tags or [],
            "source": source or "",
            "source_url": source_url,
            "difficulty": difficulty,
            "created_at": created_at.isoformat()
            if isinstance(created_at, datetime)
            else created_at,
            "metadata": metadata or {},
            **(type_data or {}),
        }

        return cls.from_dict(data)
