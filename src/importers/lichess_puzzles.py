"""Lichess puzzle importer.

Fetches tactical puzzles from Lichess and converts them to TacticExercise format.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import chess

from ..exercises import TacticExercise
from ..lichess.api import (
    LichessError,
    get_puzzle_by_id,
    get_puzzle_history,
    random_puzzles,
)
from ..lichess.models import LichessPuzzle
from .base import Importer, ImportResult

_UNIT_MAP = {
    "day": 1,
    "days": 1,
    "d": 1,
    "week": 7,
    "weeks": 7,
    "w": 7,
    "month": 30,
    "months": 30,
    "m": 30,
    "year": 365,
    "years": 365,
    "y": 365,
}

_HORIZON_RE = re.compile(r"^\s*(\d+)\s*([a-z]+)\s*$", re.IGNORECASE)


def parse_time_horizon(horizon: str) -> datetime:
    """Parse a human-friendly time horizon into a datetime cutoff.

    Supported formats:
    - ``"3 months"``, ``"30 days"``, ``"1 year"``, ``"2 weeks"``
    - ``"2025-01-01"`` (ISO date)

    Args:
        horizon: Time horizon string.

    Returns:
        A datetime representing the earliest point in time.

    Raises:
        ValueError: If the format is unrecognized.
    """
    stripped = horizon.strip()

    # Try ISO date format first
    try:
        return datetime.fromisoformat(stripped)
    except ValueError:
        pass

    # Try relative format: "<number> <unit>"
    match = _HORIZON_RE.match(stripped)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        days = _UNIT_MAP.get(unit)
        if days is not None:
            return datetime.now() - timedelta(days=amount * days)

    raise ValueError(
        f"Unrecognized time horizon: {horizon!r}. "
        f"Use formats like '3 months', '30 days', '1 year', or '2025-01-01'."
    )


class LichessPuzzleImporter(Importer):
    """Import tactical puzzles from Lichess.

    Supports multiple fetch modes:
    - By ID: Fetch specific puzzles
    - Random: Fetch random puzzles with optional filters
    - History: Fetch user's puzzle history (requires auth)
    """

    @property
    def source_name(self) -> str:
        """Return the importer source name."""
        return "Lichess Puzzles"

    def fetch(
        self,
        puzzle_ids: list[str] | None = None,
        count: int = 10,
        difficulty: str | int | None = None,
        themes: list[str] | None = None,
        from_history: bool = False,
    ) -> Iterator[TacticExercise]:
        """Fetch puzzles from Lichess.

        Args:
            puzzle_ids: Specific puzzle IDs to fetch
            count: Number of random puzzles to fetch (if not using IDs)
            difficulty: Filter by difficulty (easiest, easier, normal, harder, hardest)
            themes: Filter by tactical themes
            from_history: Fetch from user's puzzle history instead

        Yields:
            TacticExercise objects
        """
        if puzzle_ids:
            for puzzle_id in puzzle_ids:
                try:
                    data = get_puzzle_by_id(puzzle_id)
                    yield self._convert_puzzle(data)
                except (LichessError, KeyError):
                    # Log and continue
                    continue

        elif from_history:
            for data in get_puzzle_history(limit=count):
                try:
                    yield self._convert_puzzle(data)
                except (KeyError, TypeError):
                    continue

        else:
            # Random puzzles with optional filters
            fetched = 0
            theme_dict = {t: 1 for t in themes} if themes else {}

            for data in random_puzzles(
                difficulties={difficulty: 1} if difficulty else {},
                themes=theme_dict,
            ):
                try:
                    yield self._convert_puzzle(data)
                    fetched += 1
                    if fetched >= count:
                        break
                except (KeyError, TypeError):
                    continue

    def fetch_failed(
        self,
        count: int = 50,
        since: str | datetime | None = None,
        auto_tag: bool = True,
    ) -> Iterator[TacticExercise]:
        """Fetch puzzles the user previously failed on Lichess.

        Uses the ``/api/puzzle/activity`` endpoint (requires authentication)
        and filters for losses only.

        Args:
            count: Maximum number of failed puzzles to return.
            since: Time horizon — only include failures after this point.
                Accepts a datetime or a human-friendly string like
                ``"3 months"`` or ``"2025-01-01"``.
            auto_tag: Add ``failed-puzzle`` and ``needs-review`` tags.

        Yields:
            TacticExercise objects for each failed puzzle.
        """
        since_dt: datetime | None = None
        if isinstance(since, str):
            since_dt = parse_time_horizon(since)
        elif isinstance(since, datetime):
            since_dt = since

        # Convert since to a Unix timestamp in milliseconds for cutoff comparison
        since_ms: int | None = None
        if since_dt is not None:
            since_ms = int(since_dt.timestamp() * 1000)

        yielded = 0
        # Request more than count since we filter for losses
        batch_size = count * 3

        for entry in get_puzzle_history(limit=batch_size):
            if yielded >= count:
                break

            # Filter: only failed puzzles
            if entry.get("win", True):
                continue

            # Filter: respect time horizon
            entry_date = entry.get("date", 0)
            if since_ms is not None and entry_date < since_ms:
                # Activity is reverse-chronological; once we pass the cutoff, stop
                break

            try:
                exercise = self._convert_activity(entry, auto_tag=auto_tag)
                yield exercise
                yielded += 1
            except (KeyError, TypeError, ValueError):
                continue

    def import_to_failed(
        self,
        store: Any,
        count: int = 50,
        since: str | datetime | None = None,
        auto_tag: bool = True,
    ) -> ImportResult:
        """Import failed puzzles directly to a store.

        Convenience wrapper around :meth:`fetch_failed` that handles
        iteration, deduplication, and error tracking.

        Args:
            store: ExerciseStore to add exercises to.
            count: Maximum number of failed puzzles to import.
            since: Time horizon for filtering.
            auto_tag: Whether to auto-tag with ``failed-puzzle`` / ``needs-review``.

        Returns:
            ImportResult with summary statistics.
        """
        result = ImportResult(source=self.source_name)

        for exercise in self.fetch_failed(count=count, since=since, auto_tag=auto_tag):
            result.total_fetched += 1
            try:
                store.add(exercise)
                result.total_added += 1
            except Exception as e:
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    result.total_skipped += 1
                else:
                    result.errors.append(f"{exercise.id}: {e}")

        return result

    def fetch_by_id(self, puzzle_id: str) -> TacticExercise | None:
        """Fetch a single puzzle by ID."""
        try:
            data = get_puzzle_by_id(puzzle_id)
            return self._convert_puzzle(data)
        except (LichessError, KeyError):
            return None

    def _convert_puzzle(self, data: dict[str, Any]) -> TacticExercise:
        """Convert Lichess puzzle JSON to TacticExercise.

        Uses LichessPuzzle model as the canonical parser for Lichess API
        responses, then transforms to the exercise domain.
        """
        puzzle = LichessPuzzle.from_dict(data)

        solution = puzzle.solution or []
        themes = puzzle.themes or []

        # Build the position by playing the game up to the puzzle position
        # The PGN ends just before the first solution move
        board = self._position_from_pgn(puzzle.game_to_puzzle or "")

        # The first move in solution is the opponent's move that creates the tactic
        # We need to play it to get to the actual puzzle position
        if solution:
            setup_move = chess.Move.from_uci(solution[0])
            if board.is_legal(setup_move):
                board.push(setup_move)

        return TacticExercise(
            id=f"lichess:{puzzle.id}",
            fen=board.fen(),
            tags=self._map_themes(themes),
            source="lichess",
            source_url=f"https://lichess.org/training/{puzzle.id}",
            difficulty=puzzle.rating,
            created_at=datetime.now(),
            solution=solution[1:] if len(solution) > 1 else solution,  # Skip setup move
            themes=themes,
            game_id=puzzle.game_id,
        )

    def _convert_activity(self, data: dict[str, Any], *, auto_tag: bool = True) -> TacticExercise:
        """Convert a Lichess puzzle activity entry to TacticExercise.

        The activity format differs from the individual puzzle format:
        it provides ``fen`` directly (the puzzle position) plus ``lastMove``
        (the opponent's setup move, already applied to the FEN), rather
        than a game PGN.

        Args:
            data: Raw puzzle activity JSON with ``date``, ``win``, and
                ``puzzle`` containing ``fen``, ``id``, ``solution``, etc.
            auto_tag: Whether to add ``failed-puzzle`` and ``needs-review`` tags.
        """
        puzzle = data["puzzle"]
        puzzle_id = puzzle["id"]
        fen = puzzle["fen"]
        solution = puzzle.get("solution", [])
        themes = puzzle.get("themes", [])
        rating = puzzle.get("rating")

        tags = self._map_themes(themes)
        if auto_tag:
            tags.extend(["failed-puzzle", "needs-review"])

        return TacticExercise(
            id=f"lichess:{puzzle_id}",
            fen=fen,
            tags=tags,
            source="lichess",
            source_url=f"https://lichess.org/training/{puzzle_id}",
            difficulty=rating,
            created_at=datetime.now(),
            solution=solution,
            themes=themes,
        )

    def _position_from_pgn(self, pgn: str) -> chess.Board:
        """Parse PGN and return the final position."""
        board = chess.Board()

        # Simple PGN parsing - extract moves from the movetext
        # Remove comments, variations, and result
        # Remove comments
        pgn = re.sub(r"\{[^}]*\}", "", pgn)
        # Remove variations
        pgn = re.sub(r"\([^)]*\)", "", pgn)
        # Remove move numbers and results
        pgn = re.sub(r"\d+\.", "", pgn)
        pgn = re.sub(r"(1-0|0-1|1/2-1/2|\*)", "", pgn)

        # Parse moves
        for token in pgn.split():
            token = token.strip()
            if not token:
                continue
            try:
                move = board.parse_san(token)
                board.push(move)
            except (chess.InvalidMoveError, chess.AmbiguousMoveError):
                continue

        return board

    def _map_themes(self, lichess_themes: list[str]) -> list[str]:
        """Map Lichess themes to internal tag format."""
        # Keep the original themes but also add some normalized versions
        tags = list(lichess_themes)

        # Add high-level categories
        tactical_themes = {
            "fork",
            "pin",
            "skewer",
            "discoveredAttack",
            "doubleCheck",
            "sacrifice",
            "deflection",
            "decoy",
            "interference",
            "overloading",
            "xRayAttack",
            "zugzwang",
        }

        mating_themes = {
            "mate",
            "mateIn1",
            "mateIn2",
            "mateIn3",
            "mateIn4",
            "mateIn5",
            "backRankMate",
            "smotheredMate",
            "hookMate",
            "arabianMate",
            "anastasiaMate",
            "bodenMate",
        }

        if any(t in tactical_themes for t in lichess_themes):
            if "tactic" not in tags:
                tags.append("tactic")

        if any(t in mating_themes for t in lichess_themes):
            if "mating_pattern" not in tags:
                tags.append("mating_pattern")

        return tags
