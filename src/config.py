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
class EngineConfig:
    """UCI engine settings."""

    path: str | None = None  # Auto-detect if None
    hash_mb: int = 256
    threads: int = 2
    default_depth: int = 20
    default_multipv: int = 3


@dataclass
class OpeningsConfig:
    """Opening explorer and book settings."""

    explorer_source: str = "lichess"
    cache_ttl_hours: int = 168
    min_games: int = 5


@dataclass
class GameAnalysisConfig:
    """Own-game analysis and exercise generation settings."""

    analysis_depth: int = 20
    min_classification: str = "MISTAKE"  # INACCURACY, MISTAKE, or BLUNDER
    max_exercises_per_game: int = 10
    skip_first_plies: int = 6  # Skip opening theory moves


@dataclass
class TablebaseConfig:
    """Endgame tablebase settings."""

    syzygy_path: str | None = None  # Path to Syzygy tablebase directory
    use_lichess_fallback: bool = True  # Fall back to Lichess API
    max_pieces: int = 7  # Max pieces for tablebase probe


@dataclass
class ChessComConfig:
    """Chess.com API settings."""

    user_agent: str = "ChessTrainer/1.0 (github.com/user/chess_trainer)"
    request_delay: float = 0.5  # Seconds between archive page fetches


@dataclass
class AppConfig:
    """Top-level application configuration."""

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    lichess: LichessConfig = field(default_factory=LichessConfig)
    chesscom: ChessComConfig = field(default_factory=ChessComConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    web: WebConfig = field(default_factory=WebConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    openings: OpeningsConfig = field(default_factory=OpeningsConfig)
    game_analysis: GameAnalysisConfig = field(default_factory=GameAnalysisConfig)
    tablebase: TablebaseConfig = field(default_factory=TablebaseConfig)


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

    if "engine" in data:
        eng = data["engine"]
        if "path" in eng:
            config.engine.path = eng["path"]
        if "hash_mb" in eng:
            config.engine.hash_mb = int(eng["hash_mb"])
        if "threads" in eng:
            config.engine.threads = int(eng["threads"])
        if "default_depth" in eng:
            config.engine.default_depth = int(eng["default_depth"])
        if "default_multipv" in eng:
            config.engine.default_multipv = int(eng["default_multipv"])

    if "openings" in data:
        op = data["openings"]
        if "explorer_source" in op:
            config.openings.explorer_source = op["explorer_source"]
        if "cache_ttl_hours" in op:
            config.openings.cache_ttl_hours = int(op["cache_ttl_hours"])
        if "min_games" in op:
            config.openings.min_games = int(op["min_games"])

    if "game_analysis" in data:
        ga = data["game_analysis"]
        if "analysis_depth" in ga:
            config.game_analysis.analysis_depth = int(ga["analysis_depth"])
        if "min_classification" in ga:
            config.game_analysis.min_classification = ga["min_classification"].upper()
        if "max_exercises_per_game" in ga:
            config.game_analysis.max_exercises_per_game = int(ga["max_exercises_per_game"])
        if "skip_first_plies" in ga:
            config.game_analysis.skip_first_plies = int(ga["skip_first_plies"])

    if "chesscom" in data:
        cc = data["chesscom"]
        if "user_agent" in cc:
            config.chesscom.user_agent = cc["user_agent"]
        if "request_delay" in cc:
            config.chesscom.request_delay = float(cc["request_delay"])

    if "tablebase" in data:
        tb = data["tablebase"]
        if "syzygy_path" in tb:
            config.tablebase.syzygy_path = str(Path(tb["syzygy_path"]).expanduser())
        if "use_lichess_fallback" in tb:
            config.tablebase.use_lichess_fallback = bool(tb["use_lichess_fallback"])
        if "max_pieces" in tb:
            config.tablebase.max_pieces = int(tb["max_pieces"])


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
        f"{ENV_PREFIX}ENGINE_PATH": lambda v: setattr(config.engine, "path", v),
        f"{ENV_PREFIX}ENGINE_HASH_MB": lambda v: setattr(config.engine, "hash_mb", int(v)),
        f"{ENV_PREFIX}ENGINE_THREADS": lambda v: setattr(config.engine, "threads", int(v)),
        f"{ENV_PREFIX}OPENINGS_SOURCE": lambda v: setattr(config.openings, "explorer_source", v),
        f"{ENV_PREFIX}OPENINGS_CACHE_TTL": lambda v: setattr(
            config.openings, "cache_ttl_hours", int(v)
        ),
        f"{ENV_PREFIX}OPENINGS_MIN_GAMES": lambda v: setattr(config.openings, "min_games", int(v)),
        f"{ENV_PREFIX}GAME_ANALYSIS_DEPTH": lambda v: setattr(
            config.game_analysis, "analysis_depth", int(v)
        ),
        f"{ENV_PREFIX}GAME_MIN_CLASSIFICATION": lambda v: setattr(
            config.game_analysis, "min_classification", v.upper()
        ),
        f"{ENV_PREFIX}GAME_MAX_EXERCISES": lambda v: setattr(
            config.game_analysis, "max_exercises_per_game", int(v)
        ),
        f"{ENV_PREFIX}GAME_SKIP_PLIES": lambda v: setattr(
            config.game_analysis, "skip_first_plies", int(v)
        ),
        f"{ENV_PREFIX}CHESSCOM_USER_AGENT": lambda v: setattr(config.chesscom, "user_agent", v),
        f"{ENV_PREFIX}CHESSCOM_REQUEST_DELAY": lambda v: setattr(
            config.chesscom, "request_delay", float(v)
        ),
        f"{ENV_PREFIX}TABLEBASE_SYZYGY_PATH": lambda v: setattr(config.tablebase, "syzygy_path", v),
        f"{ENV_PREFIX}TABLEBASE_USE_LICHESS": lambda v: setattr(
            config.tablebase, "use_lichess_fallback", v.lower() in ("true", "1", "yes")
        ),
        f"{ENV_PREFIX}TABLEBASE_MAX_PIECES": lambda v: setattr(
            config.tablebase, "max_pieces", int(v)
        ),
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

[chesscom]
user_agent = "ChessTrainer/1.0 (github.com/user/chess_trainer)"
request_delay = 0.5  # Seconds between archive page fetches

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

[engine]
# path = "/usr/games/stockfish"  # Auto-detects if not set
hash_mb = 256
threads = 2
default_depth = 20
default_multipv = 3

[openings]
explorer_source = "lichess"  # lichess, masters, or player
cache_ttl_hours = 168        # 1 week
min_games = 5                # Minimum games to show a move

[game_analysis]
analysis_depth = 20          # Engine depth for game analysis
min_classification = "MISTAKE"  # INACCURACY, MISTAKE, or BLUNDER
max_exercises_per_game = 10  # Max exercises generated per game
skip_first_plies = 6         # Skip opening theory moves

[tablebase]
# syzygy_path = "/path/to/syzygy"  # Local Syzygy tablebase files
use_lichess_fallback = true         # Fall back to Lichess API
max_pieces = 7                      # Max pieces for tablebase probe
"""
