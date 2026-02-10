"""Normalized tag storage for exercises and openings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import duckdb


class EntityType(StrEnum):
    """Types of entities that can be tagged."""

    EXERCISE = "exercise"
    OPENING = "opening"


class TagSource(StrEnum):
    """Origin of a tag."""

    USER = "user"
    SYSTEM = "system"


@dataclass
class TagInfo:
    """A tag with its usage count."""

    tag: str
    count: int


class TagStore:
    """CRUD operations on the normalized tags table.

    Args:
        conn: Active DuckDB connection (from Repository.conn).
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Initialize with an active DuckDB connection."""
        self.conn = conn

    @staticmethod
    def _normalize_tag(tag: str) -> str:
        """Normalize a tag string: strip whitespace, lowercase.

        Raises:
            ValueError: If the tag is empty after normalization.
        """
        result = tag.strip().lower()
        if not result:
            raise ValueError("Tag cannot be empty")
        return result

    def add_tags(
        self,
        entity_type: EntityType,
        entity_id: str,
        tags: list[str],
        source: TagSource = TagSource.USER,
    ) -> int:
        """Add tags to an entity, skipping empty/duplicate tags.

        Args:
            entity_type: The type of entity being tagged.
            entity_id: The ID of the entity.
            tags: List of tag strings to add.
            source: Origin of the tags.

        Returns:
            Number of tags actually added (after dedup/normalization).
        """
        added = 0
        seen: set[str] = set()
        for raw in tags:
            try:
                normalized = self._normalize_tag(raw)
            except ValueError:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            self.conn.execute(
                """
                INSERT INTO tags (entity_type, entity_id, tag, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                [entity_type.value, entity_id, normalized, source.value],
            )
            # Check if the row was actually inserted
            # DuckDB doesn't return rowcount for ON CONFLICT, so count after
            added += 1
        return added

    def remove_tags(
        self,
        entity_type: EntityType,
        entity_id: str,
        tags: list[str],
    ) -> int:
        """Remove tags from an entity.

        Args:
            entity_type: The type of entity.
            entity_id: The ID of the entity.
            tags: List of tag strings to remove.

        Returns:
            Number of tags actually removed.
        """
        removed = 0
        for raw in tags:
            try:
                normalized = self._normalize_tag(raw)
            except ValueError:
                continue
            # Count before delete
            count_before = self.conn.execute(
                "SELECT COUNT(*) FROM tags WHERE entity_type = ? AND entity_id = ? AND tag = ?",
                [entity_type.value, entity_id, normalized],
            ).fetchone()[0]
            if count_before > 0:
                self.conn.execute(
                    "DELETE FROM tags WHERE entity_type = ? AND entity_id = ? AND tag = ?",
                    [entity_type.value, entity_id, normalized],
                )
                removed += 1
        return removed

    def get_tags(
        self,
        entity_type: EntityType,
        entity_id: str,
        source: TagSource | None = None,
    ) -> list[str]:
        """Get all tags for an entity, optionally filtered by source.

        Args:
            entity_type: The type of entity.
            entity_id: The ID of the entity.
            source: Optional filter by tag source.

        Returns:
            Sorted list of tag strings.
        """
        if source is not None:
            rows = self.conn.execute(
                """
                SELECT tag FROM tags
                WHERE entity_type = ? AND entity_id = ? AND source = ?
                ORDER BY tag
                """,
                [entity_type.value, entity_id, source.value],
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT tag FROM tags
                WHERE entity_type = ? AND entity_id = ?
                ORDER BY tag
                """,
                [entity_type.value, entity_id],
            ).fetchall()
        return [row[0] for row in rows]

    def find_by_tags(
        self,
        entity_type: EntityType,
        tags: list[str],
        match_all: bool = True,
    ) -> list[str]:
        """Find entity IDs that have the given tags.

        Args:
            entity_type: The type of entity to search.
            tags: Tags to match against.
            match_all: If True, entity must have ALL tags (AND).
                       If False, entity must have ANY tag (OR).

        Returns:
            List of entity IDs.
        """
        normalized: list[str] = []
        for raw in tags:
            try:
                normalized.append(self._normalize_tag(raw))
            except ValueError:
                continue
        if not normalized:
            return []

        placeholders = ", ".join(["?"] * len(normalized))
        params: list = [entity_type.value, *normalized]

        if match_all:
            rows = self.conn.execute(
                f"""
                SELECT entity_id
                FROM tags
                WHERE entity_type = ? AND tag IN ({placeholders})
                GROUP BY entity_id
                HAVING COUNT(DISTINCT tag) = ?
                """,
                [*params, len(normalized)],
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT DISTINCT entity_id
                FROM tags
                WHERE entity_type = ? AND tag IN ({placeholders})
                """,
                params,
            ).fetchall()
        return [row[0] for row in rows]

    def list_all_tags(
        self,
        entity_type: EntityType | None = None,
    ) -> list[TagInfo]:
        """List all tags with their usage counts.

        Args:
            entity_type: Optional filter by entity type.

        Returns:
            List of TagInfo ordered by count descending.
        """
        if entity_type is not None:
            rows = self.conn.execute(
                """
                SELECT tag, COUNT(*) AS cnt
                FROM tags
                WHERE entity_type = ?
                GROUP BY tag
                ORDER BY cnt DESC, tag
                """,
                [entity_type.value],
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT tag, COUNT(*) AS cnt
                FROM tags
                GROUP BY tag
                ORDER BY cnt DESC, tag
                """,
            ).fetchall()
        return [TagInfo(tag=row[0], count=int(row[1])) for row in rows]

    def search_tags(
        self,
        query: str,
        entity_type: EntityType | None = None,
    ) -> list[TagInfo]:
        """Search tags by substring match.

        Args:
            query: Substring to search for.
            entity_type: Optional filter by entity type.

        Returns:
            List of matching TagInfo ordered by count descending.
        """
        pattern = f"%{query.strip().lower()}%"
        if entity_type is not None:
            rows = self.conn.execute(
                """
                SELECT tag, COUNT(*) AS cnt
                FROM tags
                WHERE entity_type = ? AND tag LIKE ?
                GROUP BY tag
                ORDER BY cnt DESC, tag
                """,
                [entity_type.value, pattern],
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT tag, COUNT(*) AS cnt
                FROM tags
                WHERE tag LIKE ?
                GROUP BY tag
                ORDER BY cnt DESC, tag
                """,
                [pattern],
            ).fetchall()
        return [TagInfo(tag=row[0], count=int(row[1])) for row in rows]
