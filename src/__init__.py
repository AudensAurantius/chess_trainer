import logging
from rich.logging import RichHandler
from pathlib import Path


logging.getLogger().setLevel("DEBUG")

SRC_DIR = Path(__file__).parent
ASSETS = SRC_DIR.parent.joinpath("assets")


def get_logger(name):
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(RichHandler())
    return logger
