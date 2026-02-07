# Chess Trainer: Design Review and Recommendations

**Date:** 2026-02-06
**Reviewer:** Claude Opus 4.5

---

## Executive Summary

This project has solid foundations — a clean Lichess API client, well-structured data models, and thoughtful notes on spaced repetition algorithms. However, the core architecture for a unified training system doesn't yet exist. The main work ahead is:

1. Designing the **Exercise abstraction** that unifies all training types
2. Implementing the **spaced repetition engine**
3. Building the **content import pipeline** for non-Lichess sources
4. Creating a **unified training UI**

---

## What Exists

| Component | Status | Quality |
|-----------|--------|---------|
| Lichess API client | Complete | Good |
| Data models (puzzles, games) | Complete | Good |
| HTTP utilities | Complete | Good |
| Theme fetching | Complete | Good |
| PGN parsing | Stub | — |
| Chess board (pygame) | Partial | Needs work |
| Visualization | Prototype | — |
| Database layer | Empty | — |
| Spaced repetition | Notes only | — |
| Exercise abstraction | Missing | — |
| Training UI | Missing | — |

---

## Architecture Recommendations

### 1. Core Domain Model

The fundamental insight from your `claude.md` is that **all training types share a common structure**:

```
Position → Challenge → Response → Evaluation → Feedback
```

I recommend a unified `Exercise` abstraction:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
import chess

class ExerciseType(Enum):
    TACTIC = auto()      # Find the winning move(s)
    OPENING = auto()     # Play the theory move
    ENDGAME = auto()     # Execute the winning technique
    POSITIONAL = auto()  # Identify/execute the key idea

@dataclass
class Exercise(ABC):
    """Base class for all training exercises."""
    id: str
    exercise_type: ExerciseType
    position: chess.Board          # Starting position
    tags: list[str]                # Searchable metadata
    source: str                    # Where this came from
    difficulty: float | None       # Estimated difficulty (Elo-like)

    @abstractmethod
    def get_challenge(self) -> str:
        """What the user is asked to do."""
        ...

    @abstractmethod
    def evaluate(self, moves: list[chess.Move]) -> "ExerciseResult":
        """Evaluate the user's response."""
        ...

    @abstractmethod
    def get_explanation(self) -> str:
        """Explanation shown after attempt."""
        ...


@dataclass
class ExerciseResult:
    """Result of attempting an exercise."""
    correct: bool
    partial_credit: float          # 0.0 to 1.0
    time_taken_ms: int
    moves_played: list[chess.Move]
    feedback: str
```

### 2. Exercise Type Implementations

**Tactics (from Lichess):**
```python
@dataclass
class TacticExercise(Exercise):
    solution: list[chess.Move]     # The winning line
    themes: list[str]              # fork, pin, skewer, etc.

    def evaluate(self, moves: list[chess.Move]) -> ExerciseResult:
        # Check if moves match solution (with some tolerance for transpositions)
        ...
```

**Openings:**
```python
@dataclass
class OpeningExercise(Exercise):
    line: list[chess.Move]         # The full opening line
    current_move_index: int        # Which move we're testing
    eco_code: str                  # E.g., "B90"
    opening_name: str              # E.g., "Sicilian Najdorf"

    def get_challenge(self) -> str:
        return f"What is the main line for {self.side_to_move}?"

    def evaluate(self, moves: list[chess.Move]) -> ExerciseResult:
        expected = self.line[self.current_move_index]
        # Allow alternative theory moves with partial credit
        ...
```

**Endgames:**
```python
@dataclass
class EndgameExercise(Exercise):
    winning_side: chess.Color
    technique_name: str            # "Lucena Position", "Philidor Defense"
    key_ideas: list[str]           # From your YAML notes
    tablebase_eval: int | None     # DTZ if available

    def evaluate(self, moves: list[chess.Move]) -> ExerciseResult:
        # Check against tablebase or verify the technique is applied
        ...
```

**Positional:**
```python
@dataclass
class PositionalExercise(Exercise):
    correct_plans: list[str]       # Acceptable strategic ideas
    correct_moves: list[chess.Move]  # Moves that demonstrate understanding
    source_game: str | None        # "Capablanca vs Tartakower, 1924"
    concept: str                   # "Minority attack", "Good vs bad bishop"

    def get_challenge(self) -> str:
        return f"Find the best plan for {self.side_to_move}."
```

### 3. Spaced Repetition Engine

Based on your notes, I recommend **FSRS (Free Spaced Repetition Scheduler)** — it's the algorithm behind Anki's newer versions and has strong empirical support.

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import exp, log

@dataclass
class ReviewCard:
    """Tracks learning state for a single exercise."""
    exercise_id: str
    stability: float = 1.0         # Days until P drops to 90%
    difficulty: float = 0.3        # Item difficulty (0-1)
    last_review: datetime | None = None
    next_review: datetime | None = None
    reps: int = 0
    lapses: int = 0                # Times forgotten

    def recall_probability(self, now: datetime = None) -> float:
        """Current probability of recall."""
        if self.last_review is None:
            return 0.0
        now = now or datetime.now()
        elapsed_days = (now - self.last_review).total_seconds() / 86400
        return exp(-elapsed_days / self.stability * log(10) / log(0.9))

    def schedule_next(self, grade: int, now: datetime = None):
        """
        Update card after review.

        Grade: 1=forgot, 2=hard, 3=good, 4=easy
        """
        now = now or datetime.now()
        self.last_review = now
        self.reps += 1

        if grade == 1:  # Forgot
            self.lapses += 1
            self.stability = max(1.0, self.stability * 0.5)
        else:
            # Stability increases more for harder recalls
            retrievability = self.recall_probability(now)
            stability_gain = 1 + exp(1 - retrievability) * (grade - 2) * 0.5
            self.stability *= stability_gain

        # Schedule next review at 90% recall probability
        interval_days = self.stability * 0.9
        self.next_review = now + timedelta(days=interval_days)


class ReviewScheduler:
    """Manages review scheduling across all exercises."""

    def __init__(self, storage: "ExerciseStorage"):
        self.storage = storage

    def get_due_cards(self, limit: int = 20) -> list[ReviewCard]:
        """Get cards due for review, prioritized by overdueness."""
        now = datetime.now()
        due = [c for c in self.storage.get_all_cards()
               if c.next_review is None or c.next_review <= now]
        # Sort by how overdue (most overdue first)
        due.sort(key=lambda c: c.next_review or datetime.min)
        return due[:limit]

    def get_new_cards(self, exercise_type: ExerciseType = None,
                      limit: int = 5) -> list[Exercise]:
        """Get new exercises not yet in the review system."""
        ...

    def record_review(self, card: ReviewCard, grade: int):
        """Record a review and update scheduling."""
        card.schedule_next(grade)
        self.storage.save_card(card)
```

### 4. Content Import System

This is where the "lack of APIs" problem lives. I suggest a plugin architecture:

```python
from abc import ABC, abstractmethod
from pathlib import Path

class ContentImporter(ABC):
    """Base class for content import plugins."""

    @abstractmethod
    def can_import(self, source: str | Path) -> bool:
        """Check if this importer handles the given source."""
        ...

    @abstractmethod
    def import_exercises(self, source: str | Path) -> list[Exercise]:
        """Import exercises from the source."""
        ...


class LichessPuzzleImporter(ContentImporter):
    """Import tactics from Lichess API."""

    def can_import(self, source: str | Path) -> bool:
        return source == "lichess:puzzles"

    def import_exercises(self, source: str | Path) -> list[Exercise]:
        # Use your existing API client
        ...


class PGNImporter(ContentImporter):
    """Import from PGN files (openings, annotated games)."""

    def can_import(self, source: str | Path) -> bool:
        return Path(source).suffix.lower() == ".pgn"

    def import_exercises(self, source: str | Path) -> list[Exercise]:
        # Parse PGN, extract positions with annotations
        # Annotations like "!" or "only move" become tactical exercises
        # Opening lines become opening exercises
        ...


class YAMLEndgameImporter(ContentImporter):
    """Import from your structured YAML format."""

    def can_import(self, source: str | Path) -> bool:
        return Path(source).suffix.lower() in (".yaml", ".yml")


class ChessTempoImporter(ContentImporter):
    """Import from ChessTempo CSV exports."""
    ...


class ImportManager:
    """Registry of importers."""

    def __init__(self):
        self.importers: list[ContentImporter] = [
            LichessPuzzleImporter(),
            PGNImporter(),
            YAMLEndgameImporter(),
        ]

    def import_from(self, source: str | Path) -> list[Exercise]:
        for importer in self.importers:
            if importer.can_import(source):
                return importer.import_exercises(source)
        raise ValueError(f"No importer found for {source}")
```

### 5. Storage Layer

Given your requirements.txt exploration of embedded databases, I recommend **DuckDB** for its SQL interface and excellent Python integration:

```python
import duckdb
from pathlib import Path

class ExerciseStorage:
    """Persistent storage for exercises and review cards."""

    def __init__(self, db_path: Path = Path("data/chess_trainer.duckdb")):
        self.conn = duckdb.connect(str(db_path))
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS exercises (
                id VARCHAR PRIMARY KEY,
                type VARCHAR NOT NULL,
                position_fen VARCHAR NOT NULL,
                data JSON NOT NULL,  -- Type-specific fields
                tags VARCHAR[],
                source VARCHAR,
                difficulty FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS review_cards (
                exercise_id VARCHAR PRIMARY KEY REFERENCES exercises(id),
                stability FLOAT NOT NULL DEFAULT 1.0,
                difficulty FLOAT NOT NULL DEFAULT 0.3,
                last_review TIMESTAMP,
                next_review TIMESTAMP,
                reps INTEGER DEFAULT 0,
                lapses INTEGER DEFAULT 0
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS review_history (
                id INTEGER PRIMARY KEY,
                exercise_id VARCHAR REFERENCES exercises(id),
                reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                grade INTEGER NOT NULL,
                time_taken_ms INTEGER,
                moves_played JSON
            )
        """)
```

### 6. Training UI

For the UI, I see three options:

**Option A: Terminal UI (Textual)**
- Pros: Fast to develop, works over SSH, keyboard-driven
- Cons: Less visual appeal, harder to show board positions
- Good for: Rapid prototyping, CLI-first workflow

**Option B: Web UI (FastAPI + HTMX + chess.js)**
- Pros: Rich interactivity, easy board rendering, cross-platform
- Cons: More infrastructure, browser dependency
- Good for: Full-featured app, shareable

**Option C: Desktop UI (pygame, which you've started)**
- Pros: Native feel, no browser needed
- Cons: More boilerplate, harder to style
- Good for: Focused single-purpose app

Given your existing pygame code and the "reduce context-switching" goal, I'd suggest **Option B** — a local web app is the best balance of development speed and UX quality. You can use `chess.js` for board rendering and HTMX for reactivity without a heavy JS framework.

---

## Code Quality Notes

### Current Strengths

1. **Clean data models** — `dataclasses_json` with proper serialization config
2. **Good API client structure** — Separation of concerns, proper error handling
3. **Logging** — Consistent `get_logger` pattern throughout

### Issues to Address

**1. Global mutable state in `chess_browser.py`:**
```python
turn_step = 0
selection = 100
valid_moves = []
```
These should be encapsulated in a `GameState` class.

**2. Root logger modification:**
```python
# src/__init__.py
logging.getLogger().setLevel("DEBUG")
```
This affects all libraries. Configure only your package's logger.

**3. Incomplete Yellow constraint (from Wordle review, but same pattern):**
The `get_valid_theme` function returns `Theme` objects but compares `name.lower()` against `theme.lower()`:
```python
return next(
    name  # This is a Theme object, not a string
    for name in get_puzzle_themes()
    if name.lower() == theme.lower().strip()  # AttributeError if Theme
)
```
Should be `theme_obj.name.lower()`.

**4. Hardcoded path:**
```python
DICTIONARY = Path("/home/hactar/.local/share/dict/wordle")
```
Wait, that's in the Wordle project. But similar pattern here:
```python
DATA = Path(__file__).parent.joinpath("data/puzzle_history.10000.json")
```
This is fine for now but should eventually be configurable.

---

## Feature Roadmap

### Phase 1: Core Infrastructure (Foundation)
- [ ] Define `Exercise` base class and type-specific subclasses
- [ ] Implement `ReviewCard` and `ReviewScheduler` with FSRS
- [ ] Set up DuckDB storage layer
- [ ] Create `LichessPuzzleImporter` (refactor existing code)

### Phase 2: Tactics Training (MVP)
- [ ] Import Lichess puzzles into storage
- [ ] Build minimal training loop (terminal-based is fine)
- [ ] Integrate spaced repetition scheduling
- [ ] Track and display progress statistics

### Phase 3: Content Expansion
- [ ] `PGNImporter` for opening lines
- [ ] `YAMLEndgameImporter` for your structured endgame notes
- [ ] Basic opening training mode
- [ ] Basic endgame training mode

### Phase 4: Rich UI
- [ ] Web UI with FastAPI + HTMX + chess.js
- [ ] Interactive board with move input
- [ ] Progress dashboard
- [ ] Training session configuration

### Phase 5: Advanced Features
- [ ] Position classification ("is this tactical, positional, or endgame?")
- [ ] Adaptive difficulty based on performance
- [ ] Woodpecker-style rapid review mode
- [ ] Export/import for Anki interoperability

---

## Key Design Decisions Needed

1. **How to handle alternative correct moves?**
   - Tactics: Lichess provides one solution, but there may be transpositions
   - Openings: Multiple playable moves exist
   - Suggestion: Allow "primary" and "acceptable" move lists

2. **How to represent positional exercises?**
   - Unlike tactics, there's often no single "correct" move
   - Suggestion: Store acceptable plans/moves + explanations, grade on partial matches

3. **How to seed difficulty for new exercises?**
   - Lichess puzzles have ratings
   - Other content doesn't
   - Suggestion: Use exercise type + material/position features as initial estimate, refine with user performance

4. **Single-user or multi-user?**
   - Affects storage design, auth needs
   - Suggestion: Start single-user, design storage to allow multi-user later

---

## Quick Wins

1. **Rename `chess_browser.py` to `ui/pygame_board.py`** and refactor state into a class
2. **Add `__all__` exports** to `src/__init__.py` and `src/lichess/__init__.py`
3. **Create `src/exercises/` package** with the domain model
4. **Move `viz.py` to `src/analytics/`** and make it import from the storage layer
5. **Add a simple CLI** using `click` or `typer` for training sessions

---

## References

- [FSRS Algorithm Paper](https://github.com/open-spaced-repetition/fsrs4anki/wiki)
- [chess.js](https://github.com/jhlywa/chess.js) — JavaScript chess library for web UI
- [python-chess](https://python-chess.readthedocs.io/) — Already in your deps, excellent
- [Lichess API Docs](https://lichess.org/api)
- [Chessboard.js](https://chessboardjs.com/) — Board rendering for web UI

---

*This document should be updated as design decisions are made and implementation progresses.*
