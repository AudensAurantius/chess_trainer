"""Storage operations for opening lines and explorer cache."""

import json
from datetime import datetime, timedelta

import duckdb

from ..openings.models import BookColor, ExplorerSource, OpeningLine


class OpeningStore:
    """Store for opening book lines and explorer API cache."""

    def __init__(self, conn: duckdb.DuckDBPyConnection):
        """Initialize opening store with database connection."""
        self.conn = conn

    # ── Lines CRUD ────────────────────────────────────────────────────────────

    def add_line(self, line: OpeningLine) -> None:
        """Add a new opening line to the book."""
        self.conn.execute(
            """
            INSERT INTO opening_lines (
                id, color, eco_code, name, variation,
                moves, annotations, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                line.id,
                line.color.value,
                line.eco_code,
                line.name,
                line.variation,
                json.dumps(line.moves),
                json.dumps({str(k): v for k, v in line.annotations.items()}),
                line.created_at,
                line.updated_at,
            ],
        )

    def get_line(self, line_id: str) -> OpeningLine | None:
        """Get an opening line by ID."""
        result = self.conn.execute(
            """
            SELECT id, color, eco_code, name, variation,
                   moves, annotations, created_at, updated_at
            FROM opening_lines WHERE id = ?
            """,
            [line_id],
        ).fetchone()

        if not result:
            return None

        return self._row_to_line(result)

    def list_lines(
        self,
        color: BookColor | None = None,
        name_contains: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[OpeningLine]:
        """List opening lines with optional filters."""
        conditions: list[str] = []
        params: list = []

        if color is not None:
            conditions.append("color = ?")
            params.append(color.value)

        if name_contains is not None:
            conditions.append("LOWER(name) LIKE ?")
            params.append(f"%{name_contains.lower()}%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        results = self.conn.execute(
            f"""
            SELECT id, color, eco_code, name, variation,
                   moves, annotations, created_at, updated_at
            FROM opening_lines
            WHERE {where_clause}
            ORDER BY name, variation, created_at
            LIMIT {limit} OFFSET {offset}
            """,
            params,
        ).fetchall()

        return [self._row_to_line(row) for row in results]

    def delete_line(self, line_id: str) -> bool:
        """Delete an opening line by ID. Returns True if deleted."""
        result = self.conn.execute(
            "DELETE FROM opening_lines WHERE id = ? RETURNING id",
            [line_id],
        ).fetchone()
        return result is not None

    def count_lines(self, color: BookColor | None = None) -> int:
        """Count opening lines, optionally filtered by color."""
        if color is not None:
            result = self.conn.execute(
                "SELECT COUNT(*) FROM opening_lines WHERE color = ?",
                [color.value],
            ).fetchone()
        else:
            result = self.conn.execute("SELECT COUNT(*) FROM opening_lines").fetchone()
        return result[0] if result else 0

    def update_line(self, line: OpeningLine) -> None:
        """Update an existing opening line (DELETE + INSERT)."""
        self.conn.execute("DELETE FROM opening_lines WHERE id = ?", [line.id])
        self.add_line(line)

    # ── Explorer cache ────────────────────────────────────────────────────────

    def cache_get(self, fen: str, source: ExplorerSource, ttl_hours: int) -> dict | None:
        """Get a cached explorer response if it exists and is fresh."""
        cache_key = f"{source.value}:{fen}"
        cutoff = datetime.now() - timedelta(hours=ttl_hours)

        result = self.conn.execute(
            """
            SELECT response_json FROM explorer_cache
            WHERE cache_key = ? AND fetched_at >= ?
            """,
            [cache_key, cutoff],
        ).fetchone()

        if not result:
            return None

        raw = result[0]
        return json.loads(raw) if isinstance(raw, str) else raw

    def cache_put(self, fen: str, source: ExplorerSource, response: dict) -> None:
        """Store an explorer response in the cache."""
        cache_key = f"{source.value}:{fen}"
        # DELETE + INSERT to handle upsert
        self.conn.execute(
            "DELETE FROM explorer_cache WHERE cache_key = ?",
            [cache_key],
        )
        self.conn.execute(
            """
            INSERT INTO explorer_cache (
                cache_key, fen, source, response_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                cache_key,
                fen,
                source.value,
                json.dumps(response),
                datetime.now(),
            ],
        )

    def cache_clear(self, older_than_hours: int | None = None) -> int:
        """Clear cached explorer responses.

        Args:
            older_than_hours: If set, only clear entries older than this.
                If None, clear all cache entries.

        Returns:
            Number of entries cleared.
        """
        if older_than_hours is not None:
            cutoff = datetime.now() - timedelta(hours=older_than_hours)
            result = self.conn.execute(
                "DELETE FROM explorer_cache WHERE fetched_at < ? RETURNING cache_key",
                [cutoff],
            ).fetchall()
        else:
            result = self.conn.execute("DELETE FROM explorer_cache RETURNING cache_key").fetchall()
        return len(result)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _row_to_line(self, row: tuple) -> OpeningLine:
        """Convert a database row to an OpeningLine."""
        (
            id_,
            color,
            eco_code,
            name,
            variation,
            moves,
            annotations,
            created_at,
            updated_at,
        ) = row

        moves = json.loads(moves) if isinstance(moves, str) else moves
        annotations = json.loads(annotations) if isinstance(annotations, str) else annotations

        return OpeningLine(
            id=id_,
            color=BookColor(color),
            eco_code=eco_code or "",
            name=name or "",
            variation=variation or "",
            moves=moves or [],
            annotations={int(k): v for k, v in annotations.items()} if annotations else {},
            created_at=created_at
            if isinstance(created_at, datetime)
            else datetime.fromisoformat(str(created_at)),
            updated_at=updated_at
            if isinstance(updated_at, datetime)
            else datetime.fromisoformat(str(updated_at)),
        )
