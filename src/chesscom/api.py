"""Chess.com public API client.

Provides functions to fetch games, puzzles, and player data from
the Chess.com API. No authentication required — only a User-Agent
header with contact info.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import requests

from .. import get_logger
from .constants import CHESSCOM_API, DEFAULT_USER_AGENT

logger = get_logger(__name__)


class ChessComError(Exception):
    """Raised when a Chess.com API call fails."""


def get_chesscom(
    endpoint: str,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict:
    """Send a GET request to the Chess.com API.

    Args:
        endpoint: API endpoint path (appended to CHESSCOM_API).
        user_agent: User-Agent header value.

    Returns:
        Parsed JSON response as a dict.

    Raises:
        ChessComError: On network or HTTP errors.
    """
    url = f"{CHESSCOM_API}/{endpoint}"
    headers = {"User-Agent": user_agent}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 429:
            raise ChessComError("Rate limited by Chess.com. Please wait and try again.")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise ChessComError(f"Chess.com API request failed: {e}") from e


def get_player_archives(
    username: str,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Get a list of monthly archive URLs for a player.

    Args:
        username: Chess.com username.
        user_agent: User-Agent header value.

    Returns:
        List of archive endpoint URLs (newest last).

    Raises:
        ChessComError: On network or HTTP errors.
    """
    logger.info("Fetching archives for player %s", username)
    data = get_chesscom(f"player/{username}/games/archives", user_agent=user_agent)
    return data.get("archives", [])


def get_monthly_games(
    username: str,
    year: int,
    month: int,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[dict]:
    """Fetch all games for a player in a specific month.

    Args:
        username: Chess.com username.
        year: Four-digit year.
        month: Month number (1-12).
        user_agent: User-Agent header value.

    Returns:
        List of game dicts from the API.

    Raises:
        ChessComError: On network or HTTP errors.
    """
    logger.info("Fetching games for %s: %04d/%02d", username, year, month)
    data = get_chesscom(
        f"player/{username}/games/{year:04d}/{month:02d}",
        user_agent=user_agent,
    )
    return data.get("games", [])


def get_recent_games(
    username: str,
    max_games: int = 10,
    since_year: int | None = None,
    since_month: int | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    request_delay: float = 0.5,
) -> Iterator[dict]:
    """Walk monthly archives backwards to yield recent games.

    Args:
        username: Chess.com username.
        max_games: Maximum number of games to yield.
        since_year: Stop walking archives before this year.
        since_month: Stop walking archives before this month (1-12).
        user_agent: User-Agent header value.
        request_delay: Seconds to sleep between archive fetches.

    Yields:
        Game dicts, newest first.

    Raises:
        ChessComError: On network or HTTP errors.
    """
    archives = get_player_archives(username, user_agent=user_agent)
    if not archives:
        return

    count = 0
    # Walk archives in reverse (newest first)
    for archive_url in reversed(archives):
        # Extract year/month from URL: .../YYYY/MM
        parts = archive_url.rstrip("/").split("/")
        try:
            arch_year = int(parts[-2])
            arch_month = int(parts[-1])
        except (IndexError, ValueError):
            continue

        # Stop if we've gone past the since boundary
        if since_year is not None and since_month is not None:
            if (arch_year, arch_month) < (since_year, since_month):
                break

        if count > 0:
            time.sleep(request_delay)

        games = get_monthly_games(username, arch_year, arch_month, user_agent=user_agent)

        # Yield in reverse (newest game first within the month)
        for game in reversed(games):
            yield game
            count += 1
            if count >= max_games:
                return


def get_daily_puzzle(
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict:
    """Fetch today's Chess.com daily puzzle.

    Args:
        user_agent: User-Agent header value.

    Returns:
        Puzzle data dict.

    Raises:
        ChessComError: On network or HTTP errors.
    """
    logger.info("Fetching Chess.com daily puzzle")
    return get_chesscom("puzzle", user_agent=user_agent)


def get_random_puzzle(
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict:
    """Fetch a random Chess.com puzzle.

    Args:
        user_agent: User-Agent header value.

    Returns:
        Puzzle data dict.

    Raises:
        ChessComError: On network or HTTP errors.
    """
    logger.info("Fetching Chess.com random puzzle")
    return get_chesscom("puzzle/random", user_agent=user_agent)
