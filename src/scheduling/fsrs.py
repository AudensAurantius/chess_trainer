"""FSRS (Free Spaced Repetition Scheduler) implementation.

FSRS is based on the DSR (Difficulty, Stability, Retrievability) memory model
and provides more accurate scheduling than SM-2 by modeling memory decay
as a power function of time.

References:
- https://github.com/open-spaced-repetition/fsrs4anki
- https://supermemo.guru/wiki/Two_components_of_memory
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum
from math import exp, pow

from .card import CardState, ReviewCard


class Rating(IntEnum):
    """User's self-assessment of recall difficulty."""

    AGAIN = 1  # Complete failure to recall
    HARD = 2  # Recalled with significant difficulty
    GOOD = 3  # Recalled with some effort
    EASY = 4  # Recalled effortlessly


@dataclass
class FSRSParameters:
    """FSRS-4.5 algorithm parameters.

    These defaults are optimized from large-scale Anki data analysis.
    Individual users can have personalized parameters derived from
    their review history.

    TODO: Store weights in a data file (JSON, YAML, or similar)
    instead of hardcoding them in this dataclass.
    """

    # Initial stability values for each rating on first review
    w0: float = 0.4  # Again
    w1: float = 0.6  # Hard
    w2: float = 2.4  # Good
    w3: float = 5.8  # Easy

    # Difficulty parameters
    w4: float = 4.93  # Initial difficulty weight
    w5: float = 0.94  # Difficulty mean reversion
    w6: float = 0.86  # Difficulty update on recall
    w7: float = 0.01  # Difficulty update on forget

    # Stability parameters
    w8: float = 1.49  # Stability increase base
    w9: float = 0.14  # Stability increase difficulty factor
    w10: float = 0.94  # Stability increase stability factor
    w11: float = 2.18  # Stability increase retrievability factor
    w12: float = 0.05  # Stability decrease factor (hard penalty)
    w13: float = 0.34  # Stability on forget
    w14: float = 1.26  # Stability on forget difficulty factor
    w15: float = 0.29  # Stability on forget stability factor
    w16: float = 2.61  # Stability on forget retrievability factor

    # Target retention
    request_retention: float = 0.9  # Desired probability of recall at review

    # Learning steps (in minutes) for new cards
    learning_steps: list[int] = field(default_factory=lambda: [1, 10])
    # Relearning steps for lapsed cards
    relearning_steps: list[int] = field(default_factory=lambda: [10])

    # Limits
    maximum_interval: int = 36500  # ~100 years, effectively no limit


@dataclass
class SchedulingResult:
    """Result of scheduling a review, with options for each rating."""

    card: ReviewCard
    again: ReviewCard
    hard: ReviewCard
    good: ReviewCard
    easy: ReviewCard

    def get_card(self, rating: Rating) -> ReviewCard:
        """Get the updated card for a given rating."""
        return {
            Rating.AGAIN: self.again,
            Rating.HARD: self.hard,
            Rating.GOOD: self.good,
            Rating.EASY: self.easy,
        }[rating]


class FSRSScheduler:
    """FSRS scheduler that computes next review dates based on memory model.

    The scheduler maintains the DSR (Difficulty, Stability, Retrievability)
    parameters for each card and uses them to determine optimal review timing.
    """

    def __init__(self, params: FSRSParameters | None = None):
        """Initialize the FSRS scheduler with optional custom parameters."""
        self.p = params or FSRSParameters()

    def schedule(self, card: ReviewCard, now: datetime | None = None) -> SchedulingResult:
        """Compute scheduling options for all possible ratings.

        Args:
            card: The card to schedule
            now: Current time (defaults to datetime.now())

        Returns:
            SchedulingResult with updated cards for each rating choice
        """
        now = now or datetime.now()

        # Calculate current retrievability based on time elapsed
        if card.last_review and card.stability > 0:
            elapsed_days = (now - card.last_review).total_seconds() / 86400
            card.retrievability = self._retrievability(card.stability, elapsed_days)
        else:
            card.retrievability = 1.0

        # Branch into possible outcomes
        if card.state == CardState.NEW:
            return self._schedule_new(card, now)
        elif card.state == CardState.LEARNING:
            return self._schedule_learning(card, now)
        elif card.state == CardState.RELEARNING:
            return self._schedule_relearning(card, now)
        else:  # REVIEW
            return self._schedule_review(card, now)

    def _schedule_new(self, card: ReviewCard, now: datetime) -> SchedulingResult:
        """Schedule a card being reviewed for the first time."""
        again = self._copy_card(card)
        hard = self._copy_card(card)
        good = self._copy_card(card)
        easy = self._copy_card(card)

        # Initialize difficulty for all outcomes
        init_d = self._init_difficulty(Rating.GOOD)
        for c in [again, hard, good, easy]:
            c.difficulty = init_d
            c.last_review = now

        # AGAIN: Enter learning, first step
        again.state = CardState.LEARNING
        again.step_index = 0
        again.stability = self.p.w0
        again.due = now + timedelta(minutes=self.p.learning_steps[0])

        # HARD: Enter learning, first step (slightly longer)
        hard.state = CardState.LEARNING
        hard.step_index = 0
        hard.stability = self.p.w1
        hard.due = now + timedelta(minutes=self.p.learning_steps[0] * 1.5)

        # GOOD: Enter learning, advance to next step or graduate
        good.stability = self.p.w2
        if len(self.p.learning_steps) > 1:
            good.state = CardState.LEARNING
            good.step_index = 1
            good.due = now + timedelta(minutes=self.p.learning_steps[1])
        else:
            good.state = CardState.REVIEW
            good.reps = 1
            good.due = now + timedelta(days=self._next_interval(good.stability))

        # EASY: Graduate immediately with bonus
        easy.state = CardState.REVIEW
        easy.stability = self.p.w3
        easy.reps = 1
        easy.due = now + timedelta(days=self._next_interval(easy.stability))

        return SchedulingResult(card=card, again=again, hard=hard, good=good, easy=easy)

    def _schedule_learning(self, card: ReviewCard, now: datetime) -> SchedulingResult:
        """Schedule a card in the learning phase."""
        again = self._copy_card(card)
        hard = self._copy_card(card)
        good = self._copy_card(card)
        easy = self._copy_card(card)

        for c in [again, hard, good, easy]:
            c.last_review = now

        # AGAIN: Reset to first learning step
        again.step_index = 0
        again.due = now + timedelta(minutes=self.p.learning_steps[0])

        # HARD: Stay at current step
        hard.due = now + timedelta(minutes=self.p.learning_steps[card.step_index] * 1.5)

        # GOOD: Advance to next step or graduate
        next_step = card.step_index + 1
        if next_step < len(self.p.learning_steps):
            good.step_index = next_step
            good.due = now + timedelta(minutes=self.p.learning_steps[next_step])
        else:
            good.state = CardState.REVIEW
            good.stability = self._init_stability(Rating.GOOD)
            good.reps = card.reps + 1
            good.due = now + timedelta(days=self._next_interval(good.stability))

        # EASY: Graduate immediately
        easy.state = CardState.REVIEW
        easy.stability = self._init_stability(Rating.EASY)
        easy.reps = card.reps + 1
        easy.due = now + timedelta(days=self._next_interval(easy.stability))

        return SchedulingResult(card=card, again=again, hard=hard, good=good, easy=easy)

    def _schedule_relearning(self, card: ReviewCard, now: datetime) -> SchedulingResult:
        """Schedule a card being relearned after a lapse."""
        again = self._copy_card(card)
        hard = self._copy_card(card)
        good = self._copy_card(card)
        easy = self._copy_card(card)

        for c in [again, hard, good, easy]:
            c.last_review = now

        # AGAIN: Reset to first relearning step
        again.step_index = 0
        again.due = now + timedelta(minutes=self.p.relearning_steps[0])

        # HARD: Stay at current step
        step_time = self.p.relearning_steps[min(card.step_index, len(self.p.relearning_steps) - 1)]
        hard.due = now + timedelta(minutes=step_time * 1.5)

        # GOOD: Advance or graduate back to review
        next_step = card.step_index + 1
        if next_step < len(self.p.relearning_steps):
            good.step_index = next_step
            good.due = now + timedelta(minutes=self.p.relearning_steps[next_step])
        else:
            good.state = CardState.REVIEW
            good.due = now + timedelta(days=self._next_interval(card.stability))

        # EASY: Graduate immediately
        easy.state = CardState.REVIEW
        easy.due = now + timedelta(days=self._next_interval(card.stability))

        return SchedulingResult(card=card, again=again, hard=hard, good=good, easy=easy)

    def _schedule_review(self, card: ReviewCard, now: datetime) -> SchedulingResult:
        """Schedule a card in the review phase."""
        again = self._copy_card(card)
        hard = self._copy_card(card)
        good = self._copy_card(card)
        easy = self._copy_card(card)

        for c in [again, hard, good, easy]:
            c.last_review = now

        # AGAIN: Lapse - enter relearning
        again.state = CardState.RELEARNING
        again.step_index = 0
        again.lapses += 1
        again.stability = self._next_forget_stability(
            card.difficulty, card.stability, card.retrievability
        )
        again.due = now + timedelta(minutes=self.p.relearning_steps[0])

        # HARD: Successful recall with difficulty
        hard.stability = self._next_recall_stability(
            card.difficulty, card.stability, card.retrievability, Rating.HARD
        )
        hard.difficulty = self._next_difficulty(card.difficulty, Rating.HARD)
        hard.reps += 1
        interval = self._next_interval(hard.stability)
        # Hard interval should be at least current interval
        hard.due = now + timedelta(days=max(interval, 1))

        # GOOD: Normal successful recall
        good.stability = self._next_recall_stability(
            card.difficulty, card.stability, card.retrievability, Rating.GOOD
        )
        good.difficulty = self._next_difficulty(card.difficulty, Rating.GOOD)
        good.reps += 1
        good.due = now + timedelta(days=self._next_interval(good.stability))

        # EASY: Excellent recall
        easy.stability = self._next_recall_stability(
            card.difficulty, card.stability, card.retrievability, Rating.EASY
        )
        easy.difficulty = self._next_difficulty(card.difficulty, Rating.EASY)
        easy.reps += 1
        easy.due = now + timedelta(days=self._next_interval(easy.stability))

        return SchedulingResult(card=card, again=again, hard=hard, good=good, easy=easy)

    def _retrievability(self, stability: float, elapsed_days: float) -> float:
        """Calculate probability of recall using power forgetting curve.

        R(t) = (1 + t/S)^(-1)

        where t is elapsed time and S is stability.
        """
        if stability <= 0:
            return 0.0
        return pow(1 + elapsed_days / stability, -1)

    def _init_difficulty(self, rating: Rating) -> float:
        """Calculate initial difficulty based on first rating."""
        # D0(G) = w4 - (G-3) * w5
        # Clamp to [0.1, 0.9] to avoid extremes
        d = self.p.w4 - (rating.value - 3) * self.p.w5
        return max(0.1, min(0.9, d))

    def _init_stability(self, rating: Rating) -> float:
        """Get initial stability for a rating."""
        return [self.p.w0, self.p.w1, self.p.w2, self.p.w3][rating.value - 1]

    def _next_difficulty(self, d: float, rating: Rating) -> float:
        """Update difficulty after a review.

        D'(D,G) = w6 * D0(G) + (1 - w6) * D
        """
        d0 = self._init_difficulty(rating)
        d_new = self.p.w6 * d0 + (1 - self.p.w6) * d
        return max(0.1, min(0.9, d_new))

    def _next_recall_stability(self, d: float, s: float, r: float, rating: Rating) -> float:
        """Calculate new stability after successful recall.

        S'(D,S,R,G) = S * (e^w8 * (11-D) * S^(-w9) * (e^(w10*(1-R)) - 1) * HardPenalty * EasyBonus + 1)
        """
        hard_penalty = self.p.w12 if rating == Rating.HARD else 1.0
        easy_bonus = self.p.w13 if rating == Rating.EASY else 1.0

        s_new = s * (
            exp(self.p.w8)
            * (11 - d)
            * pow(s, -self.p.w9)
            * (exp(self.p.w10 * (1 - r)) - 1)
            * hard_penalty
            * easy_bonus
            + 1
        )

        return min(s_new, self.p.maximum_interval)

    def _next_forget_stability(self, d: float, s: float, r: float) -> float:
        """Calculate new stability after forgetting (lapse).

        S'(D,S,R) = w11 * D^(-w12) * ((S+1)^w13 - 1) * e^(w14*(1-R))
        """
        s_new = (
            self.p.w13
            * pow(d, -self.p.w14)
            * (pow(s + 1, self.p.w15) - 1)
            * exp(self.p.w16 * (1 - r))
        )

        return max(0.1, min(s_new, s))  # New stability after lapse is at most old stability

    def _next_interval(self, stability: float) -> float:
        """Calculate review interval from stability to achieve target retention.

        I(S,R) = S * (R^(1/-1) - 1)

        For target R = 0.9: I ≈ S * 0.111
        """
        r = self.p.request_retention
        interval = stability * (pow(r, -1) - 1)
        return max(1, min(interval, self.p.maximum_interval))

    def _copy_card(self, card: ReviewCard) -> ReviewCard:
        """Create a copy of a card for branching."""
        return ReviewCard(
            exercise_id=card.exercise_id,
            state=card.state,
            difficulty=card.difficulty,
            stability=card.stability,
            retrievability=card.retrievability,
            due=card.due,
            last_review=card.last_review,
            reps=card.reps,
            lapses=card.lapses,
            step_index=card.step_index,
            created_at=card.created_at,
        )
