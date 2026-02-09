"""Lichess Explorer API client with persistent caching."""

from __future__ import annotations

from typing import TYPE_CHECKING

import chess
import requests

from .models import ExplorerFilter, ExplorerResult, ExplorerSource, MoveStats, RepertoireInfo

if TYPE_CHECKING:
    from ..storage.opening_store import OpeningStore

EXPLORER_API = "https://explorer.lichess.ovh"


class ExplorerError(Exception):
    """Error communicating with the Lichess Explorer API."""


# ── Raw API functions ─────────────────────────────────────────────────────────


def explore_lichess(
    fen: str,
    speeds: list[str] | None = None,
    ratings: list[int] | None = None,
) -> dict:
    """Query the Lichess database for a position.

    Args:
        fen: Position in FEN notation.
        speeds: Filter by speed (e.g. ["blitz", "rapid", "classical"]).
        ratings: Filter by rating brackets (e.g. [1600, 1800, 2000]).

    Returns:
        Raw JSON response from the API.

    Raises:
        ExplorerError: If the API request fails.
    """
    params: dict = {"fen": fen}
    if speeds:
        params["speeds"] = ",".join(speeds)
    if ratings:
        params["ratings"] = ",".join(str(r) for r in ratings)

    return _request(f"{EXPLORER_API}/lichess", params)


def explore_masters(fen: str) -> dict:
    """Query the masters database for a position.

    Args:
        fen: Position in FEN notation.

    Returns:
        Raw JSON response from the API.

    Raises:
        ExplorerError: If the API request fails.
    """
    return _request(f"{EXPLORER_API}/masters", {"fen": fen})


def explore_player(
    fen: str,
    player: str,
    color: str = "white",
    speeds: list[str] | None = None,
) -> dict:
    """Query a specific player's games for a position.

    Args:
        fen: Position in FEN notation.
        player: Lichess username.
        color: "white" or "black".
        speeds: Filter by speed.

    Returns:
        Raw JSON response from the API.

    Raises:
        ExplorerError: If the API request fails.
    """
    params: dict = {"fen": fen, "player": player, "color": color}
    if speeds:
        params["speeds"] = ",".join(speeds)

    return _request(f"{EXPLORER_API}/player", params)


def _request(url: str, params: dict) -> dict:
    """Make a GET request to the Explorer API.

    Raises:
        ExplorerError: On network or HTTP errors.
    """
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise ExplorerError(f"Explorer API request failed: {e}") from e


# ── Parsers ───────────────────────────────────────────────────────────────────


def _parse_move_stats(data: dict) -> MoveStats:
    """Parse a single move entry from the API response."""
    return MoveStats(
        uci=data.get("uci", ""),
        san=data.get("san", ""),
        white_wins=data.get("white", 0),
        draws=data.get("draws", 0),
        black_wins=data.get("black", 0),
        average_rating=data.get("averageRating", 0),
    )


def _parse_explorer_response(data: dict, fen: str, source: ExplorerSource) -> ExplorerResult:
    """Parse a full explorer API response into an ExplorerResult."""
    moves = [_parse_move_stats(m) for m in data.get("moves", [])]

    opening = data.get("opening", {}) or {}

    return ExplorerResult(
        fen=fen,
        white_wins=data.get("white", 0),
        draws=data.get("draws", 0),
        black_wins=data.get("black", 0),
        moves=moves,
        opening_eco=opening.get("eco", ""),
        opening_name=opening.get("name", ""),
        source=source,
    )


# ── Filtering ─────────────────────────────────────────────────────────────────


def _normalize_fen(fen: str) -> str:
    """Normalize a FEN to its first 4 fields (position, turn, castling, en passant).

    This avoids false negatives from halfmove/fullmove counter differences.
    """
    parts = fen.split()
    return " ".join(parts[:4])


def filter_moves(result: ExplorerResult, filt: ExplorerFilter) -> ExplorerResult:
    """Apply client-side filters to an ExplorerResult.

    Filters compose with AND logic. Position-level stats are preserved unchanged.
    Returns a new ExplorerResult with filtered moves list.

    Args:
        result: The explorer result to filter.
        filt: The filter to apply.

    Returns:
        A new ExplorerResult with only moves passing all thresholds.
    """
    moves = result.moves

    if filt.min_games is not None:
        moves = [m for m in moves if m.total_games >= filt.min_games]
    if filt.min_white_pct is not None:
        moves = [m for m in moves if m.white_pct >= filt.min_white_pct]
    if filt.max_white_pct is not None:
        moves = [m for m in moves if m.white_pct <= filt.max_white_pct]
    if filt.min_draw_pct is not None:
        moves = [m for m in moves if m.draw_pct >= filt.min_draw_pct]
    if filt.max_draw_pct is not None:
        moves = [m for m in moves if m.draw_pct <= filt.max_draw_pct]
    if filt.min_black_pct is not None:
        moves = [m for m in moves if m.black_pct >= filt.min_black_pct]
    if filt.max_black_pct is not None:
        moves = [m for m in moves if m.black_pct <= filt.max_black_pct]

    return ExplorerResult(
        fen=result.fen,
        white_wins=result.white_wins,
        draws=result.draws,
        black_wins=result.black_wins,
        moves=moves,
        opening_eco=result.opening_eco,
        opening_name=result.opening_name,
        source=result.source,
    )


def get_repertoire_moves(
    fen: str,
    explorer_moves: list[MoveStats],
    store: OpeningStore,
) -> RepertoireInfo:
    """Cross-reference explorer moves with the personal opening book.

    Walks each book line on a board. At each position whose normalized FEN
    matches the target, the next move in the line is a "book move".

    Args:
        fen: Target position FEN.
        explorer_moves: Moves from the explorer result.
        store: The opening store containing book lines.

    Returns:
        RepertoireInfo with the set of book moves and coverage.
    """
    target_norm = _normalize_fen(fen)
    book_ucis: set[str] = set()

    for line in store.list_lines():
        board = chess.Board()
        for i, uci in enumerate(line.moves):
            current_norm = _normalize_fen(board.fen())
            if current_norm == target_norm and i < len(line.moves):
                book_ucis.add(uci)
            board.push(chess.Move.from_uci(uci))

    explorer_ucis = {m.uci for m in explorer_moves}
    overlap = book_ucis & explorer_ucis
    total = len(explorer_moves)
    coverage = len(overlap) / total if total > 0 else 0.0

    return RepertoireInfo(
        book_moves=frozenset(book_ucis),
        total_moves=total,
        coverage=coverage,
    )


# ── Cached client ─────────────────────────────────────────────────────────────


class OpeningExplorer:
    """Cached opening explorer that persists results in the database."""

    def __init__(  # noqa: D107
        self,
        store: OpeningStore,
        cache_ttl_hours: int = 168,
        min_games: int = 5,
    ):
        self.store = store
        self.cache_ttl_hours = cache_ttl_hours
        self.min_games = min_games

    def explore(
        self,
        fen: str,
        source: ExplorerSource = ExplorerSource.LICHESS,
        *,
        player: str | None = None,
        color: str | None = None,
        speeds: list[str] | None = None,
        ratings: list[int] | None = None,
        use_cache: bool = True,
        explorer_filter: ExplorerFilter | None = None,
    ) -> ExplorerResult:
        """Explore a position, using cache when available.

        Args:
            fen: Position in FEN notation.
            source: Which explorer database to query.
            player: Lichess username (required for PLAYER source).
            color: Side to query for PLAYER source.
            speeds: Speed filter (overridden by explorer_filter.speeds if set).
            ratings: Rating bracket filter (overridden by explorer_filter.ratings if set).
            use_cache: Whether to check the cache first.
            explorer_filter: Optional advanced filter with server-side and client-side thresholds.

        Returns:
            Parsed explorer result with move statistics.

        Raises:
            ExplorerError: If the API request fails.
        """
        # Filter's server-side params take precedence over direct args
        if explorer_filter is not None:
            if explorer_filter.speeds is not None:
                speeds = list(explorer_filter.speeds)
            if explorer_filter.ratings is not None:
                ratings = list(explorer_filter.ratings)

        # Check cache
        if use_cache:
            cached = self.store.cache_get(fen, source, self.cache_ttl_hours)
            if cached is not None:
                result = _parse_explorer_response(cached, fen, source)
                result = self._filter_moves(result)
                if explorer_filter is not None:
                    result = filter_moves(result, explorer_filter)
                return result

        # Call the appropriate API endpoint
        if source == ExplorerSource.MASTERS:
            raw = explore_masters(fen)
        elif source == ExplorerSource.PLAYER:
            if not player:
                raise ExplorerError("Player username required for player explorer")
            raw = explore_player(fen, player, color=color or "white", speeds=speeds)
        else:
            raw = explore_lichess(fen, speeds=speeds, ratings=ratings)

        # Store in cache
        self.store.cache_put(fen, source, raw)

        # Parse and filter
        result = _parse_explorer_response(raw, fen, source)
        result = self._filter_moves(result)
        if explorer_filter is not None:
            result = filter_moves(result, explorer_filter)
        return result

    def _filter_moves(self, result: ExplorerResult) -> ExplorerResult:
        """Remove moves with fewer games than min_games."""
        filtered = [m for m in result.moves if m.total_games >= self.min_games]
        return ExplorerResult(
            fen=result.fen,
            white_wins=result.white_wins,
            draws=result.draws,
            black_wins=result.black_wins,
            moves=filtered,
            opening_eco=result.opening_eco,
            opening_name=result.opening_name,
            source=result.source,
        )
