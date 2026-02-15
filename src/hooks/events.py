"""Hook event definitions and payload builders."""

from __future__ import annotations

from enum import StrEnum

STREAK_MILESTONES = [7, 30, 100, 365]


class HookEvent(StrEnum):
    """Training events that can trigger hook scripts."""

    ON_EXERCISE_COMPLETE = "on_exercise_complete"
    ON_SESSION_END = "on_session_end"
    ON_STREAK_MILESTONE = "on_streak_milestone"
    ON_BUNDLE_CYCLE_COMPLETE = "on_bundle_cycle_complete"
    ON_DAILY_GOAL_MET = "on_daily_goal_met"
    ON_IMPORT_COMPLETE = "on_import_complete"


def exercise_complete_payload(
    *,
    exercise_id: str,
    exercise_type: str,
    rating: int,
    correct: bool,
    time_ms: int | None = None,
) -> dict:
    """Build payload for on_exercise_complete."""
    return {
        "event": HookEvent.ON_EXERCISE_COMPLETE.value,
        "exercise_id": exercise_id,
        "exercise_type": exercise_type,
        "rating": rating,
        "correct": correct,
        "time_ms": time_ms,
    }


def session_end_payload(
    *,
    total_reviewed: int,
    correct: int,
    incorrect: int,
    partial: int,
    accuracy: float,
    duration_seconds: float | None = None,
) -> dict:
    """Build payload for on_session_end."""
    return {
        "event": HookEvent.ON_SESSION_END.value,
        "total_reviewed": total_reviewed,
        "correct": correct,
        "incorrect": incorrect,
        "partial": partial,
        "accuracy": accuracy,
        "duration_seconds": duration_seconds,
    }


def streak_milestone_payload(*, streak_days: int) -> dict:
    """Build payload for on_streak_milestone."""
    return {
        "event": HookEvent.ON_STREAK_MILESTONE.value,
        "streak_days": streak_days,
    }


def bundle_cycle_complete_payload(
    *,
    bundle_id: str,
    cycle_number: int,
    accuracy: float,
    passed: bool,
) -> dict:
    """Build payload for on_bundle_cycle_complete."""
    return {
        "event": HookEvent.ON_BUNDLE_CYCLE_COMPLETE.value,
        "bundle_id": bundle_id,
        "cycle_number": cycle_number,
        "accuracy": accuracy,
        "passed": passed,
    }


def daily_goal_met_payload(*, reviews_today: int, goal: int) -> dict:
    """Build payload for on_daily_goal_met."""
    return {
        "event": HookEvent.ON_DAILY_GOAL_MET.value,
        "reviews_today": reviews_today,
        "goal": goal,
    }


def import_complete_payload(
    *,
    source: str,
    added: int,
    skipped: int,
    errors: int,
) -> dict:
    """Build payload for on_import_complete."""
    return {
        "event": HookEvent.ON_IMPORT_COMPLETE.value,
        "source": source,
        "added": added,
        "skipped": skipped,
        "errors": errors,
    }
