"""Tests for endgame master games module."""

from unittest.mock import MagicMock, patch

import chess
import chess.pgn
import pytest

from src.endgame_masters.catalog import ENDGAME_TYPES, get_category
from src.endgame_masters.detector import (
    annotate_endgame,
    build_endgame_phase,
    find_endgame_start,
    is_endgame,
)
from src.endgame_masters.fetcher import (
    FetcherError,
    explore_masters_with_games,
    fetch_master_pgn,
    find_endgame_games,
)
from src.endgame_masters.generator import (
    classify_endgame_type,
    generate_endgame_exercises,
)
from src.endgame_masters.models import (
    AnnotatedPosition,
    EndgamePhase,
    MasterGameInfo,
)
from src.tablebase.models import TablebaseMove, TablebaseResult

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_game_info(**kwargs) -> MasterGameInfo:
    """Create a MasterGameInfo with defaults."""
    defaults = {
        "game_id": "testGM01",
        "white": "Carlsen, M.",
        "white_rating": 2850,
        "black": "Caruana, F.",
        "black_rating": 2800,
        "winner": "white",
        "year": 2023,
        "uci": "e2e4",
    }
    defaults.update(kwargs)
    return MasterGameInfo(**defaults)


def _make_simple_pgn(moves_str: str = "1. e4 e5 2. Nf3 Nc6") -> chess.pgn.Game:
    """Create a chess.pgn.Game from a move string."""
    import io

    pgn_text = f'[Event "Test"]\n[Result "*"]\n\n{moves_str} *'
    return chess.pgn.read_game(io.StringIO(pgn_text))


def _make_endgame_game() -> chess.pgn.Game:
    """Create a game that reaches an endgame (queens traded).

    1. e4 e5 2. d4 exd4 3. Qxd4 Qf6 4. Qxf6 Nxf6 5. Bc4 Bc5 6. Nf3 Nc6
    After move 8 (4. Qxf6), queens are off the board → endgame.
    """
    game = chess.pgn.Game()
    uci_moves = [
        "e2e4",
        "e7e5",
        "d2d4",
        "e5d4",
        "d1d4",
        "d8f6",
        "d4f6",
        "g8f6",
        "f1c4",
        "f8c5",
        "g1f3",
        "b8c6",
    ]
    node = game
    for uci in uci_moves:
        node = node.add_variation(chess.Move.from_uci(uci))
    return game


def _make_tb_result(wdl=2, dtz=5, moves=None) -> TablebaseResult:
    """Create a TablebaseResult with defaults."""
    if moves is None:
        moves = [
            TablebaseMove(uci="e1e2", san="Ke2", wdl=2, dtz=4, category="win"),
            TablebaseMove(uci="e1d1", san="Kd1", wdl=2, dtz=6, category="win"),
            TablebaseMove(uci="e1f1", san="Kf1", wdl=0, dtz=0, category="draw"),
        ]
    return TablebaseResult(wdl=wdl, dtz=dtz, category="win", moves=moves)


# ── Model tests ──────────────────────────────────────────────────────────────


class TestMasterGameInfo:
    """Tests for MasterGameInfo dataclass."""

    def test_creation(self):
        info = _make_game_info()
        assert info.game_id == "testGM01"
        assert info.white == "Carlsen, M."
        assert info.white_rating == 2850
        assert info.black == "Caruana, F."
        assert info.winner == "white"
        assert info.year == 2023

    def test_draw(self):
        info = _make_game_info(winner=None)
        assert info.winner is None

    def test_frozen(self):
        info = _make_game_info()
        with pytest.raises(AttributeError):
            info.game_id = "x"  # type: ignore[misc]


class TestAnnotatedPosition:
    """Tests for AnnotatedPosition dataclass."""

    def test_creation(self):
        pos = AnnotatedPosition(
            fen="8/8/4k3/8/4P3/4K3/8/8 w - - 0 1",
            ply=42,
            move_played=chess.Move.from_uci("e3e4"),
            move_san="Ke4",
            wdl=2,
            dtz=5,
            category="win",
            is_critical=True,
            wdl_after=2,
        )
        assert pos.ply == 42
        assert pos.is_critical is True
        assert pos.wdl == 2
        assert pos.wdl_after == 2

    def test_no_move(self):
        pos = AnnotatedPosition(
            fen="8/8/4k3/8/8/4K3/8/8 w - - 0 1",
            ply=50,
            move_played=None,
            move_san="",
            wdl=0,
            dtz=0,
            category="draw",
            is_critical=False,
            wdl_after=None,
        )
        assert pos.move_played is None
        assert pos.wdl_after is None


class TestEndgamePhase:
    """Tests for EndgamePhase dataclass."""

    def test_critical_moments(self):
        positions = [
            AnnotatedPosition("fen1", 10, None, "", 2, 5, "win", False, 2),
            AnnotatedPosition("fen2", 11, None, "", 2, 5, "win", True, 0),
            AnnotatedPosition("fen3", 12, None, "", 0, 0, "draw", True, -2),
            AnnotatedPosition("fen4", 13, None, "", -2, -3, "loss", False, -2),
        ]
        phase = EndgamePhase(
            game_info=_make_game_info(),
            pgn_text="",
            endgame_start_ply=10,
            positions=positions,
        )
        critical = phase.critical_moments
        assert len(critical) == 2
        assert critical[0].ply == 11
        assert critical[1].ply == 12

    def test_no_critical_moments(self):
        positions = [
            AnnotatedPosition("fen1", 10, None, "", 2, 5, "win", False, 2),
        ]
        phase = EndgamePhase(
            game_info=_make_game_info(),
            pgn_text="",
            endgame_start_ply=10,
            positions=positions,
        )
        assert phase.critical_moments == []


# ── Catalog tests ────────────────────────────────────────────────────────────


class TestCatalog:
    """Tests for endgame type catalog."""

    def test_all_types_have_valid_fens(self):
        for key, cat in ENDGAME_TYPES.items():
            assert cat.name, f"Category {key} has no name"
            assert cat.seed_fens, f"Category {key} has no seed FENs"
            for fen in cat.seed_fens:
                board = chess.Board(fen)
                assert board.is_valid(), f"Invalid FEN in {key}: {fen}"

    def test_get_category_valid(self):
        cat = get_category("rook")
        assert cat.name == "Rook Endgames"

    def test_get_category_case_insensitive(self):
        cat = get_category("ROOK")
        assert cat.name == "Rook Endgames"

    def test_get_category_unknown(self):
        with pytest.raises(KeyError, match="Unknown endgame type"):
            get_category("dragon")


# ── Fetcher tests ────────────────────────────────────────────────────────────


class TestExploreMastersWithGames:
    """Tests for explore_masters_with_games."""

    @patch("src.endgame_masters.fetcher.requests.get")
    def test_parses_top_games(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "moves": [],
                    "topGames": [
                        {
                            "id": "abc123",
                            "white": {"name": "Kasparov, G.", "rating": 2850},
                            "black": {"name": "Karpov, A.", "rating": 2780},
                            "winner": "white",
                            "year": 1990,
                            "uci": "e2e4",
                        },
                        {
                            "id": "def456",
                            "white": {"name": "Fischer, R.", "rating": 2785},
                            "black": {"name": "Spassky, B.", "rating": 2660},
                            "winner": None,
                            "year": 1972,
                            "uci": "d2d4",
                        },
                    ],
                }
            ),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        data, games = explore_masters_with_games(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )

        assert len(games) == 2
        assert games[0].game_id == "abc123"
        assert games[0].white == "Kasparov, G."
        assert games[0].winner == "white"
        assert games[1].winner is None

    @patch("src.endgame_masters.fetcher.requests.get")
    def test_empty_top_games(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"moves": [], "topGames": []}),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        data, games = explore_masters_with_games("8/8/4k3/8/4P3/4K3/8/8 w - - 0 1")
        assert games == []

    @patch("src.endgame_masters.fetcher.requests.get")
    def test_http_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.RequestException("Connection failed")
        with pytest.raises(FetcherError, match="Masters API request failed"):
            explore_masters_with_games("8/8/4k3/8/4P3/4K3/8/8 w - - 0 1")


class TestFetchMasterPgn:
    """Tests for fetch_master_pgn."""

    @patch("src.endgame_masters.fetcher.requests.get")
    def test_returns_pgn_text(self, mock_get):
        pgn_text = '[Event "Test"]\n\n1. e4 e5 *'
        mock_get.return_value = MagicMock(status_code=200, text=pgn_text)
        mock_get.return_value.raise_for_status = MagicMock()

        result = fetch_master_pgn("abc123")
        assert result == pgn_text

    @patch("src.endgame_masters.fetcher.requests.get")
    def test_http_error(self, mock_get):
        import requests

        mock_get.side_effect = requests.RequestException("Not found")
        with pytest.raises(FetcherError, match="PGN download failed"):
            fetch_master_pgn("badid")


class TestFindEndgameGames:
    """Tests for find_endgame_games."""

    @patch("src.endgame_masters.fetcher.fetch_master_pgn")
    @patch("src.endgame_masters.fetcher.explore_masters_with_games")
    def test_filters_to_endgame_games(self, mock_explore, mock_pgn):
        info = _make_game_info(game_id="gm1")
        mock_explore.return_value = ({}, [info])

        # Build PGN string from a game that actually reaches endgame
        game = _make_endgame_game()
        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
        pgn_text = game.accept(exporter)
        mock_pgn.return_value = pgn_text

        results = find_endgame_games(fen="8/8/4k3/8/4P3/4K3/8/8 w - - 0 1")
        assert len(results) == 1
        assert results[0][0].game_id == "gm1"

    def test_no_fen_or_type_raises(self):
        with pytest.raises(FetcherError, match="Either fen or type_key"):
            find_endgame_games()

    def test_unknown_type_raises(self):
        with pytest.raises(KeyError, match="Unknown endgame type"):
            find_endgame_games(type_key="dragon")


# ── Detector tests ───────────────────────────────────────────────────────────


class TestIsEndgame:
    """Tests for is_endgame detection."""

    def test_no_queens(self):
        board = chess.Board("8/8/4k3/8/4P3/4K3/8/1r2R3 w - - 0 1")
        assert is_endgame(board) is True

    def test_queens_with_low_material(self):
        # Two queens = 18 pts > 13, not endgame
        board = chess.Board("8/8/4k3/4q3/4Q3/4K3/8/8 w - - 0 1")
        assert is_endgame(board) is False

    def test_queen_alone_is_endgame(self):
        # One queen = 9 pts <= 13
        board = chess.Board("8/8/4k3/8/4Q3/4K3/8/8 w - - 0 1")
        assert is_endgame(board) is True

    def test_queens_high_material(self):
        board = chess.Board("r3k2r/8/8/4q3/4Q3/8/8/R3K2R w KQkq - 0 1")
        assert is_endgame(board) is False

    def test_starting_position(self):
        board = chess.Board()
        assert is_endgame(board) is False

    def test_pure_pawn_endgame(self):
        board = chess.Board("8/5k2/5p2/5P2/5K2/8/8/8 w - - 0 1")
        assert is_endgame(board) is True

    def test_rook_and_pawns(self):
        board = chess.Board("8/5k2/5p2/4RP2/5K2/8/8/3r4 w - - 0 1")
        assert is_endgame(board) is True


class TestFindEndgameStart:
    """Tests for find_endgame_start."""

    def test_returns_correct_ply(self):
        game = _make_endgame_game()
        start = find_endgame_start(game)
        # Queens traded at ply 8 (4. Qxf6 Nxf6)
        assert start is not None
        assert start == 8

    def test_no_endgame_in_short_game(self):
        game = _make_simple_pgn("1. e4 e5")
        start = find_endgame_start(game)
        assert start is None


class TestAnnotateEndgame:
    """Tests for annotate_endgame."""

    def test_probes_each_position(self):
        game = _make_endgame_game()
        start = find_endgame_start(game)
        assert start is not None

        tb = MagicMock()
        tb.is_tablebase_position.return_value = True
        tb.probe.return_value = _make_tb_result()

        positions = annotate_endgame(game, start, tb)
        assert tb.probe.call_count > 0
        assert len(positions) > 0

    def test_skips_non_tablebase_positions(self):
        game = _make_endgame_game()
        start = find_endgame_start(game)
        assert start is not None

        tb = MagicMock()
        tb.is_tablebase_position.return_value = False

        positions = annotate_endgame(game, start, tb)
        assert positions == []
        assert tb.probe.call_count == 0

    def test_marks_wdl_worsening_as_critical(self):
        game = _make_endgame_game()
        start = find_endgame_start(game)
        assert start is not None

        tb = MagicMock()
        tb.is_tablebase_position.return_value = True

        winning_result = _make_tb_result(wdl=2, dtz=5)
        drawing_result = _make_tb_result(wdl=0, dtz=0, moves=[])

        # Alternate: before=winning, after=drawing → wdl worsens
        tb.probe.side_effect = [winning_result, drawing_result] * 20

        positions = annotate_endgame(game, start, tb)
        critical = [p for p in positions if p.is_critical]
        assert len(critical) > 0


class TestBuildEndgamePhase:
    """Tests for build_endgame_phase."""

    def test_returns_none_for_no_endgame(self):
        game = _make_simple_pgn("1. e4 e5")
        tb = MagicMock()
        result = build_endgame_phase(_make_game_info(), "", game, tb)
        assert result is None

    def test_returns_phase_with_positions(self):
        game = _make_endgame_game()
        tb = MagicMock()
        tb.is_tablebase_position.return_value = True
        tb.probe.return_value = _make_tb_result()

        result = build_endgame_phase(_make_game_info(), "pgn text", game, tb)
        assert result is not None
        assert result.game_info.game_id == "testGM01"
        assert len(result.positions) > 0


# ── Generator tests ──────────────────────────────────────────────────────────


class TestClassifyEndgameType:
    """Tests for classify_endgame_type."""

    def test_rook_endgame(self):
        board = chess.Board("8/8/4k3/8/4P3/4K3/8/1r2R3 w - - 0 1")
        assert classify_endgame_type(board) == "Rook Endgame"

    def test_pawn_endgame(self):
        board = chess.Board("8/5k2/5p2/5P2/5K2/8/8/8 w - - 0 1")
        assert classify_endgame_type(board) == "Pawn Endgame"

    def test_queen_endgame(self):
        board = chess.Board("8/8/4k3/8/4Q3/4K3/4P3/8 w - - 0 1")
        assert classify_endgame_type(board) == "Queen Endgame"

    def test_knight_endgame(self):
        board = chess.Board("8/8/4k3/8/4N3/4K3/8/4n3 w - - 0 1")
        assert classify_endgame_type(board) == "Knight Endgame"

    def test_bishop_endgame(self):
        board = chess.Board("8/8/4k3/8/2B5/8/4K3/8 w - - 0 1")
        assert classify_endgame_type(board) == "Bishop Endgame"

    def test_opposite_color_bishops(self):
        # White bishop on c4 (light), black bishop on d1 (dark)
        board = chess.Board("8/8/3k4/8/2B5/8/4K3/3b4 w - - 0 1")
        result = classify_endgame_type(board)
        assert result in ("Opposite-Color Bishops", "Same-Color Bishops")

    def test_king_vs_king(self):
        board = chess.Board("8/8/4k3/8/8/4K3/8/8 w - - 0 1")
        assert classify_endgame_type(board) == "King vs King"

    def test_rook_and_bishop(self):
        board = chess.Board("8/8/4k3/8/2B1R3/8/4K3/8 w - - 0 1")
        assert classify_endgame_type(board) == "Rook and Bishop Endgame"


class TestGenerateEndgameExercises:
    """Tests for generate_endgame_exercises."""

    def _make_phase_with_critical(self) -> EndgamePhase:
        """Create a phase with critical moments."""
        fen = "8/8/4k3/8/4P3/4K3/8/1r2R3 w - - 0 1"
        positions = [
            AnnotatedPosition(
                fen=fen,
                ply=42,
                move_played=chess.Move.from_uci("e3e4"),
                move_san="Ke4",
                wdl=2,
                dtz=5,
                category="win",
                is_critical=True,
                wdl_after=0,
            ),
            AnnotatedPosition(
                fen=fen,
                ply=44,
                move_played=chess.Move.from_uci("e4e5"),
                move_san="Ke5",
                wdl=2,
                dtz=3,
                category="win",
                is_critical=True,
                wdl_after=2,
            ),
            AnnotatedPosition(
                fen=fen,
                ply=46,
                move_played=None,
                move_san="",
                wdl=0,
                dtz=0,
                category="draw",
                is_critical=False,
                wdl_after=None,
            ),
        ]
        return EndgamePhase(
            game_info=_make_game_info(game_id="gm42"),
            pgn_text="",
            endgame_start_ply=40,
            positions=positions,
        )

    def test_creates_exercises(self):
        phase = self._make_phase_with_critical()
        tb = MagicMock()
        tb.probe.return_value = _make_tb_result()

        exercises = list(generate_endgame_exercises(phase, tb))
        assert len(exercises) == 2

    def test_exercise_id_format(self):
        phase = self._make_phase_with_critical()
        tb = MagicMock()
        tb.probe.return_value = _make_tb_result()

        exercises = list(generate_endgame_exercises(phase, tb))
        assert exercises[0].id == "masters:gm42:p42"
        assert exercises[1].id == "masters:gm42:p44"

    def test_exercise_fields(self):
        phase = self._make_phase_with_critical()
        tb = MagicMock()
        tb.probe.return_value = _make_tb_result()

        exercises = list(generate_endgame_exercises(phase, tb))
        ex = exercises[0]
        assert ex.source == "master-games"
        assert ex.tablebase_eval == 5
        assert "endgame" in ex.tags
        assert "master-game" in ex.tags
        assert ex.technique_name == "Rook Endgame"
        assert ex.target_outcome == "win"
        assert len(ex.acceptable_first_moves) == 2  # Two best moves from TB
        assert ex.metadata["game_id"] == "gm42"
        assert ex.metadata["white"] == "Carlsen, M."

    def test_empty_critical_moments(self):
        phase = EndgamePhase(
            game_info=_make_game_info(),
            pgn_text="",
            endgame_start_ply=10,
            positions=[
                AnnotatedPosition("fen", 10, None, "", 2, 5, "win", False, 2),
            ],
        )
        tb = MagicMock()
        exercises = list(generate_endgame_exercises(phase, tb))
        assert exercises == []

    def test_max_exercises_limit(self):
        fen = "8/8/4k3/8/4P3/4K3/8/1r2R3 w - - 0 1"
        positions = [AnnotatedPosition(fen, i, None, "", 2, 5, "win", True, 2) for i in range(10)]
        phase = EndgamePhase(
            game_info=_make_game_info(),
            pgn_text="",
            endgame_start_ply=0,
            positions=positions,
        )
        tb = MagicMock()
        tb.probe.return_value = _make_tb_result()

        exercises = list(generate_endgame_exercises(phase, tb, max_exercises=3))
        assert len(exercises) == 3


# ── CLI tests ────────────────────────────────────────────────────────────────


class TestEndgameMastersCLI:
    """Tests for the endgame-masters CLI command."""

    def test_no_fen_or_type_shows_error(self):
        from typer.testing import CliRunner

        from src.cli.app import app

        runner = CliRunner()
        result = runner.invoke(app, ["endgame-masters"])
        assert result.exit_code == 1

    @patch("src.endgame_masters.build_endgame_phase")
    @patch("src.endgame_masters.find_endgame_games")
    def test_browse_mode_displays_table(self, mock_find, mock_build):
        from typer.testing import CliRunner

        from src.cli.app import app

        fen = "8/8/4k3/8/4P3/4K3/8/1r2R3 w - - 0 1"
        info = _make_game_info()
        game = _make_simple_pgn()
        mock_find.return_value = [(info, game)]

        phase = EndgamePhase(
            game_info=info,
            pgn_text="",
            endgame_start_ply=10,
            positions=[
                AnnotatedPosition(fen, 10, None, "Ke4", 2, 5, "win", True, 0),
            ],
        )
        mock_build.return_value = phase

        runner = CliRunner()
        result = runner.invoke(app, ["endgame-masters", fen])
        assert result.exit_code == 0
        assert "Carlsen" in result.output

    @patch("src.endgame_masters.find_endgame_games")
    def test_type_flag_uses_catalog(self, mock_find):
        from typer.testing import CliRunner

        from src.cli.app import app

        mock_find.return_value = []

        runner = CliRunner()
        result = runner.invoke(app, ["endgame-masters", "--type", "rook"])
        assert result.exit_code == 0
        mock_find.assert_called_once()
        assert mock_find.call_args.kwargs.get("type_key") == "rook"

    @patch("src.endgame_masters.find_endgame_games")
    def test_api_error_handled(self, mock_find):
        from typer.testing import CliRunner

        from src.cli.app import app

        mock_find.side_effect = FetcherError("Connection timeout")

        runner = CliRunner()
        result = runner.invoke(app, ["endgame-masters", "--type", "rook"])
        assert result.exit_code == 1
        assert "Connection timeout" in result.output

    @patch("src.endgame_masters.build_endgame_phase")
    @patch("src.endgame_masters.find_endgame_games")
    def test_replay_mode_with_quit(self, mock_find, mock_build):
        from typer.testing import CliRunner

        from src.cli.app import app

        fen = "8/8/4k3/8/4P3/4K3/8/1r2R3 w - - 0 1"
        info = _make_game_info()
        game = _make_simple_pgn()
        mock_find.return_value = [(info, game)]

        phase = EndgamePhase(
            game_info=info,
            pgn_text="",
            endgame_start_ply=10,
            positions=[
                AnnotatedPosition(fen, 10, None, "Ke4", 2, 5, "win", True, 0),
            ],
        )
        mock_build.return_value = phase

        runner = CliRunner()
        result = runner.invoke(app, ["endgame-masters", fen, "--replay"], input="q\n")
        assert result.exit_code == 0
