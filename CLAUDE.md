# CLAUDE.md — Chess Trainer Project

## Build & Run

```bash
# Install all dependencies (core + dev + web + extras)
uv sync --all-extras

# Run the full test suite (1225+ tests)
uv run pytest tests/ -v

# Lint and format
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/

# Check without modifying
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/

# Run a single test file or keyword
uv run pytest tests/ -v -k "test_bundles"

# Coverage report
uv run pytest tests/ --cov=src --cov-report=term-missing

# Justfile shortcuts (just install, just test, just lint, just fmt, just coverage)
```

Entry point: `chess-trainer` CLI via Typer (`src/cli/app.py`).

## Architecture

```
src/
├── auth/            # User authentication (models, passwords, store, service)
├── exercises/       # Domain model (base + tactics/openings/endgames/positional/bundle)
├── scheduling/      # FSRS-4.5 spaced repetition (ReviewCard, FSRSScheduler)
├── storage/         # DuckDB storage (Repository, ExerciseStore, CardStore, OpeningStore, TagStore, BundleStore)
├── training/        # TrainingSession coordinator + WoodpeckerSession (bundle cycling)
├── importers/       # Content import (Lichess puzzles, games, Chess.com puzzles/games)
├── analysis/        # UCI engine analysis (EngineManager, MistakeDetector)
├── openings/        # Opening explorer (Lichess API) + personal book (PGN, exercise gen)
├── tablebase/       # Endgame tablebase probing (Syzygy local + Lichess API fallback)
├── endgame_masters/ # Master game endgame discovery, annotation, exercise gen
├── analytics/       # Progress analytics (trends, streaks, retention)
├── vision/          # Vision-based board recognition (Claude/OpenAI/local backends)
├── chesscom/        # Chess.com API client (mirrors src/lichess/)
├── lichess/         # Lichess API client
├── cli/             # Typer CLI with board renderer
├── web/             # FastAPI web GUI (Jinja2 + chessboard.js + auth middleware)
└── config.py        # TOML config with hierarchical overrides (defaults → file → env → CLI)
```

## Key API Contracts

- `Repository` is a context manager: `with Repository(path) as repo:`
- `ExerciseStore.add()` (not `save()`) — `CardStore` uses `save()`
- `TrainingSession.submit(moves, time_ms)` → `(ExerciseResult, SchedulingResult)`
- `session.next()` pre-computes scheduling; `rate()` requires prior `next()` call
- `TacticExercise.solution` stores UCI strings; `get_solution()` returns `chess.Move` list
- `Exercise.evaluate()` with empty moves returns `correct=False, partial_credit=0.0`
- For tactics: solution alternates user/opponent moves; `user_moves = solution[::2]`
- `WoodpeckerSession` is standalone (not a `TrainingSession` subclass)
- Bundle IDs: `"bundle:{slug}"` format; slugs: lowercase alphanum+hyphens, 2-64 chars
- `TagStore.find_by_tags(entity_type, tags, match_all)` — AND/OR logic
- Session tag filter: `SessionConfig(include_tags=, exclude_tags=)` → OR logic for both
- FSRS Rating: AGAIN(1), HARD(2), GOOD(3), EASY(4)
- `AuthStore` manages its own DuckDB connection to `auth.db` (separate from `trainer.db`)
- `AuthService(store, session_expiry_hours)` — business logic layer for register/login/session
- Auth exceptions: `AuthError` base, `InvalidInviteCodeError`, `InvalidCredentialsError`, etc.
- Auth is optional: `config.auth.enabled = False` (default) — middleware is a no-op

## Coding Conventions

- **Style:** Google docstrings, type hints on all functions, `ruff` for lint+format
- **Line length:** 100 chars (`pyproject.toml [tool.ruff]`)
- **Commits:** Conventional Commits (`feat/fix/docs/test/refactor`), include `Co-Authored-By` trailer. **Commits must be modular** — one logical unit per commit. For multi-step features, commit each layer separately (e.g., models, then store, then service, then config, then routes, then tests, then docs). Each commit should compile and pass tests independently. Never squash an entire feature into a single commit.
- **Branching:** Create a feature branch off `claude/implement-from-notes` for each roadmap item or significant feature (e.g., `claude/b1-user-auth`, `claude/b2-multi-tenant`). Develop and commit incrementally on the feature branch. Merge back to `claude/implement-from-notes` when complete and validated. This keeps the primary branch clean and makes features reviewable as a series of commits.
- **Testing:** All new functionality must have thorough unit tests. Write integration tests for cross-module interactions (e.g., storage ↔ domain, web ↔ storage). Run full test suite before commits. Verify no regressions in test count.
- **Quality:** `ruff check --fix` before every commit. The pre-commit hook enforces this.
- **Imports:** Use `from __future__ import annotations` + `TYPE_CHECKING` to avoid circular imports

## Common Pitfalls

1. **DuckDB INSERT OR REPLACE with FK** doesn't update all columns → use DELETE + INSERT (`card_store.py`)
2. **Circular imports** in openings: `explorer.py` ↔ `storage.opening_store` → use `TYPE_CHECKING` + `from __future__ import annotations`
3. **`import chess.pgn` inside conditional branch** makes `chess` local to entire function → move import to function top
4. **CLI local imports:** `from ..tablebase import X` inside function → patch `src.tablebase.X` not `src.cli.app.X` in tests
5. **CLI tests without engine/API mocks** cause real Stockfish + HTTP calls → always mock `EngineManager.open` and `requests.get`
6. **Real `LICHESS_TOKEN` env var** can leak into tests → `monkeypatch.delenv()` first
7. **DuckDB cursor corruption:** `iterate_all()` + queries in same loop → materialize with `list()` first
8. **Mutable default args** in API functions: `dict = {}` → `dict | None = None`
9. **SessionManager.start_bundle_session** must NOT call `end_session()` (which closes repo) — clear fields directly
10. **`get_type_hints()`** with `from __future__ import annotations` returns `types.UnionType` for `str | None`, not `typing.Union`
11. **DuckDB returns naive datetimes** — comparing with `datetime.now(UTC)` (timezone-aware) raises `TypeError`. Use `.replace(tzinfo=None)` or `datetime.utcnow()` equivalent for comparisons (`auth/service.py`)

## Package Layout

Non-standard layout for uv_build:
```toml
[tool.uv.build-backend]
module-name = "src"
module-root = ""
```

Web deps: `httpx` needed for FastAPI TestClient (in dev deps).

## Decision Log

[`DECISION_LOG.md`](DECISION_LOG.md) — significant design and architectural decisions with rationale.
Update this when making decisions that affect the project's direction, storage model, or public API.

## Roadmap

Active roadmap: `memory/roadmap-v3.md` in the Claude memory directory.

Next items: F16 (import failed puzzles), F17 (training hooks), then enhancements (E1-E18).

E16-E18 were added from a TODO review (2026-02-09):
- E16: Strict type safety for HTTP/API layer (resolve `get_lichess()` return type union)
- E17: Serialization cleanup with dataclasses-json (config + card boilerplate)
- E18: Database schema migration tracking (version table + sequential migrations)
