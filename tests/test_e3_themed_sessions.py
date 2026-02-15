"""Tests for E3: Themed sessions with duration limits."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.exercises import TacticExercise
from src.storage import Repository
from src.training.session import SessionConfig, SessionStats, TrainingSession

SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def _seed_exercises(repo: Repository, count: int = 5) -> list[TacticExercise]:
    """Seed the repository with a number of tactic exercises."""
    exercises = []
    for i in range(count):
        ex = TacticExercise(
            id=f"test:{i:03d}",
            fen=SAMPLE_FEN,
            tags=["fork"],
            source="test",
            difficulty=1500.0,
            solution=["g7g6"],
            themes=["fork"],
        )
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex.id)
        exercises.append(ex)
    return exercises


class TestDurationLimit:
    """Test max_duration_minutes in TrainingSession."""

    def test_no_duration_runs_until_queue_exhausted(self, tmp_path):
        """Without a duration limit, sessions run until the queue is empty."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo, 3)
            config = SessionConfig(max_new_cards=10, max_reviews=10)
            session = TrainingSession(repo, config)
            session.start()

            count = 0
            while session.next() is not None:
                count += 1
            assert count == 3

    def test_duration_expires_returns_none(self, tmp_path):
        """When duration expires, next() returns None."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo, 5)
            config = SessionConfig(max_new_cards=10, max_reviews=10, max_duration_minutes=10)
            session = TrainingSession(repo, config)
            session.start()

            # First exercise should work (we just started)
            ex1 = session.next()
            assert ex1 is not None

            # Simulate time passing: set started_at to 11 minutes ago
            session.stats.started_at = datetime.now() - timedelta(minutes=11)

            # Now next() should return None due to time expiry
            ex2 = session.next()
            assert ex2 is None

    def test_time_expired_property(self, tmp_path):
        """time_expired reflects whether duration limit is reached."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo, 1)
            config = SessionConfig(max_new_cards=10, max_reviews=10, max_duration_minutes=5)
            session = TrainingSession(repo, config)
            session.start()

            assert session.time_expired is False

            # Set start time to 6 minutes ago
            session.stats.started_at = datetime.now() - timedelta(minutes=6)
            assert session.time_expired is True

    def test_time_expired_false_when_no_limit(self, tmp_path):
        """time_expired is False when no duration limit is set."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo, 1)
            config = SessionConfig(max_new_cards=10, max_reviews=10)
            session = TrainingSession(repo, config)
            session.start()

            assert session.time_expired is False

    def test_current_exercise_still_completes(self, tmp_path):
        """Duration check only on next() — current exercise can be finished."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo, 3)
            config = SessionConfig(max_new_cards=10, max_reviews=10, max_duration_minutes=1)
            session = TrainingSession(repo, config)
            session.start()

            # Get first exercise
            ex1 = session.next()
            assert ex1 is not None

            # Expire the timer mid-exercise
            session.stats.started_at = datetime.now() - timedelta(minutes=2)

            # Current exercise is still accessible
            assert session.current_exercise is not None

            # But next() should return None
            assert session.next() is None


class TestDifficultyFiltering:
    """Test difficulty preset filtering in SessionConfig."""

    def test_min_max_difficulty_filters_exercises(self, tmp_path):
        """Exercises outside difficulty range are excluded."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            # Add exercises with different difficulties
            easy = TacticExercise(
                id="test:easy",
                fen=SAMPLE_FEN,
                tags=["fork"],
                source="test",
                difficulty=800.0,
                solution=["g7g6"],
                themes=["fork"],
            )
            hard = TacticExercise(
                id="test:hard",
                fen=SAMPLE_FEN,
                tags=["fork"],
                source="test",
                difficulty=2000.0,
                solution=["g7g6"],
                themes=["fork"],
            )
            repo.exercises.add(easy)
            repo.exercises.add(hard)
            repo.cards.get_or_create(easy.id)
            repo.cards.get_or_create(hard.id)

            # Filter for medium difficulty (1200-1800)
            config = SessionConfig(
                max_new_cards=10,
                max_reviews=10,
                min_difficulty=1200,
                max_difficulty=1800,
            )
            session = TrainingSession(repo, config)
            session.start()

            # Neither exercise should be in range
            assert session.remaining == 0

    def test_easy_preset_range(self, tmp_path):
        """Easy preset (0-1200) includes only easy exercises."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            easy = TacticExercise(
                id="test:easy",
                fen=SAMPLE_FEN,
                tags=[],
                source="test",
                difficulty=800.0,
                solution=["g7g6"],
                themes=[],
            )
            hard = TacticExercise(
                id="test:hard",
                fen=SAMPLE_FEN,
                tags=[],
                source="test",
                difficulty=2000.0,
                solution=["g7g6"],
                themes=[],
            )
            repo.exercises.add(easy)
            repo.exercises.add(hard)
            repo.cards.get_or_create(easy.id)
            repo.cards.get_or_create(hard.id)

            config = SessionConfig(
                max_new_cards=10,
                max_reviews=10,
                min_difficulty=0,
                max_difficulty=1200,
            )
            session = TrainingSession(repo, config)
            session.start()

            assert session.remaining == 1  # Only the easy one


class TestSessionStats:
    """Test SessionStats duration tracking."""

    def test_duration_minutes_calculation(self):
        """duration_minutes returns correct value."""
        stats = SessionStats()
        stats.started_at = datetime.now() - timedelta(minutes=10)
        # Allow some tolerance for test execution time
        assert 9.9 < stats.duration_minutes < 10.5

    def test_duration_minutes_with_ended_at(self):
        """duration_minutes uses ended_at when set."""
        now = datetime.now()
        stats = SessionStats()
        stats.started_at = now - timedelta(minutes=20)
        stats.ended_at = now - timedelta(minutes=5)
        assert 14.5 < stats.duration_minutes < 15.5
