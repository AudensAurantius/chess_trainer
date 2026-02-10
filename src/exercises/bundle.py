"""Exercise bundle and Woodpecker method domain model.

Bundles group exercises into curated sets for focused training.
The Woodpecker method cycles through the entire bundle at increasing
intervals with decreasing time limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]{1,2}$")


def validate_slug(slug: str) -> str:
    """Validate and normalize a bundle slug.

    Rules: lowercase alphanumeric and hyphens, 2-64 chars,
    cannot start or end with a hyphen.

    Args:
        slug: Raw slug string.

    Returns:
        Normalized slug (lowercased).

    Raises:
        ValueError: If the slug is invalid.
    """
    normalized = slug.strip().lower()
    if not normalized:
        raise ValueError("Slug cannot be empty")
    if len(normalized) < 2:
        raise ValueError(f"Slug must be at least 2 characters, got {len(normalized)}")
    if len(normalized) > 64:
        raise ValueError(f"Slug must be at most 64 characters, got {len(normalized)}")
    if not _SLUG_RE.match(normalized):
        raise ValueError(
            f"Invalid slug: {normalized!r}. "
            "Use lowercase letters, digits, and hyphens (no leading/trailing hyphens)."
        )
    return normalized


def generate_bundle_id(slug: str) -> str:
    """Generate a bundle ID from a validated slug.

    Args:
        slug: Validated slug string.

    Returns:
        Bundle ID in ``bundle:{slug}`` format.
    """
    return f"bundle:{slug}"


@dataclass
class WoodpeckerCycle:
    """Configuration for a single Woodpecker cycle."""

    cycle_number: int  # 1-based
    rest_days: int  # Wait before this cycle starts
    time_limit_seconds: int | None = None  # None = unlimited


@dataclass
class BundleConfig:
    """Configuration for how a bundle should be trained."""

    woodpecker_mode: bool = False
    woodpecker_cycles: list[WoodpeckerCycle] = field(default_factory=list)
    pass_threshold: float = 0.9
    shuffle: bool = False
    time_limit_seconds: int | None = None  # Non-Woodpecker per-exercise limit

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "woodpecker_mode": self.woodpecker_mode,
            "woodpecker_cycles": [
                {
                    "cycle_number": c.cycle_number,
                    "rest_days": c.rest_days,
                    "time_limit_seconds": c.time_limit_seconds,
                }
                for c in self.woodpecker_cycles
            ],
            "pass_threshold": self.pass_threshold,
            "shuffle": self.shuffle,
            "time_limit_seconds": self.time_limit_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> BundleConfig:
        """Deserialize from a dict."""
        cycles = [
            WoodpeckerCycle(
                cycle_number=c["cycle_number"],
                rest_days=c["rest_days"],
                time_limit_seconds=c.get("time_limit_seconds"),
            )
            for c in data.get("woodpecker_cycles", [])
        ]
        return cls(
            woodpecker_mode=data.get("woodpecker_mode", False),
            woodpecker_cycles=cycles,
            pass_threshold=data.get("pass_threshold", 0.9),
            shuffle=data.get("shuffle", False),
            time_limit_seconds=data.get("time_limit_seconds"),
        )


@dataclass
class ExerciseBundle:
    """A curated collection of exercises for focused training."""

    id: str  # "bundle:{slug}"
    name: str
    description: str = ""
    exercise_ids: list[str] = field(default_factory=list)
    auto_tags: list[str] = field(default_factory=list)
    config: BundleConfig = field(default_factory=BundleConfig)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def slug(self) -> str:
        """Extract the slug from the bundle ID."""
        return self.id.removeprefix("bundle:")

    @property
    def exercise_count(self) -> int:
        """Number of exercises in the bundle."""
        return len(self.exercise_ids)

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "exercise_ids": self.exercise_ids,
            "auto_tags": self.auto_tags,
            "config": self.config.to_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExerciseBundle:
        """Deserialize from a dict."""
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            exercise_ids=data.get("exercise_ids", []),
            auto_tags=data.get("auto_tags", []),
            config=BundleConfig.from_dict(data.get("config", {})),
            created_at=datetime.fromisoformat(data["created_at"])
            if isinstance(data.get("created_at"), str)
            else data.get("created_at", datetime.now()),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if isinstance(data.get("updated_at"), str)
            else data.get("updated_at", datetime.now()),
        )


@dataclass
class CycleResult:
    """Result of completing one Woodpecker cycle."""

    cycle_number: int
    accuracy: float
    passed: bool
    started_at: datetime
    completed_at: datetime
    time_limit_seconds: int | None
    exercises_attempted: int
    exercises_correct: int

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "cycle_number": self.cycle_number,
            "accuracy": self.accuracy,
            "passed": self.passed,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "time_limit_seconds": self.time_limit_seconds,
            "exercises_attempted": self.exercises_attempted,
            "exercises_correct": self.exercises_correct,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CycleResult:
        """Deserialize from a dict."""
        return cls(
            cycle_number=data["cycle_number"],
            accuracy=data["accuracy"],
            passed=data["passed"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]),
            time_limit_seconds=data.get("time_limit_seconds"),
            exercises_attempted=data["exercises_attempted"],
            exercises_correct=data["exercises_correct"],
        )


@dataclass
class BundleProgress:
    """Progress state for a bundle's training cycles."""

    bundle_id: str
    current_cycle: int = 1
    cycle_started_at: datetime | None = None
    exercises_attempted: int = 0
    exercises_correct: int = 0
    completed_cycles: list[CycleResult] = field(default_factory=list)

    @property
    def cycle_accuracy(self) -> float:
        """Accuracy for the current in-progress cycle."""
        if self.exercises_attempted == 0:
            return 0.0
        return self.exercises_correct / self.exercises_attempted

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "bundle_id": self.bundle_id,
            "current_cycle": self.current_cycle,
            "cycle_started_at": self.cycle_started_at.isoformat()
            if self.cycle_started_at
            else None,
            "exercises_attempted": self.exercises_attempted,
            "exercises_correct": self.exercises_correct,
            "completed_cycles": [c.to_dict() for c in self.completed_cycles],
        }

    @classmethod
    def from_dict(cls, data: dict) -> BundleProgress:
        """Deserialize from a dict."""
        return cls(
            bundle_id=data["bundle_id"],
            current_cycle=data.get("current_cycle", 1),
            cycle_started_at=datetime.fromisoformat(data["cycle_started_at"])
            if data.get("cycle_started_at")
            else None,
            exercises_attempted=data.get("exercises_attempted", 0),
            exercises_correct=data.get("exercises_correct", 0),
            completed_cycles=[
                CycleResult.from_dict(c) for c in data.get("completed_cycles", [])
            ],
        )
