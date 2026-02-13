"""Own-game importer for exercise generation from mistakes.

Imports games from PGN files or Lichess API, analyzes them for mistakes,
and generates TacticExercise objects from the worst positions.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC
from pathlib import Path

import chess.pgn

from ..analysis.classification import MoveClassification
from ..analysis.engine import EngineManager
from ..analysis.mistakes import (
    EnginePositionAnalyzer,
    LichessServerAnalyzer,
    MistakeDetector,
    PositionAnalyzer,
)
from ..exercises import Exercise
from ..lichess.api import get_user_games
from .base import Importer


def parse_pgn_games(pgn_source: str | Path) -> list[chess.pgn.Game]:
    """Parse one or more games from a PGN file or string.

    Args:
        pgn_source: Either a file path or a PGN string.

    Returns:
        List of parsed chess.pgn.Game objects.
    """
    text = pgn_source
    if isinstance(pgn_source, Path):
        text = pgn_source.read_text()
    elif isinstance(pgn_source, str) and Path(pgn_source).is_file():
        text = Path(pgn_source).read_text()

    games: list[chess.pgn.Game] = []
    stream = io.StringIO(text)

    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        games.append(game)

    return games


class GameImporter(Importer):
    """Import own games and generate exercises from mistakes.

    Supports three modes:
    - PGN file + local engine analysis
    - Lichess username + local engine analysis
    - Lichess username + server-side evaluations (no engine needed)

    Args:
        engine: EngineManager for local analysis (None for server evals).
        depth: Analysis depth for the engine.
        min_classification: Minimum mistake severity for exercise generation.
        max_exercises: Maximum exercises per game.
        skip_first_plies: Number of opening plies to skip.
        cp_tolerance: Centipawns within best to accept as alternative first move.
        multipv_count: Number of multi-PV lines for acceptable move computation.
        evaluate_depth: User moves to evaluate per exercise (1 = first move only).
    """

    def __init__(
        self,
        engine: EngineManager | None = None,
        *,
        depth: int = 20,
        min_classification: MoveClassification = MoveClassification.MISTAKE,
        max_exercises: int = 10,
        skip_first_plies: int = 6,
        cp_tolerance: int = 0,
        multipv_count: int = 1,
        evaluate_depth: int | None = None,
    ) -> None:
        """Initialize the importer with analysis parameters."""
        self._engine = engine
        self._depth = depth
        self._min_classification = min_classification
        self._max_exercises = max_exercises
        self._skip_first_plies = skip_first_plies
        self._cp_tolerance = cp_tolerance
        self._multipv_count = multipv_count
        self._evaluate_depth = evaluate_depth

    @property
    def source_name(self) -> str:
        """Return the importer source name."""
        return "Game Analysis"

    def fetch(
        self,
        *,
        pgn_path: str | Path | None = None,
        username: str | None = None,
        use_server_evals: bool = False,
        max_games: int = 10,
        color: str | None = None,
        since: int | None = None,
        until: int | None = None,
        rated: bool | None = None,
        perf_type: str | None = None,
    ) -> Iterator[Exercise]:
        """Fetch games and generate exercises from mistakes.

        Args:
            pgn_path: Path to a PGN file (mutually exclusive with username).
            username: Lichess username to fetch games for.
            use_server_evals: Use Lichess server evaluations instead of engine.
            max_games: Maximum number of games to process.
            color: Only generate exercises for this color ("white" or "black").
            since: Only games since this Unix timestamp (ms).
            until: Only games until this Unix timestamp (ms).
            rated: Filter for rated/unrated games.
            perf_type: Filter by speed (blitz, rapid, classical, etc.).

        Yields:
            TacticExercise objects for each qualifying mistake.
        """
        if pgn_path is not None:
            yield from self._fetch_pgn(pgn_path, color=color)
        elif username is not None:
            yield from self._fetch_lichess(
                username,
                use_server_evals=use_server_evals,
                max_games=max_games,
                color=color,
                since=since,
                until=until,
                rated=rated,
                perf_type=perf_type,
            )

    def _make_detector(self, analyzer: PositionAnalyzer) -> MistakeDetector:
        """Create a MistakeDetector with the current config."""
        return MistakeDetector(
            analyzer,
            min_classification=self._min_classification,
            max_exercises=self._max_exercises,
            skip_first_plies=self._skip_first_plies,
            cp_tolerance=self._cp_tolerance,
            multipv_count=self._multipv_count,
            evaluate_depth=self._evaluate_depth,
        )

    @staticmethod
    def _build_pgn_context(game: chess.pgn.Game, color: str | None) -> dict:
        """Build game_context dict from PGN headers.

        Args:
            game: Parsed PGN game.
            color: Player's color ("white" or "black"), if known.

        Returns:
            Dict with game_date, opponent, time_control, player_color.
        """
        headers = game.headers
        context: dict = {}

        date = headers.get("Date", headers.get("UTCDate"))
        if date and date != "????.??.??":
            context["game_date"] = date

        time_control = headers.get("TimeControl")
        if time_control:
            context["time_control"] = time_control

        if color:
            context["player_color"] = color
            opponent_key = "Black" if color == "white" else "White"
            opponent = headers.get(opponent_key)
            if opponent and opponent != "?":
                context["opponent"] = opponent

        return context

    def _fetch_pgn(
        self,
        pgn_path: str | Path,
        *,
        color: str | None = None,
    ) -> Iterator[Exercise]:
        """Analyze games from a PGN file using the local engine."""
        games = parse_pgn_games(pgn_path)

        if not self._engine:
            return

        analyzer = EnginePositionAnalyzer(self._engine, depth=self._depth)
        detector = self._make_detector(analyzer)

        for game in games:
            context = self._build_pgn_context(game, color) or None
            yield from detector.generate_exercises(game, color=color, game_context=context)

    def _fetch_lichess(
        self,
        username: str,
        *,
        use_server_evals: bool = False,
        max_games: int = 10,
        color: str | None = None,
        since: int | None = None,
        until: int | None = None,
        rated: bool | None = None,
        perf_type: str | None = None,
    ) -> Iterator[Exercise]:
        """Fetch and analyze games from Lichess."""
        game_data_iter = get_user_games(
            username,
            max=max_games,
            evals=use_server_evals,
            since=since,
            until=until,
            rated=rated,
            perf_type=perf_type,
        )

        for game_data in game_data_iter:
            game_id = game_data.get("id", "unknown")
            source_url = f"https://lichess.org/{game_id}"

            # Parse the PGN from the JSON response
            pgn_text = game_data.get("pgn", "")
            if not pgn_text:
                continue

            game = chess.pgn.read_game(io.StringIO(pgn_text))
            if game is None:
                continue

            if use_server_evals:
                # Use Lichess server evals
                evals = self._extract_lichess_evals(game_data)
                analyzer = LichessServerAnalyzer(evals)
            elif self._engine:
                analyzer = EnginePositionAnalyzer(self._engine, depth=self._depth)
            else:
                continue

            detector = self._make_detector(analyzer)

            # Build game context from Lichess JSON + PGN
            user_color = color
            if not user_color:
                players = game_data.get("players", {})
                for c in ("white", "black"):
                    user = players.get(c, {}).get("user", {})
                    if user.get("name", "").lower() == username.lower():
                        user_color = c
                        break

            context = self._build_pgn_context(game, user_color)
            # Supplement with Lichess-specific data
            if "clock" in game_data:
                clock = game_data["clock"]
                initial = clock.get("initial", 0)
                increment = clock.get("increment", 0)
                context["time_control"] = f"{initial // 60}+{increment}"
            if "lastMoveAt" in game_data:
                from datetime import datetime

                ts = game_data["lastMoveAt"] / 1000
                dt = datetime.fromtimestamp(ts, tz=UTC)
                context["game_date"] = dt.strftime("%Y-%m-%d")

            yield from detector.generate_exercises(
                game,
                game_id=game_id,
                source_url=source_url,
                color=color,
                game_context=context or None,
            )

    def _extract_lichess_evals(self, game_data: dict) -> list[dict | None]:
        """Extract per-ply eval data from a Lichess game JSON.

        Lichess stores evals in the ``analysis`` field as a list of
        dicts with ``eval`` keys containing ``cp`` or ``mate``.
        """
        analysis = game_data.get("analysis", [])
        evals: list[dict | None] = []

        # Initial position eval (before any moves)
        evals.append({"cp": 0})

        for ply_data in analysis:
            if ply_data is None:
                evals.append(None)
            elif "eval" in ply_data:
                evals.append(ply_data["eval"])
            else:
                evals.append(ply_data)

        return evals
