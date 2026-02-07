"""Tests for opening, endgame, and positional exercise types."""

from datetime import datetime

import chess
import pytest

from src.exercises import ExerciseType
from src.exercises.endgames import EndgameExercise
from src.exercises.openings import OpeningExercise
from src.exercises.positional import PositionalExercise

# Position after 1. e4 e5 2. Nf3 Nc6 — White to play
RUY_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"

# Simple KP vs K endgame — White to play
ENDGAME_FEN = "8/8/8/3k4/8/3K4/3P4/8 w - - 0 1"

# Italian Game middlegame — White to play
POSITIONAL_FEN = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"


# ---------------------------------------------------------------------------
# OpeningExercise
# ---------------------------------------------------------------------------


class TestOpeningExercise:
    """Tests for OpeningExercise domain model."""

    def _make_opening(self, **overrides):
        defaults = dict(
            id="open:1",
            fen=RUY_FEN,
            tags=["opening", "ruy-lopez"],
            source="test",
            created_at=datetime(2025, 6, 1),
            line=["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"],
            current_move_index=4,  # Testing Bb5
            opening_name="Ruy Lopez",
            variation_name="",
            eco_code="C60",
            alternative_moves=["f1c4"],  # Italian is also acceptable
        )
        defaults.update(overrides)
        return OpeningExercise(**defaults)

    def test_exercise_type(self):
        ex = self._make_opening()
        assert ex.exercise_type == ExerciseType.OPENING

    def test_side_to_move(self):
        ex = self._make_opening()
        assert ex.side_to_move == "White"

    def test_get_challenge_with_name(self):
        ex = self._make_opening()
        challenge = ex.get_challenge()
        assert "White" in challenge
        assert "Ruy Lopez" in challenge

    def test_get_challenge_with_variation(self):
        ex = self._make_opening(variation_name="Exchange")
        challenge = ex.get_challenge()
        assert "Exchange" in challenge
        assert "Ruy Lopez" in challenge

    def test_get_solution(self):
        ex = self._make_opening()
        solution = ex.get_solution()
        assert len(solution) == 1
        assert solution[0] == chess.Move.from_uci("f1b5")

    def test_get_solution_index_out_of_range(self):
        ex = self._make_opening(current_move_index=99)
        assert ex.get_solution() == []

    def test_evaluate_correct(self):
        ex = self._make_opening()
        move = chess.Move.from_uci("f1b5")
        result = ex.evaluate([move], 5000)
        assert result.correct is True
        assert result.partial_credit == 1.0
        assert "main line" in result.feedback

    def test_evaluate_alternative_gives_partial_credit(self):
        ex = self._make_opening()
        alt_move = chess.Move.from_uci("f1c4")  # Italian
        result = ex.evaluate([alt_move], 5000)
        assert result.correct is False
        assert result.partial_credit == pytest.approx(0.7)
        assert "playable" in result.feedback

    def test_evaluate_wrong_move(self):
        ex = self._make_opening()
        wrong = chess.Move.from_uci("d2d3")
        result = ex.evaluate([wrong], 5000)
        assert result.correct is False
        assert result.partial_credit == 0.0
        assert "not theory" in result.feedback

    def test_evaluate_empty(self):
        ex = self._make_opening()
        result = ex.evaluate([], 0)
        assert result.correct is False
        assert result.partial_credit == 0.0
        assert "No move" in result.feedback

    def test_get_explanation_basic(self):
        ex = self._make_opening()
        explanation = ex.get_explanation()
        assert "Ruy Lopez" in explanation
        assert "C60" in explanation

    def test_get_explanation_with_variation(self):
        ex = self._make_opening(variation_name="Exchange")
        explanation = ex.get_explanation()
        assert "Exchange" in explanation

    def test_get_explanation_with_alternatives(self):
        ex = self._make_opening()
        explanation = ex.get_explanation()
        assert "Alternative" in explanation

    def test_get_explanation_no_line(self):
        ex = self._make_opening(line=[])
        assert "No line" in ex.get_explanation()

    def test_to_dict_from_dict_roundtrip(self):
        ex = self._make_opening(variation_name="Exchange")
        data = ex.to_dict()
        restored = OpeningExercise.from_dict(data)
        assert restored.id == ex.id
        assert restored.fen == ex.fen
        assert restored.line == ex.line
        assert restored.current_move_index == ex.current_move_index
        assert restored.eco_code == ex.eco_code
        assert restored.opening_name == ex.opening_name
        assert restored.variation_name == ex.variation_name
        assert restored.alternative_moves == ex.alternative_moves
        assert restored.tags == ex.tags
        assert restored.difficulty == ex.difficulty

    def test_from_dict_minimal(self):
        data = {
            "id": "open:min",
            "fen": RUY_FEN,
            "created_at": datetime(2025, 1, 1).isoformat(),
        }
        ex = OpeningExercise.from_dict(data)
        assert ex.id == "open:min"
        assert ex.line == []
        assert ex.opening_name == ""

    def test_type_specific_dict(self):
        ex = self._make_opening()
        d = ex._type_specific_dict()
        assert "line" in d
        assert "eco_code" in d
        assert "opening_name" in d


# ---------------------------------------------------------------------------
# EndgameExercise
# ---------------------------------------------------------------------------


class TestEndgameExercise:
    """Tests for EndgameExercise domain model."""

    def _make_endgame(self, **overrides):
        defaults = dict(
            id="end:1",
            fen=ENDGAME_FEN,
            tags=["endgame", "KP-vs-K"],
            source="test",
            created_at=datetime(2025, 6, 1),
            technique_name="Opposition",
            key_ideas=["Maintain direct opposition", "Advance pawn when opponent yields"],
            key_squares=["d4", "d5", "e4", "e5"],
            acceptable_first_moves=["d3e3"],  # Kd3-e3 takes opposition
            tablebase_eval=None,
            target_outcome="win",
        )
        defaults.update(overrides)
        return EndgameExercise(**defaults)

    def test_exercise_type(self):
        ex = self._make_endgame()
        assert ex.exercise_type == ExerciseType.ENDGAME

    def test_side_to_move(self):
        ex = self._make_endgame()
        assert ex.side_to_move == "White"

    def test_get_challenge_with_technique(self):
        ex = self._make_endgame()
        challenge = ex.get_challenge()
        assert "White" in challenge
        assert "Opposition" in challenge

    def test_get_challenge_win(self):
        ex = self._make_endgame(technique_name="", target_outcome="win")
        challenge = ex.get_challenge()
        assert "win" in challenge.lower()

    def test_get_challenge_draw(self):
        ex = self._make_endgame(technique_name="", target_outcome="draw")
        challenge = ex.get_challenge()
        assert "draw" in challenge.lower()

    def test_get_challenge_default(self):
        ex = self._make_endgame(technique_name="", target_outcome="hold")
        challenge = ex.get_challenge()
        assert "best continuation" in challenge.lower()

    def test_get_solution(self):
        ex = self._make_endgame()
        solution = ex.get_solution()
        assert len(solution) == 1
        assert solution[0] == chess.Move.from_uci("d3e3")

    def test_evaluate_correct(self):
        ex = self._make_endgame()
        move = chess.Move.from_uci("d3e3")
        result = ex.evaluate([move], 5000)
        assert result.correct is True
        assert result.partial_credit == 1.0
        assert "technique" in result.feedback

    def test_evaluate_wrong(self):
        ex = self._make_endgame()
        wrong = chess.Move.from_uci("d3c3")
        result = ex.evaluate([wrong], 5000)
        assert result.correct is False
        assert result.partial_credit == 0.0
        assert "doesn't demonstrate" in result.feedback

    def test_evaluate_empty(self):
        ex = self._make_endgame()
        result = ex.evaluate([], 0)
        assert result.correct is False
        assert "No move" in result.feedback

    def test_get_explanation_full(self):
        ex = self._make_endgame(tablebase_eval=5)
        explanation = ex.get_explanation()
        assert "Opposition" in explanation
        assert "Key ideas" in explanation
        assert "Key squares" in explanation
        assert "DTZ: 5" in explanation

    def test_get_explanation_empty(self):
        ex = self._make_endgame(
            technique_name="",
            key_ideas=[],
            key_squares=[],
            acceptable_first_moves=[],
            tablebase_eval=None,
        )
        assert "No explanation" in ex.get_explanation()

    def test_get_explanation_moves_listed(self):
        ex = self._make_endgame()
        explanation = ex.get_explanation()
        assert "Correct moves" in explanation

    def test_to_dict_from_dict_roundtrip(self):
        ex = self._make_endgame(tablebase_eval=12)
        data = ex.to_dict()
        restored = EndgameExercise.from_dict(data)
        assert restored.id == ex.id
        assert restored.fen == ex.fen
        assert restored.technique_name == ex.technique_name
        assert restored.key_ideas == ex.key_ideas
        assert restored.key_squares == ex.key_squares
        assert restored.acceptable_first_moves == ex.acceptable_first_moves
        assert restored.tablebase_eval == ex.tablebase_eval
        assert restored.target_outcome == ex.target_outcome
        assert restored.winning_side == ex.winning_side

    def test_from_dict_minimal(self):
        data = {
            "id": "end:min",
            "fen": ENDGAME_FEN,
            "created_at": datetime(2025, 1, 1).isoformat(),
        }
        ex = EndgameExercise.from_dict(data)
        assert ex.id == "end:min"
        assert ex.acceptable_first_moves == []
        assert ex.technique_name == ""

    def test_type_specific_dict(self):
        ex = self._make_endgame()
        d = ex._type_specific_dict()
        assert "technique_name" in d
        assert "key_ideas" in d
        assert "acceptable_first_moves" in d
        assert "tablebase_eval" in d
        assert "target_outcome" in d


# ---------------------------------------------------------------------------
# PositionalExercise
# ---------------------------------------------------------------------------


class TestPositionalExercise:
    """Tests for PositionalExercise domain model."""

    def _make_positional(self, **overrides):
        defaults = dict(
            id="pos:1",
            fen=POSITIONAL_FEN,
            tags=["positional", "center"],
            source="test",
            created_at=datetime(2025, 6, 1),
            concept="Center control",
            question="",
            correct_moves=["d2d3", "c2c3"],
            explanation_text="Solidify the center before expanding on the wings.",
            key_features=["Open e-file", "Pawn tension in center"],
            wrong_ideas=["Premature wing attack without center control"],
        )
        defaults.update(overrides)
        return PositionalExercise(**defaults)

    def test_exercise_type(self):
        ex = self._make_positional()
        assert ex.exercise_type == ExerciseType.POSITIONAL

    def test_side_to_move(self):
        ex = self._make_positional()
        assert ex.side_to_move == "White"

    def test_get_challenge_with_question(self):
        ex = self._make_positional(question="What is the best plan?")
        assert ex.get_challenge() == "What is the best plan?"

    def test_get_challenge_with_concept(self):
        ex = self._make_positional(question="")
        challenge = ex.get_challenge()
        assert "Center control" in challenge

    def test_get_challenge_default(self):
        ex = self._make_positional(question="", concept="")
        challenge = ex.get_challenge()
        assert "best plan" in challenge.lower()

    def test_get_solution(self):
        ex = self._make_positional()
        solution = ex.get_solution()
        assert len(solution) == 2
        assert chess.Move.from_uci("d2d3") in solution
        assert chess.Move.from_uci("c2c3") in solution

    def test_evaluate_correct_first_move(self):
        ex = self._make_positional()
        move = chess.Move.from_uci("d2d3")
        result = ex.evaluate([move], 5000)
        assert result.correct is True
        assert result.partial_credit == 1.0
        assert "concept" in result.feedback

    def test_evaluate_correct_second_move(self):
        ex = self._make_positional()
        move = chess.Move.from_uci("c2c3")
        result = ex.evaluate([move], 5000)
        assert result.correct is True

    def test_evaluate_wrong(self):
        ex = self._make_positional()
        wrong = chess.Move.from_uci("a2a4")
        result = ex.evaluate([wrong], 5000)
        assert result.correct is False
        assert result.partial_credit == 0.0
        assert "doesn't demonstrate" in result.feedback

    def test_evaluate_empty(self):
        ex = self._make_positional()
        result = ex.evaluate([], 0)
        assert result.correct is False
        assert "No move" in result.feedback

    def test_get_explanation_full(self):
        ex = self._make_positional()
        explanation = ex.get_explanation()
        assert "Center control" in explanation
        assert "Key features" in explanation
        assert "Correct moves" in explanation
        assert "Solidify" in explanation
        assert "Common mistakes" in explanation

    def test_get_explanation_empty(self):
        ex = self._make_positional(
            concept="",
            key_features=[],
            correct_moves=[],
            explanation_text="",
            wrong_ideas=[],
        )
        assert "No explanation" in ex.get_explanation()

    def test_to_dict_from_dict_roundtrip(self):
        ex = self._make_positional(question="What is the plan?")
        data = ex.to_dict()
        restored = PositionalExercise.from_dict(data)
        assert restored.id == ex.id
        assert restored.fen == ex.fen
        assert restored.concept == ex.concept
        assert restored.question == ex.question
        assert restored.correct_moves == ex.correct_moves
        assert restored.explanation_text == ex.explanation_text
        assert restored.key_features == ex.key_features
        assert restored.wrong_ideas == ex.wrong_ideas
        assert restored.tags == ex.tags

    def test_from_dict_minimal(self):
        data = {
            "id": "pos:min",
            "fen": POSITIONAL_FEN,
            "created_at": datetime(2025, 1, 1).isoformat(),
        }
        ex = PositionalExercise.from_dict(data)
        assert ex.id == "pos:min"
        assert ex.concept == ""
        assert ex.correct_moves == []

    def test_type_specific_dict(self):
        ex = self._make_positional()
        d = ex._type_specific_dict()
        assert "concept" in d
        assert "question" in d
        assert "correct_moves" in d
        assert "explanation_text" in d
        assert "key_features" in d
        assert "wrong_ideas" in d
