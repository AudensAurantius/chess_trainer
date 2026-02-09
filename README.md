# Chess Trainer

![CI](https://github.com/AudensAurantius/chess_trainer/actions/workflows/ci.yml/badge.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)

A spaced repetition training system for chess improvement. Import tactical puzzles from Lichess, analyze your own games for mistakes, explore opening theory, probe endgame tablebases, and track your progress — all scheduled with the FSRS-4.5 algorithm for optimal retention.

## Features

- **Spaced Repetition** — FSRS-4.5 algorithm schedules reviews at optimal intervals based on your performance
- **Lichess Integration** — Import thousands of tactical puzzles with difficulty and theme filters, fetch games by username, and query the opening explorer
- **Own-Game Analysis** — Import games from PGN files or Lichess, detect mistakes with Stockfish or server evaluations, and automatically generate exercises from your blunders
- **Opening Explorer & Personal Book** — Browse opening statistics from the Lichess database (lichess, masters, or player), build a personal repertoire, and generate training exercises from your lines
- **Endgame Tablebase** — Probe positions with local Syzygy tablebases or the Lichess API fallback, with ranked move lists showing WDL and DTZ
- **Progress Analytics** — Track accuracy trends over time, identify weak areas by theme/type, view training streaks, and monitor retention curves
- **Interactive Training** — Drag-and-drop board (web UI) or SAN/UCI input (CLI), with hints, auto-rating, and self-report mode
- **Configuration** — TOML config file with hierarchical overrides (defaults, config file, environment variables, CLI flags)

## Quick Start

```bash
# Install
uv sync

# Import some puzzles
uv run chess-trainer import-puzzles --count 20

# Create review cards
uv run chess-trainer init-cards

# Start training (CLI)
uv run chess-trainer train

# Or launch the web interface
uv sync --extra web
uv run chess-trainer web
# Open http://127.0.0.1:8000
```

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Core (CLI only)
uv sync

# With web interface
uv sync --extra web

# With analysis dependencies (pandas/numpy for game analysis)
uv sync --extra analysis

# Development (tests, linting, formatting)
uv sync --group dev --extra web --extra analysis
```

## CLI Reference

### Core

| Command | Description |
|---------|-------------|
| `chess-trainer import-puzzles` | Import tactical puzzles from Lichess |
| `chess-trainer init-cards` | Create review cards for imported exercises |
| `chess-trainer train` | Start an interactive training session |
| `chess-trainer train --self-report` | Self-report mode (think, reveal, rate) |
| `chess-trainer stats` | Show exercise and card statistics |
| `chess-trainer web` | Launch the web training interface |

### Analysis

| Command | Description |
|---------|-------------|
| `chess-trainer analyze [FEN]` | Analyze a position with a UCI engine |
| `chess-trainer analyze --interactive` | Interactive analysis REPL |
| `chess-trainer analyze-game --pgn FILE` | Move-by-move quality report for a PGN game |
| `chess-trainer analyze-game --game-id ID` | Analyze a Lichess game by ID |
| `chess-trainer import-games --user NAME` | Import games from Lichess and generate exercises from mistakes |
| `chess-trainer import-games --pgn FILE` | Import games from a PGN file |

### Openings

| Command | Description |
|---------|-------------|
| `chess-trainer explore [FEN]` | Browse opening statistics from the Lichess explorer |
| `chess-trainer explore --repertoire` | Explorer with personal book overlay |
| `chess-trainer book add` | Add an opening line to your personal book |
| `chess-trainer book list` | List lines in your opening book |
| `chess-trainer book delete ID` | Delete an opening line |
| `chess-trainer book import-pgn FILE` | Import opening lines from a PGN file |
| `chess-trainer book sync` | Generate training exercises from book lines |
| `chess-trainer book train` | Train opening exercises |

### Endgame & Analytics

| Command | Description |
|---------|-------------|
| `chess-trainer tablebase FEN` | Probe endgame tablebases for a position |
| `chess-trainer tablebase --interactive` | Interactive tablebase explorer |
| `chess-trainer progress` | Show all progress analytics |
| `chess-trainer progress --accuracy` | Accuracy trend over time |
| `chess-trainer progress --weak` | Identify weak areas by theme |
| `chess-trainer progress --streaks` | Training streak and activity |
| `chess-trainer progress --retention` | Retention curve by repetition count |

### Configuration

| Command | Description |
|---------|-------------|
| `chess-trainer config init` | Generate a default config file |
| `chess-trainer config show` | Show effective configuration |

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

[engine]
# path = "/usr/bin/stockfish"
hash_mb = 128
threads = 1
default_depth = 20
default_multipv = 3

[openings]
explorer_source = "lichess"
cache_ttl_hours = 24
min_games = 5

[game_analysis]
analysis_depth = 18
min_classification = "MISTAKE"
max_exercises_per_game = 5
skip_first_plies = 10

[tablebase]
# syzygy_path = "/path/to/syzygy"
use_lichess_fallback = true
max_pieces = 7

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
  storage/       # DuckDB persistence (Repository, ExerciseStore, CardStore, OpeningStore)
  importers/     # Content import (Lichess puzzles, PGN games)
  training/      # Session coordinator
  analysis/      # UCI engine integration, move classification, mistake detection
  openings/      # Opening explorer (Lichess API), personal book, exercise generation
  tablebase/     # Endgame tablebase probing (Syzygy local + Lichess API fallback)
  analytics/     # Progress analytics (accuracy trends, weak areas, streaks, retention)
  lichess/       # Lichess API client
  config.py      # TOML configuration with hierarchical overrides
  cli/           # Typer CLI with Rich board renderer
  web/           # FastAPI web interface with chessboard.js
```

### Key Concepts

- **Exercise**: A chess position with a challenge and solution (tactics, openings, endgames, positional)
- **ReviewCard**: FSRS scheduling state for an exercise (stability, difficulty, due date)
- **TrainingSession**: Coordinates exercise presentation, evaluation, and scheduling
- **Repository**: Context manager wrapping DuckDB for storage operations

## Development

```bash
# Install dev dependencies
uv sync --group dev --extra web --extra analysis

# Run tests
uv run pytest tests/ -v

# Run tests with coverage
uv run pytest tests/ --cov=src --cov-report=term-missing

# Lint
uv run ruff check src/ tests/

# Format
uv run ruff format src/ tests/
```

## AI-Assisted Development

This project was designed and implemented with assistance from Claude (Anthropic). All architecture decisions, code review, and validation were directed by the author.

- Commit history includes `Co-Authored-By` trailers for transparency
- ~760 tests with ~90% code coverage serve as quality assurance
- See `DESIGN_REVIEW.md` for architectural rationale

## License

[MIT](LICENSE)
