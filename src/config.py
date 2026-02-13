"""TOML-based configuration with hierarchical overrides.

Override chain: defaults → config file → environment variables → CLI flags.
"""

from __future__ import annotations

import os
import stat
import tomllib
import types
import warnings
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Union, get_args, get_origin, get_type_hints

DEFAULT_CONFIG_DIR = Path.home() / ".chess-trainer"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"

ENV_PREFIX = "CHESS_TRAINER_"


@dataclass
class DatabaseConfig:
    """Database connection settings."""

    path: str = str(DEFAULT_CONFIG_DIR / "trainer.db")
    data_dir: str = str(DEFAULT_CONFIG_DIR / "data")


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
class BundlesConfig:
    """Exercise bundle defaults."""

    default_pass_threshold: float = 0.9
    default_shuffle: bool = False


@dataclass
class ExperimentalConfig:
    """Experimental feature flags."""

    enabled: bool = False  # Master kill-switch
    vision: bool = False  # Vision-based position import
    vision_backend: str = "claude"  # claude | openai | local
    claude_api_key: str | None = None
    openai_api_key: str | None = None
    local_model_path: str | None = None


@dataclass
class ImportConfig:
    """Content import settings."""

    failed_puzzle_default_horizon: str = "3 months"
    failed_puzzle_auto_tag: bool = True


@dataclass
class DifficultyConfig:
    """Automatic difficulty adaptation settings."""

    enabled: bool = False
    window: int = 20  # Recent reviews to consider
    min_reviews: int = 5  # Min reviews before adapting
    promote_accuracy: float = 0.80  # Accuracy threshold to increase difficulty
    demote_accuracy: float = 0.45  # Accuracy threshold to decrease difficulty
    step: int = 150  # Rating shift on promote/demote
    difficulty_range: int = 600  # Width of difficulty window


@dataclass
class AuthConfig:
    """User authentication settings."""

    enabled: bool = False
    database_path: str = str(DEFAULT_CONFIG_DIR / "auth.db")
    session_expiry_hours: int = 720  # 30 days
    require_invite: bool = True


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
    bundles: BundlesConfig = field(default_factory=BundlesConfig)
    import_settings: ImportConfig = field(default_factory=ImportConfig)
    experimental: ExperimentalConfig = field(default_factory=ExperimentalConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    difficulty: DifficultyConfig = field(default_factory=DifficultyConfig)


# TODO: Consider simplifying using dataclasses-json or similar
# Validation of parsed config can be moved to a __post_init__ method
def _apply_toml(config: AppConfig, data: dict) -> None:
    """Apply TOML data onto an AppConfig, mutating in place."""
    if "database" in data:
        db = data["database"]
        if "path" in db:
            config.database.path = str(Path(db["path"]).expanduser())
        if "data_dir" in db:
            config.database.data_dir = str(Path(db["data_dir"]).expanduser())

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

    if "bundles" in data:
        bu = data["bundles"]
        if "default_pass_threshold" in bu:
            config.bundles.default_pass_threshold = float(bu["default_pass_threshold"])
        if "default_shuffle" in bu:
            config.bundles.default_shuffle = bool(bu["default_shuffle"])

    if "import_settings" in data:
        imp = data["import_settings"]
        if "failed_puzzle_default_horizon" in imp:
            config.import_settings.failed_puzzle_default_horizon = imp[
                "failed_puzzle_default_horizon"
            ]
        if "failed_puzzle_auto_tag" in imp:
            config.import_settings.failed_puzzle_auto_tag = bool(imp["failed_puzzle_auto_tag"])

    if "experimental" in data:
        exp = data["experimental"]
        if "enabled" in exp:
            config.experimental.enabled = bool(exp["enabled"])
        if "vision" in exp:
            config.experimental.vision = bool(exp["vision"])
        if "vision_backend" in exp:
            config.experimental.vision_backend = exp["vision_backend"]
        if "claude_api_key" in exp:
            config.experimental.claude_api_key = exp["claude_api_key"]
        if "openai_api_key" in exp:
            config.experimental.openai_api_key = exp["openai_api_key"]
        if "local_model_path" in exp:
            config.experimental.local_model_path = exp["local_model_path"]

    if "auth" in data:
        au = data["auth"]
        if "enabled" in au:
            config.auth.enabled = bool(au["enabled"])
        if "database_path" in au:
            config.auth.database_path = str(Path(au["database_path"]).expanduser())
        if "session_expiry_hours" in au:
            config.auth.session_expiry_hours = int(au["session_expiry_hours"])
        if "require_invite" in au:
            config.auth.require_invite = bool(au["require_invite"])

    if "difficulty" in data:
        diff = data["difficulty"]
        if "enabled" in diff:
            config.difficulty.enabled = bool(diff["enabled"])
        if "window" in diff:
            config.difficulty.window = int(diff["window"])
        if "min_reviews" in diff:
            config.difficulty.min_reviews = int(diff["min_reviews"])
        if "promote_accuracy" in diff:
            config.difficulty.promote_accuracy = float(diff["promote_accuracy"])
        if "demote_accuracy" in diff:
            config.difficulty.demote_accuracy = float(diff["demote_accuracy"])
        if "step" in diff:
            config.difficulty.step = int(diff["step"])
        if "difficulty_range" in diff:
            config.difficulty.difficulty_range = int(diff["difficulty_range"])


def _apply_env(config: AppConfig) -> None:
    """Apply environment variable overrides onto an AppConfig."""
    env_map = {
        f"{ENV_PREFIX}DB_PATH": lambda v: setattr(config.database, "path", v),
        f"{ENV_PREFIX}DATA_DIR": lambda v: setattr(config.database, "data_dir", v),
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
        f"{ENV_PREFIX}EXPERIMENTAL_ENABLED": lambda v: setattr(
            config.experimental, "enabled", v.lower() in ("true", "1", "yes")
        ),
        f"{ENV_PREFIX}EXPERIMENTAL_VISION": lambda v: setattr(
            config.experimental, "vision", v.lower() in ("true", "1", "yes")
        ),
        f"{ENV_PREFIX}EXPERIMENTAL_VISION_BACKEND": lambda v: setattr(
            config.experimental, "vision_backend", v
        ),
        f"{ENV_PREFIX}CLAUDE_API_KEY": lambda v: setattr(config.experimental, "claude_api_key", v),
        "ANTHROPIC_API_KEY": lambda v: setattr(config.experimental, "claude_api_key", v),
        f"{ENV_PREFIX}OPENAI_API_KEY": lambda v: setattr(config.experimental, "openai_api_key", v),
        "OPENAI_API_KEY": lambda v: setattr(config.experimental, "openai_api_key", v),
        f"{ENV_PREFIX}AUTH_ENABLED": lambda v: setattr(
            config.auth, "enabled", v.lower() in ("true", "1", "yes")
        ),
        f"{ENV_PREFIX}AUTH_DB_PATH": lambda v: setattr(config.auth, "database_path", v),
        f"{ENV_PREFIX}AUTH_SESSION_EXPIRY": lambda v: setattr(
            config.auth, "session_expiry_hours", int(v)
        ),
        f"{ENV_PREFIX}AUTH_REQUIRE_INVITE": lambda v: setattr(
            config.auth, "require_invite", v.lower() in ("true", "1", "yes")
        ),
        f"{ENV_PREFIX}DIFFICULTY_ENABLED": lambda v: setattr(
            config.difficulty, "enabled", v.lower() in ("true", "1", "yes")
        ),
        f"{ENV_PREFIX}DIFFICULTY_WINDOW": lambda v: setattr(config.difficulty, "window", int(v)),
        f"{ENV_PREFIX}DIFFICULTY_STEP": lambda v: setattr(config.difficulty, "step", int(v)),
        f"{ENV_PREFIX}DIFFICULTY_RANGE": lambda v: setattr(
            config.difficulty, "difficulty_range", int(v)
        ),
    }
    for key, setter in env_map.items():
        val = os.environ.get(key)
        if val is not None:
            setter(val)


def _secure_file(path: Path) -> None:
    """Set file permissions to owner-only (0600) for secret protection.

    Also secures the parent directory to 0700 (owner-only access).
    Silently ignores errors on platforms without Unix permissions (Windows).
    """
    try:
        path.chmod(0o600)
    except OSError:
        pass  # Windows or other platforms without Unix permissions
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass


def _check_permissions(path: Path) -> None:
    """Warn if config file is readable by group or others."""
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            warnings.warn(
                f"Config file {path} has overly permissive permissions "
                f"({stat.filemode(mode)}). Consider running: chmod 600 {path}",
                stacklevel=3,
            )
    except OSError:
        pass  # File doesn't exist or platform without Unix permissions


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
        _check_permissions(config_path)
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        _apply_toml(config, data)

    _apply_env(config)
    return config


# TODO: Consider using dataclass default values and dataclasses-json
# or similar to simplify serialization of default config
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
# data_dir = "~/.chess-trainer/data"  # Per-user databases (multi-tenant)

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

[bundles]
default_pass_threshold = 0.9  # Accuracy required to pass a Woodpecker cycle
default_shuffle = false        # Shuffle exercise order within bundles

[import_settings]
failed_puzzle_default_horizon = "3 months"  # Default time horizon for failed puzzle import
failed_puzzle_auto_tag = true               # Auto-tag imported failed puzzles

# [experimental]
# enabled = false                  # Master kill-switch for experimental features
# vision = false                   # Vision-based position import from screenshots
# vision_backend = "claude"        # claude | openai | local
# claude_api_key = "sk-ant-..."    # Anthropic API key (or set ANTHROPIC_API_KEY)
# openai_api_key = "sk-..."        # OpenAI API key (or set OPENAI_API_KEY)
# local_model_path = "/path/to/model"  # Local ONNX model for vision

# [auth]
# enabled = false                  # Enable user authentication for web UI
# database_path = "~/.chess-trainer/auth.db"
# session_expiry_hours = 720       # 30 days
# require_invite = true            # Require invite code for registration

# [difficulty]
# enabled = false                  # Enable automatic difficulty adaptation
# window = 20                      # Recent reviews to consider
# min_reviews = 5                  # Min reviews before adapting
# promote_accuracy = 0.8           # Accuracy to increase difficulty
# demote_accuracy = 0.45           # Accuracy to decrease difficulty
# step = 150                       # Rating shift on promote/demote
# difficulty_range = 600           # Width of difficulty window
"""


# ── Config CLI helpers ────────────────────────────────────────────────────────


def _serialize_toml(data: dict) -> str:
    """Serialize a nested dict to TOML format.

    Handles str, int, float, bool, list[int], and None (commented out).
    Bool must be checked before int since ``bool`` is an ``int`` subclass.
    """
    lines: list[str] = []
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, val in values.items():
            if val is None:
                lines.append(f"# {key} =")
            elif isinstance(val, bool):
                lines.append(f"{key} = {str(val).lower()}")
            elif isinstance(val, int):
                lines.append(f"{key} = {val}")
            elif isinstance(val, float):
                lines.append(f"{key} = {val}")
            elif isinstance(val, list):
                items = ", ".join(str(v) for v in val)
                lines.append(f"{key} = [{items}]")
            else:
                # String — escape backslashes and quotes
                escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
        lines.append("")
    return "\n".join(lines) + "\n" if lines else ""


def get_config_keys() -> dict[str, type]:
    """Introspect AppConfig dataclass fields to build a flat key→type map.

    Returns:
        Mapping of ``"section.field"`` → Python type, e.g.
        ``{"web.port": int, "lichess.token": str, ...}``.
    """
    result: dict[str, type] = {}
    hints = get_type_hints(AppConfig)
    for f in fields(AppConfig):
        sub_cls = hints[f.name]
        sub_hints = get_type_hints(sub_cls)
        for sf in fields(sub_cls):
            tp = sub_hints[sf.name]
            # Unwrap Optional (str | None → str)
            origin = get_origin(tp)
            if origin is Union or isinstance(tp, types.UnionType):
                args = [a for a in get_args(tp) if a is not type(None)]
                tp = args[0] if args else str
            # Unwrap generics (list[int] → list)
            origin = get_origin(tp)
            if origin is not None:
                tp = origin
            result[f"{f.name}.{sf.name}"] = tp
    return result


def coerce_value(raw: str, target_type: type) -> object:
    """Coerce a CLI string value to the target Python type.

    Args:
        raw: Raw string from the CLI.
        target_type: Expected Python type (str, int, float, bool, list).

    Returns:
        Coerced Python value.

    Raises:
        ValueError: If the value cannot be coerced.
    """
    # Empty string → None for Optional fields (caller handles this)
    if raw == "" and target_type is str:
        return None

    if target_type is bool:
        lower = raw.lower()
        if lower in ("true", "yes", "1"):
            return True
        if lower in ("false", "no", "0"):
            return False
        raise ValueError(f"Invalid boolean: {raw!r}. Use true/false/yes/no/1/0.")

    if target_type is int:
        return int(raw)

    if target_type is float:
        return float(raw)

    if target_type is list:
        # Accept "1,10" or "[1, 10]" or "[]"
        stripped = raw.strip().strip("[]")
        if not stripped:
            return []
        return [int(x.strip()) for x in stripped.split(",")]

    return raw  # str


_VALIDATION_RULES: dict[str, tuple] = {
    "web.port": ("range", 1, 65535),
    "scheduler.request_retention": ("range", 0.0, 1.0),
    "engine.default_depth": ("range", 1, 100),
    "engine.default_multipv": ("range", 1, 20),
    "engine.hash_mb": ("range", 1, 65536),
    "engine.threads": ("range", 1, 256),
    "training.max_new_cards": ("range", 0, 10000),
    "training.max_reviews": ("range", 0, 10000),
    "openings.min_games": ("range", 0, 1000000),
    "openings.cache_ttl_hours": ("range", 0, 100000),
    "game_analysis.analysis_depth": ("range", 1, 100),
    "game_analysis.max_exercises_per_game": ("range", 1, 1000),
    "game_analysis.skip_first_plies": ("range", 0, 200),
    "scheduler.maximum_interval": ("range", 1, 365000),
    "tablebase.max_pieces": ("range", 3, 7),
    "chesscom.request_delay": ("range", 0.0, 60.0),
    "logging.level": ("enum", {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}),
    "game_analysis.min_classification": ("enum", {"INACCURACY", "MISTAKE", "BLUNDER"}),
    "openings.explorer_source": ("enum", {"lichess", "masters", "player"}),
    "bundles.default_pass_threshold": ("range", 0.0, 1.0),
    "experimental.vision_backend": ("enum", {"claude", "openai", "local"}),
    "auth.session_expiry_hours": ("range", 1, 87600),
    "difficulty.window": ("range", 1, 1000),
    "difficulty.min_reviews": ("range", 1, 1000),
    "difficulty.promote_accuracy": ("range", 0.0, 1.0),
    "difficulty.demote_accuracy": ("range", 0.0, 1.0),
    "difficulty.step": ("range", 1, 1000),
    "difficulty.difficulty_range": ("range", 50, 3000),
}


def _validate_value(key: str, value: object) -> None:
    """Validate a config value against domain constraints.

    Raises:
        ValueError: If the value violates constraints.
    """
    rule = _VALIDATION_RULES.get(key)
    if rule is None:
        return

    kind = rule[0]
    if kind == "range":
        lo, hi = rule[1], rule[2]
        if not (lo <= value <= hi):
            raise ValueError(f"{key} must be between {lo} and {hi}, got {value}")
    elif kind == "enum":
        allowed = rule[1]
        if value not in allowed:
            raise ValueError(f"{key} must be one of {sorted(allowed)}, got {value!r}")


def get_config_value(config: AppConfig, key: str) -> object:
    """Get a config value by dotted key (e.g. ``"web.port"``).

    Raises:
        KeyError: If the section or field is unknown.
    """
    parts = key.split(".", 1)
    if len(parts) != 2:
        raise KeyError(f"Invalid key format: {key!r}. Expected 'section.field'.")
    section, field_name = parts
    try:
        section_obj = getattr(config, section)
    except AttributeError:
        raise KeyError(f"Unknown config section: {section!r}")
    try:
        return getattr(section_obj, field_name)
    except AttributeError:
        raise KeyError(f"Unknown field {field_name!r} in section {section!r}")


def set_config_value(key: str, raw_value: str, config_path: Path | None = None) -> object:
    """Validate, coerce, and persist a config value to the TOML file.

    Creates the file and parent directories if they don't exist.

    Args:
        key: Dotted key, e.g. ``"web.port"``.
        raw_value: Raw CLI string to set.
        config_path: Path to the TOML file. Defaults to ``DEFAULT_CONFIG_PATH``.

    Returns:
        The coerced Python value that was written.

    Raises:
        KeyError: Unknown key.
        ValueError: Invalid value.
    """
    keys = get_config_keys()
    if key not in keys:
        raise KeyError(f"Unknown config key: {key!r}")

    target_type = keys[key]
    value = coerce_value(raw_value, target_type)

    # Case normalization for enum-like fields
    if key in ("logging.level", "game_analysis.min_classification") and isinstance(value, str):
        value = value.upper()
    if key == "experimental.vision_backend" and isinstance(value, str):
        value = value.lower()

    _validate_value(key, value)

    # Path expansion
    if key in (
        "database.path",
        "database.data_dir",
        "tablebase.syzygy_path",
        "auth.database_path",
    ) and isinstance(value, str):
        value = str(Path(value).expanduser())

    # Read existing TOML
    path = config_path or DEFAULT_CONFIG_PATH
    data: dict = {}
    if path.is_file():
        with open(path, "rb") as f:
            data = tomllib.load(f)

    # Update nested dict
    section, field_name = key.split(".", 1)
    if section not in data:
        data[section] = {}
    data[section][field_name] = value

    # Write back
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialize_toml(data))
    _secure_file(path)

    return value


def reset_config_value(key: str | None = None, config_path: Path | None = None) -> None:
    """Reset a config key to its default, or reset the entire file.

    Args:
        key: Dotted key to reset. If ``None``, resets the entire config file
            to the commented default template.
        config_path: Path to the TOML file. Defaults to ``DEFAULT_CONFIG_PATH``.

    Raises:
        KeyError: Unknown key.
    """
    path = config_path or DEFAULT_CONFIG_PATH

    if key is None:
        # Full reset — restore the commented default template
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generate_default_config())
        _secure_file(path)
        return

    keys = get_config_keys()
    if key not in keys:
        raise KeyError(f"Unknown config key: {key!r}")

    # Remove just this key from the TOML file
    data: dict = {}
    if path.is_file():
        with open(path, "rb") as f:
            data = tomllib.load(f)

    section, field_name = key.split(".", 1)
    if section in data and field_name in data[section]:
        del data[section][field_name]
        # Remove empty sections
        if not data[section]:
            del data[section]

    path.parent.mkdir(parents=True, exist_ok=True)
    if data:
        path.write_text(_serialize_toml(data))
    else:
        # All keys removed → write empty file so defaults take effect
        path.write_text("")
    _secure_file(path)


def is_experimental_enabled(config: AppConfig, feature: str) -> bool:
    """Check if an experimental feature is enabled.

    Both the master ``experimental.enabled`` flag and the per-feature flag
    must be ``True`` for the feature to be considered active.

    Args:
        config: Application configuration.
        feature: Feature name (e.g. ``"vision"``).

    Returns:
        ``True`` only if both flags are enabled.
    """
    if not config.experimental.enabled:
        return False
    return bool(getattr(config.experimental, feature, False))
