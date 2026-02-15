"""Integration tests for F16 — Hook emission from web SessionManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import AppConfig, HooksConfig


def _make_manager(tmp_path: Path):
    """Create a SessionManager with hooks pointing at tmp_path."""
    from src.web.session_manager import SessionManager

    config = AppConfig()
    config.hooks = HooksConfig(enabled=True, directory=str(tmp_path / "hooks"))
    config.database.path = str(tmp_path / "trainer.db")
    return SessionManager(config)


# ── Hook emission from rate() ──────────────────────────────────────────────────


class TestRateHookEmission:
    """Verify rate() fires on_exercise_complete."""

    def test_rate_fires_exercise_complete_hook(self, tmp_path):
        mgr = _make_manager(tmp_path)

        # Start a session with a real exercise
        from src.exercises.tactics import TacticExercise

        ex = TacticExercise(
            id="test-1",
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            solution=["e2e4"],
            source="test",
        )

        # Set up the session state manually
        from src.web.session_manager import ExerciseState

        mgr._exercise_state = ExerciseState(
            exercise=ex,
            fen=ex.fen,
            side_to_move="white",
            challenge="Test",
            solution_uci=["e2e4"],
        )

        # Mock the session and hook manager
        mock_session = MagicMock()
        mock_card = MagicMock()
        mock_card.due = MagicMock()
        # Make the due property return a future datetime
        from datetime import datetime, timedelta

        mock_card.due = datetime.now() + timedelta(days=1)
        mock_card.state = MagicMock(name="New")
        mock_session.rate.return_value = mock_card
        mock_session.stats = MagicMock(correct=1, incorrect=0, partial=0)
        mock_session.remaining = 5
        mgr._session = mock_session

        with patch.object(mgr, "_fire_hook") as mock_fire:
            mgr.rate(3)

            # Should fire on_exercise_complete
            calls = [c for c in mock_fire.call_args_list if c[0][0].value == "on_exercise_complete"]
            assert len(calls) == 1
            payload = calls[0][0][1]
            assert payload["exercise_id"] == "test-1"
            assert payload["exercise_type"] == "TACTIC"
            assert payload["rating"] == 3
            assert payload["correct"] is True

    def test_rate_checks_daily_goal(self, tmp_path):
        mgr = _make_manager(tmp_path)

        mock_session = MagicMock()
        from datetime import datetime, timedelta

        mock_card = MagicMock()
        mock_card.due = datetime.now() + timedelta(days=1)
        mock_card.state = MagicMock(name="New")
        mock_session.rate.return_value = mock_card
        mock_session.remaining = 5
        mgr._session = mock_session

        with patch.object(mgr, "_check_daily_goal") as mock_check:
            mgr.rate(3)
            mock_check.assert_called_once()


# ── Hook emission from end_session() ──────────────────────────────────────────


class TestEndSessionHookEmission:
    """Verify end_session() fires on_session_end and checks streak."""

    def test_end_session_fires_session_end_hook(self, tmp_path):
        mgr = _make_manager(tmp_path)

        mock_session = MagicMock()
        mock_stats = MagicMock(correct=7, incorrect=2, partial=1)
        mock_session.end.return_value = mock_stats
        mgr._session = mock_session
        mgr._session_start_time = MagicMock()

        with patch.object(mgr, "_fire_hook") as mock_fire:
            with patch.object(mgr, "_check_streak_milestone"):
                stats = mgr.end_session()

            assert stats is mock_stats
            calls = [c for c in mock_fire.call_args_list if c[0][0].value == "on_session_end"]
            assert len(calls) == 1
            payload = calls[0][0][1]
            assert payload["total_reviewed"] == 10
            assert payload["correct"] == 7
            assert payload["accuracy"] == 0.7

    def test_end_session_checks_streak_milestone(self, tmp_path):
        mgr = _make_manager(tmp_path)

        mock_session = MagicMock()
        mock_session.end.return_value = MagicMock(correct=1, incorrect=0, partial=0)
        mgr._session = mock_session

        with patch.object(mgr, "_check_streak_milestone") as mock_streak:
            with patch.object(mgr, "_fire_hook"):
                mgr.end_session()
            mock_streak.assert_called_once()

    def test_end_session_resets_daily_goal_flag(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr._daily_goal_fired = True

        mock_session = MagicMock()
        mock_session.end.return_value = MagicMock(correct=1, incorrect=0, partial=0)
        mgr._session = mock_session

        with patch.object(mgr, "_fire_hook"):
            with patch.object(mgr, "_check_streak_milestone"):
                mgr.end_session()

        assert mgr._daily_goal_fired is False


# ── Hook emission from import ──────────────────────────────────────────────────


class TestImportHookEmission:
    """Verify _import_result fires on_import_complete."""

    def test_import_result_fires_import_hook(self, tmp_path):
        mgr = _make_manager(tmp_path)

        mock_result = MagicMock(total_added=5, total_skipped=2, errors=["err1"])

        with patch.object(mgr, "_create_cards_and_tags", return_value=5):
            with patch.object(mgr, "_fire_hook") as mock_fire:
                result = mgr._import_result(mock_result, "lichess")

        assert result["added"] == 5
        calls = [c for c in mock_fire.call_args_list if c[0][0].value == "on_import_complete"]
        assert len(calls) == 1
        payload = calls[0][0][1]
        assert payload["source"] == "lichess"
        assert payload["added"] == 5
        assert payload["skipped"] == 2
        assert payload["errors"] == 1


# ── Hook emission from bundle ──────────────────────────────────────────────────


class TestBundleHookEmission:
    """Verify bundle rate/end fires hooks."""

    def test_rate_bundle_fires_exercise_complete_hook(self, tmp_path):
        mgr = _make_manager(tmp_path)

        from src.exercises.tactics import TacticExercise
        from src.web.session_manager import ExerciseState

        ex = TacticExercise(
            id="b-1", fen="8/8/8/8/8/8/8/8 w - - 0 1", solution=["e2e4"], source="test"
        )
        mgr._exercise_state = ExerciseState(
            exercise=ex,
            fen=ex.fen,
            side_to_move="white",
            challenge="Test",
            solution_uci=["e2e4"],
        )

        mock_ws = MagicMock()
        mock_ws.remaining = 3
        mock_ws.progress = MagicMock(current_cycle=1)
        mgr._woodpecker_session = mock_ws

        with patch.object(mgr, "_fire_hook") as mock_fire:
            mgr.rate_bundle(3)

        calls = [c for c in mock_fire.call_args_list if c[0][0].value == "on_exercise_complete"]
        assert len(calls) == 1

    def test_end_bundle_fires_cycle_complete_hook(self, tmp_path):
        mgr = _make_manager(tmp_path)

        mock_ws = MagicMock()
        mock_ws.bundle = MagicMock(id="bundle:test")
        mock_ws.end_cycle.return_value = MagicMock(
            cycle_number=2,
            accuracy=0.95,
            passed=True,
            exercises_attempted=10,
            exercises_correct=9,
        )
        mgr._woodpecker_session = mock_ws

        with patch.object(mgr, "_fire_hook") as mock_fire:
            result = mgr.end_bundle_session()

        assert result["passed"] is True
        calls = [c for c in mock_fire.call_args_list if c[0][0].value == "on_bundle_cycle_complete"]
        assert len(calls) == 1
        payload = calls[0][0][1]
        assert payload["bundle_id"] == "bundle:test"
        assert payload["accuracy"] == 0.95


# ── Daily goal and streak milestone ───────────────────────────────────────────


class TestDailyGoalAndStreak:
    """Tests for _check_daily_goal and _check_streak_milestone."""

    def test_daily_goal_not_fired_when_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.config.training.daily_review_goal = None

        with patch.object(mgr, "_fire_hook") as mock_fire:
            mgr._check_daily_goal()
        mock_fire.assert_not_called()

    def test_daily_goal_not_fired_when_already_fired(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.config.training.daily_review_goal = 10
        mgr._daily_goal_fired = True

        with patch.object(mgr, "_fire_hook") as mock_fire:
            mgr._check_daily_goal()
        mock_fire.assert_not_called()

    def test_daily_goal_fires_when_met(self, tmp_path):
        from datetime import date

        mgr = _make_manager(tmp_path)
        mgr.config.training.daily_review_goal = 5

        mock_streak = MagicMock()
        mock_day = MagicMock()
        mock_day.day = date.today()
        mock_day.review_count = 5
        mock_streak.daily_activity = [mock_day]

        with patch.object(mgr, "_get_analytics_store") as mock_store:
            mock_store.return_value.streaks.return_value = mock_streak
            with patch.object(mgr, "_fire_hook") as mock_fire:
                mgr._check_daily_goal()

        assert mgr._daily_goal_fired is True
        mock_fire.assert_called_once()
        payload = mock_fire.call_args[0][1]
        assert payload["event"] == "on_daily_goal_met"
        assert payload["reviews_today"] == 5
        assert payload["goal"] == 5

    def test_daily_goal_does_not_fire_below_target(self, tmp_path):
        from datetime import date

        mgr = _make_manager(tmp_path)
        mgr.config.training.daily_review_goal = 10

        mock_streak = MagicMock()
        mock_day = MagicMock()
        mock_day.day = date.today()
        mock_day.review_count = 3
        mock_streak.daily_activity = [mock_day]

        with patch.object(mgr, "_get_analytics_store") as mock_store:
            mock_store.return_value.streaks.return_value = mock_streak
            with patch.object(mgr, "_fire_hook") as mock_fire:
                mgr._check_daily_goal()

        assert mgr._daily_goal_fired is False
        mock_fire.assert_not_called()

    def test_streak_milestone_fires(self, tmp_path):
        mgr = _make_manager(tmp_path)

        mock_streak = MagicMock()
        mock_streak.current_streak = 30  # A milestone

        with patch.object(mgr, "_get_analytics_store") as mock_store:
            mock_store.return_value.streaks.return_value = mock_streak
            with patch.object(mgr, "_fire_hook") as mock_fire:
                mgr._check_streak_milestone()

        mock_fire.assert_called_once()
        payload = mock_fire.call_args[0][1]
        assert payload["streak_days"] == 30

    def test_streak_non_milestone_does_not_fire(self, tmp_path):
        mgr = _make_manager(tmp_path)

        mock_streak = MagicMock()
        mock_streak.current_streak = 15  # Not a milestone

        with patch.object(mgr, "_get_analytics_store") as mock_store:
            mock_store.return_value.streaks.return_value = mock_streak
            with patch.object(mgr, "_fire_hook") as mock_fire:
                mgr._check_streak_milestone()

        mock_fire.assert_not_called()

    def test_hook_failure_does_not_block(self, tmp_path):
        """_fire_hook should swallow exceptions."""
        mgr = _make_manager(tmp_path)

        # Make the hook manager's fire method raise
        mock_hook_mgr = MagicMock()
        mock_hook_mgr.fire.side_effect = RuntimeError("boom")
        mgr._hook_manager = mock_hook_mgr

        # Should not raise
        mgr._fire_hook("on_exercise_complete", {})
