"""Integration tests for multi-tenant storage isolation."""

import pytest
from fastapi.testclient import TestClient

from src.auth.service import AuthService
from src.config import AppConfig
from src.exercises import TacticExercise
from src.storage import Repository
from src.web import create_app

SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


@pytest.fixture
def tenant_app(tmp_path):
    """App with auth enabled for multi-tenant testing."""
    config = AppConfig()
    config.database.path = str(tmp_path / "trainer.db")
    config.database.data_dir = str(tmp_path / "data")
    config.auth.enabled = True
    config.auth.database_path = str(tmp_path / "auth.db")
    config.auth.session_expiry_hours = 24
    config.auth.require_invite = True
    return create_app(config)


@pytest.fixture
def two_users(tenant_app):
    """Register two users and return their login helpers."""
    svc: AuthService = tenant_app.state.auth_service

    code_a = svc.create_invite_code()
    user_a = svc.register("alice", "pass-alice", code_a)

    code_b = svc.create_invite_code()
    user_b = svc.register("bob", "pass-bob", code_b)

    return {"alice": user_a, "bob": user_b}


def _login(client: TestClient, username: str, password: str) -> TestClient:
    """Log in and return the same client (now with session cookie)."""
    resp = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    return client


def _seed_exercises(app, user_id: str, exercise_ids: list[str]) -> None:
    """Insert exercises directly into a user's database via the pool."""
    pool = app.state.manager_pool
    mgr = pool.get(user_id)
    repo = mgr._open_repo()
    for eid in exercise_ids:
        tactic = TacticExercise(
            id=eid,
            fen=SAMPLE_FEN,
            tags=["test"],
            source="test",
            difficulty=1500.0,
            solution=["g7g6"],
            themes=["test"],
        )
        repo.exercises.add(tactic)
        repo.cards.get_or_create(tactic.id)


# ── Data isolation ───────────────────────────────────────────────────────────


class TestDataIsolation:
    def test_users_have_separate_databases(self, tenant_app, two_users):
        """Each user's exercises are invisible to the other."""
        _seed_exercises(tenant_app, two_users["alice"].id, ["alice:001", "alice:002"])
        _seed_exercises(tenant_app, two_users["bob"].id, ["bob:001"])

        pool = tenant_app.state.manager_pool
        alice_mgr = pool.get(two_users["alice"].id)
        bob_mgr = pool.get(two_users["bob"].id)

        alice_stats = alice_mgr.get_stats()
        bob_stats = bob_mgr.get_stats()

        assert alice_stats["exercise_count"] == 2
        assert bob_stats["exercise_count"] == 1

    def test_users_see_own_stats_via_api(self, tenant_app, two_users):
        """API returns per-user stats based on auth."""
        _seed_exercises(tenant_app, two_users["alice"].id, ["alice:001", "alice:002", "alice:003"])
        _seed_exercises(tenant_app, two_users["bob"].id, ["bob:001"])

        # Alice's client
        alice_client = TestClient(tenant_app)
        _login(alice_client, "alice", "pass-alice")
        resp = alice_client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.json()["exercise_count"] == 3

        # Bob's client
        bob_client = TestClient(tenant_app)
        _login(bob_client, "bob", "pass-bob")
        resp = bob_client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.json()["exercise_count"] == 1

    def test_independent_training_sessions(self, tenant_app, two_users):
        """Two users can start training sessions independently."""
        _seed_exercises(tenant_app, two_users["alice"].id, ["alice:001"])
        _seed_exercises(tenant_app, two_users["bob"].id, ["bob:001"])

        alice_client = TestClient(tenant_app)
        _login(alice_client, "alice", "pass-alice")

        bob_client = TestClient(tenant_app)
        _login(bob_client, "bob", "pass-bob")

        # Both start sessions
        resp_a = alice_client.post("/api/session/start")
        assert resp_a.status_code == 200
        assert resp_a.json()["queue_size"] == 1

        resp_b = bob_client.post("/api/session/start")
        assert resp_b.status_code == 200
        assert resp_b.json()["queue_size"] == 1

        # Alice's session is independent of Bob's
        next_a = alice_client.get("/api/session/next")
        assert next_a.status_code == 200
        assert next_a.json()["status"] == "ok"

        next_b = bob_client.get("/api/session/next")
        assert next_b.status_code == 200
        assert next_b.json()["status"] == "ok"


# ── Backwards compatibility ──────────────────────────────────────────────────


class TestAuthDisabledBackwardsCompat:
    def test_no_auth_uses_default_db(self, tmp_path):
        """Auth-disabled mode uses config.database.path (same as before B2)."""
        config = AppConfig()
        config.database.path = str(tmp_path / "trainer.db")
        app = create_app(config)

        client = TestClient(app)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.json()["exercise_count"] == 0

    def test_no_auth_pool_uses_default_key(self, tmp_path):
        """Without auth, the pool creates a single _default manager."""
        config = AppConfig()
        config.database.path = str(tmp_path / "trainer.db")
        app = create_app(config)
        pool = app.state.manager_pool

        client = TestClient(app)
        client.get("/api/stats")  # Triggers manager creation

        assert "_default" in pool._managers
        assert len(pool._managers) == 1

    def test_no_auth_seeded_exercises_visible(self, tmp_path):
        """Exercises seeded via Repository are visible in auth-disabled mode."""
        config = AppConfig()
        config.database.path = str(tmp_path / "trainer.db")

        # Seed directly
        with Repository(tmp_path / "trainer.db") as repo:
            tactic = TacticExercise(
                id="test:001",
                fen=SAMPLE_FEN,
                tags=["test"],
                source="test",
                difficulty=1500.0,
                solution=["g7g6"],
                themes=["test"],
            )
            repo.exercises.add(tactic)

        app = create_app(config)
        client = TestClient(app)
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        assert resp.json()["exercise_count"] == 1
