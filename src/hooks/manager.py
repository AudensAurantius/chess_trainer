"""HookManager — fires hook scripts on training events."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from ..config import HooksConfig
from .events import HookEvent

logger = logging.getLogger(__name__)

_EXAMPLE_SCRIPT = """\
#!/bin/bash
# Example hook script for {event}
# Receives a JSON payload on stdin.
# Exit 0 for success; non-zero is logged as a warning.

# Read payload
payload=$(cat)
echo "Hook fired: {event}"
echo "Payload: $payload"
"""


class HookManager:
    """Manages discovery and execution of hook scripts.

    Hook scripts live in a configurable directory (default ``~/.chess-trainer/hooks/``).
    Each script is named after the event it handles (e.g. ``on_exercise_complete``).
    Scripts receive a JSON payload on stdin and are executed with a configurable timeout.
    """

    def __init__(self, config: HooksConfig) -> None:  # noqa: D107
        self._enabled = config.enabled
        self._directory = Path(config.directory).expanduser()
        self._timeout = config.timeout_seconds

    @property
    def directory(self) -> Path:
        """Hook scripts directory."""
        return self._directory

    def fire(self, event: HookEvent | str, payload: dict) -> bool:
        """Execute the hook script for an event, if it exists.

        Args:
            event: The event name or ``HookEvent`` enum member.
            payload: JSON-serializable payload dict passed via stdin.

        Returns:
            ``True`` if the script executed successfully (exit code 0),
            ``False`` if disabled, missing, or failed.
        """
        if not self._enabled:
            return False

        event_name = event.value if isinstance(event, HookEvent) else event
        script = self._directory / event_name

        if not script.is_file():
            return False

        if not _is_executable(script):
            logger.warning("Hook script %s exists but is not executable", script)
            return False

        try:
            result = subprocess.run(
                [str(script)],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if result.returncode != 0:
                logger.warning(
                    "Hook %s exited with code %d: %s",
                    event_name,
                    result.returncode,
                    result.stderr.strip(),
                )
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.warning("Hook %s timed out after %ds", event_name, self._timeout)
            return False
        except OSError as exc:
            logger.warning("Hook %s failed to execute: %s", event_name, exc)
            return False

    def is_installed(self, event: HookEvent | str) -> bool:
        """Check whether a hook script exists for the given event."""
        event_name = event.value if isinstance(event, HookEvent) else event
        return (self._directory / event_name).is_file()

    def list_hooks(self) -> list[dict]:
        """List all events with their installation status.

        Returns:
            List of dicts with ``event``, ``installed``, and ``path`` keys.
        """
        result = []
        for event in HookEvent:
            script = self._directory / event.value
            result.append(
                {
                    "event": event.value,
                    "installed": script.is_file(),
                    "path": str(script),
                }
            )
        return result

    def init_hooks_dir(self) -> Path:
        """Create the hooks directory with example scripts.

        Returns:
            Path to the hooks directory.
        """
        self._directory.mkdir(parents=True, exist_ok=True)
        for event in HookEvent:
            example = self._directory / f"{event.value}.example"
            if not example.exists():
                example.write_text(_EXAMPLE_SCRIPT.format(event=event.value))
        return self._directory


def _is_executable(path: Path) -> bool:
    """Check if a file is executable."""
    try:
        import os

        return os.access(path, os.X_OK)
    except OSError:
        return False
