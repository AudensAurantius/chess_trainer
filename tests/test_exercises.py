"""Tests for exercise domain model."""

from datetime import datetime

import chess
import pytest

from src.exercises import ExerciseResult, ExerciseType, TacticExercise


class TestExerciseResult:
    """Tests for ExerciseResult.grade property."""

    def _make_result(self, correct, partial_credit, time_ms):
        return ExerciseResult(
            correct=correct,
            partial_credit=partial_credit,
            time_taken_ms=time_ms,
            moves_played=[],
            expected_moves=[],
            feedback="",
        )

    def test_grade_wrong_no_credit(self):
        result = self._make_result(False, 0.0, 5000)
        assert result.grade == 1

    def test_grade_wrong_low_credit(self):
        result = self._make_result(False, 0.3, 5000)
        assert result.grade == 1

    def test_grade_wrong_high_credit(self):
        result = self._make_result(False, 0.6, 5000)
        assert result.grade == 2

    def test_grade_correct_slow(self):
        result = self._make_result(True, 1.0, 40000)
        assert result.grade == 3

    def test_grade_correct_normal(self):
        result = self._make_result(True, 1.0, 15000)
        assert result.grade == 3

    def test_grade_correct_fast(self):
        result = self._make_result(True, 1.0, 5000)
        assert result.grade == 4


class TestTacticExercise:
    """Tests for TacticExercise evaluation and serialization."""

    FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"

    def _make_tactic(self, solution=None):
        return TacticExercise(
            id="test:t1",
            fen=self.FEN,
            tags=["fork"],
            source="test",
            difficulty=1500.0,
            created_at=datetime(2025, 1, 1),
            solution=solution or ["g7g6"],
            themes=["fork"],
        )

    def test_position_loads(self):
        ex = self._make_tactic()
        board = ex.position
        assert board.turn == chess.BLACK

    def test_side_to_move(self):
        ex = self._make_tactic()
        assert ex.side_to_move == "Black"

    def test_get_solution_returns_moves(self):
        ex = self._make_tactic()
        solution = ex.get_solution()
        assert len(solution) == 1
        assert isinstance(solution[0], chess.Move)
        assert solution[0] == chess.Move.from_uci("g7g6")

    def test_evaluate_correct(self):
        ex = self._make_tactic()
        correct_move = chess.Move.from_uci("g7g6")
        result = ex.evaluate([correct_move], 5000)
        assert result.correct is True
        assert result.partial_credit == 1.0

    def test_evaluate_wrong(self):
        ex = self._make_tactic()
        wrong_move = chess.Move.from_uci("g8f6")
        result = ex.evaluate([wrong_move], 5000)
        assert result.correct is False
        assert result.partial_credit == 0.0

    def test_evaluate_empty_moves(self):
        ex = self._make_tactic()
        result = ex.evaluate([], 0)
        assert result.correct is False
        assert result.partial_credit == 0.0

    def test_evaluate_multi_move_partial(self):
        # Multi-move solution: user/opponent alternating
        ex = self._make_tactic(solution=["g7g6", "h5f3", "g8f6"])
        # User plays first move correctly but fails second
        correct_first = chess.Move.from_uci("g7g6")
        wrong_second = chess.Move.from_uci("d7d6")
        result = ex.evaluate([correct_first, wrong_second], 5000)
        assert result.correct is False
        assert result.partial_credit == pytest.approx(0.5)

    def test_get_challenge(self):
        ex = self._make_tactic()
        assert "Black" in ex.get_challenge()
        assert "best move" in ex.get_challenge()

    def test_get_explanation(self):
        ex = self._make_tactic()
        explanation = ex.get_explanation()
        assert "Solution" in explanation
        assert "fork" in explanation

    def test_to_dict_from_dict_roundtrip(self):
        ex = self._make_tactic()
        data = ex.to_dict()
        restored = TacticExercise.from_dict(data)
        assert restored.id == ex.id
        assert restored.fen == ex.fen
        assert restored.solution == ex.solution
        assert restored.themes == ex.themes
        assert restored.tags == ex.tags
        assert restored.difficulty == ex.difficulty

    def test_exercise_type(self):
        ex = self._make_tactic()
        assert ex.exercise_type == ExerciseType.TACTIC
