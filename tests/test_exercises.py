"""Tests for exercise domain model."""

from datetime import datetime
from unittest.mock import MagicMock

import chess
import pytest

from src.exercises import ExerciseResult, ExerciseType, TacticExercise
from src.exercises.endgames import EndgameExercise
from src.tablebase import TablebaseError, TablebaseMove, TablebaseResult


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


class TestEndgameExerciseTablebase:
    """Tests for EndgameExercise.evaluate() with tablebase integration."""

    # KPK position: White king f3, pawn e2, Black king e1
    FEN = "8/8/8/8/8/5K2/4P3/4k3 w - - 0 1"

    def _make_endgame(self, acceptable_moves=None, target_outcome="win"):
        return EndgameExercise(
            id="test:e1",
            fen=self.FEN,
            tags=["KPK"],
            source="test",
            created_at=datetime(2025, 1, 1),
            winning_side=True,
            technique_name="King and Pawn",
            acceptable_first_moves=acceptable_moves if acceptable_moves is not None else ["e2e4"],
            target_outcome=target_outcome,
        )

    def test_evaluate_without_tablebase_correct(self):
        """Static list check works without tablebase."""
        ex = self._make_endgame()
        result = ex.evaluate([chess.Move.from_uci("e2e4")], 5000)
        assert result.correct is True
        assert result.partial_credit == 1.0

    def test_evaluate_without_tablebase_wrong(self):
        """Static list check rejects move not in list without tablebase."""
        ex = self._make_endgame()
        result = ex.evaluate([chess.Move.from_uci("f3f4")], 5000)
        assert result.correct is False

    def test_evaluate_no_moves(self):
        ex = self._make_endgame()
        result = ex.evaluate([], 0)
        assert result.correct is False
        assert "No move played" in result.feedback

    def test_evaluate_in_static_list_with_tablebase(self):
        """If move is in acceptable list, tablebase is not consulted."""
        mock_tb = MagicMock()
        ex = self._make_endgame()
        result = ex.evaluate([chess.Move.from_uci("e2e4")], 5000, tablebase=mock_tb)
        assert result.correct is True
        mock_tb.probe.assert_not_called()

    def test_evaluate_tablebase_maintains_win(self):
        """Move maintains the winning outcome → correct."""
        mock_tb = MagicMock()
        # Before: winning (wdl=2)
        mock_tb.probe.side_effect = [
            TablebaseResult(
                wdl=2,
                dtz=5,
                category="win",
                moves=[
                    TablebaseMove(uci="e2e4", san="e4", wdl=2, dtz=3, category="win"),
                    TablebaseMove(uci="f3f4", san="Kf4", wdl=2, dtz=7, category="win"),
                ],
            ),
            # After Kf4: opponent view, wdl=-2 (losing for them)
            TablebaseResult(wdl=-2, dtz=-7, category="loss"),
        ]

        ex = self._make_endgame(acceptable_moves=["e2e4"])  # Kf4 not in list
        result = ex.evaluate([chess.Move.from_uci("f3f4")], 5000, tablebase=mock_tb)
        assert result.correct is True
        assert "maintains" in result.feedback

    def test_evaluate_tablebase_worsens_outcome(self):
        """Move changes win to draw → incorrect."""
        mock_tb = MagicMock()
        mock_tb.probe.side_effect = [
            TablebaseResult(wdl=2, dtz=5, category="win", moves=[]),
            # After move: opponent view, wdl=0 (draw for them)
            TablebaseResult(wdl=0, dtz=0, category="draw"),
        ]

        ex = self._make_endgame(acceptable_moves=["e2e4"])
        result = ex.evaluate([chess.Move.from_uci("f3e3")], 5000, tablebase=mock_tb)
        assert result.correct is False
        assert "win" in result.feedback
        assert "draw" in result.feedback

    def test_evaluate_tablebase_improves_outcome(self):
        """Move improves draw to win → correct with full credit."""
        mock_tb = MagicMock()
        mock_tb.probe.side_effect = [
            TablebaseResult(wdl=0, dtz=0, category="draw", moves=[]),
            # After move: opponent loses
            TablebaseResult(wdl=-2, dtz=-5, category="loss"),
        ]

        ex = self._make_endgame(acceptable_moves=[], target_outcome="draw")
        result = ex.evaluate([chess.Move.from_uci("e2e4")], 5000, tablebase=mock_tb)
        assert result.correct is True
        assert result.partial_credit == 1.0

    def test_evaluate_tablebase_optimal_dtz_full_credit(self):
        """Best DTZ move gets full credit."""
        mock_tb = MagicMock()
        mock_tb.probe.side_effect = [
            TablebaseResult(
                wdl=2,
                dtz=3,
                category="win",
                moves=[
                    TablebaseMove(uci="e2e4", san="e4", wdl=2, dtz=3, category="win"),
                ],
            ),
            TablebaseResult(wdl=-2, dtz=-3, category="loss"),
        ]

        ex = self._make_endgame(acceptable_moves=[])
        result = ex.evaluate([chess.Move.from_uci("e2e4")], 5000, tablebase=mock_tb)
        assert result.correct is True
        assert result.partial_credit == 1.0

    def test_evaluate_tablebase_suboptimal_dtz_partial_credit(self):
        """Non-optimal but winning move gets 0.8 credit."""
        mock_tb = MagicMock()
        mock_tb.probe.side_effect = [
            TablebaseResult(
                wdl=2,
                dtz=3,
                category="win",
                moves=[
                    TablebaseMove(uci="e2e4", san="e4", wdl=2, dtz=3, category="win"),
                ],
            ),
            # After Kf4: still winning for us
            TablebaseResult(wdl=-2, dtz=-7, category="loss"),
        ]

        ex = self._make_endgame(acceptable_moves=[])
        result = ex.evaluate([chess.Move.from_uci("f3f4")], 5000, tablebase=mock_tb)
        assert result.correct is True
        assert result.partial_credit == 0.8

    def test_evaluate_tablebase_error_falls_back(self):
        """If tablebase probe fails, falls back to static check."""
        mock_tb = MagicMock()
        mock_tb.probe.side_effect = TablebaseError("Network error")

        ex = self._make_endgame(acceptable_moves=["e2e4"])
        result = ex.evaluate([chess.Move.from_uci("f3f4")], 5000, tablebase=mock_tb)
        assert result.correct is False
        assert "doesn't demonstrate" in result.feedback

    def test_evaluate_tablebase_empty_acceptable_list(self):
        """With empty acceptable list and no tablebase, move is rejected."""
        ex = self._make_endgame(acceptable_moves=[])
        result = ex.evaluate([chess.Move.from_uci("e2e4")], 5000)
        assert result.correct is False
