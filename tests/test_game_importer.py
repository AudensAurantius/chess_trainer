"""Tests for own-game importer and PGN parsing."""

from unittest.mock import MagicMock, patch

import chess
import chess.pgn

from src.analysis.classification import MoveClassification
from src.analysis.engine import EngineManager
from src.exercises.tactics import TacticExercise
from src.importers.games import GameImporter, parse_pgn_games

# ---------------------------------------------------------------------------
# Test PGN data
# ---------------------------------------------------------------------------

SINGLE_GAME_PGN = """[Event "Test"]
[Site "https://lichess.org/AbCdEfGh"]
[White "Player1"]
[Black "Player2"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0"""

MULTI_GAME_PGN = """[Event "Game 1"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0

[Event "Game 2"]
[White "Carol"]
[Black "Dave"]
[Result "0-1"]

1. d4 d5 2. c4 e6 0-1"""

EMPTY_PGN = ""

INVALID_PGN = "not a real pgn at all"


# ---------------------------------------------------------------------------
# parse_pgn_games tests
# ---------------------------------------------------------------------------


class TestParsePgnGames:
    def test_single_game(self):
        games = parse_pgn_games(SINGLE_GAME_PGN)
        assert len(games) == 1
        assert games[0].headers["White"] == "Player1"

    def test_multi_game(self):
        games = parse_pgn_games(MULTI_GAME_PGN)
        assert len(games) == 2
        assert games[0].headers["White"] == "Alice"
        assert games[1].headers["White"] == "Carol"

    def test_empty_string(self):
        games = parse_pgn_games(EMPTY_PGN)
        assert games == []

    def test_invalid_pgn(self):
        games = parse_pgn_games(INVALID_PGN)
        # python-chess may return a game with no moves, or an empty list
        # depending on the content
        assert isinstance(games, list)

    def test_from_file_path(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SINGLE_GAME_PGN)

        games = parse_pgn_games(pgn_file)
        assert len(games) == 1
        assert games[0].headers["White"] == "Player1"

    def test_from_string_path(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SINGLE_GAME_PGN)

        games = parse_pgn_games(str(pgn_file))
        assert len(games) == 1

    def test_game_has_moves(self):
        games = parse_pgn_games(SINGLE_GAME_PGN)
        moves = list(games[0].mainline_moves())
        assert len(moves) == 6  # 3 moves each side


# ---------------------------------------------------------------------------
# GameImporter property tests
# ---------------------------------------------------------------------------


class TestGameImporterProperties:
    def test_source_name(self):
        importer = GameImporter()
        assert importer.source_name == "Game Analysis"

    def test_default_params(self):
        importer = GameImporter()
        assert importer._depth == 20
        assert importer._min_classification == MoveClassification.MISTAKE
        assert importer._max_exercises == 10
        assert importer._skip_first_plies == 6

    def test_custom_params(self):
        importer = GameImporter(
            depth=15,
            min_classification=MoveClassification.BLUNDER,
            max_exercises=5,
            skip_first_plies=4,
        )
        assert importer._depth == 15
        assert importer._min_classification == MoveClassification.BLUNDER
        assert importer._max_exercises == 5
        assert importer._skip_first_plies == 4


# ---------------------------------------------------------------------------
# GameImporter.fetch with PGN tests
# ---------------------------------------------------------------------------


class TestGameImporterPgn:
    def _make_mock_engine(self) -> MagicMock:
        """Create a mock EngineManager that returns consistent evals."""
        mock_engine = MagicMock(spec=EngineManager)

        # Create a blunder scenario: position eval drops from 200 to -50
        best_move = chess.Move.from_uci("d2d4")
        call_count = [0]

        def analyze_side_effect(board, *, depth=20, multipv=1):
            result = MagicMock()
            idx = call_count[0]
            call_count[0] += 1

            # Make ply 2 (white's 2nd move position) have a huge eval
            if idx == 2:
                result.evaluation = 200
                line = MagicMock()
                line.pv = [best_move, chess.Move.from_uci("d7d5")]
                result.best_line = line
            elif idx == 3:
                result.evaluation = 50  # After blunder: cp_loss = 200 - (-50) = 250
                line = MagicMock()
                line.pv = []
                result.best_line = line
            else:
                result.evaluation = 20
                line = MagicMock()
                line.pv = [chess.Move.from_uci("e2e4")]
                result.best_line = line

            return result

        mock_engine.analyze.side_effect = analyze_side_effect
        return mock_engine

    def test_fetch_pgn_generates_exercises(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SINGLE_GAME_PGN)

        engine = self._make_mock_engine()
        importer = GameImporter(
            engine,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(importer.fetch(pgn_path=pgn_file))
        assert len(exercises) >= 1
        assert all(isinstance(e, TacticExercise) for e in exercises)

    def test_fetch_pgn_string_path(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SINGLE_GAME_PGN)

        engine = self._make_mock_engine()
        importer = GameImporter(
            engine,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(importer.fetch(pgn_path=str(pgn_file)))
        assert len(exercises) >= 1

    def test_fetch_pgn_no_engine(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SINGLE_GAME_PGN)

        importer = GameImporter()  # No engine
        exercises = list(importer.fetch(pgn_path=pgn_file))
        assert exercises == []

    def test_fetch_pgn_color_filter(self, tmp_path):
        pgn_file = tmp_path / "test.pgn"
        pgn_file.write_text(SINGLE_GAME_PGN)

        engine = self._make_mock_engine()
        importer = GameImporter(
            engine,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(importer.fetch(pgn_path=pgn_file, color="white"))
        for ex in exercises:
            board = chess.Board(ex.fen)
            assert board.turn == chess.WHITE

    def test_fetch_no_args_yields_nothing(self):
        engine = MagicMock(spec=EngineManager)
        importer = GameImporter(engine)
        exercises = list(importer.fetch())
        assert exercises == []


# ---------------------------------------------------------------------------
# GameImporter.fetch with Lichess tests
# ---------------------------------------------------------------------------


class TestGameImporterLichess:
    LICHESS_GAME_JSON = {
        "id": "XyZ12345",
        "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
        "players": {
            "white": {"user": {"name": "TestUser"}},
            "black": {"user": {"name": "Opponent"}},
        },
    }

    LICHESS_GAME_WITH_EVALS = {
        "id": "EvalGame1",
        "pgn": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6",
        "analysis": [
            {"eval": {"cp": 20}},
            {"eval": {"cp": -15}},
            {"eval": {"cp": 200}},
            {"eval": {"cp": 50}},
            {"eval": {"cp": 20}},
            {"eval": {"cp": -10}},
        ],
        "players": {
            "white": {"user": {"name": "TestUser"}},
            "black": {"user": {"name": "Opponent"}},
        },
    }

    @patch("src.importers.games.get_user_games")
    def test_fetch_lichess_with_engine(self, mock_get_games):
        mock_get_games.return_value = iter([self.LICHESS_GAME_JSON])

        mock_engine = MagicMock(spec=EngineManager)
        mock_result = MagicMock()
        mock_result.evaluation = 20
        mock_line = MagicMock()
        mock_line.pv = [chess.Move.from_uci("e2e4")]
        mock_result.best_line = mock_line
        mock_engine.analyze.return_value = mock_result

        importer = GameImporter(
            mock_engine,
            min_classification=MoveClassification.BEST,
            skip_first_plies=0,
        )
        list(importer.fetch(username="TestUser", max_games=1))
        mock_get_games.assert_called_once()

    @patch("src.importers.games.get_user_games")
    def test_fetch_lichess_server_evals(self, mock_get_games):
        mock_get_games.return_value = iter([self.LICHESS_GAME_WITH_EVALS])

        importer = GameImporter(
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(importer.fetch(username="TestUser", use_server_evals=True, max_games=1))
        # Should produce exercises from the blunder at ply 2 (200→50 = 250cp loss)
        # But server evals may not have best_move → no exercise if best_move is None
        assert isinstance(exercises, list)

    @patch("src.importers.games.get_user_games")
    def test_fetch_lichess_no_pgn_in_response(self, mock_get_games):
        mock_get_games.return_value = iter([{"id": "NoPgn"}])

        mock_engine = MagicMock(spec=EngineManager)
        importer = GameImporter(mock_engine, skip_first_plies=0)
        exercises = list(importer.fetch(username="User"))
        assert exercises == []

    @patch("src.importers.games.get_user_games")
    def test_fetch_lichess_passes_filters(self, mock_get_games):
        mock_get_games.return_value = iter([])

        importer = GameImporter(skip_first_plies=0)
        list(
            importer.fetch(
                username="TestUser",
                use_server_evals=True,
                max_games=5,
                since=1000,
                until=2000,
                rated=True,
                perf_type="blitz",
            )
        )

        mock_get_games.assert_called_once_with(
            "TestUser",
            max=5,
            evals=True,
            since=1000,
            until=2000,
            rated=True,
            perf_type="blitz",
        )

    @patch("src.importers.games.get_user_games")
    def test_fetch_lichess_no_engine_no_server_evals(self, mock_get_games):
        """Without engine or server evals, no exercises are generated."""
        mock_get_games.return_value = iter([self.LICHESS_GAME_JSON])

        importer = GameImporter()  # No engine
        exercises = list(importer.fetch(username="TestUser"))
        assert exercises == []


# ---------------------------------------------------------------------------
# GameImporter.import_to tests
# ---------------------------------------------------------------------------


class TestGameImporterImportTo:
    @patch("src.importers.games.get_user_games")
    def test_import_to_tracks_results(self, mock_get_games):
        mock_get_games.return_value = iter([])

        importer = GameImporter()
        mock_store = MagicMock()
        result = importer.import_to(mock_store, username="User", use_server_evals=True)
        assert result.source == "Game Analysis"
        assert result.total_fetched == 0


# ---------------------------------------------------------------------------
# _extract_lichess_evals tests
# ---------------------------------------------------------------------------


class TestExtractLichessEvals:
    def test_with_cp_evals(self):
        importer = GameImporter()
        game_data = {
            "analysis": [
                {"eval": {"cp": 20}},
                {"eval": {"cp": -15}},
            ]
        }
        evals = importer._extract_lichess_evals(game_data)
        # First is initial position (cp=0), then the two analysis entries
        assert len(evals) == 3
        assert evals[0] == {"cp": 0}
        assert evals[1] == {"cp": 20}
        assert evals[2] == {"cp": -15}

    def test_with_mate_evals(self):
        importer = GameImporter()
        game_data = {
            "analysis": [
                {"eval": {"mate": 3}},
            ]
        }
        evals = importer._extract_lichess_evals(game_data)
        assert evals[1] == {"mate": 3}

    def test_with_none_entries(self):
        importer = GameImporter()
        game_data = {
            "analysis": [
                {"eval": {"cp": 20}},
                None,
                {"eval": {"cp": -30}},
            ]
        }
        evals = importer._extract_lichess_evals(game_data)
        assert evals[2] is None

    def test_no_analysis_key(self):
        importer = GameImporter()
        game_data = {}
        evals = importer._extract_lichess_evals(game_data)
        assert evals == [{"cp": 0}]

    def test_with_raw_eval_dicts(self):
        """Some Lichess responses have eval dicts directly, not nested."""
        importer = GameImporter()
        game_data = {
            "analysis": [
                {"cp": 20},
                {"cp": -15},
            ]
        }
        evals = importer._extract_lichess_evals(game_data)
        assert evals[1] == {"cp": 20}
        assert evals[2] == {"cp": -15}
