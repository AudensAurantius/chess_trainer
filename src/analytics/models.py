"""Data models for progress analytics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class AccuracyPoint:
    """A single data point in an accuracy trend."""

    period: date
    total_reviews: int
    correct_count: int
    accuracy: float  # 0-100%


@dataclass(frozen=True)
class AccuracyTrend:
    """Accuracy trend over time with configurable granularity."""

    points: list[AccuracyPoint]
    overall_accuracy: float
    total_reviews: int
    granularity: str  # "day" | "week"


@dataclass(frozen=True)
class WeakArea:
    """An area where the user struggles."""

    name: str  # Theme name, exercise type, or difficulty tier
    category: str  # "type" | "theme" | "difficulty"
    total_reviews: int
    correct_count: int
    accuracy: float  # 0-100%
    avg_lapses: float
    card_count: int


@dataclass(frozen=True)
class DayActivity:
    """Activity for a single day."""

    day: date
    review_count: int


@dataclass(frozen=True)
class StreakInfo:
    """Streak and activity tracking."""

    current_streak: int
    longest_streak: int
    total_active_days: int
    daily_activity: list[DayActivity] = field(default_factory=list)


@dataclass(frozen=True)
class RetentionPoint:
    """A point on the retention curve grouped by repetition count."""

    reps: int
    card_count: int
    avg_stability_days: float
    actual_recall_rate: float  # From most-recent review correctness
    predicted_retrievability: float


@dataclass(frozen=True)
class ProgressReport:
    """Top-level container for all progress analytics."""

    accuracy: AccuracyTrend
    weak_areas: list[WeakArea]
    streaks: StreakInfo
    retention: list[RetentionPoint]
