"""Chess.com puzzle importer.

Fetches puzzles from the Chess.com public API and converts them
to TacticExercise format. Supports daily puzzle and random puzzles.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import chess

from ..chesscom.api import ChessComError, get_daily_puzzle, get_random_puzzle
from ..chesscom.models import ChessComPuzzle
from ..exercises import TacticExercise
from .base import Importer


class ChessComPuzzleImporter(Importer):
    """Import tactical puzzles from Chess.com.

    Supports two fetch modes:
    - Daily: Fetch today's daily puzzle
    - Random: Fetch random puzzles (no difficulty/theme filtering)

    Args:
        user_agent: User-Agent header for Chess.com API requests.
    """

    def __init__(self, user_agent: str | None = None) -> None:
        """Initialize the importer with optional User-Agent."""
        self._user_agent = user_agent

    @property
    def source_name(self) -> str:
        """Return the importer source name."""
        return "Chess.com Puzzles"

    def fetch(
        self,
        count: int = 10,
        include_daily: bool = True,
    ) -> Iterator[TacticExercise]:
        """Fetch puzzles from Chess.com.

        Args:
            count: Number of random puzzles to fetch.
            include_daily: Whether to include today's daily puzzle.

        Yields:
            TacticExercise objects.
        """
        seen_ids: set[str] = set()
        kwargs: dict[str, Any] = {}
        if self._user_agent:
            kwargs["user_agent"] = self._user_agent

        if include_daily:
            try:
                data = get_daily_puzzle(**kwargs)
                exercise = self._convert_puzzle(data, is_daily=True)
                if exercise and exercise.id not in seen_ids:
                    seen_ids.add(exercise.id)
                    yield exercise
            except (ChessComError, KeyError, ValueError):
                pass

        fetched = 0
        max_attempts = count * 3  # Avoid infinite loops on repeated puzzles
        attempts = 0
        while fetched < count and attempts < max_attempts:
            attempts += 1
            try:
                data = get_random_puzzle(**kwargs)
                exercise = self._convert_puzzle(data, is_daily=False)
                if exercise and exercise.id not in seen_ids:
                    seen_ids.add(exercise.id)
                    yield exercise
                    fetched += 1
            except (ChessComError, KeyError, ValueError):
                continue

    def _convert_puzzle(
        self,
        data: dict[str, Any],
        *,
        is_daily: bool = False,
    ) -> TacticExercise | None:
        """Convert a Chess.com puzzle API response to a TacticExercise.

        Args:
            data: Raw puzzle dict from the API.
            is_daily: Whether this is the daily puzzle.

        Returns:
            TacticExercise, or None if the puzzle can't be parsed.
        """
        puzzle = ChessComPuzzle.from_dict(data)

        if not puzzle.fen or not puzzle.pgn:
            return None

        # Parse the solution PGN into UCI moves
        solution_uci = self._parse_solution_pgn(puzzle.fen, puzzle.pgn)
        if not solution_uci:
            return None

        # Generate a stable ID
        if is_daily:
            puzzle_id = f"chesscom:daily:{puzzle.publish_time}"
        else:
            # Hash FEN + solution for dedup of random puzzles
            content = puzzle.fen + "|" + ",".join(solution_uci)
            digest = hashlib.sha256(content.encode()).hexdigest()[:12]
            puzzle_id = f"chesscom:random:{digest}"

        tags = ["tactic"]
        if is_daily:
            tags.append("chesscom_daily")

        return TacticExercise(
            id=puzzle_id,
            fen=puzzle.fen,
            tags=tags,
            source="chesscom",
            source_url=puzzle.url or None,
            difficulty=None,
            created_at=datetime.now(),
            solution=solution_uci,
            themes=[],
        )

    def _parse_solution_pgn(self, fen: str, pgn: str) -> list[str]:
        """Parse a Chess.com puzzle solution PGN into UCI move strings.

        Chess.com puzzles provide the solution as a PGN starting from
        the puzzle FEN. We parse SAN moves and convert to UCI.

        Args:
            fen: Starting position FEN.
            pgn: Solution PGN text.

        Returns:
            List of UCI move strings.
        """
        import re

        board = chess.Board(fen)
        uci_moves: list[str] = []

        # Strip comments, variations, move numbers, and results
        cleaned = re.sub(r"\{[^}]*\}", "", pgn)
        cleaned = re.sub(r"\([^)]*\)", "", cleaned)
        cleaned = re.sub(r"\d+\.+", "", cleaned)
        cleaned = re.sub(r"(1-0|0-1|1/2-1/2|\*)", "", cleaned)

        for token in cleaned.split():
            token = token.strip()
            if not token:
                continue
            try:
                move = board.parse_san(token)
                uci_moves.append(move.uci())
                board.push(move)
            except (chess.InvalidMoveError, chess.AmbiguousMoveError, chess.IllegalMoveError):
                continue

        return uci_moves
