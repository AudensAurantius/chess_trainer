# Chess Trainer — project task runner
# https://github.com/casey/just

set dotenv-load := false

# Project paths
src          := "src"
tests        := "tests"
project_name := "chess-trainer"

# Defaults
default_depth   := "20"
default_multipv := "3"
default_count   := "20"
default_host    := "127.0.0.1"
default_port    := "8000"

# ─── build ────────────────────────────────────────────────────────────────────

[group: 'build']
[doc('Install all dependencies (core + dev + web)')]
install:
    uv sync --all-extras

[group: 'build']
[doc('Build the package')]
build:
    uv build

[group: 'build']
[doc('Publish the package to PyPI')]
publish: build
    uv publish

[group: 'build']
[doc('Remove build artifacts and caches')]
clean:
    rm -rf dist/ build/ .pytest_cache/ .ruff_cache/
    find . -type d -name __pycache__ -not -path './.direnv/*' -not -path './.venv/*' -exec rm -rf {} +

# ─── lint ─────────────────────────────────────────────────────────────────────

[group: 'lint']
[doc('Run ruff linter and fix auto-fixable issues')]
lint *args:
    uv run ruff check --fix {{ args }} {{ src }} {{ tests }}

[group: 'lint']
[doc('Run ruff formatter')]
fmt *args:
    uv run ruff format {{ args }} {{ src }} {{ tests }}

[group: 'lint']
[doc('Check formatting and lint without modifying files')]
check:
    uv run ruff format --check {{ src }} {{ tests }}
    uv run ruff check {{ src }} {{ tests }}

# ─── test ─────────────────────────────────────────────────────────────────────

[group: 'test']
[doc('Run the full test suite')]
test *args:
    uv run pytest {{ tests }} -v {{ args }}

[group: 'test']
[doc('Run tests matching a keyword expression (e.g. just test-k analysis)')]
test-k pattern *args:
    uv run pytest {{ tests }} -v -k "{{ pattern }}" {{ args }}

[group: 'test']
[doc('Run tests with coverage report')]
coverage *args:
    uv run pytest {{ tests }} --cov={{ src }} --cov-report=term-missing {{ args }}

# ─── run ──────────────────────────────────────────────────────────────────────

[group: 'run']
[doc('Start the web training interface')]
web host=default_host port=default_port:
    uv run {{ project_name }} web --host {{ host }} --port {{ port }}

[group: 'run']
[doc('Start an interactive training session')]
train *args:
    uv run {{ project_name }} train {{ args }}

[group: 'run']
[doc('Show training statistics')]
stats *args:
    uv run {{ project_name }} stats {{ args }}

# ─── import ───────────────────────────────────────────────────────────────────

[group: 'import']
[doc('Import tactical puzzles from Lichess')]
import-puzzles count=default_count *args:
    uv run {{ project_name }} import-puzzles --count {{ count }} {{ args }}

[group: 'import']
[doc('Create review cards for all exercises without one')]
init-cards *args:
    uv run {{ project_name }} init-cards {{ args }}

# ─── analyze ──────────────────────────────────────────────────────────────────

[group: 'analyze']
[doc('Analyze a FEN position (starting position if omitted)')]
analyze fen="" depth=default_depth multipv=default_multipv *args:
    uv run {{ project_name }} analyze {{ if fen != "" { '"' + fen + '"' } else { "" } }} --depth {{ depth }} --multipv {{ multipv }} {{ args }}

[group: 'analyze']
[doc('Start interactive analysis (play moves, undo, explore)')]
analyze-interactive fen="" *args:
    uv run {{ project_name }} analyze {{ if fen != "" { '"' + fen + '"' } else { "" } }} --interactive {{ args }}

[group: 'analyze']
[doc('Analyze a game from PGN file')]
analyze-game pgn *args:
    uv run {{ project_name }} analyze-game --pgn "{{ pgn }}" {{ args }}

# ─── games ───────────────────────────────────────────────────────────────

[group: 'games']
[doc('Import games from a PGN file and generate exercises')]
import-games-pgn pgn *args:
    uv run {{ project_name }} import-games --pgn "{{ pgn }}" {{ args }}

[group: 'games']
[doc('Import games from Lichess (with server evals, no engine needed)')]
import-games-lichess username *args:
    uv run {{ project_name }} import-games --user {{ username }} --server-evals {{ args }}

[group: 'games']
[doc('Import games from Lichess with local engine analysis')]
import-games-engine username *args:
    uv run {{ project_name }} import-games --user {{ username }} {{ args }}

# ─── explore ─────────────────────────────────────────────────────────────────

[group: 'explore']
[doc('Explore opening statistics interactively')]
explore fen="" *args:
    uv run {{ project_name }} explore {{ if fen != "" { '"' + fen + '"' } else { "" } }} {{ args }}

[group: 'explore']
[doc('Explore filtered by speeds (e.g. just explore-speed blitz,rapid)')]
explore-speed speeds fen="" *args:
    uv run {{ project_name }} explore {{ if fen != "" { '"' + fen + '"' } else { "" } }} --speeds {{ speeds }} {{ args }}

[group: 'explore']
[doc('Explore filtered by rating brackets (e.g. just explore-rating 1600,1800,2000)')]
explore-rating ratings fen="" *args:
    uv run {{ project_name }} explore {{ if fen != "" { '"' + fen + '"' } else { "" } }} --ratings {{ ratings }} {{ args }}

[group: 'explore']
[doc('Explore with repertoire overlay showing book moves')]
explore-repertoire fen="" *args:
    uv run {{ project_name }} explore {{ if fen != "" { '"' + fen + '"' } else { "" } }} --repertoire {{ args }}

[group: 'explore']
[doc('Explore moves where white scores well (min white win %)')]
explore-white min_pct="50" fen="" *args:
    uv run {{ project_name }} explore {{ if fen != "" { '"' + fen + '"' } else { "" } }} --min-white-pct {{ min_pct }} {{ args }}

[group: 'explore']
[doc('Explore moves where black scores well (min black win %)')]
explore-black min_pct="50" fen="" *args:
    uv run {{ project_name }} explore {{ if fen != "" { '"' + fen + '"' } else { "" } }} --min-black-pct {{ min_pct }} {{ args }}

# ─── book ────────────────────────────────────────────────────────────────────

[group: 'book']
[doc('Add an opening line to your book')]
book-add pgn color *args:
    uv run {{ project_name }} book add --pgn "{{ pgn }}" --color {{ color }} {{ args }}

[group: 'book']
[doc('List opening lines in your book')]
book-list *args:
    uv run {{ project_name }} book list {{ args }}

[group: 'book']
[doc('Sync book lines into training exercises')]
book-sync *args:
    uv run {{ project_name }} book sync {{ args }}

[group: 'book']
[doc('Start a training session with opening exercises')]
book-train *args:
    uv run {{ project_name }} book train {{ args }}

# ─── tablebase ───────────────────────────────────────────────────────────────

[group: 'tablebase']
[doc('Probe a FEN position in the endgame tablebase')]
tablebase fen *args:
    uv run {{ project_name }} tablebase "{{ fen }}" {{ args }}

[group: 'tablebase']
[doc('Interactive tablebase explorer')]
tablebase-interactive fen="" *args:
    uv run {{ project_name }} tablebase {{ if fen != "" { '"' + fen + '"' } else { "" } }} --interactive {{ args }}

# ─── endgame-masters ────────────────────────────────────────────────────────

[group: 'endgame-masters']
[doc('Browse master games with endgame tablebase eval')]
endgame-masters fen="" *args:
    uv run {{ project_name }} endgame-masters {{ if fen != "" { '"' + fen + '"' } else { "" } }} {{ args }}

[group: 'endgame-masters']
[doc('Replay a master game endgame interactively')]
endgame-replay fen *args:
    uv run {{ project_name }} endgame-masters "{{ fen }}" --replay {{ args }}

[group: 'endgame-masters']
[doc('Generate exercises from master game endgames')]
endgame-generate fen *args:
    uv run {{ project_name }} endgame-masters "{{ fen }}" --generate {{ args }}

# ─── vision ──────────────────────────────────────────────────────────────────

[group: 'vision']
[doc('Scan a chess board image and recognize the position')]
scan image *args:
    uv run {{ project_name }} scan "{{ image }}" {{ args }}

[group: 'vision']
[doc('Scan an image and run engine analysis on the result')]
scan-analyze image *args:
    uv run {{ project_name }} scan "{{ image }}" --analyze {{ args }}

# ─── config ───────────────────────────────────────────────────────────────────

[group: 'config']
[doc('Show effective configuration')]
config-show:
    uv run {{ project_name }} config show

[group: 'config']
[doc('Generate default config file at ~/.chess-trainer/config.toml')]
config-init:
    uv run {{ project_name }} config init
