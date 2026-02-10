"""Training session implementation.

A session coordinates the flow of exercises through the spaced repetition
system, presenting exercises, collecting responses, and updating schedules.
"""

from dataclasses import dataclass, field
from datetime import datetime

import chess

from ..exercises import Exercise, ExerciseResult, ExerciseType
from ..scheduling import CardState, FSRSParameters, FSRSScheduler, ReviewCard
from ..scheduling.fsrs import Rating, SchedulingResult
from ..storage import Repository
from ..storage.tag_store import EntityType


@dataclass
class SessionConfig:
    """Configuration for a training session."""

    # Card limits
    max_new_cards: int = 20
    max_reviews: int = 100

    # Which exercise types to include (None = all)
    exercise_types: list[ExerciseType] | None = None

    # Tag filters (None = no filter)
    include_tags: list[str] | None = None
    exclude_tags: list[str] | None = None

    # FSRS parameters (None = use defaults)
    fsrs_params: FSRSParameters | None = None

    # Behavior
    interleave_new: bool = True  # Mix new cards with reviews
    show_answer_immediately: bool = False  # For "reveal" mode


@dataclass
class SessionStats:
    """Statistics for a training session."""

    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None

    exercises_shown: int = 0
    correct: int = 0
    incorrect: int = 0
    partial: int = 0

    new_cards_seen: int = 0
    reviews_completed: int = 0

    total_time_ms: int = 0

    @property
    def accuracy(self) -> float:
        """Percentage of fully correct responses."""
        total = self.correct + self.incorrect + self.partial
        return (self.correct / total * 100) if total > 0 else 0.0

    @property
    def duration_minutes(self) -> float:
        """Session duration in minutes."""
        end = self.ended_at or datetime.now()
        return (end - self.started_at).total_seconds() / 60


class TrainingSession:
    """Manages a single training session.

    Handles the flow of:
    1. Fetching due cards and new cards
    2. Presenting exercises to the user
    3. Evaluating responses
    4. Updating schedules based on performance
    """

    def __init__(self, repo: Repository, config: SessionConfig | None = None):
        """Initialize training session with repository and config."""
        self.repo = repo
        self.config = config or SessionConfig()
        self.scheduler = FSRSScheduler(self.config.fsrs_params)
        self.stats = SessionStats()

        self._queue: list[ReviewCard] = []
        self._current_card: ReviewCard | None = None
        self._current_exercise: Exercise | None = None
        self._current_scheduling: SchedulingResult | None = None

    def start(self) -> None:
        """Initialize the session and build the review queue."""
        self._build_queue()
        self.stats.started_at = datetime.now()

    def _build_queue(self) -> None:
        """Build the queue of cards to review."""
        # Get due reviews
        due_cards = self.repo.cards.get_due(
            limit=self.config.max_reviews,
            include_new=False,
        )

        # Get new cards
        new_cards = []
        if self.config.max_new_cards > 0:
            new_cards = self.repo.cards.get_new(limit=self.config.max_new_cards)

        # Filter by exercise type if specified
        if self.config.exercise_types:
            type_names = {t.name for t in self.config.exercise_types}
            due_cards = [
                c for c in due_cards if self._get_exercise_type(c.exercise_id) in type_names
            ]
            new_cards = [
                c for c in new_cards if self._get_exercise_type(c.exercise_id) in type_names
            ]

        # Filter by tags if specified
        if self.config.include_tags or self.config.exclude_tags:
            included_ids: set[str] | None = None
            excluded_ids: set[str] = set()

            if self.config.include_tags:
                included_ids = set(
                    self.repo.tags.find_by_tags(
                        EntityType.EXERCISE,
                        self.config.include_tags,
                        match_all=False,
                    )
                )
            if self.config.exclude_tags:
                excluded_ids = set(
                    self.repo.tags.find_by_tags(
                        EntityType.EXERCISE,
                        self.config.exclude_tags,
                        match_all=False,
                    )
                )

            def _tag_ok(card: ReviewCard) -> bool:
                eid = card.exercise_id
                if included_ids is not None and eid not in included_ids:
                    return False
                return eid not in excluded_ids

            due_cards = [c for c in due_cards if _tag_ok(c)]
            new_cards = [c for c in new_cards if _tag_ok(c)]

        # Interleave new cards with reviews
        if self.config.interleave_new and new_cards and due_cards:
            # Insert new cards at regular intervals
            interval = max(1, len(due_cards) // len(new_cards))
            self._queue = []
            new_iter = iter(new_cards)
            for i, card in enumerate(due_cards):
                self._queue.append(card)
                if (i + 1) % interval == 0:
                    try:
                        self._queue.append(next(new_iter))
                    except StopIteration:
                        pass
            # Add remaining new cards
            self._queue.extend(new_iter)
        else:
            # Reviews first, then new
            self._queue = due_cards + new_cards

    def _get_exercise_type(self, exercise_id: str) -> str | None:
        """Get the exercise type for filtering."""
        exercise = self.repo.exercises.get(exercise_id)
        return exercise.exercise_type.name if exercise else None

    @property
    def remaining(self) -> int:
        """Number of cards remaining in the queue."""
        return len(self._queue)

    @property
    def current_exercise(self) -> Exercise | None:
        """Get the current exercise being presented."""
        return self._current_exercise

    @property
    def current_card(self) -> ReviewCard | None:
        """Get the current review card."""
        return self._current_card

    def next(self) -> Exercise | None:
        """Get the next exercise to present.

        Returns None when the session is complete.
        """
        # Check for cards in learning that are now due
        learning = self.repo.cards.get_learning()
        due_learning = [c for c in learning if c.is_due]
        if due_learning:
            self._current_card = due_learning[0]
        elif self._queue:
            self._current_card = self._queue.pop(0)
        else:
            return None

        self._current_exercise = self.repo.exercises.get(self._current_card.exercise_id)
        if not self._current_exercise:
            # Exercise deleted? Skip this card
            return self.next()

        # Pre-compute scheduling for all rating options
        self._current_scheduling = self.scheduler.schedule(self._current_card)

        self.stats.exercises_shown += 1
        if self._current_card.state == CardState.NEW:
            self.stats.new_cards_seen += 1
        else:
            self.stats.reviews_completed += 1

        return self._current_exercise

    # TODO: Fix typing error in return type
    def submit(
        self,
        moves: list[chess.Move],
        time_taken_ms: int,
    ) -> tuple[ExerciseResult, SchedulingResult]:
        """Submit an answer for the current exercise.

        Args:
            moves: The moves played by the user
            time_taken_ms: Time taken to respond

        Returns:
            Tuple of (ExerciseResult, SchedulingResult)
        """
        if not self._current_exercise or not self._current_card:
            raise RuntimeError("No active exercise")

        # Evaluate the answer
        result = self._current_exercise.evaluate(moves, time_taken_ms)

        # Update stats
        self.stats.total_time_ms += time_taken_ms
        if result.correct:
            self.stats.correct += 1
        elif result.partial_credit > 0:
            self.stats.partial += 1
        else:
            self.stats.incorrect += 1

        return result, self._current_scheduling

    def rate(self, rating: Rating) -> ReviewCard:
        """Apply the user's self-rating and update the schedule.

        Args:
            rating: User's rating of recall difficulty

        Returns:
            Updated ReviewCard
        """
        if not self._current_card or not self._current_scheduling:
            raise RuntimeError("No active exercise")

        stability_before = self._current_card.stability

        # Get the updated card for this rating
        updated_card = self._current_scheduling.get_card(rating)

        # Save to database
        self.repo.cards.save(updated_card)

        # Record in history
        self.repo.cards.record_review(
            card=updated_card,
            rating=rating,
            time_taken_ms=self.stats.total_time_ms,
            correct=rating >= Rating.GOOD,
            stability_before=stability_before,
            stability_after=updated_card.stability,
        )

        # If the card is in learning/relearning, it might come back soon
        if updated_card.state in (CardState.LEARNING, CardState.RELEARNING):
            # Don't add to queue - will be picked up by learning check in next()
            pass

        self._current_card = None
        self._current_exercise = None
        self._current_scheduling = None

        return updated_card

    def auto_rate(self, result: ExerciseResult) -> Rating:
        """Automatically determine rating based on exercise result.

        Uses the grade from ExerciseResult to map to FSRS ratings.
        """
        grade = result.grade

        if grade == 1:
            return Rating.AGAIN
        elif grade == 2:
            return Rating.HARD
        elif grade == 3:
            return Rating.GOOD
        else:
            return Rating.EASY

    def end(self) -> SessionStats:
        """End the session and return final statistics."""
        self.stats.ended_at = datetime.now()
        return self.stats

    def get_queue_preview(self, count: int = 5) -> list[tuple[ReviewCard, Exercise | None]]:
        """Preview upcoming cards in the queue."""
        preview = []
        for card in self._queue[:count]:
            exercise = self.repo.exercises.get(card.exercise_id)
            preview.append((card, exercise))
        return preview
