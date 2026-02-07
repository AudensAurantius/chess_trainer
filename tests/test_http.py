"""Tests for HTTP utilities, Lichess API client, and constants with mocked requests."""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest
from requests import HTTPError, Response

from src.http import _get_headers, _handle_response, _load_ndjson
from src.lichess.api import (
    LichessError,
    get_daily_puzzle,
    get_game,
    get_games,
    get_lichess,
    get_puzzle_by_id,
    get_puzzle_history,
    get_random_puzzle,
    post_lichess,
    random_puzzles,
    write_puzzle_history,
)
from src.lichess.constants import (
    PUZZLE_DIFFICULTIES,
    get_difficulty,
    get_puzzle_themes,
    get_valid_theme,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(
    content: bytes = b"",
    status_code: int = 200,
    content_type: str = "application/json",
    iter_lines_data: list[bytes] | None = None,
) -> MagicMock:
    """Build a mock ``requests.Response`` with common attributes."""
    resp = MagicMock(spec=Response)
    resp.status_code = status_code
    resp.content = content
    resp.headers = {"Content-Type": content_type}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    if iter_lines_data is not None:
        resp.iter_lines = MagicMock(return_value=iter(iter_lines_data))
    return resp


SAMPLE_PUZZLE_JSON = {
    "game": {"id": "abc123", "pgn": "e4 e5 Bc4 Nc6 Qh5"},
    "puzzle": {
        "id": "ABCDE",
        "rating": 1500,
        "plays": 1000,
        "solution": ["g7g6"],
        "themes": ["fork", "short"],
        "initialPly": 5,
    },
}


# ===========================================================================
# src/http.py
# ===========================================================================


class TestGetHeaders:
    """Tests for _get_headers."""

    def test_empty_headers(self):
        assert _get_headers() == {}

    def test_bearer_token(self):
        h = _get_headers(oauth_token="tok123")
        assert h == {"Authorization": "Bearer tok123"}

    def test_content_type(self):
        h = _get_headers(content_type="application/json")
        assert h == {"Content-Type": "application/json"}

    def test_accept(self):
        h = _get_headers(accept="application/x-ndjson")
        assert h == {"Accept": "application/x-ndjson"}

    def test_all_headers(self):
        h = _get_headers(
            oauth_token="tok",
            content_type="application/json",
            accept="text/plain",
        )
        assert h == {
            "Authorization": "Bearer tok",
            "Content-Type": "application/json",
            "Accept": "text/plain",
        }

    def test_falsy_values_omitted(self):
        assert _get_headers(oauth_token=False, content_type="", accept=None) == {}


class TestHandleResponse:
    """Tests for _handle_response."""

    def test_json_content_type(self):
        body = {"key": "value"}
        resp = _mock_response(
            content=json.dumps(body).encode(),
            content_type="application/json",
        )
        result = _handle_response(resp, "http://example.com")
        assert result == body

    def test_ndjson_content_type(self):
        lines = [b'{"a":1}', b'{"b":2}']
        resp = _mock_response(
            content_type="application/x-ndjson",
            iter_lines_data=lines,
        )
        result = _handle_response(resp, "http://example.com")
        # Returns a generator — consume it
        items = list(result)
        assert items == [{"a": 1}, {"b": 2}]

    def test_unknown_content_type_returns_response(self):
        resp = _mock_response(content_type="text/html")
        result = _handle_response(resp, "http://example.com")
        assert result is resp

    def test_http_error_raises(self):
        resp = _mock_response(status_code=404)
        with pytest.raises(HTTPError):
            _handle_response(resp, "http://example.com")


class TestLoadNdjson:
    """Tests for _load_ndjson."""

    def test_parses_ndjson_lines(self):
        resp = MagicMock()
        resp.iter_lines.return_value = [b'{"x":1}', b'{"x":2}', b'[3,4]']
        items = list(_load_ndjson(resp))
        assert items == [{"x": 1}, {"x": 2}, [3, 4]]

    def test_empty_response(self):
        resp = MagicMock()
        resp.iter_lines.return_value = []
        assert list(_load_ndjson(resp)) == []


# ===========================================================================
# src/lichess/api.py
# ===========================================================================


class TestGetLichess:
    """Tests for get_lichess."""

    @patch("src.lichess.api.requests.get")
    def test_simple_get(self, mock_get):
        body = {"result": "ok"}
        mock_get.return_value = _mock_response(
            content=json.dumps(body).encode(),
            content_type="application/json",
        )
        result = get_lichess("puzzle/daily")
        assert result == body
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "puzzle/daily" in args[0]

    @patch("src.lichess.api.requests.get")
    def test_with_query_params(self, mock_get):
        mock_get.return_value = _mock_response(
            content=b'{"ok":true}', content_type="application/json"
        )
        get_lichess("endpoint", query_params={"max": "10"})
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"max": "10"}

    @patch("src.lichess.api.LICHESS_TOKEN", "my-token")
    @patch("src.lichess.api.requests.get")
    def test_auth_includes_token(self, mock_get):
        mock_get.return_value = _mock_response(
            content=b'{}', content_type="application/json"
        )
        get_lichess("endpoint", auth=True)
        _, kwargs = mock_get.call_args
        assert "Bearer my-token" in kwargs["headers"].get("Authorization", "")

    @patch("src.lichess.api.requests.get")
    def test_stream_flag_passed(self, mock_get):
        mock_get.return_value = _mock_response(
            content=b'{}', content_type="application/json"
        )
        get_lichess("endpoint", stream=True)
        _, kwargs = mock_get.call_args
        assert kwargs["stream"] is True

    @patch("src.lichess.api.requests.get")
    def test_accept_header_passed(self, mock_get):
        mock_get.return_value = _mock_response(
            content=b'{}', content_type="application/json"
        )
        get_lichess("endpoint", accept="application/x-ndjson")
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Accept"] == "application/x-ndjson"


class TestPostLichess:
    """Tests for post_lichess."""

    @patch("src.lichess.api.requests.post")
    def test_simple_post(self, mock_post):
        lines = [b'{"id":"g1"}', b'{"id":"g2"}']
        mock_post.return_value = _mock_response(
            content_type="application/x-ndjson", iter_lines_data=lines
        )
        result = post_lichess("games/export/_ids", body="g1,g2")
        items = list(result)
        assert items == [{"id": "g1"}, {"id": "g2"}]
        _, kwargs = mock_post.call_args
        assert kwargs["data"] == "g1,g2"


class TestDailyPuzzle:
    """Tests for get_daily_puzzle."""

    @patch("src.lichess.api.requests.get")
    def test_returns_puzzle(self, mock_get):
        mock_get.return_value = _mock_response(
            content=json.dumps(SAMPLE_PUZZLE_JSON).encode(),
            content_type="application/json",
        )
        result = get_daily_puzzle()
        assert result["puzzle"]["id"] == "ABCDE"


class TestGetPuzzleById:
    """Tests for get_puzzle_by_id."""

    @patch("src.lichess.api.requests.get")
    def test_fetches_puzzle(self, mock_get):
        mock_get.return_value = _mock_response(
            content=json.dumps(SAMPLE_PUZZLE_JSON).encode(),
            content_type="application/json",
        )
        result = get_puzzle_by_id("ABCDE")
        assert result["puzzle"]["id"] == "ABCDE"
        assert "puzzle/ABCDE" in mock_get.call_args[0][0]


class TestGetRandomPuzzle:
    """Tests for get_random_puzzle."""

    @patch("src.lichess.api.get_valid_theme", return_value="fork")
    @patch("src.lichess.api.requests.get")
    def test_with_theme(self, mock_get, _mock_theme):
        mock_get.return_value = _mock_response(
            content=json.dumps(SAMPLE_PUZZLE_JSON).encode(),
            content_type="application/json",
        )
        result = get_random_puzzle(theme="fork")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["angle"] == "fork"

    @patch("src.lichess.api.get_difficulty", return_value="normal")
    @patch("src.lichess.api.requests.get")
    def test_with_difficulty(self, mock_get, _mock_diff):
        mock_get.return_value = _mock_response(
            content=json.dumps(SAMPLE_PUZZLE_JSON).encode(),
            content_type="application/json",
        )
        result = get_random_puzzle(difficulty="normal")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["difficulty"] == "normal"

    @patch("src.lichess.api.get_difficulty", return_value=None)
    def test_invalid_difficulty_raises(self, _mock_diff):
        with pytest.raises(LichessError, match="Invalid puzzle difficulty"):
            get_random_puzzle(difficulty="impossible")

    @patch("src.lichess.api.get_valid_theme", return_value=None)
    def test_invalid_theme_raises(self, _mock_theme):
        with pytest.raises(LichessError, match="Invalid puzzle theme"):
            get_random_puzzle(theme="nonexistent")


class TestRandomPuzzles:
    """Tests for random_puzzles iterator."""

    @patch("src.lichess.api.get_valid_theme", return_value=None)
    @patch("src.lichess.api.get_difficulty", return_value=None)
    @patch("src.lichess.api.requests.get")
    def test_yields_puzzles(self, mock_get, _d, _t):
        mock_get.return_value = _mock_response(
            content=json.dumps(SAMPLE_PUZZLE_JSON).encode(),
            content_type="application/json",
        )
        gen = random_puzzles()
        first = next(gen)
        second = next(gen)
        assert first["puzzle"]["id"] == "ABCDE"
        assert mock_get.call_count == 2

    @patch("src.lichess.api.get_difficulty", return_value=None)
    def test_invalid_difficulty_raises(self, _mock_diff):
        with pytest.raises(LichessError, match="Invalid puzzle difficulty"):
            gen = random_puzzles(difficulties=["impossible"])
            next(gen)

    @patch("src.lichess.api.get_valid_theme", return_value=None)
    def test_invalid_theme_raises(self, _mock_theme):
        with pytest.raises(LichessError, match="Invalid puzzle theme"):
            gen = random_puzzles(themes=["nonexistent"])
            next(gen)

    @patch("src.lichess.api.get_valid_theme", return_value="fork")
    @patch("src.lichess.api.get_difficulty", return_value="normal")
    @patch("src.lichess.api.requests.get")
    def test_with_weighted_filters(self, mock_get, _d, _t):
        mock_get.return_value = _mock_response(
            content=json.dumps(SAMPLE_PUZZLE_JSON).encode(),
            content_type="application/json",
        )
        gen = random_puzzles(
            difficulties={"normal": 2},
            themes={"fork": 3},
        )
        first = next(gen)
        assert first["puzzle"]["id"] == "ABCDE"


class TestGetGames:
    """Tests for get_games / get_game."""

    @patch("src.lichess.api.requests.post")
    def test_get_games_yields(self, mock_post):
        lines = [b'{"id":"g1","pgn":"e4"}', b'{"id":"g2","pgn":"d4"}']
        mock_post.return_value = _mock_response(
            content_type="application/x-ndjson", iter_lines_data=lines
        )
        games = list(get_games("g1", "g2"))
        assert len(games) == 2
        assert games[0]["id"] == "g1"
        _, kwargs = mock_post.call_args
        assert kwargs["data"] == "g1,g2"
        assert kwargs["params"] == {"pgnInJson": "true"}

    @patch("src.lichess.api.requests.post")
    def test_get_game_returns_single(self, mock_post):
        mock_post.return_value = _mock_response(
            content_type="application/x-ndjson",
            iter_lines_data=[b'{"id":"g1","pgn":"e4"}'],
        )
        game = get_game("g1")
        assert game["id"] == "g1"


class TestGetPuzzleHistory:
    """Tests for get_puzzle_history."""

    @patch("src.lichess.api.LICHESS_TOKEN", "tok")
    @patch("src.lichess.api.requests.get")
    def test_yields_history(self, mock_get):
        lines = [b'{"puzzle":{"id":"P1"}}', b'{"puzzle":{"id":"P2"}}']
        mock_get.return_value = _mock_response(
            content_type="application/x-ndjson", iter_lines_data=lines
        )
        items = list(get_puzzle_history(limit=2))
        assert len(items) == 2
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["max"] == "2"
        assert kwargs["stream"] is True


class TestWritePuzzleHistory:
    """Tests for write_puzzle_history."""

    @patch("src.lichess.api.LICHESS_TOKEN", "tok")
    @patch("src.lichess.api.requests.get")
    def test_writes_to_file(self, mock_get, tmp_path):
        lines = [b'{"puzzle":{"id":"P1"}}', b'{"puzzle":{"id":"P2"}}']
        resp = _mock_response(content_type="application/x-ndjson")
        resp.iter_lines = MagicMock(return_value=iter(lines))
        mock_get.return_value = resp

        outfile = tmp_path / "history.ndjson"
        write_puzzle_history(outfile, limit=2)

        content = outfile.read_text()
        assert '{"puzzle":{"id":"P1"}}' in content
        assert '{"puzzle":{"id":"P2"}}' in content


# ===========================================================================
# src/lichess/constants.py
# ===========================================================================


class TestGetDifficulty:
    """Tests for get_difficulty."""

    def test_valid_string(self):
        assert get_difficulty("normal") == "normal"

    def test_case_insensitive(self):
        assert get_difficulty("HARDER") == "harder"

    def test_with_whitespace(self):
        assert get_difficulty("  easiest  ") == "easiest"

    def test_valid_index(self):
        assert get_difficulty(0) == "easiest"
        assert get_difficulty(4) == "hardest"

    def test_invalid_string(self):
        assert get_difficulty("impossible") is None

    def test_out_of_range_index(self):
        assert get_difficulty(-1) is None
        assert get_difficulty(5) is None

    def test_none_returns_none(self):
        assert get_difficulty(None) is None


SAMPLE_THEMES_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<resources>
  <string name="advancedPawn">Advanced pawn</string>
  <string name="advancedPawnDescription">A pushed pawn close to promotion.</string>
  <string name="fork">Fork</string>
  <string name="forkDescription">A piece attacks two enemy pieces at once.</string>
</resources>
"""


class TestGetPuzzleThemes:
    """Tests for get_puzzle_themes with mocked HTTP + filesystem."""

    @patch("src.lichess.constants.PUZZLE_THEMES", {})
    @patch("src.lichess.constants.PUZZLE_THEMES_FILE")
    @patch("src.lichess.constants.requests.get")
    def test_downloads_and_caches(self, mock_get, mock_file):
        mock_file.is_file.return_value = False
        mock_file.open = mock_open()
        mock_get.return_value = _mock_response(
            content=SAMPLE_THEMES_XML,
            content_type="application/xml",
        )

        themes = get_puzzle_themes(refresh=False)
        mock_get.assert_called_once()
        # Should have parsed at least 2 themes (advancedPawn, fork)
        names = [t.name for t in themes]
        assert "fork" in names or "advancedPawn" in names

    @patch("src.lichess.constants.PUZZLE_THEMES", {})
    @patch("src.lichess.constants.PUZZLE_THEMES_FILE")
    @patch("src.lichess.constants.requests.get")
    def test_refresh_forces_download(self, mock_get, mock_file):
        mock_file.is_file.return_value = True
        mock_file.open = mock_open()
        mock_get.return_value = _mock_response(
            content=SAMPLE_THEMES_XML,
            content_type="application/xml",
        )

        themes = get_puzzle_themes(refresh=True)
        mock_get.assert_called_once()

    @patch("src.lichess.constants.PUZZLE_THEMES", {})
    @patch("src.lichess.constants.PUZZLE_THEMES_FILE")
    @patch("src.lichess.constants.requests.get")
    def test_name_filter(self, mock_get, mock_file):
        mock_file.is_file.return_value = False
        mock_file.open = mock_open()
        mock_get.return_value = _mock_response(
            content=SAMPLE_THEMES_XML,
            content_type="application/xml",
        )

        themes = get_puzzle_themes(name_contains="fork")
        names = [t.name for t in themes]
        assert all("fork" in n.lower() for n in names)

    @patch("src.lichess.constants.PUZZLE_THEMES", {})
    @patch("src.lichess.constants.PUZZLE_THEMES_FILE")
    @patch("src.lichess.constants.requests.get")
    def test_desc_filter(self, mock_get, mock_file):
        mock_file.is_file.return_value = False
        mock_file.open = mock_open()
        mock_get.return_value = _mock_response(
            content=SAMPLE_THEMES_XML,
            content_type="application/xml",
        )

        themes = get_puzzle_themes(desc_contains="promotion")
        # advancedPawn has "promotion" in description
        names = [t.name for t in themes]
        assert "advancedPawn" in names


class TestGetValidTheme:
    """Tests for get_valid_theme."""

    @patch("src.lichess.constants.PUZZLE_THEMES", {})
    @patch("src.lichess.constants.PUZZLE_THEMES_FILE")
    @patch("src.lichess.constants.requests.get")
    def test_valid_theme_returns_name(self, mock_get, mock_file):
        mock_file.is_file.return_value = False
        mock_file.open = mock_open()
        mock_get.return_value = _mock_response(
            content=SAMPLE_THEMES_XML,
            content_type="application/xml",
        )

        result = get_valid_theme("Fork")
        assert result == "fork"

    @patch("src.lichess.constants.PUZZLE_THEMES", {})
    @patch("src.lichess.constants.PUZZLE_THEMES_FILE")
    @patch("src.lichess.constants.requests.get")
    def test_invalid_theme_returns_none(self, mock_get, mock_file):
        mock_file.is_file.return_value = False
        mock_file.open = mock_open()
        mock_get.return_value = _mock_response(
            content=SAMPLE_THEMES_XML,
            content_type="application/xml",
        )

        result = get_valid_theme("nonexistent")
        assert result is None


# ===========================================================================
# src/importers/lichess_puzzles.py (fetch modes with mocked API)
# ===========================================================================


MULTI_MOVE_PUZZLE = {
    "game": {"id": "game1", "pgn": "e4 e5"},
    "puzzle": {
        "id": "P100",
        "rating": 1400,
        "plays": 500,
        "solution": ["b1c3", "d7d5", "c3d5"],
        "themes": ["fork"],
        "initialPly": 2,
    },
}


class TestImporterFetchById:
    """Tests for LichessPuzzleImporter.fetch() by ID mode."""

    @patch("src.importers.lichess_puzzles.get_puzzle_by_id")
    def test_fetch_by_ids(self, mock_api):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        mock_api.return_value = MULTI_MOVE_PUZZLE
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch(puzzle_ids=["P100"]))
        assert len(exercises) == 1
        assert exercises[0].id == "lichess:P100"
        mock_api.assert_called_once_with("P100")

    @patch("src.importers.lichess_puzzles.get_puzzle_by_id")
    def test_fetch_by_ids_skips_errors(self, mock_api):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        mock_api.side_effect = [LichessError("not found"), MULTI_MOVE_PUZZLE]
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch(puzzle_ids=["BAD", "P100"]))
        assert len(exercises) == 1

    @patch("src.importers.lichess_puzzles.get_puzzle_by_id")
    def test_fetch_by_id_single(self, mock_api):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        mock_api.return_value = MULTI_MOVE_PUZZLE
        importer = LichessPuzzleImporter()
        result = importer.fetch_by_id("P100")
        assert result is not None
        assert result.id == "lichess:P100"

    @patch("src.importers.lichess_puzzles.get_puzzle_by_id")
    def test_fetch_by_id_returns_none_on_error(self, mock_api):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        mock_api.side_effect = LichessError("not found")
        importer = LichessPuzzleImporter()
        result = importer.fetch_by_id("BAD")
        assert result is None


class TestImporterFetchRandom:
    """Tests for LichessPuzzleImporter.fetch() random mode."""

    @patch("src.importers.lichess_puzzles.random_puzzles")
    def test_fetch_random(self, mock_random):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        mock_random.return_value = iter([MULTI_MOVE_PUZZLE, MULTI_MOVE_PUZZLE])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch(count=2))
        assert len(exercises) == 2

    @patch("src.importers.lichess_puzzles.random_puzzles")
    def test_fetch_random_with_filters(self, mock_random):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        mock_random.return_value = iter([MULTI_MOVE_PUZZLE])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch(count=1, difficulty="normal", themes=["fork"]))
        assert len(exercises) == 1
        _, kwargs = mock_random.call_args
        assert kwargs["difficulties"] == {"normal": 1}
        assert kwargs["themes"] == {"fork": 1}

    @patch("src.importers.lichess_puzzles.random_puzzles")
    def test_fetch_random_skips_bad_data(self, mock_random):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        bad_data = {"game": {}, "puzzle": {}}
        mock_random.return_value = iter([bad_data, MULTI_MOVE_PUZZLE])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch(count=1))
        assert len(exercises) == 1


class TestImporterFetchHistory:
    """Tests for LichessPuzzleImporter.fetch() history mode."""

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_fetch_from_history(self, mock_history):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        mock_history.return_value = iter([MULTI_MOVE_PUZZLE])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch(from_history=True, count=1))
        assert len(exercises) == 1
        mock_history.assert_called_once_with(limit=1)

    @patch("src.importers.lichess_puzzles.get_puzzle_history")
    def test_fetch_from_history_skips_bad_data(self, mock_history):
        from src.importers.lichess_puzzles import LichessPuzzleImporter

        # solution with non-string element causes TypeError in chess.Move.from_uci()
        bad_data = {
            "game": {"id": "g1", "pgn": "e4"},
            "puzzle": {"id": "X", "rating": 0, "plays": 0, "solution": [123], "themes": []},
        }
        mock_history.return_value = iter([bad_data, MULTI_MOVE_PUZZLE])
        importer = LichessPuzzleImporter()
        exercises = list(importer.fetch(from_history=True, count=5))
        assert len(exercises) == 1
