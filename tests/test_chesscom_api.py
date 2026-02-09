"""Tests for Chess.com API client with mocked HTTP requests."""

from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError, Response

from src.chesscom.api import (
    ChessComError,
    get_chesscom,
    get_daily_puzzle,
    get_monthly_games,
    get_player_archives,
    get_random_puzzle,
    get_recent_games,
)
from src.chesscom.constants import CHESSCOM_API, DEFAULT_USER_AGENT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    json_data: dict | list | None = None,
    status_code: int = 200,
) -> MagicMock:
    """Build a mock requests.Response."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


# ---------------------------------------------------------------------------
# get_chesscom
# ---------------------------------------------------------------------------


class TestGetChessCom:
    @patch("src.chesscom.api.requests.get")
    def test_basic_get(self, mock_get):
        mock_get.return_value = _mock_response({"key": "value"})
        result = get_chesscom("test/endpoint")
        assert result == {"key": "value"}
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert f"{CHESSCOM_API}/test/endpoint" == call_args[0][0]

    @patch("src.chesscom.api.requests.get")
    def test_user_agent_header(self, mock_get):
        mock_get.return_value = _mock_response({})
        get_chesscom("test", user_agent="MyApp/1.0")
        headers = mock_get.call_args[1]["headers"]
        assert headers["User-Agent"] == "MyApp/1.0"

    @patch("src.chesscom.api.requests.get")
    def test_default_user_agent(self, mock_get):
        mock_get.return_value = _mock_response({})
        get_chesscom("test")
        headers = mock_get.call_args[1]["headers"]
        assert headers["User-Agent"] == DEFAULT_USER_AGENT

    @patch("src.chesscom.api.requests.get")
    def test_http_error_raises(self, mock_get):
        mock_get.return_value = _mock_response(status_code=404)
        with pytest.raises(ChessComError, match="API request failed"):
            get_chesscom("nonexistent")

    @patch("src.chesscom.api.requests.get")
    def test_429_rate_limit(self, mock_get):
        resp = MagicMock(spec=Response)
        resp.status_code = 429
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {}
        mock_get.return_value = resp
        with pytest.raises(ChessComError, match="Rate limited"):
            get_chesscom("test")

    @patch("src.chesscom.api.requests.get")
    def test_connection_error(self, mock_get):
        from requests.exceptions import ConnectionError

        mock_get.side_effect = ConnectionError("Connection refused")
        with pytest.raises(ChessComError, match="API request failed"):
            get_chesscom("test")

    @patch("src.chesscom.api.requests.get")
    def test_timeout_error(self, mock_get):
        from requests.exceptions import Timeout

        mock_get.side_effect = Timeout("Timed out")
        with pytest.raises(ChessComError, match="API request failed"):
            get_chesscom("test")

    @patch("src.chesscom.api.requests.get")
    def test_timeout_kwarg_passed(self, mock_get):
        mock_get.return_value = _mock_response({})
        get_chesscom("test")
        assert mock_get.call_args[1]["timeout"] == 15


# ---------------------------------------------------------------------------
# get_player_archives
# ---------------------------------------------------------------------------


class TestGetPlayerArchives:
    @patch("src.chesscom.api.requests.get")
    def test_returns_archive_urls(self, mock_get):
        archives = [
            "https://api.chess.com/pub/player/bob/games/2025/01",
            "https://api.chess.com/pub/player/bob/games/2025/02",
        ]
        mock_get.return_value = _mock_response({"archives": archives})
        result = get_player_archives("bob")
        assert result == archives

    @patch("src.chesscom.api.requests.get")
    def test_empty_archives(self, mock_get):
        mock_get.return_value = _mock_response({"archives": []})
        result = get_player_archives("newplayer")
        assert result == []

    @patch("src.chesscom.api.requests.get")
    def test_missing_archives_key(self, mock_get):
        mock_get.return_value = _mock_response({})
        result = get_player_archives("someone")
        assert result == []

    @patch("src.chesscom.api.requests.get")
    def test_custom_user_agent(self, mock_get):
        mock_get.return_value = _mock_response({"archives": []})
        get_player_archives("bob", user_agent="Custom/2.0")
        headers = mock_get.call_args[1]["headers"]
        assert headers["User-Agent"] == "Custom/2.0"


# ---------------------------------------------------------------------------
# get_monthly_games
# ---------------------------------------------------------------------------


class TestGetMonthlyGames:
    SAMPLE_GAME = {
        "url": "https://www.chess.com/game/live/111",
        "pgn": "1. e4 *",
        "time_class": "rapid",
    }

    @patch("src.chesscom.api.requests.get")
    def test_returns_games(self, mock_get):
        mock_get.return_value = _mock_response({"games": [self.SAMPLE_GAME]})
        result = get_monthly_games("bob", 2025, 1)
        assert len(result) == 1
        assert result[0]["url"] == self.SAMPLE_GAME["url"]

    @patch("src.chesscom.api.requests.get")
    def test_endpoint_format(self, mock_get):
        mock_get.return_value = _mock_response({"games": []})
        get_monthly_games("alice", 2025, 3)
        url = mock_get.call_args[0][0]
        assert "player/alice/games/2025/03" in url

    @patch("src.chesscom.api.requests.get")
    def test_empty_month(self, mock_get):
        mock_get.return_value = _mock_response({"games": []})
        result = get_monthly_games("bob", 2025, 6)
        assert result == []

    @patch("src.chesscom.api.requests.get")
    def test_missing_games_key(self, mock_get):
        mock_get.return_value = _mock_response({})
        result = get_monthly_games("bob", 2025, 1)
        assert result == []


# ---------------------------------------------------------------------------
# get_recent_games
# ---------------------------------------------------------------------------


class TestGetRecentGames:
    @patch("src.chesscom.api.time.sleep")
    @patch("src.chesscom.api.requests.get")
    def test_walks_archives_backwards(self, mock_get, mock_sleep):
        game1 = {"url": "https://chess.com/game/1", "pgn": "1. e4 *"}
        game2 = {"url": "https://chess.com/game/2", "pgn": "1. d4 *"}
        archives = [
            "https://api.chess.com/pub/player/bob/games/2025/01",
            "https://api.chess.com/pub/player/bob/games/2025/02",
        ]

        def side_effect(url, **kwargs):
            if "archives" in url:
                return _mock_response({"archives": archives})
            elif "2025/02" in url:
                return _mock_response({"games": [game2]})
            elif "2025/01" in url:
                return _mock_response({"games": [game1]})
            return _mock_response({})

        mock_get.side_effect = side_effect
        games = list(get_recent_games("bob", max_games=10, request_delay=0))
        # Should return newest month first
        assert len(games) == 2
        assert games[0]["url"] == game2["url"]
        assert games[1]["url"] == game1["url"]

    @patch("src.chesscom.api.time.sleep")
    @patch("src.chesscom.api.requests.get")
    def test_max_games_limit(self, mock_get, mock_sleep):
        game1 = {"url": "https://chess.com/game/1"}
        game2 = {"url": "https://chess.com/game/2"}
        game3 = {"url": "https://chess.com/game/3"}
        archives = ["https://api.chess.com/pub/player/bob/games/2025/01"]

        def side_effect(url, **kwargs):
            if "archives" in url:
                return _mock_response({"archives": archives})
            return _mock_response({"games": [game3, game2, game1]})

        mock_get.side_effect = side_effect
        games = list(get_recent_games("bob", max_games=2, request_delay=0))
        assert len(games) == 2

    @patch("src.chesscom.api.time.sleep")
    @patch("src.chesscom.api.requests.get")
    def test_since_boundary(self, mock_get, mock_sleep):
        archives = [
            "https://api.chess.com/pub/player/bob/games/2024/12",
            "https://api.chess.com/pub/player/bob/games/2025/01",
        ]

        def side_effect(url, **kwargs):
            if "archives" in url:
                return _mock_response({"archives": archives})
            elif "2025/01" in url:
                return _mock_response({"games": [{"url": "g1"}]})
            elif "2024/12" in url:
                # Should never reach here
                return _mock_response({"games": [{"url": "g2"}]})
            return _mock_response({})

        mock_get.side_effect = side_effect
        games = list(
            get_recent_games("bob", max_games=10, since_year=2025, since_month=1, request_delay=0)
        )
        assert len(games) == 1
        assert games[0]["url"] == "g1"

    @patch("src.chesscom.api.requests.get")
    def test_empty_archives(self, mock_get):
        mock_get.return_value = _mock_response({"archives": []})
        games = list(get_recent_games("nobody", max_games=10))
        assert games == []

    @patch("src.chesscom.api.time.sleep")
    @patch("src.chesscom.api.requests.get")
    def test_request_delay(self, mock_get, mock_sleep):
        archives = [
            "https://api.chess.com/pub/player/bob/games/2025/01",
            "https://api.chess.com/pub/player/bob/games/2025/02",
        ]

        def side_effect(url, **kwargs):
            if "archives" in url:
                return _mock_response({"archives": archives})
            return _mock_response({"games": [{"url": "g"}]})

        mock_get.side_effect = side_effect
        list(get_recent_games("bob", max_games=10, request_delay=0.5))
        # sleep called between archive pages (not before the first one)
        assert mock_sleep.called

    @patch("src.chesscom.api.time.sleep")
    @patch("src.chesscom.api.requests.get")
    def test_malformed_archive_url_skipped(self, mock_get, mock_sleep):
        archives = ["https://api.chess.com/pub/player/bob/games/badurl"]

        def side_effect(url, **kwargs):
            if "archives" in url:
                return _mock_response({"archives": archives})
            return _mock_response({})

        mock_get.side_effect = side_effect
        games = list(get_recent_games("bob", max_games=10, request_delay=0))
        assert games == []


# ---------------------------------------------------------------------------
# get_daily_puzzle / get_random_puzzle
# ---------------------------------------------------------------------------


class TestPuzzleEndpoints:
    @patch("src.chesscom.api.requests.get")
    def test_get_daily_puzzle(self, mock_get):
        puzzle_data = {
            "title": "Daily",
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        }
        mock_get.return_value = _mock_response(puzzle_data)
        result = get_daily_puzzle()
        assert result["title"] == "Daily"
        url = mock_get.call_args[0][0]
        assert url.endswith("/puzzle")

    @patch("src.chesscom.api.requests.get")
    def test_get_random_puzzle(self, mock_get):
        puzzle_data = {"title": "Random", "fen": "8/8/8/8/8/8/8/8 w - - 0 1"}
        mock_get.return_value = _mock_response(puzzle_data)
        result = get_random_puzzle()
        assert result["title"] == "Random"
        url = mock_get.call_args[0][0]
        assert url.endswith("/puzzle/random")

    @patch("src.chesscom.api.requests.get")
    def test_daily_puzzle_custom_agent(self, mock_get):
        mock_get.return_value = _mock_response({"fen": "test"})
        get_daily_puzzle(user_agent="Test/1.0")
        headers = mock_get.call_args[1]["headers"]
        assert headers["User-Agent"] == "Test/1.0"

    @patch("src.chesscom.api.requests.get")
    def test_random_puzzle_error(self, mock_get):
        mock_get.return_value = _mock_response(status_code=500)
        with pytest.raises(ChessComError):
            get_random_puzzle()
