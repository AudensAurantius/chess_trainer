"""Shared fixtures for the chess trainer test suite."""

from datetime import datetime

import pytest

from src.exercises import TacticExercise
from src.scheduling import CardState, ReviewCard
from src.storage import Repository

# --- Puzzle data: a well-known tactic (Scholar's Mate defense) ---
# Position after 1. e4 e5 2. Bc4 Nc6 3. Qh5 (threatening Qxf7#)
# Black's best is 3... g6 to block the queen
SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
SAMPLE_SOLUTION = ["g7g6"]  # After setup move already played


@pytest.fixture
def repo():
    """Fresh in-memory Repository for each test."""
    with Repository() as r:
        yield r


@pytest.fixture
def sample_tactic():
    """A known TacticExercise with predictable evaluation."""
    return TacticExercise(
        id="test:001",
        fen=SAMPLE_FEN,
        tags=["fork", "tactic"],
        source="test",
        source_url=None,
        difficulty=1500.0,
        created_at=datetime(2025, 1, 1),
        solution=SAMPLE_SOLUTION,
        themes=["fork"],
        game_id=None,
    )


@pytest.fixture
def sample_card():
    """A NEW review card linked to sample_tactic."""
    return ReviewCard(
        exercise_id="test:001",
        state=CardState.NEW,
        due=datetime(2025, 1, 1),
        created_at=datetime(2025, 1, 1),
    )


@pytest.fixture
def populated_repo(repo, sample_tactic):
    """Repository pre-loaded with a tactic exercise and its review card."""
    repo.exercises.add(sample_tactic)
    repo.cards.get_or_create(sample_tactic.id)
    return repo
