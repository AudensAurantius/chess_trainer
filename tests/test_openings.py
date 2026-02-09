"""Tests for the opening explorer and personal opening book."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import chess
import pytest
from typer.testing import CliRunner

from src.cli.app import app
from src.config import AppConfig, _apply_env, _apply_toml
from src.exercises.openings import OpeningExercise
from src.openings.book import (
    BookError,
    create_line,
    generate_exercises,
    get_alternatives_from_explorer,
    parse_pgn_file,
    parse_pgn_to_uci,
)
from src.openings.explorer import (
    ExplorerError,
    OpeningExplorer,
    _parse_explorer_response,
    _parse_move_stats,
    explore_lichess,
    explore_masters,
    explore_player,
)
from src.openings.models import (
    BookColor,
    ExplorerResult,
    ExplorerSource,
    MoveStats,
    OpeningLine,
)
from src.storage import Repository

runner = CliRunner()

# Common FEN for Sicilian Najdorf after 1.e4 c5 2.Nf3 d6 3.d4 cxd4 4.Nxd4 Nf6 5.Nc3 a6
NAJDORF_FEN = "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 6"

# Common explorer response fixture
EXPLORER_RESPONSE = {
    "white": 50000,
    "draws": 30000,
    "black": 20000,
    "moves": [
        {
            "uci": "e2e4",
            "san": "e4",
            "white": 30000,
            "draws": 15000,
            "black": 10000,
            "averageRating": 2100,
        },
        {
            "uci": "d2d4",
            "san": "d4",
            "white": 15000,
            "draws": 10000,
            "black": 8000,
            "averageRating": 2050,
        },
        {
            "uci": "c2c4",
            "san": "c4",
            "white": 5000,
            "draws": 5000,
            "black": 2000,
            "averageRating": 2000,
        },
    ],
    "opening": {
        "eco": "A00",
        "name": "Starting Position",
    },
}


@pytest.fixture
def repo(tmp_path):
    """In-memory repository for tests."""
    with Repository() as r:
        yield r


# ── Models ────────────────────────────────────────────────────────────────────


class TestBookColor:
    def test_values(self):
        assert BookColor.WHITE.value == "white"
        assert BookColor.BLACK.value == "black"

    def test_from_string(self):
        assert BookColor("white") == BookColor.WHITE
        assert BookColor("black") == BookColor.BLACK


class TestExplorerSource:
    def test_values(self):
        assert ExplorerSource.LICHESS.value == "lichess"
        assert ExplorerSource.MASTERS.value == "masters"
        assert ExplorerSource.PLAYER.value == "player"


class TestMoveStats:
    def test_total_games(self):
        m = MoveStats(uci="e2e4", san="e4", white_wins=100, draws=50, black_wins=30)
        assert m.total_games == 180

    def test_percentages(self):
        m = MoveStats(uci="e2e4", san="e4", white_wins=100, draws=50, black_wins=50)
        assert m.white_pct == 50.0
        assert m.draw_pct == 25.0
        assert m.black_pct == 25.0

    def test_zero_games_percentages(self):
        m = MoveStats(uci="e2e4", san="e4", white_wins=0, draws=0, black_wins=0)
        assert m.white_pct == 0.0
        assert m.draw_pct == 0.0
        assert m.black_pct == 0.0

    def test_average_rating_default(self):
        m = MoveStats(uci="e2e4", san="e4", white_wins=10, draws=5, black_wins=5)
        assert m.average_rating == 0

    def test_frozen(self):
        m = MoveStats(uci="e2e4", san="e4", white_wins=10, draws=5, black_wins=5)
        with pytest.raises(AttributeError):
            m.uci = "d2d4"


class TestExplorerResult:
    def test_total_games(self):
        r = ExplorerResult(
            fen=chess.STARTING_FEN,
            white_wins=100,
            draws=50,
            black_wins=50,
            moves=[],
        )
        assert r.total_games == 200

    def test_defaults(self):
        r = ExplorerResult(
            fen=chess.STARTING_FEN,
            white_wins=0,
            draws=0,
            black_wins=0,
            moves=[],
        )
        assert r.opening_eco == ""
        assert r.opening_name == ""
        assert r.source == ExplorerSource.LICHESS


class TestOpeningLine:
    def test_generate_id(self):
        id1 = OpeningLine.generate_id()
        id2 = OpeningLine.generate_id()
        assert id1.startswith("book:")
        assert id2.startswith("book:")
        assert id1 != id2
        assert len(id1) == 17  # "book:" + 12 hex chars

    def test_fen_at_end(self):
        line = OpeningLine(
            id="book:test1",
            color=BookColor.WHITE,
            moves=["e2e4", "e7e5"],
        )
        board = chess.Board()
        board.push_uci("e2e4")
        board.push_uci("e7e5")
        assert line.fen_at_end == board.fen()

    def test_san_line(self):
        line = OpeningLine(
            id="book:test1",
            color=BookColor.WHITE,
            moves=["e2e4", "e7e5", "g1f3"],
        )
        assert "1. e4" in line.san_line
        assert "e5" in line.san_line
        assert "2. Nf3" in line.san_line

    def test_san_line_black_start(self):
        # A line where moves start from a position where black moves first
        # (but our lines always start from starting position, so black's first
        # move is the second move in the list)
        line = OpeningLine(
            id="book:test1",
            color=BookColor.BLACK,
            moves=["e2e4"],
        )
        assert "1. e4" in line.san_line

    def test_to_dict_from_dict_roundtrip(self):
        now = datetime.now()
        line = OpeningLine(
            id="book:abcdef123456",
            color=BookColor.WHITE,
            eco_code="B90",
            name="Sicilian Najdorf",
            variation="English Attack",
            moves=["e2e4", "c7c5", "g1f3", "d7d6"],
            annotations={0: "Best by test", 2: "Main line"},
            created_at=now,
            updated_at=now,
        )
        data = line.to_dict()
        restored = OpeningLine.from_dict(data)

        assert restored.id == line.id
        assert restored.color == line.color
        assert restored.eco_code == line.eco_code
        assert restored.name == line.name
        assert restored.variation == line.variation
        assert restored.moves == line.moves
        assert restored.annotations == line.annotations

    def test_from_dict_minimal(self):
        line = OpeningLine.from_dict(
            {
                "id": "book:min",
                "color": "white",
            }
        )
        assert line.id == "book:min"
        assert line.color == BookColor.WHITE
        assert line.moves == []
        assert line.annotations == {}

    def test_from_dict_string_annotation_keys(self):
        line = OpeningLine.from_dict(
            {
                "id": "book:ann",
                "color": "black",
                "annotations": {"0": "note", "3": "another"},
            }
        )
        assert line.annotations == {0: "note", 3: "another"}


# ── Explorer API ──────────────────────────────────────────────────────────────


class TestParseMovestats:
    def test_parse_full(self):
        data = {
            "uci": "e2e4",
            "san": "e4",
            "white": 100,
            "draws": 50,
            "black": 30,
            "averageRating": 2100,
        }
        m = _parse_move_stats(data)
        assert m.uci == "e2e4"
        assert m.san == "e4"
        assert m.white_wins == 100
        assert m.draws == 50
        assert m.black_wins == 30
        assert m.average_rating == 2100

    def test_parse_missing_fields(self):
        m = _parse_move_stats({})
        assert m.uci == ""
        assert m.san == ""
        assert m.total_games == 0


class TestParseExplorerResponse:
    def test_parse_full_response(self):
        result = _parse_explorer_response(
            EXPLORER_RESPONSE, chess.STARTING_FEN, ExplorerSource.LICHESS
        )
        assert result.total_games == 100000
        assert len(result.moves) == 3
        assert result.opening_eco == "A00"
        assert result.opening_name == "Starting Position"
        assert result.source == ExplorerSource.LICHESS

    def test_parse_empty_response(self):
        result = _parse_explorer_response(
            {"white": 0, "draws": 0, "black": 0, "moves": []},
            chess.STARTING_FEN,
            ExplorerSource.MASTERS,
        )
        assert result.total_games == 0
        assert result.moves == []
        assert result.source == ExplorerSource.MASTERS

    def test_parse_no_opening(self):
        data = {"white": 10, "draws": 5, "black": 5, "moves": []}
        result = _parse_explorer_response(data, "some_fen", ExplorerSource.LICHESS)
        assert result.opening_eco == ""
        assert result.opening_name == ""


class TestExploreLichess:
    @patch("src.openings.explorer.requests.get")
    def test_basic_call(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=EXPLORER_RESPONSE),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = explore_lichess(chess.STARTING_FEN)
        assert result["white"] == 50000
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "lichess" in args[0]
        assert kwargs["params"]["fen"] == chess.STARTING_FEN

    @patch("src.openings.explorer.requests.get")
    def test_with_filters(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=EXPLORER_RESPONSE),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        explore_lichess(chess.STARTING_FEN, speeds=["blitz", "rapid"], ratings=[1600, 2000])
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["speeds"] == "blitz,rapid"
        assert kwargs["params"]["ratings"] == "1600,2000"

    @patch("src.openings.explorer.requests.get")
    def test_network_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.ConnectionError("timeout")
        with pytest.raises(ExplorerError, match="request failed"):
            explore_lichess(chess.STARTING_FEN)


class TestExploreMasters:
    @patch("src.openings.explorer.requests.get")
    def test_basic_call(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=EXPLORER_RESPONSE),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = explore_masters(chess.STARTING_FEN)
        assert "moves" in result
        args, kwargs = mock_get.call_args
        assert "masters" in args[0]


class TestExplorePlayer:
    @patch("src.openings.explorer.requests.get")
    def test_basic_call(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=EXPLORER_RESPONSE),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = explore_player(chess.STARTING_FEN, "DrNykterstein", color="white")
        assert "moves" in result
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["player"] == "DrNykterstein"
        assert kwargs["params"]["color"] == "white"

    @patch("src.openings.explorer.requests.get")
    def test_with_speeds(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=EXPLORER_RESPONSE),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        explore_player(chess.STARTING_FEN, "user1", speeds=["rapid"])
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["speeds"] == "rapid"


class TestOpeningExplorer:
    def test_cache_hit(self, repo):
        # Pre-populate cache
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, EXPLORER_RESPONSE)
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=1)

        result = explorer.explore(chess.STARTING_FEN)
        assert result.total_games == 100000
        assert len(result.moves) == 3

    @patch("src.openings.explorer.explore_lichess")
    def test_cache_miss_fetches(self, mock_api, repo):
        mock_api.return_value = EXPLORER_RESPONSE
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=1)

        result = explorer.explore(chess.STARTING_FEN)
        assert result.total_games == 100000
        mock_api.assert_called_once()

    @patch("src.openings.explorer.explore_lichess")
    def test_cache_stores_result(self, mock_api, repo):
        mock_api.return_value = EXPLORER_RESPONSE
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=1)

        explorer.explore(chess.STARTING_FEN)

        # Should be in cache now
        cached = repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.LICHESS, 168)
        assert cached is not None
        assert cached["white"] == 50000

    @patch("src.openings.explorer.explore_lichess")
    def test_bypass_cache(self, mock_api, repo):
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, EXPLORER_RESPONSE)
        mock_api.return_value = EXPLORER_RESPONSE
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=1)

        explorer.explore(chess.STARTING_FEN, use_cache=False)
        mock_api.assert_called_once()

    @patch("src.openings.explorer.explore_masters")
    def test_masters_source(self, mock_api, repo):
        mock_api.return_value = EXPLORER_RESPONSE
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=1)

        explorer.explore(chess.STARTING_FEN, ExplorerSource.MASTERS)
        mock_api.assert_called_once_with(chess.STARTING_FEN)

    @patch("src.openings.explorer.explore_player")
    def test_player_source(self, mock_api, repo):
        mock_api.return_value = EXPLORER_RESPONSE
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=1)

        explorer.explore(
            chess.STARTING_FEN,
            ExplorerSource.PLAYER,
            player="user1",
            color="black",
        )
        mock_api.assert_called_once_with(chess.STARTING_FEN, "user1", color="black", speeds=None)

    def test_player_source_no_username(self, repo):
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=1)
        with pytest.raises(ExplorerError, match="Player username required"):
            explorer.explore(chess.STARTING_FEN, ExplorerSource.PLAYER)

    def test_filter_moves_by_min_games(self, repo):
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, EXPLORER_RESPONSE)
        # min_games=10000 should filter out c4 (12000 games) but keep e4 and d4
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=10000)
        result = explorer.explore(chess.STARTING_FEN)
        uci_moves = [m.uci for m in result.moves]
        assert "e2e4" in uci_moves
        assert "d2d4" in uci_moves
        assert "c2c4" in uci_moves  # c4 has 12000 total

    def test_filter_moves_strict(self, repo):
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, EXPLORER_RESPONSE)
        # min_games=50000 should filter out d4 and c4
        explorer = OpeningExplorer(repo.openings, cache_ttl_hours=168, min_games=50000)
        result = explorer.explore(chess.STARTING_FEN)
        uci_moves = [m.uci for m in result.moves]
        assert "e2e4" in uci_moves  # 55000 games
        assert "d2d4" not in uci_moves  # 33000 games
        assert "c2c4" not in uci_moves  # 12000 games


# ── Book ──────────────────────────────────────────────────────────────────────


class TestParsePgnToUci:
    def test_simple_game(self):
        moves = parse_pgn_to_uci("1.e4 e5 2.Nf3 Nc6")
        assert moves == ["e2e4", "e7e5", "g1f3", "b8c6"]

    def test_without_move_numbers(self):
        moves = parse_pgn_to_uci("e4 e5 Nf3")
        assert moves == ["e2e4", "e7e5", "g1f3"]

    def test_invalid_pgn(self):
        with pytest.raises(BookError, match="Could not parse"):
            parse_pgn_to_uci("")

    def test_castling(self):
        moves = parse_pgn_to_uci("1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.O-O")
        assert "e1g1" in moves  # Kingside castling


class TestParsePgnFile:
    def test_single_game(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text('[Event "Test"]\n\n1.e4 e5 2.Nf3 *\n')
        games = parse_pgn_file(str(pgn_file))
        assert len(games) == 1
        assert games[0] == ["e2e4", "e7e5", "g1f3"]

    def test_multiple_games(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text('[Event "Game 1"]\n\n1.e4 e5 *\n\n[Event "Game 2"]\n\n1.d4 d5 *\n')
        games = parse_pgn_file(str(pgn_file))
        assert len(games) == 2
        assert games[0] == ["e2e4", "e7e5"]
        assert games[1] == ["d2d4", "d7d5"]

    def test_missing_file(self):
        with pytest.raises(BookError, match="Cannot read file"):
            parse_pgn_file("/nonexistent/file.pgn")

    def test_empty_file(self, tmp_path):
        pgn_file = tmp_path / "empty.pgn"
        pgn_file.write_text("")
        games = parse_pgn_file(str(pgn_file))
        assert games == []


class TestCreateLine:
    def test_creates_valid_line(self):
        line = create_line(
            BookColor.WHITE,
            ["e2e4", "e7e5", "g1f3"],
            name="Italian",
            variation="Two Knights",
            eco_code="C55",
        )
        assert line.id.startswith("book:")
        assert line.color == BookColor.WHITE
        assert line.name == "Italian"
        assert line.moves == ["e2e4", "e7e5", "g1f3"]
        assert line.eco_code == "C55"

    def test_invalid_uci(self):
        with pytest.raises(BookError, match="Invalid UCI"):
            create_line(BookColor.WHITE, ["xyz123"])

    def test_illegal_move(self):
        with pytest.raises(BookError, match="Illegal move"):
            create_line(BookColor.WHITE, ["e2e5"])  # Can't move pawn to e5 directly


class TestGenerateExercises:
    def test_generates_for_user_turns(self):
        line = OpeningLine(
            id="book:test1",
            color=BookColor.WHITE,
            name="Test",
            moves=["e2e4", "e7e5", "g1f3", "b8c6"],
        )
        exercises = list(generate_exercises(line))
        # White moves at indices 0 and 2
        assert len(exercises) == 2
        assert exercises[0].id == "book:test1:m0"
        assert exercises[1].id == "book:test1:m2"

    def test_generates_for_black(self):
        line = OpeningLine(
            id="book:test2",
            color=BookColor.BLACK,
            name="Sicilian",
            moves=["e2e4", "c7c5", "g1f3", "d7d6"],
        )
        exercises = list(generate_exercises(line))
        # Black moves at indices 1 and 3
        assert len(exercises) == 2
        assert exercises[0].id == "book:test2:m1"
        assert exercises[1].id == "book:test2:m3"

    def test_exercise_has_correct_fen(self):
        line = OpeningLine(
            id="book:test3",
            color=BookColor.WHITE,
            name="Test",
            moves=["e2e4", "e7e5"],
        )
        exercises = list(generate_exercises(line))
        assert len(exercises) == 1
        # The FEN should be the starting position (before e4)
        assert exercises[0].fen == chess.STARTING_FEN

    def test_exercise_has_alternatives(self):
        line = OpeningLine(
            id="book:test4",
            color=BookColor.WHITE,
            moves=["e2e4", "e7e5"],
        )
        alternatives = {0: ["d2d4", "c2c4"]}
        exercises = list(generate_exercises(line, alternatives))
        assert exercises[0].alternative_moves == ["d2d4", "c2c4"]

    def test_exercise_type_is_opening(self):
        line = OpeningLine(
            id="book:test5",
            color=BookColor.WHITE,
            moves=["e2e4"],
        )
        exercises = list(generate_exercises(line))
        assert len(exercises) == 1
        assert isinstance(exercises[0], OpeningExercise)
        assert exercises[0].source == "book"

    def test_exercise_carries_line_metadata(self):
        line = OpeningLine(
            id="book:meta",
            color=BookColor.WHITE,
            eco_code="C50",
            name="Italian Game",
            variation="Giuoco Piano",
            moves=["e2e4", "e7e5"],
        )
        exercises = list(generate_exercises(line))
        ex = exercises[0]
        assert ex.eco_code == "C50"
        assert ex.opening_name == "Italian Game"
        assert ex.variation_name == "Giuoco Piano"
        assert ex.line == ["e2e4", "e7e5"]
        assert ex.current_move_index == 0

    def test_empty_line(self):
        line = OpeningLine(id="book:empty", color=BookColor.WHITE, moves=[])
        exercises = list(generate_exercises(line))
        assert exercises == []


class TestGetAlternativesFromExplorer:
    def test_fetches_alternatives(self):
        line = OpeningLine(
            id="book:alt1",
            color=BookColor.WHITE,
            moves=["e2e4", "e7e5"],
        )
        mock_explorer = MagicMock()
        mock_explorer.explore.return_value = ExplorerResult(
            fen=chess.STARTING_FEN,
            white_wins=100,
            draws=50,
            black_wins=50,
            moves=[
                MoveStats(uci="e2e4", san="e4", white_wins=50, draws=25, black_wins=25),
                MoveStats(uci="d2d4", san="d4", white_wins=30, draws=20, black_wins=15),
                MoveStats(uci="c2c4", san="c4", white_wins=20, draws=5, black_wins=10),
            ],
        )

        alts = get_alternatives_from_explorer(line, mock_explorer, min_games=5)
        # At move 0 (white's turn), e2e4 is the main move; d2d4 and c2c4 are alternatives
        assert 0 in alts
        assert "d2d4" in alts[0]
        assert "c2c4" in alts[0]
        assert "e2e4" not in alts[0]  # Main move excluded

    def test_handles_explorer_error(self):
        line = OpeningLine(
            id="book:err",
            color=BookColor.WHITE,
            moves=["e2e4", "e7e5"],
        )
        mock_explorer = MagicMock()
        mock_explorer.explore.side_effect = ExplorerError("Network error")

        alts = get_alternatives_from_explorer(line, mock_explorer)
        assert alts == {}  # Gracefully returns empty


# ── Storage ───────────────────────────────────────────────────────────────────


class TestOpeningStoreLines:
    def test_add_and_get_line(self, repo):
        line = OpeningLine(
            id="book:store1",
            color=BookColor.WHITE,
            name="Italian",
            moves=["e2e4", "e7e5", "f1c4"],
        )
        repo.openings.add_line(line)
        restored = repo.openings.get_line("book:store1")
        assert restored is not None
        assert restored.name == "Italian"
        assert restored.moves == ["e2e4", "e7e5", "f1c4"]

    def test_get_nonexistent(self, repo):
        assert repo.openings.get_line("book:nope") is None

    def test_list_lines(self, repo):
        for i in range(3):
            line = OpeningLine(
                id=f"book:list{i}",
                color=BookColor.WHITE if i < 2 else BookColor.BLACK,
                name=f"Opening {i}",
                moves=["e2e4"],
            )
            repo.openings.add_line(line)

        all_lines = repo.openings.list_lines()
        assert len(all_lines) == 3

        white_lines = repo.openings.list_lines(color=BookColor.WHITE)
        assert len(white_lines) == 2

        black_lines = repo.openings.list_lines(color=BookColor.BLACK)
        assert len(black_lines) == 1

    def test_list_lines_name_filter(self, repo):
        repo.openings.add_line(
            OpeningLine(
                id="book:sic",
                color=BookColor.BLACK,
                name="Sicilian Najdorf",
                moves=["e2e4", "c7c5"],
            )
        )
        repo.openings.add_line(
            OpeningLine(
                id="book:ita", color=BookColor.WHITE, name="Italian Game", moves=["e2e4", "e7e5"]
            )
        )

        results = repo.openings.list_lines(name_contains="sicilian")
        assert len(results) == 1
        assert results[0].name == "Sicilian Najdorf"

    def test_delete_line(self, repo):
        repo.openings.add_line(OpeningLine(id="book:del1", color=BookColor.WHITE, moves=["e2e4"]))
        assert repo.openings.delete_line("book:del1") is True
        assert repo.openings.get_line("book:del1") is None
        assert repo.openings.delete_line("book:del1") is False

    def test_count_lines(self, repo):
        assert repo.openings.count_lines() == 0
        repo.openings.add_line(OpeningLine(id="book:c1", color=BookColor.WHITE, moves=["e2e4"]))
        repo.openings.add_line(
            OpeningLine(id="book:c2", color=BookColor.BLACK, moves=["e2e4", "c7c5"])
        )
        assert repo.openings.count_lines() == 2
        assert repo.openings.count_lines(BookColor.WHITE) == 1
        assert repo.openings.count_lines(BookColor.BLACK) == 1

    def test_update_line(self, repo):
        line = OpeningLine(
            id="book:upd1",
            color=BookColor.WHITE,
            name="Before",
            moves=["e2e4"],
        )
        repo.openings.add_line(line)
        line.name = "After"
        line.moves = ["e2e4", "e7e5"]
        repo.openings.update_line(line)

        restored = repo.openings.get_line("book:upd1")
        assert restored.name == "After"
        assert restored.moves == ["e2e4", "e7e5"]

    def test_list_lines_pagination(self, repo):
        for i in range(5):
            repo.openings.add_line(
                OpeningLine(
                    id=f"book:page{i}", color=BookColor.WHITE, name=f"Line {i}", moves=["e2e4"]
                )
            )

        page1 = repo.openings.list_lines(limit=2, offset=0)
        page2 = repo.openings.list_lines(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id


class TestOpeningStoreCache:
    def test_cache_put_and_get(self, repo):
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, {"test": True})
        cached = repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.LICHESS, ttl_hours=1)
        assert cached == {"test": True}

    def test_cache_miss(self, repo):
        assert (
            repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.LICHESS, ttl_hours=1) is None
        )

    def test_cache_different_sources(self, repo):
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, {"source": "lichess"})
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.MASTERS, {"source": "masters"})

        lichess = repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.LICHESS, 1)
        masters = repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.MASTERS, 1)
        assert lichess["source"] == "lichess"
        assert masters["source"] == "masters"

    def test_cache_upsert(self, repo):
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, {"v": 1})
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, {"v": 2})
        cached = repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.LICHESS, 1)
        assert cached["v"] == 2

    def test_cache_clear_all(self, repo):
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, {"a": 1})
        repo.openings.cache_put(NAJDORF_FEN, ExplorerSource.LICHESS, {"b": 2})
        count = repo.openings.cache_clear()
        assert count == 2
        assert repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.LICHESS, 1) is None

    def test_cache_clear_by_age(self, repo):
        # Insert an entry then clear entries older than 0 hours (everything)
        repo.openings.cache_put(chess.STARTING_FEN, ExplorerSource.LICHESS, {"a": 1})
        # Clearing with older_than=0 should clear nothing (entries are fresh)
        count = repo.openings.cache_clear(older_than_hours=9999)
        assert count == 0
        # The entry should still be there
        assert repo.openings.cache_get(chess.STARTING_FEN, ExplorerSource.LICHESS, 9999) is not None


# ── Config ────────────────────────────────────────────────────────────────────


class TestOpeningsConfig:
    def test_defaults(self):
        cfg = AppConfig()
        assert cfg.openings.explorer_source == "lichess"
        assert cfg.openings.cache_ttl_hours == 168
        assert cfg.openings.min_games == 5

    def test_toml_override(self):
        cfg = AppConfig()
        _apply_toml(
            cfg,
            {
                "openings": {
                    "explorer_source": "masters",
                    "cache_ttl_hours": 24,
                    "min_games": 100,
                }
            },
        )
        assert cfg.openings.explorer_source == "masters"
        assert cfg.openings.cache_ttl_hours == 24
        assert cfg.openings.min_games == 100

    def test_env_override(self, monkeypatch):
        cfg = AppConfig()
        monkeypatch.setenv("CHESS_TRAINER_OPENINGS_SOURCE", "player")
        monkeypatch.setenv("CHESS_TRAINER_OPENINGS_CACHE_TTL", "48")
        monkeypatch.setenv("CHESS_TRAINER_OPENINGS_MIN_GAMES", "10")
        _apply_env(cfg)
        assert cfg.openings.explorer_source == "player"
        assert cfg.openings.cache_ttl_hours == 48
        assert cfg.openings.min_games == 10

    def test_default_config_includes_openings(self):
        import tomllib

        from src.config import generate_default_config

        content = generate_default_config()
        data = tomllib.loads(content)
        assert "openings" in data
        assert data["openings"]["explorer_source"] == "lichess"


# ── CLI Commands ──────────────────────────────────────────────────────────────


class TestExploreCommand:
    @patch("src.cli.app._interactive_explore")
    def test_explore_default(self, mock_explore, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["explore", "--db", str(db_path)])
        assert result.exit_code == 0
        mock_explore.assert_called_once()

    @patch("src.cli.app._interactive_explore")
    def test_explore_with_fen(self, mock_explore, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["explore", NAJDORF_FEN, "--db", str(db_path)])
        assert result.exit_code == 0
        mock_explore.assert_called_once()
        # The board argument should have the Najdorf position
        call_board = mock_explore.call_args[0][0]
        assert call_board.fen() == chess.Board(NAJDORF_FEN).fen()

    def test_explore_invalid_fen(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["explore", "not-a-fen", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Invalid FEN" in result.output

    @patch("src.cli.app._interactive_explore")
    def test_explore_masters_source(self, mock_explore, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["explore", "--source", "masters", "--db", str(db_path)])
        assert result.exit_code == 0
        # Check source argument
        call_source = mock_explore.call_args[0][2]
        assert call_source == ExplorerSource.MASTERS

    def test_explore_invalid_source(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["explore", "--source", "invalid", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "Unknown source" in result.output


class TestBookAddCommand:
    def test_add_line(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 e5 2.Nf3",
                "--color",
                "white",
                "--name",
                "Open Game",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 0
        assert "\u2713" in result.output
        assert "Open Game" in result.output

    def test_add_invalid_color(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 e5",
                "--color",
                "green",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 1
        assert "Invalid color" in result.output

    def test_add_invalid_pgn(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "",
                "--color",
                "white",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 1


class TestBookListCommand:
    def test_list_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["book", "list", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "No lines" in result.output

    def test_list_with_lines(self, tmp_path):
        db_path = tmp_path / "test.db"
        # Add a line first
        runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 e5",
                "--color",
                "white",
                "--name",
                "Open Game",
                "--db",
                str(db_path),
            ],
        )
        result = runner.invoke(app, ["book", "list", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Opening Book" in result.output
        assert "Open Game" in result.output

    def test_list_filter_color(self, tmp_path):
        db_path = tmp_path / "test.db"
        runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 e5",
                "--color",
                "white",
                "--name",
                "White Line",
                "--db",
                str(db_path),
            ],
        )
        runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 c5",
                "--color",
                "black",
                "--name",
                "Sicilian",
                "--db",
                str(db_path),
            ],
        )
        result = runner.invoke(app, ["book", "list", "--color", "black", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "Sicilian" in result.output


class TestBookDeleteCommand:
    def test_delete_existing(self, tmp_path):
        db_path = tmp_path / "test.db"
        # Add a line
        runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 e5",
                "--color",
                "white",
                "--db",
                str(db_path),
            ],
        )
        # Get the line ID
        with Repository(db_path) as repo:
            lines = repo.openings.list_lines()
            line_id = lines[0].id

        result = runner.invoke(app, ["book", "delete", line_id, "--db", str(db_path)])
        assert result.exit_code == 0
        assert "\u2713" in result.output

    def test_delete_nonexistent(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["book", "delete", "book:nonexistent", "--db", str(db_path)])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestBookSyncCommand:
    def test_sync_empty_book(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(app, ["book", "sync", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "No lines" in result.output

    def test_sync_creates_exercises(self, tmp_path):
        db_path = tmp_path / "test.db"
        # Add a line with 4 moves (2 white turns)
        runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 e5 2.Nf3 Nc6",
                "--color",
                "white",
                "--name",
                "Open Game",
                "--db",
                str(db_path),
            ],
        )
        result = runner.invoke(app, ["book", "sync", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "2 new exercises" in result.output

        # Verify exercises were created
        with Repository(db_path) as repo:
            exercises = repo.exercises.search(source="book")
            assert len(exercises) == 2

    def test_sync_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        runner.invoke(
            app,
            [
                "book",
                "add",
                "--pgn",
                "1.e4 e5",
                "--color",
                "white",
                "--db",
                str(db_path),
            ],
        )
        # First sync
        runner.invoke(app, ["book", "sync", "--db", str(db_path)])
        # Second sync should add 0 new
        result = runner.invoke(app, ["book", "sync", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "0 new exercises" in result.output


class TestBookImportPgnCommand:
    def test_import_pgn_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text('[Event "Test"]\n\n1.e4 e5 2.Nf3 *\n')

        result = runner.invoke(
            app,
            [
                "book",
                "import-pgn",
                str(pgn_file),
                "--color",
                "white",
                "--name",
                "Test Opening",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 0
        assert "Imported 1/1" in result.output

    def test_import_invalid_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        result = runner.invoke(
            app,
            [
                "book",
                "import-pgn",
                "/nonexistent/file.pgn",
                "--color",
                "white",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 1
        assert "Import error" in result.output

    def test_import_invalid_color(self, tmp_path):
        db_path = tmp_path / "test.db"
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text('[Event "Test"]\n\n1.e4 e5 *\n')

        result = runner.invoke(
            app,
            [
                "book",
                "import-pgn",
                str(pgn_file),
                "--color",
                "purple",
                "--db",
                str(db_path),
            ],
        )
        assert result.exit_code == 1
        assert "Invalid color" in result.output


class TestConfigShowIncludesOpenings:
    def test_config_show_openings(self):
        result = runner.invoke(app, ["config", "show"])
        assert result.exit_code == 0
        assert "openings.explorer_source" in result.output
        assert "openings.cache_ttl_hours" in result.output
        assert "openings.min_games" in result.output
