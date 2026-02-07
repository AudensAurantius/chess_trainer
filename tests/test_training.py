"""Tests for TrainingSession coordinator."""

from datetime import datetime

import pytest

from src.scheduling import CardState
from src.scheduling.fsrs import Rating
from src.training import SessionConfig, SessionStats, TrainingSession


class TestSessionStats:
    """Tests for SessionStats calculations."""

    def test_accuracy_all_correct(self):
        stats = SessionStats(correct=10, incorrect=0, partial=0)
        assert stats.accuracy == 100.0

    def test_accuracy_none_correct(self):
        stats = SessionStats(correct=0, incorrect=10, partial=0)
        assert stats.accuracy == 0.0

    def test_accuracy_mixed(self):
        stats = SessionStats(correct=5, incorrect=3, partial=2)
        assert stats.accuracy == 50.0

    def test_accuracy_no_exercises(self):
        stats = SessionStats()
        assert stats.accuracy == 0.0

    def test_duration_minutes(self):
        stats = SessionStats(
            started_at=datetime(2025, 1, 1, 10, 0),
            ended_at=datetime(2025, 1, 1, 10, 30),
        )
        assert stats.duration_minutes == pytest.approx(30.0)


class TestTrainingSession:
    """Tests for the full training session lifecycle."""

    def test_start_builds_queue(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        assert session.remaining > 0

    def test_next_returns_exercise(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        exercise = session.next()
        assert exercise is not None
        assert exercise.id == "test:001"

    def test_next_returns_none_when_empty(self, repo):
        session = TrainingSession(repo)
        session.start()
        assert session.next() is None

    def test_submit_evaluates_moves(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        exercise = session.next()
        solution = exercise.get_solution()
        user_moves = solution[::2]  # User moves only
        result, scheduling = session.submit(user_moves, 5000)
        assert result.correct is True

    def test_submit_empty_is_wrong(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        session.next()
        result, scheduling = session.submit([], 0)
        assert result.correct is False

    def test_rate_saves_card(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        session.next()
        session.submit([], 0)
        updated = session.rate(Rating.AGAIN)
        assert updated.state != CardState.NEW

    def test_auto_rate_maps_grades(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        exercise = session.next()
        # Correct move
        solution = exercise.get_solution()
        result, _ = session.submit(solution[::2], 5000)
        rating = session.auto_rate(result)
        assert rating in (Rating.GOOD, Rating.EASY)

    def test_end_returns_stats(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        session.next()
        session.submit([], 0)
        session.rate(Rating.AGAIN)
        stats = session.end()
        assert stats.exercises_shown == 1
        assert stats.ended_at is not None

    def test_session_config_limits(self, populated_repo):
        config = SessionConfig(max_new_cards=0, max_reviews=100)
        session = TrainingSession(populated_repo, config)
        session.start()
        # With max_new_cards=0, no new cards should be in queue
        # But there may be due cards if the card is due
        # Since populated_repo creates a NEW card, and we set max_new=0:
        assert session.remaining == 0

    def test_session_stats_track_correct(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        exercise = session.next()
        solution = exercise.get_solution()
        result, _ = session.submit(solution[::2], 5000)
        session.rate(session.auto_rate(result))
        assert session.stats.correct == 1

    def test_session_stats_track_incorrect(self, populated_repo):
        session = TrainingSession(populated_repo)
        session.start()
        session.next()
        result, _ = session.submit([], 0)
        session.rate(Rating.AGAIN)
        assert session.stats.incorrect == 1
