"""CRUD operations for exercise bundles and training progress."""

from __future__ import annotations

import json
from datetime import datetime

import duckdb

from ..exercises.bundle import BundleConfig, BundleProgress, CycleResult, ExerciseBundle


class BundleStore:
    """CRUD operations on the bundles and bundle_progress tables.

    Args:
        conn: Active DuckDB connection (from Repository.conn).
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Initialize with an active DuckDB connection."""
        self.conn = conn

    def create(self, bundle: ExerciseBundle) -> None:
        """Insert a new bundle.

        Args:
            bundle: The bundle to create.

        Raises:
            ValueError: If a bundle with the same ID already exists.
        """
        existing = self.get(bundle.id)
        if existing is not None:
            raise ValueError(f"Bundle already exists: {bundle.id}")
        self.conn.execute(
            """
            INSERT INTO bundles (id, name, description, exercise_ids, auto_tags,
                                 config, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                bundle.id,
                bundle.name,
                bundle.description,
                json.dumps(bundle.exercise_ids),
                json.dumps(bundle.auto_tags),
                json.dumps(bundle.config.to_dict()),
                bundle.created_at,
                bundle.updated_at,
            ],
        )

    def get(self, bundle_id: str) -> ExerciseBundle | None:
        """Get a bundle by ID.

        Args:
            bundle_id: The bundle ID (e.g. ``"bundle:knight-forks"``).

        Returns:
            The bundle, or ``None`` if not found.
        """
        row = self.conn.execute(
            "SELECT id, name, description, exercise_ids, auto_tags, config, "
            "created_at, updated_at FROM bundles WHERE id = ?",
            [bundle_id],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_bundle(row)

    def list_all(self) -> list[ExerciseBundle]:
        """List all bundles, ordered by name.

        Returns:
            List of all bundles.
        """
        rows = self.conn.execute(
            "SELECT id, name, description, exercise_ids, auto_tags, config, "
            "created_at, updated_at FROM bundles ORDER BY name"
        ).fetchall()
        return [self._row_to_bundle(row) for row in rows]

    def update(self, bundle: ExerciseBundle) -> None:
        """Update an existing bundle (DELETE + INSERT to avoid DuckDB FK issues).

        Args:
            bundle: The bundle with updated fields.
        """
        bundle.updated_at = datetime.now()
        # DELETE + INSERT pattern (DuckDB INSERT OR REPLACE FK bug)
        self.conn.execute("DELETE FROM bundles WHERE id = ?", [bundle.id])
        self.conn.execute(
            """
            INSERT INTO bundles (id, name, description, exercise_ids, auto_tags,
                                 config, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                bundle.id,
                bundle.name,
                bundle.description,
                json.dumps(bundle.exercise_ids),
                json.dumps(bundle.auto_tags),
                json.dumps(bundle.config.to_dict()),
                bundle.created_at,
                bundle.updated_at,
            ],
        )

    def delete(self, bundle_id: str) -> bool:
        """Delete a bundle and its progress.

        Args:
            bundle_id: The bundle ID.

        Returns:
            ``True`` if the bundle existed and was deleted.
        """
        existing = self.get(bundle_id)
        if existing is None:
            return False
        # Delete progress first (FK constraint)
        self.conn.execute("DELETE FROM bundle_progress WHERE bundle_id = ?", [bundle_id])
        self.conn.execute("DELETE FROM bundles WHERE id = ?", [bundle_id])
        return True

    def add_exercises(self, bundle_id: str, exercise_ids: list[str]) -> int:
        """Append exercise IDs to a bundle, deduplicating.

        Args:
            bundle_id: The bundle ID.
            exercise_ids: IDs to add.

        Returns:
            Number of exercises actually added (after dedup).

        Raises:
            ValueError: If the bundle does not exist.
        """
        bundle = self.get(bundle_id)
        if bundle is None:
            raise ValueError(f"Bundle not found: {bundle_id}")

        existing_set = set(bundle.exercise_ids)
        added = 0
        for eid in exercise_ids:
            if eid not in existing_set:
                bundle.exercise_ids.append(eid)
                existing_set.add(eid)
                added += 1

        if added > 0:
            self.update(bundle)
        return added

    def remove_exercises(self, bundle_id: str, exercise_ids: list[str]) -> int:
        """Remove exercise IDs from a bundle.

        Args:
            bundle_id: The bundle ID.
            exercise_ids: IDs to remove.

        Returns:
            Number of exercises actually removed.

        Raises:
            ValueError: If the bundle does not exist.
        """
        bundle = self.get(bundle_id)
        if bundle is None:
            raise ValueError(f"Bundle not found: {bundle_id}")

        remove_set = set(exercise_ids)
        original_count = len(bundle.exercise_ids)
        bundle.exercise_ids = [eid for eid in bundle.exercise_ids if eid not in remove_set]
        removed = original_count - len(bundle.exercise_ids)

        if removed > 0:
            self.update(bundle)
        return removed

    # ── Progress tracking ────────────────────────────────────────────────────

    def get_progress(self, bundle_id: str) -> BundleProgress | None:
        """Get training progress for a bundle.

        Args:
            bundle_id: The bundle ID.

        Returns:
            Progress state, or ``None`` if no progress exists.
        """
        row = self.conn.execute(
            "SELECT bundle_id, current_cycle, cycle_started_at, "
            "exercises_attempted, exercises_correct, completed_cycles "
            "FROM bundle_progress WHERE bundle_id = ?",
            [bundle_id],
        ).fetchone()
        if row is None:
            return None
        return self._row_to_progress(row)

    def save_progress(self, progress: BundleProgress) -> None:
        """Save or update training progress (DELETE + INSERT upsert).

        Args:
            progress: The progress state to persist.
        """
        self.conn.execute(
            "DELETE FROM bundle_progress WHERE bundle_id = ?",
            [progress.bundle_id],
        )
        self.conn.execute(
            """
            INSERT INTO bundle_progress (bundle_id, current_cycle, cycle_started_at,
                                         exercises_attempted, exercises_correct,
                                         completed_cycles)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                progress.bundle_id,
                progress.current_cycle,
                progress.cycle_started_at,
                progress.exercises_attempted,
                progress.exercises_correct,
                json.dumps([c.to_dict() for c in progress.completed_cycles]),
            ],
        )

    def reset_progress(self, bundle_id: str) -> None:
        """Delete training progress for a bundle.

        Args:
            bundle_id: The bundle ID.
        """
        self.conn.execute(
            "DELETE FROM bundle_progress WHERE bundle_id = ?",
            [bundle_id],
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_bundle(row: tuple) -> ExerciseBundle:
        """Convert a database row to an ExerciseBundle."""
        raw_ids = row[3]
        exercise_ids = json.loads(raw_ids) if isinstance(raw_ids, str) else list(raw_ids or [])

        raw_tags = row[4]
        auto_tags = json.loads(raw_tags) if isinstance(raw_tags, str) else list(raw_tags or [])

        raw_config = row[5]
        config = BundleConfig.from_dict(
            json.loads(raw_config) if isinstance(raw_config, str) else (raw_config or {})
        )

        return ExerciseBundle(
            id=row[0],
            name=row[1],
            description=row[2] or "",
            exercise_ids=exercise_ids,
            auto_tags=auto_tags,
            config=config,
            created_at=row[6],
            updated_at=row[7],
        )

    @staticmethod
    def _row_to_progress(row: tuple) -> BundleProgress:
        """Convert a database row to a BundleProgress."""
        raw_cycles = row[5]
        completed = []
        if raw_cycles:
            cycle_list = json.loads(raw_cycles) if isinstance(raw_cycles, str) else raw_cycles
            completed = [CycleResult.from_dict(c) for c in cycle_list]

        return BundleProgress(
            bundle_id=row[0],
            current_cycle=row[1],
            cycle_started_at=row[2],
            exercises_attempted=row[3],
            exercises_correct=row[4],
            completed_cycles=completed,
        )
