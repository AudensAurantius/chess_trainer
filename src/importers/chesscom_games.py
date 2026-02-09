"""Chess.com game importer for exercise generation from mistakes.

Imports games from the Chess.com API, analyzes them with a local engine,
and generates TacticExercise objects from the worst positions.
"""

from __future__ import annotations

import io
from collections.abc import Iterator

import chess.pgn

from ..analysis.classification import MoveClassification
from ..analysis.engine import EngineManager
from ..analysis.mistakes import EnginePositionAnalyzer, MistakeDetector
from ..chesscom.api import ChessComError, get_recent_games
from ..chesscom.models import ChessComGame
from ..exercises import Exercise
from .base import Importer


class ChessComGameImporter(Importer):
    """Import Chess.com games and generate exercises from mistakes.

    Unlike the Lichess GameImporter, Chess.com does not provide
    server-side evaluations, so a local engine is always required.

    Args:
        engine: EngineManager for local analysis.
        depth: Analysis depth for the engine.
        min_classification: Minimum mistake severity for exercise generation.
        max_exercises: Maximum exercises per game.
        skip_first_plies: Number of opening plies to skip.
    """

    def __init__(
        self,
        engine: EngineManager | None = None,
        *,
        depth: int = 20,
        min_classification: MoveClassification = MoveClassification.MISTAKE,
        max_exercises: int = 10,
        skip_first_plies: int = 6,
    ) -> None:
        """Initialize the importer with analysis parameters."""
        self._engine = engine
        self._depth = depth
        self._min_classification = min_classification
        self._max_exercises = max_exercises
        self._skip_first_plies = skip_first_plies

    @property
    def source_name(self) -> str:
        """Return the importer source name."""
        return "Chess.com Game Analysis"

    def fetch(
        self,
        *,
        username: str | None = None,
        max_games: int = 10,
        color: str | None = None,
        time_class: str | None = None,
        rated: bool | None = None,
        since_year: int | None = None,
        since_month: int | None = None,
        user_agent: str | None = None,
        request_delay: float = 0.5,
    ) -> Iterator[Exercise]:
        """Fetch Chess.com games and generate exercises from mistakes.

        Args:
            username: Chess.com username to fetch games for.
            max_games: Maximum number of games to process.
            color: Only generate exercises for this color ("white" or "black").
            time_class: Filter by time class (bullet, blitz, rapid, daily).
            rated: Filter for rated/unrated games.
            since_year: Only fetch games from this year onwards.
            since_month: Only fetch games from this month onwards.
            user_agent: User-Agent header for API requests.
            request_delay: Seconds between archive page fetches.

        Yields:
            TacticExercise objects for each qualifying mistake.
        """
        if not username:
            return

        if not self._engine:
            return

        kwargs: dict = {"max_games": max_games, "request_delay": request_delay}
        if user_agent:
            kwargs["user_agent"] = user_agent
        if since_year is not None:
            kwargs["since_year"] = since_year
        if since_month is not None:
            kwargs["since_month"] = since_month

        try:
            game_dicts = get_recent_games(username, **kwargs)
        except ChessComError:
            return

        for game_data in game_dicts:
            game_obj = ChessComGame.from_dict(game_data)

            # Skip variants
            if game_obj.rules != "chess":
                continue

            # Apply filters
            if time_class and game_obj.time_class != time_class:
                continue
            if rated is not None and game_obj.rated != rated:
                continue

            if not game_obj.pgn:
                continue

            game = chess.pgn.read_game(io.StringIO(game_obj.pgn))
            if game is None:
                continue

            # Determine user's color
            user_color = None
            if game_obj.white.username.lower() == username.lower():
                user_color = "white"
            elif game_obj.black.username.lower() == username.lower():
                user_color = "black"

            # If a color filter is specified, only use that color
            analysis_color = color or user_color

            analyzer = EnginePositionAnalyzer(self._engine, depth=self._depth)
            detector = MistakeDetector(
                analyzer,
                min_classification=self._min_classification,
                max_exercises=self._max_exercises,
                skip_first_plies=self._skip_first_plies,
            )

            yield from detector.generate_exercises(
                game,
                game_id=f"chesscom:{game_obj.game_id}",
                source_url=game_obj.url,
                color=analysis_color,
            )
