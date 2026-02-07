"""Tests for the Lichess puzzle importer."""

import chess

from src.exercises import TacticExercise
from src.importers.lichess_puzzles import LichessPuzzleImporter

# Sample Lichess API response (minimal but valid)
SAMPLE_PUZZLE_DATA = {
    "game": {
        "id": "abc123",
        "pgn": "e4 e5 Bc4 Nc6 Qh5",
    },
    "puzzle": {
        "id": "ABCDE",
        "rating": 1500,
        "plays": 1000,
        "solution": ["g7g6"],
        "themes": ["fork", "short"],
        "initialPly": 5,
    },
}


class TestLichessPuzzleImporter:
    """Tests for LichessPuzzleImporter."""

    def test_convert_puzzle(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_puzzle(SAMPLE_PUZZLE_DATA)
        assert isinstance(exercise, TacticExercise)
        assert exercise.id == "lichess:ABCDE"
        assert exercise.source == "lichess"
        assert exercise.difficulty == 1500
        assert exercise.game_id == "abc123"

    def test_convert_puzzle_themes(self):
        importer = LichessPuzzleImporter()
        exercise = importer._convert_puzzle(SAMPLE_PUZZLE_DATA)
        assert "fork" in exercise.themes
        assert "short" in exercise.themes

    def test_position_from_pgn_simple(self):
        importer = LichessPuzzleImporter()
        board = importer._position_from_pgn("e4 e5 Nf3")
        # After 1. e4 e5 2. Nf3 — white knight on f3
        assert board.piece_at(chess.F3) is not None
        assert board.piece_at(chess.F3).piece_type == chess.KNIGHT

    def test_position_from_pgn_empty(self):
        importer = LichessPuzzleImporter()
        board = importer._position_from_pgn("")
        # Should return starting position
        assert board.fen().startswith("rnbqkbnr/pppppppp")

    def test_map_themes_adds_tactic_tag(self):
        importer = LichessPuzzleImporter()
        tags = importer._map_themes(["fork", "short"])
        assert "tactic" in tags

    def test_map_themes_adds_mating_tag(self):
        importer = LichessPuzzleImporter()
        tags = importer._map_themes(["mateIn2", "sacrifice"])
        assert "mating_pattern" in tags

    def test_map_themes_no_double_add(self):
        importer = LichessPuzzleImporter()
        tags = importer._map_themes(["fork", "pin"])
        assert tags.count("tactic") == 1

    def test_source_name(self):
        importer = LichessPuzzleImporter()
        assert importer.source_name == "Lichess Puzzles"

    def test_convert_puzzle_solution_skips_setup(self):
        """The first move in Lichess solution is the opponent's setup move."""
        data = {
            "game": {"id": "g1", "pgn": "e4 e5"},
            "puzzle": {
                "id": "P1",
                "rating": 1200,
                "plays": 100,
                "solution": ["b1c3", "d7d5", "c3d5"],
                "themes": ["fork"],
                "initialPly": 2,
            },
        }
        importer = LichessPuzzleImporter()
        exercise = importer._convert_puzzle(data)
        # First move (b1c3) is the setup move, should be excluded from solution
        assert "b1c3" not in exercise.solution
        assert exercise.solution == ["d7d5", "c3d5"]
