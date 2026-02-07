"""TOML-based configuration with hierarchical overrides.

Override chain: defaults → config file → environment variables → CLI flags.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".chess-trainer"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"

ENV_PREFIX = "CHESS_TRAINER_"


@dataclass
class DatabaseConfig:
    """Database connection settings."""

    path: str = str(DEFAULT_CONFIG_DIR / "trainer.db")


@dataclass
class LichessConfig:
    """Lichess API settings."""

    api_url: str = "https://lichess.org/api"
    token: str | None = None


@dataclass
class SchedulerConfig:
    """FSRS-4.5 scheduler parameters."""

    request_retention: float = 0.9
    learning_steps: list[int] = field(default_factory=lambda: [1, 10])
    relearning_steps: list[int] = field(default_factory=lambda: [10])
    maximum_interval: int = 36500


@dataclass
class TrainingConfig:
    """Training session defaults."""

    max_new_cards: int = 20
    max_reviews: int = 100
    interleave_new: bool = True


@dataclass
class LoggingConfig:
    """Logging settings."""

    level: str = "INFO"


@dataclass
class WebConfig:
    """Web server settings."""

    host: str = "127.0.0.1"
    port: int = 8000


@dataclass
class AppConfig:
    """Top-level application configuration."""

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    lichess: LichessConfig = field(default_factory=LichessConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    web: WebConfig = field(default_factory=WebConfig)


def _apply_toml(config: AppConfig, data: dict) -> None:
    """Apply TOML data onto an AppConfig, mutating in place."""
    if "database" in data:
        db = data["database"]
        if "path" in db:
            config.database.path = str(Path(db["path"]).expanduser())

    if "lichess" in data:
        li = data["lichess"]
        if "api_url" in li:
            config.lichess.api_url = li["api_url"]
        if "token" in li:
            config.lichess.token = li["token"]

    if "scheduler" in data:
        sched = data["scheduler"]
        if "request_retention" in sched:
            config.scheduler.request_retention = float(sched["request_retention"])
        if "learning_steps" in sched:
            config.scheduler.learning_steps = list(sched["learning_steps"])
        if "relearning_steps" in sched:
            config.scheduler.relearning_steps = list(sched["relearning_steps"])
        if "maximum_interval" in sched:
            config.scheduler.maximum_interval = int(sched["maximum_interval"])

    if "training" in data:
        tr = data["training"]
        if "max_new_cards" in tr:
            config.training.max_new_cards = int(tr["max_new_cards"])
        if "max_reviews" in tr:
            config.training.max_reviews = int(tr["max_reviews"])
        if "interleave_new" in tr:
            config.training.interleave_new = bool(tr["interleave_new"])

    if "logging" in data:
        log = data["logging"]
        if "level" in log:
            config.logging.level = log["level"].upper()

    if "web" in data:
        web = data["web"]
        if "host" in web:
            config.web.host = web["host"]
        if "port" in web:
            config.web.port = int(web["port"])


def _apply_env(config: AppConfig) -> None:
    """Apply environment variable overrides onto an AppConfig."""
    env_map = {
        f"{ENV_PREFIX}DB_PATH": lambda v: setattr(config.database, "path", v),
        f"{ENV_PREFIX}LICHESS_API_URL": lambda v: setattr(config.lichess, "api_url", v),
        f"{ENV_PREFIX}LICHESS_TOKEN": lambda v: setattr(config.lichess, "token", v),
        "LICHESS_TOKEN": lambda v: setattr(config.lichess, "token", v),
        f"{ENV_PREFIX}LOG_LEVEL": lambda v: setattr(config.logging, "level", v.upper()),
        f"{ENV_PREFIX}WEB_HOST": lambda v: setattr(config.web, "host", v),
        f"{ENV_PREFIX}WEB_PORT": lambda v: setattr(config.web, "port", int(v)),
        f"{ENV_PREFIX}MAX_NEW_CARDS": lambda v: setattr(config.training, "max_new_cards", int(v)),
        f"{ENV_PREFIX}MAX_REVIEWS": lambda v: setattr(config.training, "max_reviews", int(v)),
    }
    for key, setter in env_map.items():
        val = os.environ.get(key)
        if val is not None:
            setter(val)


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration with hierarchical overrides.

    Override chain: defaults → TOML config file → environment variables.
    CLI flags are applied by the caller after this returns.

    Args:
        path: Path to TOML config file. Defaults to ``~/.chess-trainer/config.toml``.

    Returns:
        Fully resolved ``AppConfig``.
    """
    config = AppConfig()

    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.is_file():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        _apply_toml(config, data)

    _apply_env(config)
    return config


def generate_default_config() -> str:
    """Generate a default TOML config file as a string.

    Returns:
        TOML-formatted configuration with all defaults and comments.
    """
    return """\
# Chess Trainer Configuration
# Place this file at ~/.chess-trainer/config.toml

[database]
path = "~/.chess-trainer/trainer.db"

[lichess]
api_url = "https://lichess.org/api"
# token = "lip_..."  # Your Lichess API token

[scheduler]
request_retention = 0.9
learning_steps = [1, 10]
relearning_steps = [10]
maximum_interval = 36500

[training]
max_new_cards = 20
max_reviews = 100
interleave_new = true

[logging]
level = "INFO"

[web]
host = "127.0.0.1"
port = 8000
"""
