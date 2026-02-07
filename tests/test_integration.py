"""Integration tests demonstrating compatibility between all 6 features.

Each test exercises multiple subsystems end-to-end:
  - Exercises (domain model, evaluation)
  - Scheduling (FSRS-4.5 algorithm)
  - Storage (DuckDB persistence)
  - Config (TOML configuration)
  - Training (session coordinator)
  - Web (FastAPI interface)
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.config import AppConfig, load_config
from src.exercises import TacticExercise
from src.importers.lichess_puzzles import LichessPuzzleImporter
from src.scheduling import CardState, FSRSScheduler
from src.scheduling.fsrs import Rating
from src.storage import Repository
from src.training import SessionConfig, TrainingSession
from src.web import create_app

# --- Fixtures ---


MATE_IN_ONE_FEN = "6k1/5ppp/8/8/8/8/4RPPP/6K1 w - - 0 1"
MATE_IN_ONE_SOLUTION = ["e2e8"]  # Re8#

FORK_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
FORK_SOLUTION = ["g7g6"]

MULTI_MOVE_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
MULTI_MOVE_SOLUTION = ["h5f7", "e8d8", "f7f6"]  # Qxf7+ Kd8 Qxf6


def _make_tactic(id_, fen, solution, difficulty=1500.0, themes=None):
    return TacticExercise(
        id=id_,
        fen=fen,
        tags=["tactic"] + (themes or []),
        source="test",
        difficulty=difficulty,
        created_at=datetime(2025, 1, 1),
        solution=solution,
        themes=themes or ["fork"],
    )


@pytest.fixture
def config(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"[database]\npath = '{tmp_path / 'test.db'}'\n"
        "[training]\nmax_new_cards = 10\nmax_reviews = 50\n"
        "[scheduler]\nrequest_retention = 0.9\n"
    )
    return load_config(config_file)


@pytest.fixture
def repo(tmp_path):
    with Repository(tmp_path / "test.db") as r:
        yield r


@pytest.fixture
def seeded_repo(repo):
    exercises = [
        _make_tactic("t:001", FORK_FEN, FORK_SOLUTION, 1200, ["fork"]),
        _make_tactic("t:002", MATE_IN_ONE_FEN, MATE_IN_ONE_SOLUTION, 800, ["mateIn1"]),
        _make_tactic("t:003", MULTI_MOVE_FEN, MULTI_MOVE_SOLUTION, 1800, ["sacrifice"]),
    ]
    for ex in exercises:
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex.id)
    return repo


@pytest.fixture
def web_client(tmp_path):
    cfg = AppConfig()
    cfg.database.path = str(tmp_path / "web.db")
    app = create_app(cfg)
    with Repository(tmp_path / "web.db") as r:
        for ex in [
            _make_tactic("t:001", FORK_FEN, FORK_SOLUTION, 1200, ["fork"]),
            _make_tactic("t:002", MATE_IN_ONE_FEN, MATE_IN_ONE_SOLUTION, 800, ["mateIn1"]),
        ]:
            r.exercises.add(ex)
            r.cards.get_or_create(ex.id)
    return TestClient(app)


# --- Integration Tests ---


class TestImportThroughTraining:
    """Import → Storage → Training → Scheduling end-to-end."""

    def test_imported_exercise_stored_and_retrievable(self, repo):
        """Importer converts puzzle data and storage round-trips it."""
        importer = LichessPuzzleImporter()
        puzzle_data = {
            "game": {"id": "abc123", "pgn": "e4 e5 Bc4 Nc6 Qh5"},
            "puzzle": {
                "id": "INTEG1",
                "rating": 1500,
                "plays": 1000,
                "solution": ["g7g6"],
                "themes": ["fork", "short"],
                "initialPly": 5,
            },
        }
        exercise = importer._convert_puzzle(puzzle_data)
        repo.exercises.add(exercise)

        loaded = repo.exercises.get("lichess:INTEG1")
        assert loaded is not None
        assert loaded.difficulty == 1500
        assert loaded.fen == exercise.fen
        assert loaded.solution == exercise.solution

    def test_imported_exercise_evaluates_correctly(self, repo):
        """Exercise created by importer evaluates user moves properly."""
        importer = LichessPuzzleImporter()
        # Solution has 3 moves: setup (b1c3) + user (d7d5) + opponent (c3d5)
        # After stripping setup, solution = [d7d5, c3d5], user_moves = [d7d5]
        puzzle_data = {
            "game": {"id": "abc123", "pgn": "e4 e5"},
            "puzzle": {
                "id": "INTEG2",
                "rating": 1500,
                "plays": 1000,
                "solution": ["b1c3", "d7d5", "c3d5"],
                "themes": ["fork"],
                "initialPly": 2,
            },
        }
        exercise = importer._convert_puzzle(puzzle_data)
        assert len(exercise.solution) == 2  # setup move stripped
        solution_moves = exercise.get_solution()
        user_moves = solution_moves[::2]
        result = exercise.evaluate(user_moves, 5000)
        assert result.correct is True
        assert result.grade >= 3


class TestConfigDrivesTraining:
    """Config system controls training session behavior."""

    def test_config_max_new_limits_queue(self, seeded_repo, config):
        """Config's max_new_cards setting limits new cards in session."""
        session_config = SessionConfig(
            max_new_cards=config.training.max_new_cards,
            max_reviews=config.training.max_reviews,
        )
        session = TrainingSession(seeded_repo, session_config)
        session.start()
        # All 3 are new cards, config allows 10, so all 3 should appear
        assert session.remaining == 3

        # Now restrict to 1 new card
        session_config2 = SessionConfig(max_new_cards=1, max_reviews=50)
        session2 = TrainingSession(seeded_repo, session_config2)
        session2.start()
        assert session2.remaining == 1

    def test_config_zero_new_cards(self, seeded_repo):
        """Setting max_new_cards=0 should yield no exercises for new-only queue."""
        session_config = SessionConfig(max_new_cards=0, max_reviews=100)
        session = TrainingSession(seeded_repo, session_config)
        session.start()
        assert session.remaining == 0


class TestFullTrainingCycle:
    """Complete training lifecycle: store → schedule → train → review → re-schedule."""

    def test_correct_answer_graduates_card(self, seeded_repo):
        """Answering correctly with EASY rating graduates card from NEW state."""
        session = TrainingSession(seeded_repo)
        session.start()
        exercise = session.next()
        assert exercise is not None

        solution = exercise.get_solution()
        user_moves = solution[::2]
        result, scheduling = session.submit(user_moves, 3000)
        assert result.correct is True

        card = session.rate(Rating.EASY)
        assert card.state == CardState.REVIEW
        assert card.reps == 1

        # Verify card persisted to storage
        reloaded = seeded_repo.cards.get(exercise.id)
        assert reloaded.state == CardState.REVIEW

    def test_wrong_answer_enters_learning(self, seeded_repo):
        """Wrong answer with AGAIN rating puts card into LEARNING state."""
        session = TrainingSession(seeded_repo)
        session.start()
        exercise = session.next()
        assert exercise is not None

        result, _ = session.submit([], 0)
        assert result.correct is False

        card = session.rate(Rating.AGAIN)
        assert card.state == CardState.LEARNING

    def test_multiple_exercises_track_stats(self, seeded_repo):
        """Session stats accumulate correctly across multiple exercises."""
        session = TrainingSession(seeded_repo)
        session.start()
        total = session.remaining

        correct_count = 0
        for _ in range(total):
            exercise = session.next()
            if exercise is None:
                break

            solution = exercise.get_solution()
            user_moves = solution[::2]
            result, _ = session.submit(user_moves, 5000)
            rating = session.auto_rate(result)
            session.rate(rating)
            if result.correct:
                correct_count += 1

        stats = session.end()
        assert stats.exercises_shown == total
        assert stats.correct == correct_count
        assert stats.ended_at is not None

    def test_re_review_after_lapse(self, seeded_repo):
        """Card that lapses can be re-reviewed in a subsequent session."""
        # First session: answer wrong
        session1 = TrainingSession(seeded_repo)
        session1.start()
        session1.next()
        session1.submit([], 0)
        card = session1.rate(Rating.AGAIN)
        session1.end()

        assert card.state == CardState.LEARNING

        # Second session: the learning card should be due
        session2 = TrainingSession(seeded_repo)
        session2.start()
        exercise2 = session2.next()
        # Should get the same card back (it's in learning and due)
        assert exercise2 is not None


class TestSchedulerStorageIntegration:
    """Scheduler results persist correctly through storage layer."""

    def test_scheduled_card_roundtrips_through_storage(self, seeded_repo):
        """FSRS scheduling output survives a save/reload cycle."""
        card = seeded_repo.cards.get("t:001")
        scheduler = FSRSScheduler()
        scheduling = scheduler.schedule(card)

        updated = scheduling.get_card(Rating.GOOD)
        seeded_repo.cards.save(updated)

        reloaded = seeded_repo.cards.get("t:001")
        assert reloaded.state == updated.state
        assert reloaded.stability == pytest.approx(updated.stability, abs=0.01)
        assert reloaded.difficulty == pytest.approx(updated.difficulty, abs=0.01)
        assert reloaded.reps == updated.reps

    def test_review_history_records_persist(self, seeded_repo):
        """Review history entries are correctly stored and queryable."""
        card = seeded_repo.cards.get("t:001")
        scheduler = FSRSScheduler()
        scheduling = scheduler.schedule(card)
        updated = scheduling.get_card(Rating.GOOD)

        seeded_repo.cards.save(updated)
        seeded_repo.cards.record_review(
            card=updated,
            rating=Rating.GOOD,
            time_taken_ms=4200,
            correct=True,
            stability_before=card.stability,
            stability_after=updated.stability,
        )

        count = seeded_repo.conn.execute(
            "SELECT COUNT(*) FROM review_history WHERE exercise_id = ?",
            ["t:001"],
        ).fetchone()[0]
        assert count == 1

    def test_multiple_ratings_produce_different_states(self, seeded_repo):
        """Different FSRS ratings produce appropriately different card states."""
        ids = ["t:001", "t:002", "t:003"]
        ratings = [Rating.AGAIN, Rating.GOOD, Rating.EASY]
        scheduler = FSRSScheduler()

        for ex_id, rating in zip(ids, ratings):
            card = seeded_repo.cards.get(ex_id)
            scheduling = scheduler.schedule(card)
            updated = scheduling.get_card(rating)
            seeded_repo.cards.save(updated)

        again_card = seeded_repo.cards.get("t:001")
        seeded_repo.cards.get("t:002")  # GOOD card — intermediate state
        easy_card = seeded_repo.cards.get("t:003")

        # AGAIN → LEARNING, GOOD → may still be learning step, EASY → REVIEW
        assert again_card.state == CardState.LEARNING
        assert easy_card.state == CardState.REVIEW
        assert easy_card.stability > again_card.stability


class TestWebWithFullBackend:
    """Web API exercises the full backend stack: config → storage → training → scheduling."""

    def test_web_dashboard_shows_stats_from_storage(self, web_client):
        """Dashboard page reflects exercise/card counts from the database."""
        res = web_client.get("/")
        assert res.status_code == 200
        # Should show 2 exercises and 2 cards (seeded in fixture)
        assert "2" in res.text

    def test_web_full_training_session(self, web_client):
        """Complete web training flow: start → next → move → rate → next → complete."""
        # Start session
        res = web_client.post("/api/session/start", json={})
        data = res.json()
        assert data["queue_size"] == 2

        # Get first exercise
        res = web_client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "ok"
        first_fen = data["fen"]

        # Submit a move (correct for whichever exercise we got)
        if first_fen == FORK_FEN:
            move = "g7g6"
        else:
            move = "e2e8"

        res = web_client.post("/api/session/move", json={"move": move})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is True

        # Rate the exercise
        res = web_client.post("/api/session/rate", json={"rating": 3})
        data = res.json()
        assert "next_review" in data
        assert data["remaining"] >= 0

        # Get second exercise
        res = web_client.get("/api/session/next")
        data = res.json()
        assert data["status"] == "ok"
        second_fen = data["fen"]
        assert second_fen != first_fen  # Different exercise

        # Get solution instead of solving
        res = web_client.get("/api/session/solution")
        data = res.json()
        assert "solution_san" in data
        assert len(data["solution_uci"]) > 0

        # Rate it (didn't solve, so rate AGAIN)
        res = web_client.post("/api/session/rate", json={"rating": 1})
        data = res.json()
        assert data["card_state"] == "LEARNING"

        # End session
        res = web_client.post("/api/session/end")
        data = res.json()
        assert data["status"] == "ended"
        assert data["stats"]["exercises_shown"] == 2

    def test_web_stats_api_reflects_reviews(self, web_client):
        """Stats API shows updated card states after a training session."""
        # Check initial state — all cards should be NEW
        res = web_client.get("/api/stats")
        initial = res.json()
        assert initial["exercise_count"] == 2
        assert initial["state_counts"].get("NEW", 0) == 2

        # Do a quick session — rate EASY to graduate card to REVIEW
        web_client.post("/api/session/start", json={})
        res = web_client.get("/api/session/next")
        data = res.json()
        move = "g7g6" if data["fen"] == FORK_FEN else "e2e8"
        web_client.post("/api/session/move", json={"move": move})
        web_client.post("/api/session/rate", json={"rating": 4})  # EASY graduates immediately
        web_client.post("/api/session/end")

        # Stats should show the card graduated from NEW
        res = web_client.get("/api/stats")
        after = res.json()
        # One card should now be REVIEW (graduated via EASY), one still NEW
        assert after["state_counts"].get("NEW", 0) < 2
        assert after["total_reviews"] >= 1  # EASY on NEW sets reps=1

    def test_web_wrong_move_shows_solution(self, web_client):
        """Submitting a wrong move returns feedback, then solution is available."""
        web_client.post("/api/session/start", json={})
        res = web_client.get("/api/session/next")
        data = res.json()

        # Submit wrong move (Nf6 is legal in the fork position, Ke7 in mate position)
        if data["fen"] == FORK_FEN:
            wrong_move = "g8f6"
        else:
            wrong_move = "g1h1"

        res = web_client.post("/api/session/move", json={"move": wrong_move})
        move_data = res.json()
        assert move_data["valid"] is True
        assert move_data["correct"] is False

        # Solution should still be available
        res = web_client.get("/api/session/solution")
        sol_data = res.json()
        assert "solution_san" in sol_data


class TestConfigToWebPipeline:
    """Config settings flow through to web application behavior."""

    def test_config_db_path_used_by_web(self, tmp_path):
        """Web app uses the database path from config."""
        db_path = tmp_path / "custom.db"
        cfg = AppConfig()
        cfg.database.path = str(db_path)
        app = create_app(cfg)

        # Seed the database at the custom path
        with Repository(db_path) as r:
            r.exercises.add(_make_tactic("t:cfg", FORK_FEN, FORK_SOLUTION))
            r.cards.get_or_create("t:cfg")

        client = TestClient(app)
        res = client.get("/api/stats")
        data = res.json()
        assert data["exercise_count"] == 1

    def test_config_training_limits_in_web_session(self, tmp_path):
        """Config's training limits are respected by web session."""
        db_path = tmp_path / "limits.db"
        cfg = AppConfig()
        cfg.database.path = str(db_path)
        cfg.training.max_new_cards = 1  # Only allow 1 new card
        app = create_app(cfg)

        # Seed 3 exercises
        with Repository(db_path) as r:
            for i in range(3):
                r.exercises.add(_make_tactic(f"t:lim{i}", FORK_FEN, FORK_SOLUTION, 1200 + i * 100))
                r.cards.get_or_create(f"t:lim{i}")

        client = TestClient(app)
        res = client.post("/api/session/start", json={})
        data = res.json()
        # Config says max 1 new card
        assert data["queue_size"] == 1


class TestExerciseTypeDiversity:
    """Different exercise types work through the full pipeline."""

    def test_multi_move_tactic_through_web(self, tmp_path):
        """Multi-move tactic (3 moves) works through web submit flow."""
        db_path = tmp_path / "multi.db"
        cfg = AppConfig()
        cfg.database.path = str(db_path)
        app = create_app(cfg)

        with Repository(db_path) as r:
            r.exercises.add(_make_tactic("t:multi", MULTI_MOVE_FEN, MULTI_MOVE_SOLUTION, 1800))
            r.cards.get_or_create("t:multi")

        client = TestClient(app)
        client.post("/api/session/start", json={})
        res = client.get("/api/session/next")
        data = res.json()
        assert data["fen"] == MULTI_MOVE_FEN

        # Move 1: Qxf7+ (user)
        res = client.post("/api/session/move", json={"move": "h5f7"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is True
        assert data["finished"] is False
        # Opponent responds Kd8
        assert data["opponent_move"] == "e8d8"

        # Move 2: Qxf6 (user) — this is the last user move
        res = client.post("/api/session/move", json={"move": "f7f6"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is True
        assert data["finished"] is True

    def test_exercise_difficulty_search_after_storage(self, repo):
        """Exercises stored with different difficulties are searchable."""
        exercises = [
            _make_tactic("t:easy", FORK_FEN, FORK_SOLUTION, 800),
            _make_tactic("t:med", MATE_IN_ONE_FEN, MATE_IN_ONE_SOLUTION, 1500),
            _make_tactic("t:hard", MULTI_MOVE_FEN, MULTI_MOVE_SOLUTION, 2200),
        ]
        for ex in exercises:
            repo.exercises.add(ex)

        easy = repo.exercises.search(max_difficulty=1000)
        assert len(easy) == 1
        assert easy[0].id == "t:easy"

        hard = repo.exercises.search(min_difficulty=2000)
        assert len(hard) == 1
        assert hard[0].id == "t:hard"

        mid = repo.exercises.search(min_difficulty=1000, max_difficulty=2000)
        assert len(mid) == 1
        assert mid[0].id == "t:med"
