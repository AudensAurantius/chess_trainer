"""Tests for the web interface."""

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
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded_client(app, tmp_path):
    with Repository(tmp_path / "test.db") as repo:
        tactic = TacticExercise(
            id="test:001",
            fen=SAMPLE_FEN,
            tags=["fork", "tactic"],
            source="test",
            difficulty=1500.0,
            solution=["g7g6"],
            themes=["fork"],
        )
        repo.exercises.add(tactic)
        repo.cards.get_or_create(tactic.id)
    return TestClient(app)


class TestPages:
    def test_dashboard(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "Chess Trainer" in res.text

    def test_train_page(self, client):
        res = client.get("/train")
        assert res.status_code == 200
        assert "Training Session" in res.text

    def test_stats_page(self, client):
        res = client.get("/stats")
        assert res.status_code == 200
        assert "Statistics" in res.text

    def test_static_css(self, client):
        res = client.get("/static/css/style.css")
        assert res.status_code == 200

    def test_static_js(self, client):
        res = client.get("/static/js/training.js")
        assert res.status_code == 200

    def test_train_page_has_start_feedback_element(self, client):
        """The start panel must contain a feedback div visible before session starts.

        Regression test: previously, the empty-queue feedback message was
        written to #feedback-area inside the hidden #session-panel, so users
        saw nothing when clicking Start Training with no exercises.
        """
        res = client.get("/train")
        assert 'id="start-feedback"' in res.text

    def test_training_js_has_start_feedback_handler(self, client):
        """training.js must use showStartFeedback for pre-session messages."""
        res = client.get("/static/js/training.js")
        assert "showStartFeedback" in res.text

    def test_favicon_no_404(self, client):
        """base.html should suppress the default favicon request."""
        res = client.get("/train")
        assert 'rel="icon"' in res.text

    def test_css_has_auth_styles(self, client):
        """CSS must include auth page styles."""
        res = client.get("/static/css/style.css")
        assert ".auth-container" in res.text
        assert ".auth-form" in res.text
        assert ".form-group" in res.text
        assert ".auth-error" in res.text
        assert ".auth-link" in res.text

    def test_css_has_nav_and_bundle_styles(self, client):
        """CSS must include nav user/logout and bundle grid styles."""
        res = client.get("/static/css/style.css")
        assert ".nav-user" in res.text
        assert ".nav-logout" in res.text
        assert ".bundles-grid" in res.text
        assert ".bundle-card" in res.text

    def test_bundles_page(self, client):
        res = client.get("/bundles")
        assert res.status_code == 200
        assert "Exercise Bundles" in res.text

    def test_bundles_empty_state_no_cli_reference(self, client):
        """Bundles empty state should not reference CLI."""
        res = client.get("/bundles")
        assert "chess-trainer" not in res.text
        assert "No bundles yet" in res.text

    def test_dashboard_empty_state_has_import_link(self, client):
        """Dashboard with no exercises shows import CTA."""
        res = client.get("/")
        assert 'href="/import"' in res.text
        assert "Import Exercises" in res.text

    def test_dashboard_with_exercises_has_start_training(self, seeded_client):
        """Dashboard with exercises shows Start Training."""
        res = seeded_client.get("/")
        assert "Start Training" in res.text

    def test_training_js_has_import_link(self, client):
        """training.js empty-queue message links to /import."""
        res = client.get("/static/js/training.js")
        assert "/import" in res.text


class TestSessionAPI:
    def test_start_empty(self, client):
        res = client.post("/api/session/start", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "started"
        assert data["queue_size"] == 0

    def test_start_with_exercises(self, seeded_client):
        res = seeded_client.post("/api/session/start", json={})
        data = res.json()
        assert data["queue_size"] == 1

    def test_next_without_session(self, client):
        res = client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "complete"

    def test_full_session_flow(self, seeded_client):
        # Start
        res = seeded_client.post("/api/session/start", json={})
        assert res.json()["queue_size"] == 1

        # Next exercise
        res = seeded_client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "ok"
        assert data["fen"] == SAMPLE_FEN
        assert data["side_to_move"] == "Black"

        # Submit correct move
        res = seeded_client.post("/api/session/move", json={"move": "g7g6"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is True
        assert data["finished"] is True

        # Get solution
        res = seeded_client.get("/api/session/solution")
        data = res.json()
        assert "g6" in data["solution_san"]

        # Rate
        res = seeded_client.post("/api/session/rate", json={"rating": 3})
        data = res.json()
        assert "next_review" in data

        # Next should complete
        res = seeded_client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "complete"

    def test_wrong_move(self, seeded_client):
        seeded_client.post("/api/session/start", json={})
        seeded_client.get("/api/session/next")

        # g8f6 is legal but not the solution (g7g6)
        res = seeded_client.post("/api/session/move", json={"move": "g8f6"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is False
        assert data["finished"] is True

    def test_invalid_move_format(self, seeded_client):
        seeded_client.post("/api/session/start", json={})
        seeded_client.get("/api/session/next")

        res = seeded_client.post("/api/session/move", json={"move": "xyz"})
        data = res.json()
        assert data["valid"] is False

    def test_rate_invalid(self, client):
        res = client.post("/api/session/rate", json={"rating": 5})
        assert res.status_code == 400

    def test_end_session(self, seeded_client):
        seeded_client.post("/api/session/start", json={})
        res = seeded_client.post("/api/session/end")
        data = res.json()
        assert data["status"] == "ended"


class TestStatsAPI:
    def test_get_stats(self, client):
        res = client.get("/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert "exercise_count" in data

    def test_stats_page_has_analytics_containers(self, client):
        """Stats page should include analytics section divs."""
        res = client.get("/stats")
        assert 'id="analytics-streaks"' in res.text
        assert 'id="analytics-weak-areas"' in res.text

    def test_streaks_api_returns_200(self, client):
        res = client.get("/api/analytics/streaks")
        assert res.status_code == 200
        data = res.json()
        assert "current_streak" in data
        assert "longest_streak" in data
        assert "total_active_days" in data

    def test_weak_areas_api_returns_200(self, client):
        res = client.get("/api/analytics/weak-areas")
        assert res.status_code == 200
        data = res.json()
        assert "areas" in data


class TestErrorHandlers:
    def test_404_html_page(self, client):
        res = client.get("/nonexistent-page")
        assert res.status_code == 404
        assert "not found" in res.text.lower()
        assert "dashboard" in res.text.lower()

    def test_404_api_json(self, client):
        res = client.get("/api/nonexistent")
        assert res.status_code == 404
        data = res.json()
        assert "error" in data
