"""Tests for the exercise creation factory."""

import pytest

from src.exercises.endgames import EndgameExercise
from src.exercises.factory import (
    ExerciseCreationError,
    create_exercise,
    generate_exercise_id,
    validate_fen,
    validate_moves,
    validate_single_moves,
)
from src.exercises.openings import OpeningExercise
from src.exercises.positional import PositionalExercise
from src.exercises.tactics import TacticExercise

# Standard starting position
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
# After 1.e4
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
# Mate in 1: Kh1 vs Qg2#
MATE_FEN = "7k/8/8/8/8/8/6q1/7K w - - 0 1"
# KP vs K endgame
ENDGAME_FEN = "8/8/8/8/8/4K3/4P3/4k3 w - - 0 1"


class TestValidateFen:
    def test_valid_starting_position(self):
        board = validate_fen(START_FEN)
        assert board.fen() == START_FEN

    def test_valid_mid_game(self):
        board = validate_fen(AFTER_E4_FEN)
        assert not board.turn  # Black to move

    def test_invalid_fen_garbage(self):
        with pytest.raises(ExerciseCreationError, match="Invalid FEN"):
            validate_fen("not a fen")

    def test_invalid_fen_wrong_piece_count(self):
        with pytest.raises(ExerciseCreationError, match="Invalid FEN"):
            validate_fen("rnbqkbnr/pppppppp/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


class TestValidateMoves:
    def test_valid_single_move(self):
        board = validate_fen(START_FEN)
        result = validate_moves(board, ["e2e4"])
        assert result == ["e2e4"]

    def test_valid_sequence(self):
        board = validate_fen(START_FEN)
        result = validate_moves(board, ["e2e4", "e7e5", "g1f3"])
        assert result == ["e2e4", "e7e5", "g1f3"]

    def test_empty_moves_raises(self):
        board = validate_fen(START_FEN)
        with pytest.raises(ExerciseCreationError, match="At least one move"):
            validate_moves(board, [])

    def test_illegal_move_raises(self):
        board = validate_fen(START_FEN)
        with pytest.raises(ExerciseCreationError, match="Illegal move at position 1"):
            validate_moves(board, ["e7e5"])  # Black pawn can't move on White's turn

    def test_illegal_second_move_raises(self):
        board = validate_fen(START_FEN)
        with pytest.raises(ExerciseCreationError, match="Illegal move at position 2"):
            validate_moves(board, ["e2e4", "e2e4"])  # White can't move again

    def test_invalid_uci_notation(self):
        board = validate_fen(START_FEN)
        with pytest.raises(ExerciseCreationError, match="Invalid UCI notation"):
            validate_moves(board, ["xyz"])

    def test_does_not_mutate_board(self):
        board = validate_fen(START_FEN)
        original_fen = board.fen()
        validate_moves(board, ["e2e4", "e7e5"])
        assert board.fen() == original_fen


class TestValidateSingleMoves:
    def test_valid_moves_from_same_position(self):
        board = validate_fen(START_FEN)
        result = validate_single_moves(board, ["e2e4", "d2d4", "g1f3"])
        assert result == ["e2e4", "d2d4", "g1f3"]

    def test_empty_raises(self):
        board = validate_fen(START_FEN)
        with pytest.raises(ExerciseCreationError, match="At least one move"):
            validate_single_moves(board, [])

    def test_illegal_move_raises(self):
        board = validate_fen(START_FEN)
        with pytest.raises(ExerciseCreationError, match="Illegal move from this position"):
            validate_single_moves(board, ["e7e5"])

    def test_invalid_uci_raises(self):
        board = validate_fen(START_FEN)
        with pytest.raises(ExerciseCreationError, match="Invalid UCI notation"):
            validate_single_moves(board, ["bad"])


class TestGenerateExerciseId:
    def test_without_slug_uses_uuid(self):
        eid = generate_exercise_id()
        assert eid.startswith("custom:")
        # UUID part should be 36 chars
        assert len(eid.split(":", 1)[1]) == 36

    def test_with_valid_slug(self):
        assert generate_exercise_id("my-tactic") == "custom:my-tactic"

    def test_slug_min_length(self):
        assert generate_exercise_id("ab") == "custom:ab"

    def test_slug_max_length(self):
        slug = "a" * 64
        assert generate_exercise_id(slug) == f"custom:{slug}"

    def test_slug_too_short(self):
        with pytest.raises(ExerciseCreationError, match="Slug must be"):
            generate_exercise_id("a")

    def test_slug_too_long(self):
        with pytest.raises(ExerciseCreationError, match="Slug must be"):
            generate_exercise_id("a" * 65)

    def test_slug_starts_with_hyphen(self):
        with pytest.raises(ExerciseCreationError, match="Slug must be"):
            generate_exercise_id("-bad")

    def test_slug_ends_with_hyphen(self):
        with pytest.raises(ExerciseCreationError, match="Slug must be"):
            generate_exercise_id("bad-")

    def test_slug_uppercase_rejected(self):
        with pytest.raises(ExerciseCreationError, match="Slug must be"):
            generate_exercise_id("BadSlug")

    def test_slug_special_chars_rejected(self):
        with pytest.raises(ExerciseCreationError, match="Slug must be"):
            generate_exercise_id("bad_slug")


class TestCreateTactic:
    def test_basic_tactic(self):
        ex = create_exercise("tactic", AFTER_E4_FEN, moves=["e7e5", "d2d4"])
        assert isinstance(ex, TacticExercise)
        assert ex.id.startswith("custom:")
        assert ex.fen == AFTER_E4_FEN
        assert ex.solution == ["e7e5", "d2d4"]
        assert ex.source == "custom"

    def test_with_slug(self):
        ex = create_exercise("tactic", AFTER_E4_FEN, moves=["e7e5"], slug="my-puzzle")
        assert ex.id == "custom:my-puzzle"

    def test_with_tags_and_difficulty(self):
        ex = create_exercise(
            "tactic",
            AFTER_E4_FEN,
            moves=["e7e5"],
            tags=["pin", "middlegame"],
            difficulty=1500.0,
        )
        assert ex.tags == ["pin", "middlegame"]
        assert ex.difficulty == 1500.0

    def test_with_themes(self):
        ex = create_exercise("tactic", AFTER_E4_FEN, moves=["e7e5"], themes=["fork"])
        assert ex.themes == ["fork"]

    def test_with_notes(self):
        ex = create_exercise("tactic", AFTER_E4_FEN, moves=["e7e5"], notes="Study this!")
        assert ex.notes == "Study this!"

    def test_no_moves_raises(self):
        with pytest.raises(ExerciseCreationError, match="require solution moves"):
            create_exercise("tactic", AFTER_E4_FEN)

    def test_illegal_moves_raises(self):
        with pytest.raises(ExerciseCreationError, match="Illegal move"):
            create_exercise("tactic", AFTER_E4_FEN, moves=["e2e4"])  # White can't move

    def test_case_insensitive_type(self):
        ex = create_exercise("TACTIC", AFTER_E4_FEN, moves=["e7e5"])
        assert isinstance(ex, TacticExercise)


class TestCreateEndgame:
    def test_basic_endgame(self):
        ex = create_exercise("endgame", ENDGAME_FEN, moves=["e3d4"])
        assert isinstance(ex, EndgameExercise)
        assert ex.acceptable_first_moves == ["e3d4"]
        assert ex.winning_side is True  # White to move

    def test_with_technique_and_outcome(self):
        ex = create_exercise(
            "endgame",
            ENDGAME_FEN,
            moves=["e3d4"],
            technique="King opposition",
            target_outcome="win",
        )
        assert ex.technique_name == "King opposition"
        assert ex.target_outcome == "win"

    def test_multiple_acceptable_moves(self):
        ex = create_exercise("endgame", ENDGAME_FEN, moves=["e3d4", "e3f4"])
        assert ex.acceptable_first_moves == ["e3d4", "e3f4"]

    def test_no_moves_raises(self):
        with pytest.raises(ExerciseCreationError, match="require acceptable first moves"):
            create_exercise("endgame", ENDGAME_FEN)


class TestCreatePositional:
    def test_basic_positional(self):
        ex = create_exercise("positional", AFTER_E4_FEN, moves=["e7e5"])
        assert isinstance(ex, PositionalExercise)
        assert ex.correct_moves == ["e7e5"]

    def test_with_concept_and_question(self):
        ex = create_exercise(
            "positional",
            AFTER_E4_FEN,
            moves=["e7e5"],
            concept="Center control",
            question="How should Black respond?",
            explanation="Occupying the center with a pawn",
        )
        assert ex.concept == "Center control"
        assert ex.question == "How should Black respond?"
        assert ex.explanation_text == "Occupying the center with a pawn"

    def test_no_moves_raises(self):
        with pytest.raises(ExerciseCreationError, match="require correct moves"):
            create_exercise("positional", AFTER_E4_FEN)


class TestCreateOpening:
    def test_basic_opening(self):
        ex = create_exercise("opening", START_FEN, moves=["e2e4", "e7e5", "g1f3"])
        assert isinstance(ex, OpeningExercise)
        assert ex.line == ["e2e4", "e7e5", "g1f3"]
        assert ex.current_move_index == 0

    def test_with_name_and_eco(self):
        ex = create_exercise(
            "opening",
            START_FEN,
            moves=["e2e4", "e7e5", "g1f3"],
            opening_name="King's Knight",
            eco="C44",
        )
        assert ex.opening_name == "King's Knight"
        assert ex.eco_code == "C44"

    def test_with_move_index(self):
        ex = create_exercise(
            "opening",
            START_FEN,
            moves=["e2e4", "e7e5", "g1f3"],
            move_index=2,
        )
        assert ex.current_move_index == 2

    def test_move_index_out_of_range(self):
        with pytest.raises(ExerciseCreationError, match="Move index .* out of range"):
            create_exercise("opening", START_FEN, moves=["e2e4"], move_index=1)

    def test_negative_move_index(self):
        with pytest.raises(ExerciseCreationError, match="Move index .* out of range"):
            create_exercise("opening", START_FEN, moves=["e2e4"], move_index=-1)

    def test_no_moves_raises(self):
        with pytest.raises(ExerciseCreationError, match="require line moves"):
            create_exercise("opening", START_FEN)


class TestCreateExerciseInvalidType:
    def test_unknown_type_raises(self):
        with pytest.raises(ExerciseCreationError, match="Invalid exercise type"):
            create_exercise("puzzle", START_FEN, moves=["e2e4"])

    def test_invalid_fen_raises(self):
        with pytest.raises(ExerciseCreationError, match="Invalid FEN"):
            create_exercise("tactic", "garbage", moves=["e2e4"])
