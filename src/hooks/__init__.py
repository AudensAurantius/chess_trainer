"""Training event hooks — git-hooks-style script execution on training events."""

from .events import STREAK_MILESTONES, HookEvent
from .manager import HookManager

__all__ = ["HookEvent", "HookManager", "STREAK_MILESTONES"]
