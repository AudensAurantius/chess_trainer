"""Integration tests for E21: Exercise Annotations with Study/Test Modes."""

import pytest
from fastapi.testclient import TestClient

from src.config import AppConfig
from src.exercises import TacticExercise
from src.storage import Repository
from src.web import create_app

SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


@pytest.fixture
def app(tmp_path):
    config = AppConfig()
    config.database.path = str(tmp_path / "test.db")
    return create_app(config)


@pytest.fixture
def noted_client(app, tmp_path):
    """Client with a seeded exercise that has notes."""
    with Repository(tmp_path / "test.db") as repo:
        tactic = TacticExercise(
            id="test:e21",
            fen=SAMPLE_FEN,
            tags=["fork"],
            source="test",
            solution=["g7g6"],
            themes=["fork"],
            metadata={"notes": "Look for queen escape squares"},
        )
        repo.exercises.add(tactic)
        repo.cards.get_or_create(tactic.id)
    return TestClient(app)


@pytest.fixture
def bare_client(app, tmp_path):
    """Client with a seeded exercise without notes."""
    with Repository(tmp_path / "test.db") as repo:
        tactic = TacticExercise(
            id="test:bare",
            fen=SAMPLE_FEN,
            tags=[],
            source="test",
            solution=["g7g6"],
            themes=[],
        )
        repo.exercises.add(tactic)
        repo.cards.get_or_create(tactic.id)
    return TestClient(app)


class TestStudyModeFlow:
    """Full web flow in study mode: notes visible, no penalty."""

    def test_study_mode_notes_visible_no_penalty(self, noted_client):
        # Start session in study mode (default)
        res = noted_client.post("/api/session/start", json={})
        assert res.json()["training_mode"] == "study"

        # Load exercise
        res = noted_client.get("/api/session/next")
        data = res.json()
        assert data["has_notes"] is True
        assert data["training_mode"] == "study"

        # Get notes — should include text in study mode
        res = noted_client.get("/api/session/notes")
        data = res.json()
        assert data["has_notes"] is True
        assert data["notes"] == "Look for queen escape squares"

        # Solve correctly
        res = noted_client.post("/api/session/move", json={"move": "g7g6"})
        assert res.json()["correct"] is True

        # End session — no penalty applied
        res = noted_client.post("/api/session/end")
        stats = res.json()["stats"]
        assert stats["correct"] == 1
        assert stats["partial"] == 0


class TestTestModeFlow:
    """Full web flow in test mode: hidden, reveal + penalty."""

    def test_test_mode_reveal_penalty(self, noted_client):
        # Start session in test mode
        res = noted_client.post("/api/session/start", json={"training_mode": "test"})
        assert res.json()["training_mode"] == "test"

        # Load exercise
        res = noted_client.get("/api/session/next")
        data = res.json()
        assert data["has_notes"] is True
        assert data["training_mode"] == "test"

        # Get notes — should NOT include text in test mode
        res = noted_client.get("/api/session/notes")
        data = res.json()
        assert data["has_notes"] is True
        assert "notes" not in data

        # Reveal notes (penalty trigger)
        res = noted_client.post("/api/session/reveal-notes")
        data = res.json()
        assert data["notes"] == "Look for queen escape squares"

        # Solve correctly
        res = noted_client.post("/api/session/move", json={"move": "g7g6"})
        assert res.json()["correct"] is True

        # End session — penalty demotes correct → partial
        res = noted_client.post("/api/session/end")
        stats = res.json()["stats"]
        assert stats["correct"] == 0
        assert stats["partial"] == 1


class TestNotesPersistence:
    """Notes persist across sessions."""

    def test_notes_saved_and_retrieved_across_sessions(self, bare_client):
        # Save notes
        res = bare_client.put(
            "/api/exercise/test:bare/notes",
            json={"notes": "Key pattern: back rank mate"},
        )
        assert res.status_code == 200

        # Read notes outside session
        res = bare_client.get("/api/exercise/test:bare/notes")
        assert res.json()["notes"] == "Key pattern: back rank mate"

        # Start new session and verify notes appear
        bare_client.post("/api/session/start", json={})
        res = bare_client.get("/api/session/next")
        assert res.json()["has_notes"] is True

        # Notes visible in study mode
        res = bare_client.get("/api/session/notes")
        assert res.json()["notes"] == "Key pattern: back rank mate"

        bare_client.post("/api/session/end")


class TestEdgeCases:
    """Edge cases: no notes, empty string, max length."""

    def test_no_notes_exercise(self, bare_client):
        bare_client.post("/api/session/start", json={})
        res = bare_client.get("/api/session/next")
        assert res.json()["has_notes"] is False
        bare_client.post("/api/session/end")

    def test_empty_string_removal(self, bare_client):
        # Save then clear with empty string
        bare_client.put("/api/exercise/test:bare/notes", json={"notes": "temp"})
        bare_client.put("/api/exercise/test:bare/notes", json={"notes": ""})
        res = bare_client.get("/api/exercise/test:bare/notes")
        assert res.json()["notes"] is None

    def test_max_length_enforcement(self, bare_client):
        # 5000 chars should be OK
        res = bare_client.put("/api/exercise/test:bare/notes", json={"notes": "a" * 5000})
        assert res.status_code == 200

        # 5001 chars should fail
        res = bare_client.put("/api/exercise/test:bare/notes", json={"notes": "a" * 5001})
        assert res.status_code == 400

    def test_reveal_no_session(self, bare_client):
        """Reveal notes without active session returns None."""
        res = bare_client.post("/api/session/reveal-notes")
        assert res.json()["notes"] is None
