"""Chess trainer package — spaced repetition training for chess improvement."""

from __future__ import annotations

import json
import logging
import traceback
from importlib.metadata import PackageNotFoundError, version
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

try:
    __version__ = version("chess-trainer")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

SRC_DIR = Path(__file__).parent
ASSETS = SRC_DIR.parent.joinpath("assets")

# Package logger — level is set by config on startup, defaults to INFO
_pkg_logger = logging.getLogger(__name__)
_pkg_logger.setLevel(logging.INFO)


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        entry: dict = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(entry, default=str)


def configure_logging(
    level: str = "INFO",
    file: str | None = None,
    format: str = "text",
    max_size_mb: int = 10,
    backup_count: int = 3,
) -> None:
    """Set the package-wide logging level and optionally add file logging.

    Args:
        level: Logging level name (e.g. ``"DEBUG"``, ``"INFO"``).
        file: Path to log file. Enables ``RotatingFileHandler`` when set.
        format: Log format — ``"text"`` or ``"json"``.
        max_size_mb: Maximum log file size in MB before rotation.
        backup_count: Number of rotated backup files to keep.
    """
    _pkg_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing file handlers (idempotent re-configuration)
    _pkg_logger.handlers = [
        h for h in _pkg_logger.handlers if not isinstance(h, RotatingFileHandler)
    ]

    if file:
        log_path = Path(file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        handler = RotatingFileHandler(
            str(log_path),
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
        )
        if format == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")
            )
        _pkg_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger scoped to this package with a Rich handler.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    # Guard against duplicate RichHandlers on repeated calls
    if not any(isinstance(h, RichHandler) for h in logger.handlers):
        logger.addHandler(RichHandler())
    return logger
