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


class TestAcceptableFirstMoves:
    """Tests for acceptable first moves and game context in web training flow."""

    # Open position: Black queen on d4, kings on e8/e1.
    # Solution: Qd1+ Kf2 Qd2+ (3 moves, 2 user moves).
    OWN_GAME_FEN = "4k3/8/8/8/3q4/8/8/4K3 b - - 0 1"

    @pytest.fixture
    def own_game_client(self, tmp_path):
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")
        config.own_game_eval.show_game_context = True
        app = create_app(config)
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="game:chesscom:123:m8",
                fen=self.OWN_GAME_FEN,
                tags=["own_game", "tactic"],
                source="chesscom",
                difficulty=1200.0,
                solution=["d4d1", "e1f2", "d1d2"],
                themes=["own_game"],
                acceptable_first_moves=["d4e3"],
                best_move_eval=50,
                evaluate_depth=1,
                metadata={
                    "game_context": {
                        "game_date": "2026-02-09",
                        "opponent": "magnus42",
                        "time_control": "blitz",
                        "player_color": "black",
                    }
                },
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)
        return TestClient(app)

    def test_acceptable_first_move_accepted(self, own_game_client):
        """An acceptable (near-optimal) first move should be treated as correct."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        # d4e3 is in acceptable_first_moves, not the exact solution (d4d1)
        res = own_game_client.post("/api/session/move", json={"move": "d4e3"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is True
        # With evaluate_depth=1, this is also finished after the first move
        assert data["finished"] is True

    def test_exact_solution_still_works(self, own_game_client):
        """The exact solution move should still be accepted."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        res = own_game_client.post("/api/session/move", json={"move": "d4d1"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is True
        assert data["finished"] is True

    def test_unacceptable_move_rejected(self, own_game_client):
        """A move not in solution or acceptable list should be incorrect."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        # d4a4 is legal but not in solution or acceptable list
        res = own_game_client.post("/api/session/move", json={"move": "d4a4"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is False
        assert data["finished"] is True

    def test_game_context_in_next_response(self, own_game_client):
        """Game context should appear in /api/session/next when config enables it."""
        own_game_client.post("/api/session/start", json={})
        res = own_game_client.get("/api/session/next")
        data = res.json()

        assert "game_context" in data
        ctx = data["game_context"]
        assert ctx["opponent"] == "magnus42"
        assert ctx["time_control"] == "blitz"
        assert ctx["player_color"] == "black"
        assert ctx["game_date"] == "2026-02-09"

    def test_game_context_hidden_when_config_disabled(self, tmp_path):
        """Game context should not appear when show_game_context is False."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")
        config.own_game_eval.show_game_context = False
        app = create_app(config)
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="game:test:1:m1",
                fen=self.OWN_GAME_FEN,
                tags=["own_game"],
                source="test",
                difficulty=1200.0,
                solution=["d4d1"],
                themes=[],
                metadata={"game_context": {"opponent": "someone"}},
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)
        client = TestClient(app)
        client.post("/api/session/start", json={})
        res = client.get("/api/session/next")
        data = res.json()
        assert "game_context" not in data

    def test_evaluate_depth_limits_required_moves(self, own_game_client):
        """With evaluate_depth=1, only the first user move matters."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        # The solution has 3 moves (2 user moves), but evaluate_depth=1
        # means only the first user move is checked
        res = own_game_client.post("/api/session/move", json={"move": "d4d1"})
        data = res.json()
        assert data["finished"] is True  # Done after 1 user move

    def test_no_game_context_when_absent(self, seeded_client):
        """Regular exercises without game_context should not include it."""
        seeded_client.post("/api/session/start", json={})
        res = seeded_client.get("/api/session/next")
        data = res.json()
        assert "game_context" not in data


class TestGameContextUI:
    def test_train_template_has_game_context_div(self, client):
        """The training template should include a game-context div."""
        res = client.get("/train")
        assert 'id="game-context"' in res.text

    def test_training_js_has_format_game_context(self, client):
        """training.js should include the formatGameContext helper."""
        res = client.get("/static/js/training.js")
        assert "formatGameContext" in res.text
        assert "game_context" in res.text


class TestShowMyMove:
    """Tests for E20: 'Show my move' hint for own-game exercises."""

    OWN_GAME_FEN = "4k3/8/8/8/3q4/8/8/4K3 b - - 0 1"

    @pytest.fixture
    def own_game_client(self, tmp_path):
        """Client with an own-game exercise that has played_move_uci."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")
        app = create_app(config)
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="game:test:1:m5",
                fen=self.OWN_GAME_FEN,
                tags=["own_game"],
                source="game_analysis",
                difficulty=1200.0,
                solution=["d4d1"],
                themes=["own_game"],
                evaluate_depth=1,
                metadata={
                    "played_move_uci": "d4a4",
                    "game_context": {
                        "opponent": "testuser",
                        "player_color": "black",
                    },
                },
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)
        return TestClient(app)

    def test_my_move_returns_played_move(self, own_game_client):
        """GET /api/session/my-move returns the played move data."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        res = own_game_client.get("/api/session/my-move")
        assert res.status_code == 200
        data = res.json()
        assert data["played_move_uci"] == "d4a4"
        assert data["from"] == "d4"
        assert data["to"] == "a4"
        assert "played_move_san" in data

    def test_my_move_404_for_regular_exercise(self, seeded_client):
        """Regular exercises without played_move_uci return 404."""
        seeded_client.post("/api/session/start", json={})
        seeded_client.get("/api/session/next")

        res = seeded_client.get("/api/session/my-move")
        assert res.status_code == 404

    def test_my_move_404_without_session(self, client):
        """No active exercise returns 404."""
        res = client.get("/api/session/my-move")
        assert res.status_code == 404

    def test_has_played_move_flag_in_next(self, own_game_client):
        """The next exercise response includes has_played_move for own-game."""
        own_game_client.post("/api/session/start", json={})
        res = own_game_client.get("/api/session/next")
        data = res.json()
        assert data["has_played_move"] is True

    def test_no_has_played_move_for_regular(self, seeded_client):
        """Regular exercises don't include has_played_move flag."""
        seeded_client.post("/api/session/start", json={})
        res = seeded_client.get("/api/session/next")
        data = res.json()
        assert "has_played_move" not in data

    def test_scoring_penalty_after_hint(self, own_game_client):
        """Using the hint and then solving correctly demotes correct → partial."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        # Use the hint
        res = own_game_client.get("/api/session/my-move")
        assert res.status_code == 200

        # Solve correctly
        res = own_game_client.post("/api/session/move", json={"move": "d4d1"})
        data = res.json()
        assert data["correct"] is True

        # End session — check stats reflect the penalty
        res = own_game_client.post("/api/session/end")
        data = res.json()
        stats = data["stats"]
        # Correct answer with hint should count as partial, not correct
        assert stats["correct"] == 0
        assert stats["partial"] == 1

    def test_no_penalty_without_hint(self, own_game_client):
        """Solving without using the hint keeps full correct count."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        # Solve correctly without using hint
        res = own_game_client.post("/api/session/move", json={"move": "d4d1"})
        data = res.json()
        assert data["correct"] is True

        # End session — correct should be counted normally
        res = own_game_client.post("/api/session/end")
        data = res.json()
        stats = data["stats"]
        assert stats["correct"] == 1
        assert stats["partial"] == 0

    def test_no_penalty_on_wrong_answer(self, own_game_client):
        """Hint penalty doesn't apply to incorrect answers."""
        own_game_client.post("/api/session/start", json={})
        own_game_client.get("/api/session/next")

        # Use the hint
        own_game_client.get("/api/session/my-move")

        # Submit wrong move
        res = own_game_client.post("/api/session/move", json={"move": "d4b4"})
        data = res.json()
        assert data["correct"] is False

        res = own_game_client.post("/api/session/end")
        stats = res.json()["stats"]
        assert stats["incorrect"] == 1
        assert stats["partial"] == 0


class TestShowMyMoveUI:
    """Structural UI tests for E20 elements."""

    def test_train_template_has_my_move_button(self, client):
        """Training page includes the 'What did I play?' button."""
        res = client.get("/train")
        assert 'id="my-move-btn"' in res.text
        assert "What did I play?" in res.text

    def test_training_js_has_show_my_move(self, client):
        """training.js includes the showMyMove function."""
        res = client.get("/static/js/training.js")
        assert "showMyMove" in res.text
        assert "hasPlayedMove" in res.text
        assert "/api/session/my-move" in res.text

    def test_css_has_hint_styles(self, client):
        """CSS includes hint button and highlight styles."""
        res = client.get("/static/css/style.css")
        assert ".btn-hint" in res.text
        assert ".highlight-played-move" in res.text
        assert ".feedback-hint" in res.text


class TestNotesUI:
    """Tests for notes UI elements in template, JS, and CSS."""

    def test_train_page_has_test_mode_checkbox(self, client):
        res = client.get("/train")
        assert 'id="test-mode"' in res.text
        assert "Test mode" in res.text

    def test_train_page_has_notes_panel(self, client):
        res = client.get("/train")
        assert 'id="notes-panel"' in res.text
        assert 'id="notes-content"' in res.text
        assert 'id="reveal-notes-btn"' in res.text
        assert 'id="notes-textarea"' in res.text

    def test_training_js_has_notes_functions(self, client):
        res = client.get("/static/js/training.js")
        text = res.text
        assert "loadNotes" in text
        assert "revealNotes" in text
        assert "toggleNotes" in text
        assert "saveNotes" in text
        assert "hideNotes" in text
        assert "currentTrainingMode" in text
        assert "currentExerciseId" in text

    def test_css_has_notes_styles(self, client):
        res = client.get("/static/css/style.css")
        text = res.text
        assert ".notes-panel" in text
        assert ".notes-content" in text
        assert ".notes-header" in text
        assert ".notes-toggle" in text
        assert ".notes-editor" in text
        assert ".notes-textarea" in text
        assert ".btn-small" in text


class TestNotesAPI:
    """Tests for notes API endpoints."""

    @pytest.fixture
    def noted_client(self, app, tmp_path):
        """Client with a seeded exercise that has notes."""
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="test:noted",
                fen=SAMPLE_FEN,
                tags=["fork"],
                source="test",
                solution=["g7g6"],
                themes=["fork"],
                metadata={"notes": "Key tactic: defend against Qxf7#"},
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)
        return TestClient(app)

    def test_session_start_returns_training_mode(self, seeded_client):
        res = seeded_client.post("/api/session/start", json={})
        data = res.json()
        assert data["training_mode"] == "study"

    def test_session_start_with_test_mode(self, seeded_client):
        res = seeded_client.post("/api/session/start", json={"training_mode": "test"})
        data = res.json()
        assert data["training_mode"] == "test"

    def test_next_includes_notes_and_id(self, noted_client):
        noted_client.post("/api/session/start", json={})
        res = noted_client.get("/api/session/next")
        data = res.json()
        assert data["exercise_id"] == "test:noted"
        assert data["has_notes"] is True
        assert data["training_mode"] == "study"

    def test_get_notes_study_mode(self, noted_client):
        noted_client.post("/api/session/start", json={})
        noted_client.get("/api/session/next")
        res = noted_client.get("/api/session/notes")
        data = res.json()
        assert data["has_notes"] is True
        assert data["notes"] == "Key tactic: defend against Qxf7#"

    def test_get_notes_test_mode_hidden(self, noted_client):
        noted_client.post("/api/session/start", json={"training_mode": "test"})
        noted_client.get("/api/session/next")
        res = noted_client.get("/api/session/notes")
        data = res.json()
        assert data["has_notes"] is True
        assert "notes" not in data

    def test_reveal_notes_test_mode(self, noted_client):
        noted_client.post("/api/session/start", json={"training_mode": "test"})
        noted_client.get("/api/session/next")
        res = noted_client.post("/api/session/reveal-notes")
        data = res.json()
        assert data["notes"] == "Key tactic: defend against Qxf7#"

    def test_save_notes(self, seeded_client):
        res = seeded_client.put(
            "/api/exercise/test:001/notes",
            json={"notes": "My new annotation"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "saved"

        # Verify via read endpoint
        res = seeded_client.get("/api/exercise/test:001/notes")
        assert res.json()["notes"] == "My new annotation"

    def test_save_notes_too_long(self, seeded_client):
        res = seeded_client.put(
            "/api/exercise/test:001/notes",
            json={"notes": "x" * 5001},
        )
        assert res.status_code == 400

    def test_save_notes_not_found(self, client):
        res = client.put(
            "/api/exercise/nonexistent/notes",
            json={"notes": "hello"},
        )
        assert res.status_code == 404

    def test_get_notes_not_found(self, client):
        res = client.get("/api/exercise/nonexistent/notes")
        assert res.status_code == 404

    def test_save_empty_notes_clears(self, seeded_client):
        seeded_client.put(
            "/api/exercise/test:001/notes",
            json={"notes": "temp note"},
        )
        seeded_client.put(
            "/api/exercise/test:001/notes",
            json={"notes": ""},
        )
        res = seeded_client.get("/api/exercise/test:001/notes")
        assert res.json()["notes"] is None


class TestSessionManagerNotes:
    """Tests for notes and training mode in SessionManager."""

    def test_training_mode_defaults_to_study(self, app):
        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config)
        assert mgr.training_mode == "study"

    def test_training_mode_set_on_start(self, app, tmp_path):
        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config, db_path=tmp_path / "test.db")
        mgr.start_session(training_mode="test")
        assert mgr.training_mode == "test"
        mgr.end_session()

    def test_get_notes_no_exercise(self, app):
        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config)
        result = mgr.get_exercise_notes()
        assert result["has_notes"] is False

    def test_get_notes_study_mode(self, seeded_client, app, tmp_path):
        """In study mode, notes text is returned directly."""
        # Seed exercise with notes
        with Repository(tmp_path / "test.db") as repo:
            repo.exercises.update_notes("test:001", "study note")

        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config, db_path=tmp_path / "test.db")
        mgr.start_session(training_mode="study")
        mgr.next_exercise()
        result = mgr.get_exercise_notes()
        assert result["has_notes"] is True
        assert result["notes"] == "study note"
        mgr.end_session()

    def test_get_notes_test_mode_hidden(self, app, tmp_path):
        """In test mode, notes are hidden (has_notes only)."""
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="test:n1",
                fen=SAMPLE_FEN,
                tags=[],
                source="test",
                solution=["g7g6"],
                themes=[],
                metadata={"notes": "hidden note"},
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)

        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config, db_path=tmp_path / "test.db")
        mgr.start_session(training_mode="test")
        mgr.next_exercise()
        result = mgr.get_exercise_notes()
        assert result["has_notes"] is True
        assert "notes" not in result
        mgr.end_session()

    def test_reveal_notes_sets_hint_flag(self, app, tmp_path):
        """Revealing notes in test mode marks the hint as used."""
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="test:r1",
                fen=SAMPLE_FEN,
                tags=[],
                source="test",
                solution=["g7g6"],
                themes=[],
                metadata={"notes": "revealed note"},
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)

        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config, db_path=tmp_path / "test.db")
        mgr.start_session(training_mode="test")
        mgr.next_exercise()
        result = mgr.reveal_notes()
        assert result["notes"] == "revealed note"
        assert mgr.exercise_state.used_notes_hint is True
        mgr.end_session()

    def test_save_notes_persists(self, app, tmp_path):
        """save_exercise_notes persists to DB and updates in-memory state."""
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="test:s1",
                fen=SAMPLE_FEN,
                tags=[],
                source="test",
                solution=["g7g6"],
                themes=[],
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)

        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config, db_path=tmp_path / "test.db")
        mgr.start_session()
        mgr.next_exercise()
        assert mgr.save_exercise_notes("test:s1", "New annotation") is True
        assert mgr.exercise_state.exercise.notes == "New annotation"
        mgr.end_session()

        # Verify persistence
        with Repository(tmp_path / "test.db") as repo:
            loaded = repo.exercises.get("test:s1")
            assert loaded.notes == "New annotation"

    def test_notes_penalty_correct_move(self, app, tmp_path):
        """Notes hint demotes correct → partial in stats."""
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="test:p1",
                fen=SAMPLE_FEN,
                tags=[],
                source="test",
                solution=["g7g6"],
                themes=[],
                metadata={"notes": "penalty note"},
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)

        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config, db_path=tmp_path / "test.db")
        mgr.start_session(training_mode="test")
        mgr.next_exercise()
        mgr.reveal_notes()  # Mark hint as used
        result = mgr.submit_move("g7g6")
        assert result["correct"] is True
        # Stats should show partial, not correct
        assert mgr.stats.partial == 1
        assert mgr.stats.correct == 0
        mgr.end_session()

    def test_no_double_penalty(self, app, tmp_path):
        """Using both notes hint and my-move hint applies only one demotion."""
        with Repository(tmp_path / "test.db") as repo:
            tactic = TacticExercise(
                id="test:dp1",
                fen=SAMPLE_FEN,
                tags=[],
                source="test",
                solution=["g7g6"],
                themes=[],
                metadata={"notes": "note", "played_move_uci": "g8f6"},
            )
            repo.exercises.add(tactic)
            repo.cards.get_or_create(tactic.id)

        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config, db_path=tmp_path / "test.db")
        mgr.start_session(training_mode="test")
        mgr.next_exercise()
        mgr.reveal_notes()
        mgr.get_played_move()
        assert mgr.exercise_state.used_notes_hint is True
        assert mgr.exercise_state.used_my_move_hint is True
        result = mgr.submit_move("g7g6")
        assert result["correct"] is True
        # Only one demotion: partial=1, correct=0
        assert mgr.stats.partial == 1
        assert mgr.stats.correct == 0
        mgr.end_session()

    def test_reveal_notes_no_exercise(self, app):
        from src.web.session_manager import SessionManager

        mgr = SessionManager(app.state.config)
        result = mgr.reveal_notes()
        assert result["notes"] is None


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
