"""Tests for Chess.com puzzle and game importers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.chesscom.api import ChessComError
from src.exercises import TacticExercise
from src.importers.chesscom_games import ChessComGameImporter
from src.importers.chesscom_puzzles import ChessComPuzzleImporter

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_DAILY_PUZZLE = {
    "title": "Daily Puzzle: Feb 9",
    "url": "https://www.chess.com/puzzles/problem/12345",
    "publish_time": 1700000000,
    "fen": "r1bqkbnr/pppppppp/2n5/4N3/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 1",
    "pgn": "1... Nxe5",
    "image": "https://images.chess.com/puzzle/12345.png",
}

SAMPLE_RANDOM_PUZZLE = {
    "title": "Random Puzzle",
    "url": "https://www.chess.com/puzzles/problem/99999",
    "publish_time": 1700001000,
    "fen": "rnbqkb1r/pppppppp/5n2/4P3/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2",
    "pgn": "1... Nd5",
    "image": "https://images.chess.com/puzzle/99999.png",
}

# A puzzle with a multi-move solution
SAMPLE_MULTI_MOVE_PUZZLE = {
    "title": "Combo Puzzle",
    "url": "https://www.chess.com/puzzles/problem/88888",
    "publish_time": 1700002000,
    "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "pgn": "1... e5 2. Nf3",
    "image": "",
}

SAMPLE_GAME_DICT = {
    "url": "https://www.chess.com/game/live/12345678",
    "pgn": (
        '[Event "Live Chess"]\n'
        '[White "alice"]\n'
        '[Black "bob"]\n'
        '[Result "1-0"]\n'
        "\n"
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0\n"
    ),
    "time_control": "600",
    "time_class": "rapid",
    "rated": True,
    "rules": "chess",
    "white": {"username": "alice", "rating": 1500, "result": "win"},
    "black": {"username": "bob", "rating": 1400, "result": "checkmated"},
    "end_time": 1700000000,
}


# ---------------------------------------------------------------------------
# ChessComPuzzleImporter
# ---------------------------------------------------------------------------


class TestChessComPuzzleImporter:
    def test_source_name(self):
        importer = ChessComPuzzleImporter()
        assert importer.source_name == "Chess.com Puzzles"

    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    @patch("src.importers.chesscom_puzzles.get_daily_puzzle")
    def test_fetch_daily_and_random(self, mock_daily, mock_random):
        mock_daily.return_value = SAMPLE_DAILY_PUZZLE
        mock_random.return_value = SAMPLE_RANDOM_PUZZLE

        importer = ChessComPuzzleImporter()
        exercises = list(importer.fetch(count=1, include_daily=True))

        # Should get daily + 1 random = 2
        assert len(exercises) == 2
        assert all(isinstance(e, TacticExercise) for e in exercises)
        assert exercises[0].id.startswith("chesscom:daily:")
        assert exercises[1].id.startswith("chesscom:random:")

    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    @patch("src.importers.chesscom_puzzles.get_daily_puzzle")
    def test_fetch_no_daily(self, mock_daily, mock_random):
        mock_random.return_value = SAMPLE_RANDOM_PUZZLE

        importer = ChessComPuzzleImporter()
        exercises = list(importer.fetch(count=1, include_daily=False))

        assert len(exercises) == 1
        mock_daily.assert_not_called()
        assert exercises[0].id.startswith("chesscom:random:")

    @patch("src.importers.chesscom_puzzles.get_daily_puzzle")
    def test_daily_error_continues(self, mock_daily):
        mock_daily.side_effect = ChessComError("Fail")

        importer = ChessComPuzzleImporter()
        exercises = list(importer.fetch(count=0, include_daily=True))

        # Daily failed, count=0 so no randoms
        assert len(exercises) == 0

    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    def test_random_error_continues(self, mock_random):
        calls = [0]

        def side_effect(**kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise ChessComError("Fail")
            return SAMPLE_RANDOM_PUZZLE

        mock_random.side_effect = side_effect

        importer = ChessComPuzzleImporter()
        exercises = list(importer.fetch(count=1, include_daily=False))

        assert len(exercises) == 1

    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    def test_dedup_random_puzzles(self, mock_random):
        # Same puzzle returned twice
        mock_random.return_value = SAMPLE_RANDOM_PUZZLE

        importer = ChessComPuzzleImporter()
        exercises = list(importer.fetch(count=2, include_daily=False))

        # Should only get 1 unique exercise despite requesting 2
        # (max_attempts will stop the loop)
        assert len(exercises) == 1

    def test_convert_puzzle_daily(self):
        importer = ChessComPuzzleImporter()
        exercise = importer._convert_puzzle(SAMPLE_DAILY_PUZZLE, is_daily=True)

        assert exercise is not None
        assert exercise.id == f"chesscom:daily:{SAMPLE_DAILY_PUZZLE['publish_time']}"
        assert exercise.source == "chesscom"
        assert "tactic" in exercise.tags
        assert "chesscom_daily" in exercise.tags
        assert exercise.fen == SAMPLE_DAILY_PUZZLE["fen"]
        assert exercise.source_url == SAMPLE_DAILY_PUZZLE["url"]
        assert exercise.difficulty is None

    def test_convert_puzzle_random(self):
        importer = ChessComPuzzleImporter()
        exercise = importer._convert_puzzle(SAMPLE_RANDOM_PUZZLE, is_daily=False)

        assert exercise is not None
        assert exercise.id.startswith("chesscom:random:")
        assert exercise.source == "chesscom"
        assert "tactic" in exercise.tags
        assert "chesscom_daily" not in exercise.tags

    def test_convert_puzzle_random_id_is_stable(self):
        importer = ChessComPuzzleImporter()
        e1 = importer._convert_puzzle(SAMPLE_RANDOM_PUZZLE, is_daily=False)
        e2 = importer._convert_puzzle(SAMPLE_RANDOM_PUZZLE, is_daily=False)
        assert e1.id == e2.id

    def test_convert_puzzle_different_fen_different_id(self):
        importer = ChessComPuzzleImporter()
        # Use a valid FEN+PGN combo that differs from SAMPLE_RANDOM_PUZZLE
        puzzle2 = dict(
            SAMPLE_RANDOM_PUZZLE,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            pgn="1... e5",
        )
        e1 = importer._convert_puzzle(SAMPLE_RANDOM_PUZZLE, is_daily=False)
        e2 = importer._convert_puzzle(puzzle2, is_daily=False)
        assert e1 is not None
        assert e2 is not None
        assert e1.id != e2.id

    def test_convert_puzzle_empty_fen_returns_none(self):
        importer = ChessComPuzzleImporter()
        result = importer._convert_puzzle({"fen": "", "pgn": "1. e4"})
        assert result is None

    def test_convert_puzzle_empty_pgn_returns_none(self):
        importer = ChessComPuzzleImporter()
        result = importer._convert_puzzle(
            {"fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "pgn": ""}
        )
        assert result is None

    def test_convert_puzzle_multi_move_solution(self):
        importer = ChessComPuzzleImporter()
        exercise = importer._convert_puzzle(SAMPLE_MULTI_MOVE_PUZZLE, is_daily=False)

        assert exercise is not None
        assert len(exercise.solution) >= 1  # At least one UCI move parsed

    def test_parse_solution_pgn_basic(self):
        importer = ChessComPuzzleImporter()
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        uci_moves = importer._parse_solution_pgn(fen, "1... e5 2. Nf3")
        assert len(uci_moves) == 2
        assert uci_moves[0] == "e7e5"
        assert uci_moves[1] == "g1f3"

    def test_parse_solution_pgn_with_comments(self):
        importer = ChessComPuzzleImporter()
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        uci = importer._parse_solution_pgn(fen, "1. e4 {best move} e5 {reply}")
        assert len(uci) == 2

    def test_parse_solution_pgn_empty(self):
        importer = ChessComPuzzleImporter()
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        uci = importer._parse_solution_pgn(fen, "")
        assert uci == []

    def test_user_agent_passed_to_api(self):
        importer = ChessComPuzzleImporter(user_agent="Test/1.0")
        assert importer._user_agent == "Test/1.0"

    @patch("src.importers.chesscom_puzzles.get_random_puzzle")
    @patch("src.importers.chesscom_puzzles.get_daily_puzzle")
    def test_import_to_store(self, mock_daily, mock_random):
        mock_daily.return_value = SAMPLE_DAILY_PUZZLE
        mock_random.return_value = SAMPLE_RANDOM_PUZZLE

        store = MagicMock()
        importer = ChessComPuzzleImporter()
        result = importer.import_to(store, count=1, include_daily=True)

        assert result.source == "Chess.com Puzzles"
        assert result.total_fetched >= 1
        assert store.add.called


# ---------------------------------------------------------------------------
# ChessComGameImporter
# ---------------------------------------------------------------------------


class TestChessComGameImporter:
    def test_source_name(self):
        importer = ChessComGameImporter()
        assert importer.source_name == "Chess.com Game Analysis"

    def test_fetch_no_username_yields_nothing(self):
        importer = ChessComGameImporter()
        exercises = list(importer.fetch())
        assert exercises == []

    def test_fetch_no_engine_yields_nothing(self):
        importer = ChessComGameImporter(engine=None)
        exercises = list(importer.fetch(username="alice"))
        assert exercises == []

    @patch("src.importers.chesscom_games.get_recent_games")
    def test_skips_variant_games(self, mock_games):
        variant_game = dict(SAMPLE_GAME_DICT, rules="chess960")
        mock_games.return_value = iter([variant_game])

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        exercises = list(importer.fetch(username="alice"))
        assert exercises == []

    @patch("src.importers.chesscom_games.get_recent_games")
    def test_filters_by_time_class(self, mock_games):
        blitz_game = dict(SAMPLE_GAME_DICT, time_class="blitz")
        mock_games.return_value = iter([blitz_game])

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        exercises = list(importer.fetch(username="alice", time_class="rapid"))
        assert exercises == []

    @patch("src.importers.chesscom_games.get_recent_games")
    def test_filters_by_rated(self, mock_games):
        unrated_game = dict(SAMPLE_GAME_DICT, rated=False)
        mock_games.return_value = iter([unrated_game])

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        exercises = list(importer.fetch(username="alice", rated=True))
        assert exercises == []

    @patch("src.importers.chesscom_games.get_recent_games")
    def test_skips_games_without_pgn(self, mock_games):
        no_pgn_game = dict(SAMPLE_GAME_DICT, pgn="")
        mock_games.return_value = iter([no_pgn_game])

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        exercises = list(importer.fetch(username="alice"))
        assert exercises == []

    @patch("src.importers.chesscom_games.MistakeDetector")
    @patch("src.importers.chesscom_games.EnginePositionAnalyzer")
    @patch("src.importers.chesscom_games.get_recent_games")
    def test_determines_user_color_white(self, mock_games, mock_analyzer, mock_detector):
        mock_games.return_value = iter([SAMPLE_GAME_DICT])

        mock_det_instance = MagicMock()
        mock_det_instance.generate_exercises.return_value = iter([])
        mock_detector.return_value = mock_det_instance

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        list(importer.fetch(username="alice"))

        # Should detect alice as white
        call_kwargs = mock_det_instance.generate_exercises.call_args[1]
        assert call_kwargs["color"] == "white"

    @patch("src.importers.chesscom_games.MistakeDetector")
    @patch("src.importers.chesscom_games.EnginePositionAnalyzer")
    @patch("src.importers.chesscom_games.get_recent_games")
    def test_determines_user_color_black(self, mock_games, mock_analyzer, mock_detector):
        mock_games.return_value = iter([SAMPLE_GAME_DICT])

        mock_det_instance = MagicMock()
        mock_det_instance.generate_exercises.return_value = iter([])
        mock_detector.return_value = mock_det_instance

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        list(importer.fetch(username="bob"))

        call_kwargs = mock_det_instance.generate_exercises.call_args[1]
        assert call_kwargs["color"] == "black"

    @patch("src.importers.chesscom_games.MistakeDetector")
    @patch("src.importers.chesscom_games.EnginePositionAnalyzer")
    @patch("src.importers.chesscom_games.get_recent_games")
    def test_color_override(self, mock_games, mock_analyzer, mock_detector):
        mock_games.return_value = iter([SAMPLE_GAME_DICT])

        mock_det_instance = MagicMock()
        mock_det_instance.generate_exercises.return_value = iter([])
        mock_detector.return_value = mock_det_instance

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        list(importer.fetch(username="alice", color="black"))

        call_kwargs = mock_det_instance.generate_exercises.call_args[1]
        assert call_kwargs["color"] == "black"

    @patch("src.importers.chesscom_games.MistakeDetector")
    @patch("src.importers.chesscom_games.EnginePositionAnalyzer")
    @patch("src.importers.chesscom_games.get_recent_games")
    def test_game_id_format(self, mock_games, mock_analyzer, mock_detector):
        mock_games.return_value = iter([SAMPLE_GAME_DICT])

        mock_det_instance = MagicMock()
        mock_det_instance.generate_exercises.return_value = iter([])
        mock_detector.return_value = mock_det_instance

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        list(importer.fetch(username="alice"))

        call_kwargs = mock_det_instance.generate_exercises.call_args[1]
        assert call_kwargs["game_id"].startswith("chesscom:")
        assert call_kwargs["source_url"] == SAMPLE_GAME_DICT["url"]

    @patch("src.importers.chesscom_games.get_recent_games")
    def test_api_error_returns_empty(self, mock_games):
        mock_games.side_effect = ChessComError("Fail")

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        exercises = list(importer.fetch(username="alice"))
        assert exercises == []

    @patch("src.importers.chesscom_games.MistakeDetector")
    @patch("src.importers.chesscom_games.EnginePositionAnalyzer")
    @patch("src.importers.chesscom_games.get_recent_games")
    def test_passes_user_agent_and_delay(self, mock_games, mock_analyzer, mock_detector):
        mock_games.return_value = iter([])

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        list(importer.fetch(username="alice", user_agent="Test/1.0", request_delay=1.5))

        call_kwargs = mock_games.call_args[1]
        assert call_kwargs["user_agent"] == "Test/1.0"
        assert call_kwargs["request_delay"] == 1.5

    @patch("src.importers.chesscom_games.MistakeDetector")
    @patch("src.importers.chesscom_games.EnginePositionAnalyzer")
    @patch("src.importers.chesscom_games.get_recent_games")
    def test_case_insensitive_username_match(self, mock_games, mock_analyzer, mock_detector):
        game = dict(SAMPLE_GAME_DICT)
        game["white"]["username"] = "Alice"  # Capital A
        mock_games.return_value = iter([game])

        mock_det_instance = MagicMock()
        mock_det_instance.generate_exercises.return_value = iter([])
        mock_detector.return_value = mock_det_instance

        engine = MagicMock()
        importer = ChessComGameImporter(engine=engine)
        list(importer.fetch(username="alice"))  # lowercase

        call_kwargs = mock_det_instance.generate_exercises.call_args[1]
        assert call_kwargs["color"] == "white"
