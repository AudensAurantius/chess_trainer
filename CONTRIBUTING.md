# Contributing to Chess Trainer

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Getting Started

1. **Fork and clone** the repository
2. **Install dependencies** (requires Python 3.11+ and [uv](https://docs.astral.sh/uv/)):

```bash
uv sync --group dev --extra web --extra analysis
```

3. **Run the test suite** to verify your setup:

```bash
just test
```

If you don't have [just](https://github.com/casey/just), you can use `uv run pytest tests/ -v` directly.

## Development Workflow

1. **Branch from `main`** — use a descriptive branch name (e.g. `fix/card-scheduling-bug`, `feat/chess-com-import`)
2. **Make focused commits** — one logical change per commit
3. **Follow conventional commits** for commit messages:

| Prefix | Use for |
|--------|---------|
| `feat:` | New features |
| `fix:` | Bug fixes |
| `test:` | Adding or updating tests |
| `docs:` | Documentation changes |
| `refactor:` | Code changes that don't fix bugs or add features |
| `build:` | Build system, dependencies, CI |
| `style:` | Formatting, whitespace (no logic changes) |

Example: `feat: add Chess.com puzzle importer`

4. **Push and open a PR** against `main`

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for both linting and formatting.

- **Line length**: 100 characters
- **Docstrings**: Google convention
- **Type hints**: Required on all public functions
- **Imports**: Sorted by ruff (isort-compatible)

### Quick commands

```bash
just lint          # Lint and auto-fix
just fmt           # Format code
just check         # Check without modifying (what CI runs)
```

### Pre-commit hooks

The project includes pre-commit hooks that run lint and format checks automatically. Install them with:

```bash
uv run pre-commit install
```

## Testing

All tests live in `tests/` and follow a module-per-file convention matching `src/`:

```
tests/
  test_exercises.py     # Tests for src/exercises/
  test_scheduling.py    # Tests for src/scheduling/
  test_storage.py       # Tests for src/storage/
  ...
```

### Running tests

```bash
just test                    # Full suite
just test-k "scheduling"     # Filter by keyword
just coverage                # With coverage report
```

Or directly:

```bash
uv run pytest tests/ -v
uv run pytest tests/ -v -k "test_card"
uv run pytest tests/ --cov=src --cov-report=term-missing
```

### Writing tests

- Name test files `test_*.py` and test functions `test_*`
- Use `pytest` fixtures and `unittest.mock` for mocking
- Mock external HTTP calls (Lichess API, etc.) — never hit real APIs in tests
- Aim to cover both happy paths and edge cases
- Check existing tests for patterns (e.g. `test_http.py` for HTTP mocking, `test_storage.py` for DuckDB fixtures)

## Submitting Changes

1. **Open an issue first** for large changes or new features — this avoids wasted effort
2. **Keep PRs focused** — one feature or fix per PR
3. **CI must pass** — the GitHub Actions pipeline runs lint + full test suite
4. **Update tests** — new features need tests; bug fixes should include a regression test
5. **Update docs if needed** — if your change affects CLI commands or configuration, update the README

## Project Structure

The codebase lives under `src/` with each module handling a distinct concern:

```
src/
  exercises/     # Domain model — Exercise base class + type-specific subclasses
  scheduling/    # FSRS-4.5 spaced repetition engine (ReviewCard, FSRSScheduler)
  storage/       # DuckDB persistence (Repository, ExerciseStore, CardStore, OpeningStore)
  importers/     # Content import (Lichess puzzles, PGN games)
  training/      # Session coordinator (present → evaluate → schedule)
  analysis/      # UCI engine integration, move classification, mistake detection
  openings/      # Opening explorer (Lichess API), personal book, exercise generation
  tablebase/     # Endgame tablebase probing (Syzygy + Lichess API fallback)
  analytics/     # Progress analytics (accuracy, weak areas, streaks, retention)
  lichess/       # Lichess API client
  config.py      # TOML config with hierarchical overrides
  cli/           # Typer CLI with Rich board renderer
  web/           # FastAPI web interface with chessboard.js
```

See the [README](README.md) for the full architecture overview, CLI reference, and configuration options.

## Questions?

Open a [question issue](https://github.com/AudensAurantius/chess_trainer/issues/new?template=question.md) or start a discussion in an existing issue thread.
