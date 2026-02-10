"""Woodpecker method training session.

A standalone session that cycles through all exercises in a bundle,
optionally with decreasing time limits. FSRS cards are updated as
a side effect, but the bundle's own cycle schedule takes priority
over FSRS due dates.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime

import chess

from ..exercises import Exercise, ExerciseResult
from ..exercises.bundle import (
    BundleProgress,
    CycleResult,
    ExerciseBundle,
    WoodpeckerCycle,
)
from ..scheduling.fsrs import FSRSScheduler, Rating
from ..storage import Repository


@dataclass
class WoodpeckerStats:
    """Statistics for a Woodpecker training cycle."""

    bundle_id: str
    cycle_number: int
    time_limit_seconds: int | None
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    exercises_shown: int = 0
    correct: int = 0
    incorrect: int = 0
    over_time: int = 0
    total_time_ms: int = 0

    @property
    def accuracy(self) -> float:
        """Accuracy where over-time exercises count as incorrect."""
        total = self.correct + self.incorrect + self.over_time
        if total == 0:
            return 0.0
        return self.correct / total

    @property
    def lenient_accuracy(self) -> float:
        """Accuracy where over-time exercises count as correct."""
        total = self.correct + self.incorrect + self.over_time
        if total == 0:
            return 0.0
        return (self.correct + self.over_time) / total


class WoodpeckerSession:
    """Manages a Woodpecker training cycle through a bundle.

    Unlike TrainingSession, this presents ALL exercises in the bundle
    regardless of FSRS state. The bundle's cycle schedule controls pacing.
    """

    def __init__(
        self,
        repo: Repository,
        bundle: ExerciseBundle,
        progress: BundleProgress | None = None,
    ) -> None:
        """Initialize a Woodpecker session.

        Args:
            repo: Repository for exercise and card access.
            bundle: The bundle to train.
            progress: Existing progress (loads from DB if None).
        """
        self.repo = repo
        self.bundle = bundle
        self.progress = progress or BundleProgress(bundle_id=bundle.id)
        self.scheduler = FSRSScheduler()

        self._queue: list[str] = []  # Exercise IDs
        self._current_exercise: Exercise | None = None
        self._current_scheduling = None
        self._current_card = None
        self.stats: WoodpeckerStats | None = None

    @property
    def time_limit(self) -> int | None:
        """Current cycle time limit in seconds."""
        cycle_config = self._get_cycle_config(self.progress.current_cycle)
        if cycle_config and cycle_config.time_limit_seconds is not None:
            return cycle_config.time_limit_seconds
        return self.bundle.config.time_limit_seconds

    @property
    def remaining(self) -> int:
        """Exercises remaining in the queue."""
        return len(self._queue)

    @property
    def current_exercise(self) -> Exercise | None:
        """The exercise currently being presented."""
        return self._current_exercise

    def start(self) -> None:
        """Build the exercise queue and initialize stats."""
        self._queue = list(self.bundle.exercise_ids)
        if self.bundle.config.shuffle:
            random.shuffle(self._queue)

        self.progress.cycle_started_at = datetime.now()
        self.progress.exercises_attempted = 0
        self.progress.exercises_correct = 0

        self.stats = WoodpeckerStats(
            bundle_id=self.bundle.id,
            cycle_number=self.progress.current_cycle,
            time_limit_seconds=self.time_limit,
        )

    def next(self) -> Exercise | None:
        """Get the next exercise from the queue.

        Returns:
            The next exercise, or None if the cycle is complete.
        """
        while self._queue:
            exercise_id = self._queue.pop(0)
            exercise = self.repo.exercises.get(exercise_id)
            if exercise is None:
                continue  # Exercise was deleted, skip

            self._current_exercise = exercise

            # Pre-compute FSRS scheduling for side-effect rating
            card = self.repo.cards.get(exercise_id)
            if card is None:
                card = self.repo.cards.get_or_create(exercise_id)
            self._current_card = card
            self._current_scheduling = self.scheduler.schedule(card)

            if self.stats:
                self.stats.exercises_shown += 1
            return exercise

        self._current_exercise = None
        self._current_card = None
        self._current_scheduling = None
        return None

    def submit(
        self,
        moves: list[chess.Move],
        time_ms: int,
    ) -> tuple[ExerciseResult, bool]:
        """Submit an answer and check time limit.

        Args:
            moves: The moves played by the user.
            time_ms: Time taken in milliseconds.

        Returns:
            Tuple of (ExerciseResult, over_time).

        Raises:
            RuntimeError: If no exercise is active.
        """
        if self._current_exercise is None:
            raise RuntimeError("No active exercise")

        result = self._current_exercise.evaluate(moves, time_ms)

        # Check time limit
        over_time = False
        limit = self.time_limit
        if limit is not None and time_ms > limit * 1000:
            over_time = True

        # Update stats
        if self.stats:
            self.stats.total_time_ms += time_ms
            if over_time:
                self.stats.over_time += 1
            elif result.correct:
                self.stats.correct += 1
            else:
                self.stats.incorrect += 1

        # Update progress counters
        self.progress.exercises_attempted += 1
        if result.correct and not over_time:
            self.progress.exercises_correct += 1

        return result, over_time

    def auto_rate_woodpecker(self, result: ExerciseResult, over_time: bool) -> Rating:
        """Automatically determine rating based on result and time.

        Over-time exercises get HARD, otherwise use the grade from the result.
        """
        if over_time:
            return Rating.HARD
        grade = result.grade
        if grade == 1:
            return Rating.AGAIN
        elif grade == 2:
            return Rating.HARD
        elif grade == 3:
            return Rating.GOOD
        else:
            return Rating.EASY

    def rate(self, rating: Rating) -> None:
        """Apply FSRS rating as a side effect.

        Args:
            rating: The FSRS rating to apply.
        """
        if self._current_card is None or self._current_scheduling is None:
            return

        stability_before = self._current_card.stability
        updated_card = self._current_scheduling.get_card(rating)
        self.repo.cards.save(updated_card)
        self.repo.cards.record_review(
            card=updated_card,
            rating=rating,
            time_taken_ms=self.stats.total_time_ms if self.stats else 0,
            correct=rating >= Rating.GOOD,
            stability_before=stability_before,
            stability_after=updated_card.stability,
        )

        self._current_card = None
        self._current_exercise = None
        self._current_scheduling = None

    def end_cycle(self) -> CycleResult:
        """Finalize the current cycle and compute results.

        Saves progress. Advances to the next cycle if passed.

        Returns:
            The CycleResult for the completed cycle.
        """
        now = datetime.now()
        if self.stats:
            self.stats.ended_at = now

        accuracy = self.progress.cycle_accuracy
        passed = accuracy >= self.bundle.config.pass_threshold

        cycle_result = CycleResult(
            cycle_number=self.progress.current_cycle,
            accuracy=accuracy,
            passed=passed,
            started_at=self.progress.cycle_started_at or now,
            completed_at=now,
            time_limit_seconds=self.time_limit,
            exercises_attempted=self.progress.exercises_attempted,
            exercises_correct=self.progress.exercises_correct,
        )

        self.progress.completed_cycles.append(cycle_result)

        if passed:
            self.progress.current_cycle += 1

        # Reset cycle counters
        self.progress.exercises_attempted = 0
        self.progress.exercises_correct = 0
        self.progress.cycle_started_at = None

        # Persist progress
        self.repo.bundles.save_progress(self.progress)

        return cycle_result

    def _get_cycle_config(self, cycle_num: int) -> WoodpeckerCycle | None:
        """Get the WoodpeckerCycle config for a given cycle number.

        Returns None if no specific config exists for this cycle.
        """
        for cycle in self.bundle.config.woodpecker_cycles:
            if cycle.cycle_number == cycle_num:
                return cycle
        return None
