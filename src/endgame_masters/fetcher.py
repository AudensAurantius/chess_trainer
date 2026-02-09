"""Masters database API client for endgame game discovery."""

from __future__ import annotations

import io
import logging

import chess.pgn
import requests

from .catalog import ENDGAME_TYPES
from .models import MasterGameInfo

logger = logging.getLogger(__name__)

MASTERS_API = "https://explorer.lichess.ovh/masters"


class FetcherError(Exception):
    """Error fetching data from the Lichess Masters API."""


def explore_masters_with_games(
    fen: str,
    top_games: int = 15,
) -> tuple[dict, list[MasterGameInfo]]:
    """Query the Masters explorer and extract top game metadata.

    Args:
        fen: Position in FEN notation.
        top_games: Number of top games to request.

    Returns:
        Tuple of (raw API response, list of MasterGameInfo).

    Raises:
        FetcherError: On network or HTTP errors.
    """
    params: dict = {"fen": fen, "topGames": top_games}
    try:
        resp = requests.get(MASTERS_API, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise FetcherError(f"Masters API request failed: {e}") from e

    games: list[MasterGameInfo] = []
    for g in data.get("topGames", []):
        winner = None
        if g.get("winner") == "white":
            winner = "white"
        elif g.get("winner") == "black":
            winner = "black"

        games.append(
            MasterGameInfo(
                game_id=g.get("id", ""),
                white=g.get("white", {}).get("name", "Unknown"),
                white_rating=g.get("white", {}).get("rating", 0),
                black=g.get("black", {}).get("name", "Unknown"),
                black_rating=g.get("black", {}).get("rating", 0),
                winner=winner,
                year=g.get("year", 0),
                uci=g.get("uci", ""),
            )
        )

    return data, games


def fetch_master_pgn(game_id: str) -> str:
    """Download the PGN for a specific master game.

    Args:
        game_id: The explorer database game ID.

    Returns:
        Raw PGN text.

    Raises:
        FetcherError: On network or HTTP errors.
    """
    url = f"{MASTERS_API}/pgn/{game_id}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        raise FetcherError(f"PGN download failed for {game_id}: {e}") from e


def find_endgame_games(
    fen: str | None = None,
    type_key: str | None = None,
    top_games: int = 15,
) -> list[tuple[MasterGameInfo, chess.pgn.Game]]:
    """Find master games that reach an endgame phase.

    Either ``fen`` or ``type_key`` must be provided. If ``type_key`` is used,
    the seed FENs from the catalog are queried.

    Args:
        fen: A specific FEN to query.
        type_key: An endgame type key from the catalog (e.g. "rook").
        top_games: Number of top games to request per query.

    Returns:
        List of (MasterGameInfo, parsed Game) tuples for games with endgames.

    Raises:
        FetcherError: On network errors.
        KeyError: If type_key is not found in the catalog.
    """
    from .detector import find_endgame_start

    fens: list[str] = []
    if type_key is not None:
        category = ENDGAME_TYPES.get(type_key.lower())
        if category is None:
            valid = ", ".join(sorted(ENDGAME_TYPES.keys()))
            raise KeyError(f"Unknown endgame type '{type_key}'. Valid types: {valid}")
        fens = category.seed_fens
    elif fen is not None:
        fens = [fen]
    else:
        raise FetcherError("Either fen or type_key must be provided")

    # Collect unique games across all seed FENs
    seen_ids: set[str] = set()
    results: list[tuple[MasterGameInfo, chess.pgn.Game]] = []

    for seed_fen in fens:
        _, games = explore_masters_with_games(seed_fen, top_games=top_games)

        for info in games:
            if info.game_id in seen_ids:
                continue
            seen_ids.add(info.game_id)

            try:
                pgn_text = fetch_master_pgn(info.game_id)
            except FetcherError:
                logger.warning("Failed to fetch PGN for %s, skipping", info.game_id)
                continue

            game = chess.pgn.read_game(io.StringIO(pgn_text))
            if game is None:
                continue

            # Only include games that actually reach an endgame
            if find_endgame_start(game) is not None:
                results.append((info, game))

    return results
