"""Chess trainer package — spaced repetition training for chess improvement."""

import logging
from pathlib import Path

from rich.logging import RichHandler

SRC_DIR = Path(__file__).parent
ASSETS = SRC_DIR.parent.joinpath("assets")

# Package logger — level is set by config on startup, defaults to INFO
_pkg_logger = logging.getLogger(__name__)
_pkg_logger.setLevel(logging.INFO)


def configure_logging(level: str = "INFO") -> None:
    """Set the package-wide logging level.

    Args:
        level: Logging level name (e.g. ``"DEBUG"``, ``"INFO"``).
    """
    _pkg_logger.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str) -> logging.Logger:
    """Get a logger scoped to this package with a Rich handler.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(RichHandler())
    return logger
