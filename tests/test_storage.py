"""Tests for DuckDB storage layer."""

from datetime import datetime, timedelta

import pytest

from src.exercises import ExerciseType, TacticExercise
from src.scheduling import CardState
from src.scheduling.fsrs import Rating


class TestExerciseStore:
    """Tests for ExerciseStore CRUD operations."""

    def _make_tactic(self, id_="test:1"):
        return TacticExercise(
            id=id_,
            fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
            tags=["fork"],
            source="test",
            difficulty=1500.0,
            created_at=datetime(2025, 1, 1),
            solution=["e7e5"],
            themes=["fork"],
        )

    def test_add_and_get(self, repo):
        ex = self._make_tactic()
        repo.exercises.add(ex)
        loaded = repo.exercises.get("test:1")
        assert loaded is not None
        assert loaded.id == "test:1"
        assert loaded.fen == ex.fen
        assert loaded.solution == ex.solution

    def test_get_nonexistent(self, repo):
        assert repo.exercises.get("nonexistent") is None

    def test_add_duplicate_raises(self, repo):
        ex = self._make_tactic()
        repo.exercises.add(ex)
        with pytest.raises(Exception):
            repo.exercises.add(ex)

    def test_add_many_skips_duplicates(self, repo):
        ex1 = self._make_tactic("test:1")
        ex2 = self._make_tactic("test:2")
        repo.exercises.add(ex1)
        added = repo.exercises.add_many([ex1, ex2])
        assert added == 1  # Only ex2 was new

    def test_count(self, repo):
        assert repo.exercises.count() == 0
        repo.exercises.add(self._make_tactic("test:1"))
        repo.exercises.add(self._make_tactic("test:2"))
        assert repo.exercises.count() == 2

    def test_count_by_type(self, repo):
        repo.exercises.add(self._make_tactic("test:1"))
        assert repo.exercises.count(ExerciseType.TACTIC) == 1
        assert repo.exercises.count(ExerciseType.OPENING) == 0

    def test_get_by_type(self, repo):
        repo.exercises.add(self._make_tactic("test:1"))
        repo.exercises.add(self._make_tactic("test:2"))
        tactics = repo.exercises.get_by_type(ExerciseType.TACTIC)
        assert len(tactics) == 2
        openings = repo.exercises.get_by_type(ExerciseType.OPENING)
        assert len(openings) == 0

    def test_iterate_all(self, repo):
        for i in range(5):
            repo.exercises.add(self._make_tactic(f"test:{i}"))
        all_exercises = list(repo.exercises.iterate_all())
        assert len(all_exercises) == 5

    def test_delete(self, repo):
        repo.exercises.add(self._make_tactic())
        assert repo.exercises.delete("test:1") is True
        assert repo.exercises.get("test:1") is None

    def test_delete_nonexistent(self, repo):
        assert repo.exercises.delete("nonexistent") is False

    def test_search_by_difficulty(self, repo):
        low = self._make_tactic("test:low")
        low.difficulty = 800.0
        high = self._make_tactic("test:high")
        high.difficulty = 2000.0
        repo.exercises.add(low)
        repo.exercises.add(high)
        results = repo.exercises.search(min_difficulty=1000.0)
        assert len(results) == 1
        assert results[0].id == "test:high"


class TestCardStore:
    """Tests for CardStore CRUD and queries."""

    def test_get_or_create(self, populated_repo):
        card = populated_repo.cards.get("test:001")
        assert card is not None
        assert card.exercise_id == "test:001"
        assert card.state == CardState.NEW

    def test_save_and_reload(self, populated_repo):
        card = populated_repo.cards.get("test:001")
        card.state = CardState.REVIEW
        card.stability = 5.0
        card.reps = 3
        populated_repo.cards.save(card)
        reloaded = populated_repo.cards.get("test:001")
        assert reloaded.state == CardState.REVIEW
        assert reloaded.stability == 5.0
        assert reloaded.reps == 3

    def test_get_due(self, populated_repo):
        # Card is due (default due is datetime.now() from get_or_create)
        due = populated_repo.cards.get_due(include_new=True)
        assert len(due) == 1

    def test_get_due_excludes_future(self, populated_repo):
        card = populated_repo.cards.get("test:001")
        card.state = CardState.REVIEW
        card.due = datetime.now() + timedelta(days=30)
        populated_repo.cards.save(card)
        due = populated_repo.cards.get_due()
        assert len(due) == 0

    def test_get_new(self, populated_repo):
        new_cards = populated_repo.cards.get_new()
        assert len(new_cards) == 1
        assert new_cards[0].state == CardState.NEW

    def test_get_learning(self, populated_repo):
        card = populated_repo.cards.get("test:001")
        card.state = CardState.LEARNING
        populated_repo.cards.save(card)
        learning = populated_repo.cards.get_learning()
        assert len(learning) == 1

    def test_get_stats(self, populated_repo):
        stats = populated_repo.cards.get_stats()
        assert stats["total_cards"] == 1
        assert stats["total_reviews"] == 0

    def test_record_review(self, populated_repo):
        card = populated_repo.cards.get("test:001")
        populated_repo.cards.record_review(
            card=card,
            rating=Rating.GOOD,
            time_taken_ms=5000,
            correct=True,
            stability_before=0.0,
            stability_after=2.4,
        )
        # Verify it was recorded (no exception)
        history_count = populated_repo.conn.execute(
            "SELECT COUNT(*) FROM review_history"
        ).fetchone()[0]
        assert history_count == 1

    def test_count_by_state(self, populated_repo):
        counts = populated_repo.cards.count_by_state()
        assert counts.get("NEW", 0) == 1

    def test_delete_card(self, populated_repo):
        assert populated_repo.cards.delete("test:001") is True
        assert populated_repo.cards.get("test:001") is None
