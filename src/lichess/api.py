"""Lichess API client for puzzles, games, and user history."""

from collections.abc import Iterator
from pathlib import Path
from random import choices

import requests
from rich.progress import Progress

from .. import get_logger
from ..http import JsonGenerator, JsonObject, _get_headers, _handle_response
from .constants import LICHESS_API, LICHESS_TOKEN, get_difficulty, get_valid_theme

logger = get_logger(__name__)


class LichessError(Exception):
    """Raised when a Lichess API call fails or receives invalid parameters."""


def get_lichess(
    endpoint: str,
    query_params: dict[str, str] | None = None,
    auth: bool = False,
    accept: str | None = None,
    stream: bool = False,
) -> JsonObject | JsonGenerator | requests.Response:
    """Send a GET request to the Lichess API.

    Args:
        endpoint: API endpoint path (appended to ``LICHESS_API``).
        query_params: URL query parameters.
        auth: Whether to include the OAuth token.
        accept: Accept header value.
        stream: Whether to stream the response.

    Returns:
        Parsed JSON, an NDJSON generator, or the raw response.
    """
    url = f"{LICHESS_API}/{endpoint}"
    headers = _get_headers(oauth_token=auth and LICHESS_TOKEN, accept=accept)
    response = requests.get(url, params=query_params or {}, headers=headers, stream=stream)
    return _handle_response(response, url)


def post_lichess(
    endpoint: str,
    body: str = "",
    query_params: dict[str, str] | None = None,
    auth: bool = False,
    accept: str | None = "application/x-ndjson",
) -> JsonObject | JsonGenerator | requests.Response:
    """Send a POST request to the Lichess API.

    Args:
        endpoint: API endpoint path.
        body: Request body string.
        query_params: URL query parameters.
        auth: Whether to include the OAuth token.
        accept: Accept header value.

    Returns:
        Parsed JSON, an NDJSON generator, or the raw response.
    """
    url = f"{LICHESS_API}/{endpoint}"
    headers = _get_headers(oauth_token=auth and LICHESS_TOKEN, accept=accept)
    response = requests.post(url, params=query_params or {}, headers=headers, data=body)
    return _handle_response(response, url)


def get_daily_puzzle() -> JsonObject:
    """Fetch today's Lichess daily puzzle.

    Returns:
        Puzzle data as a JSON object.
    """
    logger.info("Getting daily puzzle")
    return get_lichess("puzzle/daily")


def get_puzzle_by_id(puzzle_id: str) -> JsonObject:
    """Fetch a specific puzzle by ID.

    Args:
        puzzle_id: The Lichess puzzle identifier.

    Returns:
        Puzzle data as a JSON object.
    """
    logger.info("Getting puzzle ID %s", puzzle_id)
    return get_lichess(f"puzzle/{puzzle_id}")


def get_random_puzzle(
    difficulty: str | int | None = None,
    theme: str | None = None,
    filter_seen: bool = True,
) -> JsonObject:
    """Fetch a random puzzle with optional filters.

    Args:
        difficulty: Difficulty level name or index.
        theme: Tactical theme name.
        filter_seen: Exclude previously seen puzzles (requires auth).

    Returns:
        Puzzle data as a JSON object.

    Raises:
        LichessError: If difficulty or theme is invalid.
    """
    params: dict[str, str] = {}
    if difficulty is not None:
        params["difficulty"] = get_difficulty(difficulty)
        if params["difficulty"] is None:
            raise LichessError(f"Invalid puzzle difficulty {difficulty!r}")
    if theme is not None:
        params["angle"] = get_valid_theme(theme)
        if params["angle"] is None:
            raise LichessError(f"Invalid puzzle theme {theme!r}")
    logger.info(
        "Getting random puzzle: difficulty %s, theme %s, filter_seen %s",
        params.get("difficulty"),
        params.get("theme"),
        filter_seen,
    )
    return get_lichess("puzzle/next", query_params=params, auth=filter_seen)


def random_puzzles(
    difficulties: dict[str | int, int | float] | list[str | int] | None = None,
    themes: dict[str, int | float] | list[str] | None = None,
    filter_seen: bool = True,
) -> Iterator[JsonObject]:
    """Generate an infinite stream of random puzzles with weighted filters.

    Args:
        difficulties: Difficulty values or weighted dict of difficulties.
        themes: Theme names or weighted dict of themes.
        filter_seen: Exclude previously seen puzzles.

    Yields:
        Puzzle data JSON objects.

    Raises:
        LichessError: If any difficulty or theme is invalid.
    """
    diff_choices: list[str | None] = []
    diff_weights: list[int | float] = []
    theme_choices: list[str | None] = []
    theme_weights: list[int | float] = []

    if difficulties:
        if not isinstance(difficulties, dict):
            difficulties = {d: 1 for d in difficulties}
        while difficulties:
            diff, weight = difficulties.popitem()
            if (d := get_difficulty(diff)) is not None or diff is None:
                diff_choices.append(d)
                diff_weights.append(weight)
            else:
                raise LichessError(f"Invalid puzzle difficulty {diff!r}")
    else:
        diff_choices.append(None)
        diff_weights.append(1)
    if themes:
        if not isinstance(themes, dict):
            themes = {t: 1 for t in themes}
        while themes:
            theme, weight = themes.popitem()
            if (t := get_valid_theme(theme)) is not None or theme is None:
                theme_choices.append(t)
                theme_weights.append(weight)
            else:
                raise LichessError(f"Invalid puzzle theme {theme!r}")
    else:
        theme_choices.append(None)
        theme_weights.append(1)

    while True:
        params: dict[str, str] = {}
        diff, theme = (
            choices(diff_choices, weights=diff_weights, k=1)[0],
            choices(theme_choices, weights=theme_weights, k=1)[0],
        )
        if diff is not None:
            params["difficulty"] = diff
        if theme is not None:
            params["angle"] = theme
        logger.info(
            "Getting random puzzle: difficulty %s, theme %s, filter_seen %s",
            params.get("difficulty"),
            params.get("theme"),
            filter_seen,
        )
        yield get_lichess("puzzle/next", query_params=params, auth=filter_seen)


def get_games(*game_ids: str) -> Iterator[JsonObject]:
    """Export one or more games by ID.

    Args:
        *game_ids: One or more Lichess game IDs.

    Yields:
        Game data JSON objects.
    """
    logger.info("Getting game IDs %s", game_ids)
    yield from post_lichess(
        "games/export/_ids", body=",".join(game_ids), query_params={"pgnInJson": "true"}
    )


def get_game(game_id: str) -> JsonObject:
    """Export a single game by ID.

    Args:
        game_id: The Lichess game identifier.

    Returns:
        Game data as a JSON object.
    """
    return list(get_games(game_id))[0]


def get_puzzle_history(limit: int = 100) -> Iterator[JsonObject]:
    """Fetch the authenticated user's puzzle history.

    Args:
        limit: Maximum number of puzzles to retrieve.

    Yields:
        Puzzle activity JSON objects.
    """
    logger.info("Getting puzzle history, limit %s puzzles", limit)
    yield from get_lichess(
        "puzzle/activity", query_params={"max": str(limit)}, stream=True, auth=True
    )


def get_user_games(
    username: str,
    *,
    max: int = 10,
    evals: bool = False,
    opening: bool = True,
    pgn_in_json: bool = True,
    since: int | None = None,
    until: int | None = None,
    rated: bool | None = None,
    perf_type: str | None = None,
) -> Iterator[JsonObject]:
    """Fetch games for a Lichess user.

    Args:
        username: Lichess username.
        max: Maximum number of games to retrieve.
        evals: Include per-ply engine evaluations.
        opening: Include opening information.
        pgn_in_json: Include PGN in the JSON response.
        since: Only games played since this Unix timestamp (ms).
        until: Only games played until this Unix timestamp (ms).
        rated: Filter for rated/unrated games.
        perf_type: Filter by speed (blitz, rapid, classical, etc.).

    Yields:
        Game data JSON objects.
    """
    logger.info("Getting games for user %s (max=%d, evals=%s)", username, max, evals)
    params: dict[str, str] = {
        "max": str(max),
        "evals": str(evals).lower(),
        "opening": str(opening).lower(),
        "pgnInJson": str(pgn_in_json).lower(),
    }
    if since is not None:
        params["since"] = str(since)
    if until is not None:
        params["until"] = str(until)
    if rated is not None:
        params["rated"] = str(rated).lower()
    if perf_type is not None:
        params["perfType"] = perf_type

    yield from get_lichess(
        f"games/user/{username}",
        query_params=params,
        accept="application/x-ndjson",
        stream=True,
    )


def write_puzzle_history(filename: str | Path, limit: int = 100) -> None:
    """Download puzzle history to a file with a progress bar.

    Args:
        filename: Destination file path.
        limit: Maximum number of puzzles to download.
    """
    logger.info("Writing puzzle history to file %s: limit %s puzzles", filename, limit)
    response = requests.get(
        f"{LICHESS_API}/puzzle/activity",
        params={"max": limit},
        headers=_get_headers(oauth_token=LICHESS_TOKEN),
        stream=True,
    )
    response.raise_for_status()
    with Progress() as progress:
        download_task = progress.add_task("Downloading puzzle history...", total=limit)
        with Path(filename).open("w") as stream:
            for line in response.iter_lines():
                stream.write(f"{line.decode()}\n")
                progress.update(download_task, advance=1)
