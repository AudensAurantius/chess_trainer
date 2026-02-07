# Chess Trainer

A spaced repetition training system for chess improvement. Import tactical puzzles from Lichess, train with an interactive board, and track your progress using the FSRS-4.5 scheduling algorithm.

## Features

- **Spaced Repetition**: FSRS-4.5 algorithm schedules reviews at optimal intervals
- **Lichess Integration**: Import thousands of tactical puzzles with difficulty and theme filters
- **Interactive Training**: Drag-and-drop board (web) or SAN/UCI input (CLI)
- **Dark-themed Web UI**: Lichess-inspired interface with chessboard.js
- **CLI**: Full-featured command-line interface with Rich terminal output
- **DuckDB Storage**: Fast embedded database with zero configuration
- **TOML Configuration**: Hierarchical overrides (defaults, config file, env vars, CLI flags)

## Quick Start

```bash
# Install
pip install -e .

# Import some puzzles
chess-trainer import-puzzles --count 20

# Create review cards
chess-trainer init-cards

# Start training (CLI)
chess-trainer train

# Or launch the web interface
pip install -e ".[web]"
chess-trainer web
# Open http://127.0.0.1:8000
```

## Installation

Requires Python 3.11+.

```bash
# Core (CLI only)
pip install -e .

# With web interface
pip install -e ".[web]"

# Development (tests, linting)
pip install -e ".[dev,web]"
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `chess-trainer import-puzzles` | Import puzzles from Lichess |
| `chess-trainer init-cards` | Create review cards for imported exercises |
| `chess-trainer train` | Start an interactive training session |
| `chess-trainer train --self-report` | Self-report mode (think, reveal, rate) |
| `chess-trainer stats` | Show training statistics |
| `chess-trainer web` | Launch the web interface |
| `chess-trainer config init` | Generate default config file |
| `chess-trainer config show` | Show effective configuration |

### Import Options

```bash
chess-trainer import-puzzles --count 50 --difficulty harder --theme fork
```

### Training Options

```bash
chess-trainer train --new 10 --reviews 50 --type TACTIC
```

## Configuration

Config file location: `~/.chess-trainer/config.toml`

Generate a default config:

```bash
chess-trainer config init
```

### Example Config

```toml
[database]
path = "~/.chess-trainer/trainer.db"

[lichess]
api_url = "https://lichess.org/api"
# token = "lip_..."

[scheduler]
request_retention = 0.9
learning_steps = [1, 10]

[training]
max_new_cards = 20
max_reviews = 100
interleave_new = true

[logging]
level = "INFO"

[web]
host = "127.0.0.1"
port = 8000
```

### Environment Variables

All settings can be overridden with environment variables (prefix `CHESS_TRAINER_`):

| Variable | Config Key |
|----------|-----------|
| `CHESS_TRAINER_DB_PATH` | `database.path` |
| `CHESS_TRAINER_LICHESS_TOKEN` | `lichess.token` |
| `LICHESS_TOKEN` | `lichess.token` (legacy) |
| `CHESS_TRAINER_LOG_LEVEL` | `logging.level` |
| `CHESS_TRAINER_WEB_PORT` | `web.port` |
| `CHESS_TRAINER_MAX_NEW_CARDS` | `training.max_new_cards` |

## Architecture

```
src/
  exercises/     # Domain model (tactics, openings, endgames, positional)
  scheduling/    # FSRS-4.5 spaced repetition engine
  storage/       # DuckDB persistence (Repository, ExerciseStore, CardStore)
  importers/     # Content import (Lichess puzzle API)
  training/      # Session coordinator
  config.py      # TOML configuration system
  cli/           # Typer CLI with Rich output
  web/           # FastAPI web interface
```

### Key Concepts

- **Exercise**: A chess position with a challenge and solution
- **ReviewCard**: FSRS scheduling state for an exercise (stability, difficulty, due date)
- **TrainingSession**: Coordinates exercise presentation, evaluation, and scheduling
- **Repository**: Context manager wrapping DuckDB for storage operations

## Development

```bash
# Install dev dependencies
pip install -e ".[dev,web]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## License

MIT
