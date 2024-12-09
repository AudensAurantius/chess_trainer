import requests
from random import choices
from typing import Iterable
from .constants import LICHESS_TOKEN, LICHESS_API, get_difficulty, get_valid_theme
from .. import get_logger
from ..http import _handle_response, _get_headers


logger = get_logger(__name__)


class LichessError(Exception):
    pass


def get_lichess(
    endpoint,
    query_params={},
    auth: bool = False,
    accept: str | None = None,
):
    url = f"{LICHESS_API}/{endpoint}"
    headers = _get_headers(oauth_token=auth and LICHESS_TOKEN, accept=accept)
    response = requests.get(url, params=query_params, headers=headers)
    response.raise_for_status()
    return _handle_response(response, url)


def post_lichess(
    endpoint,
    body: str = "",
    query_params={},
    auth: bool = False,
    accept: str | None = "application/x-ndjson",
):
    url = f"{LICHESS_API}/{endpoint}"
    headers = _get_headers(oauth_token=auth and LICHESS_TOKEN, accept=accept)
    response = requests.post(url, params=query_params, headers=headers, data=body)
    response.raise_for_status()
    return _handle_response(response, url)


def get_daily_puzzle():
    logger.info("Getting daily puzzle")
    return get_lichess("puzzle/daily")


def get_puzzle_by_id(puzzle_id: str):
    logger.info("Getting puzzle ID %s", puzzle_id)
    return get_lichess(f"puzzle/{puzzle_id}")


def get_random_puzzle(
    difficulty: str | int | None = None,
    theme: str | None = None,
    filter_seen: bool = True,
):
    params = {}
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
    difficulties: Iterable[str | int] | dict[str | int, int | float] = {},
    themes: Iterable[str] | dict[str, int | float] = {},
    filter_seen: bool = True,
):
    diff_choices, diff_weights = [], []
    theme_choices, theme_weights = [], []
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
        params = {}
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


def get_puzzle_history(limit: int = 100): ...


def get_games(*game_ids: str):
    logger.info("Getting game IDs %s", game_ids)
    return post_lichess(
        "games/export/_ids", body=",".join(game_ids), query_params={"pgnInJson": True}
    )


def get_game(game_id: str):
    return list(get_games(game_id))[0]
