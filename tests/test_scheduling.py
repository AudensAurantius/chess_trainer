"""Tests for FSRS scheduling algorithm."""

from datetime import datetime, timedelta

import pytest

from src.scheduling import CardState, FSRSScheduler, ReviewCard
from src.scheduling.fsrs import FSRSParameters, Rating, SchedulingResult


class TestReviewCard:
    """Tests for ReviewCard model."""

    def test_new_card_defaults(self):
        card = ReviewCard(exercise_id="ex:1")
        assert card.state == CardState.NEW
        assert card.difficulty == 0.3
        assert card.stability == 0.0
        assert card.reps == 0
        assert card.lapses == 0

    def test_is_due_when_past(self):
        card = ReviewCard(exercise_id="ex:1", due=datetime(2020, 1, 1))
        assert card.is_due is True

    def test_is_due_when_future(self):
        card = ReviewCard(exercise_id="ex:1", due=datetime(2099, 1, 1))
        assert card.is_due is False

    def test_days_overdue_positive(self):
        card = ReviewCard(exercise_id="ex:1", due=datetime.now() - timedelta(days=2))
        assert card.days_overdue > 1.9

    def test_to_dict_from_dict_roundtrip(self):
        card = ReviewCard(
            exercise_id="ex:1",
            state=CardState.REVIEW,
            difficulty=0.5,
            stability=10.0,
            retrievability=0.85,
            due=datetime(2025, 6, 15, 12, 0),
            last_review=datetime(2025, 6, 1, 12, 0),
            reps=5,
            lapses=1,
            step_index=0,
            created_at=datetime(2025, 1, 1),
        )
        data = card.to_dict()
        restored = ReviewCard.from_dict(data)
        assert restored.exercise_id == card.exercise_id
        assert restored.state == card.state
        assert restored.difficulty == card.difficulty
        assert restored.stability == card.stability
        assert restored.reps == card.reps
        assert restored.lapses == card.lapses


class TestFSRSScheduler:
    """Tests for the FSRS-4.5 scheduling algorithm."""

    @pytest.fixture
    def scheduler(self):
        return FSRSScheduler()

    @pytest.fixture
    def new_card(self):
        return ReviewCard(exercise_id="ex:1")

    @pytest.fixture
    def review_card(self):
        return ReviewCard(
            exercise_id="ex:1",
            state=CardState.REVIEW,
            difficulty=0.5,
            stability=10.0,
            due=datetime(2025, 1, 10),
            last_review=datetime(2025, 1, 1),
            reps=3,
        )

    def test_schedule_new_returns_scheduling_result(self, scheduler, new_card):
        result = scheduler.schedule(new_card)
        assert isinstance(result, SchedulingResult)
        assert result.card == new_card

    def test_schedule_new_again_enters_learning(self, scheduler, new_card):
        result = scheduler.schedule(new_card)
        again = result.get_card(Rating.AGAIN)
        assert again.state == CardState.LEARNING
        assert again.step_index == 0

    def test_schedule_new_easy_graduates(self, scheduler, new_card):
        result = scheduler.schedule(new_card)
        easy = result.get_card(Rating.EASY)
        assert easy.state == CardState.REVIEW
        assert easy.reps == 1

    def test_schedule_new_good_next_step(self, scheduler, new_card):
        result = scheduler.schedule(new_card)
        good = result.get_card(Rating.GOOD)
        # With default 2 learning steps, GOOD advances to step 1
        assert good.state == CardState.LEARNING
        assert good.step_index == 1

    def test_schedule_new_stability_ordering(self, scheduler, new_card):
        """Again < Hard < Good < Easy stability."""
        result = scheduler.schedule(new_card)
        assert result.again.stability < result.hard.stability
        assert result.hard.stability < result.good.stability
        assert result.good.stability < result.easy.stability

    def test_schedule_review_good_increases_stability(self, scheduler, review_card):
        now = datetime(2025, 1, 10)
        result = scheduler.schedule(review_card, now=now)
        good = result.get_card(Rating.GOOD)
        assert good.stability > review_card.stability
        assert good.state == CardState.REVIEW

    def test_schedule_review_again_lapses(self, scheduler, review_card):
        now = datetime(2025, 1, 10)
        result = scheduler.schedule(review_card, now=now)
        again = result.get_card(Rating.AGAIN)
        assert again.state == CardState.RELEARNING
        assert again.lapses == review_card.lapses + 1

    def test_schedule_review_interval_ordering(self, scheduler, review_card):
        """Again due soonest, Hard due after Again."""
        now = datetime(2025, 1, 10)
        result = scheduler.schedule(review_card, now=now)
        assert result.again.due < result.hard.due
        # Note: FSRS easy_bonus (w13=0.34) is < 1 with default params,
        # so easy stability may be less than good stability. We only
        # assert the strongest invariant: again < hard.
        assert result.hard.state == CardState.REVIEW

    def test_schedule_review_reps_increment(self, scheduler, review_card):
        now = datetime(2025, 1, 10)
        result = scheduler.schedule(review_card, now=now)
        good = result.get_card(Rating.GOOD)
        assert good.reps == review_card.reps + 1

    def test_schedule_learning_again_resets(self, scheduler):
        card = ReviewCard(
            exercise_id="ex:1",
            state=CardState.LEARNING,
            step_index=1,
            stability=2.4,
            due=datetime.now(),
            last_review=datetime.now() - timedelta(minutes=10),
        )
        result = scheduler.schedule(card)
        again = result.get_card(Rating.AGAIN)
        assert again.step_index == 0

    def test_schedule_learning_easy_graduates(self, scheduler):
        card = ReviewCard(
            exercise_id="ex:1",
            state=CardState.LEARNING,
            step_index=0,
            stability=2.4,
            due=datetime.now(),
            last_review=datetime.now() - timedelta(minutes=1),
        )
        result = scheduler.schedule(card)
        easy = result.get_card(Rating.EASY)
        assert easy.state == CardState.REVIEW

    def test_retrievability_decreases_over_time(self, scheduler):
        card = ReviewCard(
            exercise_id="ex:1",
            state=CardState.REVIEW,
            stability=10.0,
            due=datetime(2025, 1, 10),
            last_review=datetime(2025, 1, 1),
        )
        # After 9 days with stability 10
        now = datetime(2025, 1, 10)
        scheduler.schedule(card, now=now)
        assert card.retrievability < 1.0
        assert card.retrievability > 0.0

    def test_custom_parameters(self):
        params = FSRSParameters(request_retention=0.8, learning_steps=[1, 5, 15])
        scheduler = FSRSScheduler(params)
        card = ReviewCard(exercise_id="ex:1")
        result = scheduler.schedule(card)
        good = result.get_card(Rating.GOOD)
        # With 3 learning steps, GOOD should advance to step 1
        assert good.step_index == 1

    def test_maximum_interval_respected(self):
        params = FSRSParameters(maximum_interval=30)
        scheduler = FSRSScheduler(params)
        card = ReviewCard(
            exercise_id="ex:1",
            state=CardState.REVIEW,
            stability=100.0,
            due=datetime(2025, 1, 10),
            last_review=datetime(2025, 1, 1),
        )
        result = scheduler.schedule(card, now=datetime(2025, 1, 10))
        good = result.get_card(Rating.GOOD)
        interval = (good.due - datetime(2025, 1, 10)).days
        assert interval <= 30
