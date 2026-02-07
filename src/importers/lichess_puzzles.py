"""
Lichess puzzle importer.

Fetches tactical puzzles from Lichess and converts them to TacticExercise format.
"""

from datetime import datetime
from typing import Iterator, Any

import chess

from .base import Importer
from ..exercises import TacticExercise
from ..lichess.api import (
    get_puzzle_by_id,
    get_random_puzzle,
    random_puzzles,
    get_puzzle_history,
    LichessError,
)


class LichessPuzzleImporter(Importer):
    """
    Import tactical puzzles from Lichess.

    Supports multiple fetch modes:
    - By ID: Fetch specific puzzles
    - Random: Fetch random puzzles with optional filters
    - History: Fetch user's puzzle history (requires auth)
    """

    @property
    def source_name(self) -> str:
        return "Lichess Puzzles"

    def fetch(
        self,
        puzzle_ids: list[str] | None = None,
        count: int = 10,
        difficulty: str | int | None = None,
        themes: list[str] | None = None,
        from_history: bool = False,
    ) -> Iterator[TacticExercise]:
        """
        Fetch puzzles from Lichess.

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
                except (LichessError, KeyError) as e:
                    # Log and continue
                    continue

        elif from_history:
            for data in get_puzzle_history(limit=count):
                try:
                    # History format wraps puzzle in a "puzzle" key
                    puzzle_data = data.get("puzzle", data)
                    yield self._convert_puzzle(puzzle_data)
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

    def fetch_by_id(self, puzzle_id: str) -> TacticExercise | None:
        """Fetch a single puzzle by ID."""
        try:
            data = get_puzzle_by_id(puzzle_id)
            return self._convert_puzzle(data)
        except (LichessError, KeyError):
            return None

    def _convert_puzzle(self, data: dict[str, Any]) -> TacticExercise:
        """
        Convert Lichess puzzle JSON to TacticExercise.

        Lichess format:
        {
            "game": {"id": "...", "pgn": "..."},
            "puzzle": {
                "id": "...",
                "rating": 1500,
                "plays": 12345,
                "solution": ["e2e4", "d7d5", ...],
                "themes": ["fork", "middlegame"]
            }
        }
        """
        puzzle = data.get("puzzle", data)
        game = data.get("game", {})

        puzzle_id = puzzle["id"]
        solution = puzzle["solution"]
        themes = puzzle.get("themes", [])
        rating = puzzle.get("rating")

        # Build the position by playing the game up to the puzzle position
        # The PGN ends just before the first solution move
        pgn = game.get("pgn", "")
        board = self._position_from_pgn(pgn)

        # The first move in solution is the opponent's move that creates the tactic
        # We need to play it to get to the actual puzzle position
        if solution:
            setup_move = chess.Move.from_uci(solution[0])
            if board.is_legal(setup_move):
                board.push(setup_move)

        return TacticExercise(
            id=f"lichess:{puzzle_id}",
            fen=board.fen(),
            tags=self._map_themes(themes),
            source="lichess",
            source_url=f"https://lichess.org/training/{puzzle_id}",
            difficulty=rating,
            created_at=datetime.now(),
            solution=solution[1:] if len(solution) > 1 else solution,  # Skip setup move
            themes=themes,
            game_id=game.get("id"),
        )

    def _position_from_pgn(self, pgn: str) -> chess.Board:
        """Parse PGN and return the final position."""
        board = chess.Board()

        # Simple PGN parsing - extract moves from the movetext
        # Remove comments, variations, and result
        import re

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
            "fork", "pin", "skewer", "discoveredAttack",
            "doubleCheck", "sacrifice", "deflection", "decoy",
            "interference", "overloading", "xRayAttack", "zugzwang",
        }

        mating_themes = {
            "mate", "mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5",
            "backRankMate", "smotheredMate", "hookMate", "arabianMate",
            "anastasiaMate", "bodenMate",
        }

        if any(t in tactical_themes for t in lichess_themes):
            if "tactic" not in tags:
                tags.append("tactic")

        if any(t in mating_themes for t in lichess_themes):
            if "mating_pattern" not in tags:
                tags.append("mating_pattern")

        return tags
