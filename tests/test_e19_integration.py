"""Integration tests for E19: Own-Game Exercise Improvements.

End-to-end tests covering the full lifecycle: config → exercise creation →
storage roundtrip → training with acceptable moves → game context display.
"""

import chess
import pytest

from src.config import AppConfig, OwnGameEvalConfig
from src.exercises import TacticExercise
from src.storage import Repository

# ── Test fixtures ───────────────────────────────────────────────────────────


# Open position: Black queen on d4 vs White king on e1.
# Solution: Qd1+ Kf2 Qd2+ (3 moves, 2 user moves).
SIMPLE_FEN = "4k3/8/8/8/3q4/8/8/4K3 b - - 0 1"

# Mate position: Black can deliver Qd1# (back-rank pattern with rook support).
MATE_FEN = "4k3/8/8/8/8/8/3r4/3qK3 b - - 0 1"


def _make_own_game_exercise(
    exercise_id: str = "game:test:1:m1",
    fen: str = SIMPLE_FEN,
    solution: list[str] | None = None,
    acceptable_first_moves: list[str] | None = None,
    best_move_eval: int | None = 50,
    evaluate_depth: int | None = 1,
    game_context: dict | None = None,
) -> TacticExercise:
    """Create a TacticExercise mimicking an own-game import."""
    if solution is None:
        solution = ["d4d1", "e1f2", "d1d2"]
    metadata = {}
    if game_context is not None:
        metadata["game_context"] = game_context

    return TacticExercise(
        id=exercise_id,
        fen=fen,
        tags=["own_game"],
        source="test",
        difficulty=1200.0,
        solution=solution,
        themes=["own_game"],
        acceptable_first_moves=acceptable_first_moves or [],
        best_move_eval=best_move_eval,
        evaluate_depth=evaluate_depth,
        metadata=metadata,
    )


# ── Storage roundtrip tests ────────────────────────────────────────────────


class TestStorageRoundtrip:
    """Verify new fields survive add → get through DuckDB storage."""

    def test_acceptable_first_moves_roundtrip(self, tmp_path):
        """acceptable_first_moves should be preserved through storage."""
        ex = _make_own_game_exercise(acceptable_first_moves=["d4e3", "d4d3"])
        with Repository(tmp_path / "test.db") as repo:
            repo.exercises.add(ex)
            loaded = repo.exercises.get(ex.id)

        assert isinstance(loaded, TacticExercise)
        assert loaded.acceptable_first_moves == ["d4e3", "d4d3"]

    def test_best_move_eval_roundtrip(self, tmp_path):
        """best_move_eval should be preserved through storage."""
        ex = _make_own_game_exercise(best_move_eval=123)
        with Repository(tmp_path / "test.db") as repo:
            repo.exercises.add(ex)
            loaded = repo.exercises.get(ex.id)

        assert isinstance(loaded, TacticExercise)
        assert loaded.best_move_eval == 123

    def test_evaluate_depth_roundtrip(self, tmp_path):
        """evaluate_depth should be preserved through storage."""
        ex = _make_own_game_exercise(evaluate_depth=2)
        with Repository(tmp_path / "test.db") as repo:
            repo.exercises.add(ex)
            loaded = repo.exercises.get(ex.id)

        assert isinstance(loaded, TacticExercise)
        assert loaded.evaluate_depth == 2

    def test_game_context_in_metadata_roundtrip(self, tmp_path):
        """game_context stored in metadata should survive roundtrip."""
        context = {
            "game_date": "2026-01-15",
            "opponent": "DrDrunkenstein",
            "time_control": "3+0",
            "player_color": "black",
        }
        ex = _make_own_game_exercise(game_context=context)
        with Repository(tmp_path / "test.db") as repo:
            repo.exercises.add(ex)
            loaded = repo.exercises.get(ex.id)

        assert isinstance(loaded, TacticExercise)
        assert loaded.metadata["game_context"] == context

    def test_empty_acceptable_moves_roundtrip(self, tmp_path):
        """Empty acceptable_first_moves should roundtrip as empty list."""
        ex = _make_own_game_exercise(acceptable_first_moves=[])
        with Repository(tmp_path / "test.db") as repo:
            repo.exercises.add(ex)
            loaded = repo.exercises.get(ex.id)

        assert isinstance(loaded, TacticExercise)
        assert loaded.acceptable_first_moves == []

    def test_none_fields_roundtrip(self, tmp_path):
        """None values for optional fields should be preserved."""
        ex = _make_own_game_exercise(best_move_eval=None, evaluate_depth=None, game_context=None)
        with Repository(tmp_path / "test.db") as repo:
            repo.exercises.add(ex)
            loaded = repo.exercises.get(ex.id)

        assert isinstance(loaded, TacticExercise)
        assert loaded.best_move_eval is None
        assert loaded.evaluate_depth is None
        assert "game_context" not in loaded.metadata


# ── Evaluate tests with config interaction ──────────────────────────────────


class TestEvaluateWithConfig:
    """Test TacticExercise.evaluate() with E19 fields."""

    def test_acceptable_first_move_is_correct(self):
        """User plays an acceptable first move — should be marked correct."""
        ex = _make_own_game_exercise(
            acceptable_first_moves=["d4e3"],
            evaluate_depth=1,
        )
        # d4e3 is acceptable but not the exact solution (d4d1)
        user_moves = [chess.Move.from_uci("d4e3")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is True

    def test_exact_solution_is_correct(self):
        """Exact solution should always be correct."""
        ex = _make_own_game_exercise(
            acceptable_first_moves=["d4e3"],
            evaluate_depth=1,
        )
        user_moves = [chess.Move.from_uci("d4d1")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is True

    def test_unacceptable_move_is_incorrect(self):
        """A move neither in solution nor acceptable list is incorrect."""
        ex = _make_own_game_exercise(
            acceptable_first_moves=["d4e3"],
            evaluate_depth=1,
        )
        user_moves = [chess.Move.from_uci("d4a4")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is False
        assert result.partial_credit == 0.0

    def test_evaluate_depth_none_checks_all_moves(self):
        """With evaluate_depth=None, all user moves are checked."""
        ex = _make_own_game_exercise(evaluate_depth=None)
        # Solution: d4d1, e1f2, d1d2 — user moves are d4d1, d1d2
        # Only playing first user move should give partial credit
        user_moves = [chess.Move.from_uci("d4d1")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is False
        assert result.partial_credit == 0.5  # 1 of 2 user moves

    def test_evaluate_depth_1_checks_only_first(self):
        """With evaluate_depth=1, only the first user move is checked."""
        ex = _make_own_game_exercise(evaluate_depth=1)
        user_moves = [chess.Move.from_uci("d4d1")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is True

    def test_evaluate_depth_greater_than_solution(self):
        """evaluate_depth > number of user moves uses all available moves."""
        ex = _make_own_game_exercise(evaluate_depth=10)
        # Only 2 user moves in solution; depth=10 just means "check all"
        user_moves = [chess.Move.from_uci("d4d1"), chess.Move.from_uci("d1d2")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is True

    def test_acceptable_only_applies_to_first_move(self):
        """Acceptable moves should only apply to the first user move."""
        ex = _make_own_game_exercise(
            acceptable_first_moves=["d4e3", "d1c2"],
            evaluate_depth=None,  # Check all moves
        )
        # First move: exact solution. Second move: d1c2 in acceptable but
        # acceptable only applies to first move, so this should be wrong.
        user_moves = [chess.Move.from_uci("d4d1"), chess.Move.from_uci("d1c2")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is False
        assert result.partial_credit == 0.5  # First move correct, second wrong

    def test_empty_acceptable_falls_through_to_exact(self):
        """With empty acceptable_first_moves, only exact match works."""
        ex = _make_own_game_exercise(
            acceptable_first_moves=[],
            evaluate_depth=1,
        )
        # d4e3 would be acceptable if the list had it, but it's empty
        user_moves = [chess.Move.from_uci("d4e3")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is False


# ── Config defaults and interaction ─────────────────────────────────────────


class TestConfigInteraction:
    """Test OwnGameEvalConfig field interactions."""

    def test_default_config_values(self):
        """Default config should have sensible values for own-game eval."""
        config = OwnGameEvalConfig()
        assert config.cp_tolerance == 50
        assert config.multipv_count == 3
        assert config.evaluate_depth == 1
        assert config.show_game_context is True

    def test_config_wired_to_app_config(self):
        """OwnGameEvalConfig should be accessible from AppConfig."""
        config = AppConfig()
        assert isinstance(config.own_game_eval, OwnGameEvalConfig)
        assert config.own_game_eval.cp_tolerance == 50

    def test_zero_cp_tolerance_means_exact_only(self):
        """cp_tolerance=0 should mean only the best move is acceptable."""
        config = OwnGameEvalConfig(cp_tolerance=0)
        assert config.cp_tolerance == 0
        # With cp_tolerance=0 at import time, acceptable_first_moves
        # would only contain moves at exact same eval as best — effectively
        # just the best move itself

    def test_high_cp_tolerance_is_valid(self):
        """High tolerance values should be accepted (for blitz analysis)."""
        config = OwnGameEvalConfig(cp_tolerance=200)
        assert config.cp_tolerance == 200


# ── Web integration tests (full API flow) ───────────────────────────────────


class TestWebIntegration:
    """Full web API flow tests with E19 features."""

    @pytest.fixture
    def e19_app(self, tmp_path):
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")
        config.own_game_eval.show_game_context = True

        from src.web import create_app

        app = create_app(config)

        with Repository(tmp_path / "test.db") as repo:
            # Exercise with acceptable moves and game context
            ex = _make_own_game_exercise(
                acceptable_first_moves=["d4e3"],
                evaluate_depth=1,
                game_context={
                    "game_date": "2026-02-09",
                    "opponent": "hikaru",
                    "time_control": "5+3",
                    "player_color": "black",
                },
            )
            repo.exercises.add(ex)
            repo.cards.get_or_create(ex.id)

        from fastapi.testclient import TestClient

        return TestClient(app)

    def test_full_flow_with_acceptable_move(self, e19_app):
        """Complete flow: start → next → acceptable move → rate → complete."""
        # Start session
        res = e19_app.post("/api/session/start", json={})
        assert res.json()["queue_size"] == 1

        # Get exercise — should include game context
        res = e19_app.get("/api/session/next")
        data = res.json()
        assert data["status"] == "ok"
        assert "game_context" in data
        assert data["game_context"]["opponent"] == "hikaru"

        # Submit acceptable (but not exact) first move
        res = e19_app.post("/api/session/move", json={"move": "d4e3"})
        data = res.json()
        assert data["valid"] is True
        assert data["correct"] is True
        assert data["finished"] is True

        # Get solution
        res = e19_app.get("/api/session/solution")
        data = res.json()
        assert "solution_san" in data

        # Rate
        res = e19_app.post("/api/session/rate", json={"rating": 3})
        data = res.json()
        assert "next_review" in data

        # Session should be complete
        res = e19_app.get("/api/session/next")
        assert res.json()["status"] == "complete"

    def test_full_flow_with_exact_solution(self, e19_app):
        """Complete flow using the exact solution move."""
        e19_app.post("/api/session/start", json={})
        e19_app.get("/api/session/next")

        res = e19_app.post("/api/session/move", json={"move": "d4d1"})
        data = res.json()
        assert data["correct"] is True
        assert data["finished"] is True

    def test_full_flow_with_wrong_move(self, e19_app):
        """Wrong move should end exercise as incorrect."""
        e19_app.post("/api/session/start", json={})
        e19_app.get("/api/session/next")

        res = e19_app.post("/api/session/move", json={"move": "d4a4"})
        data = res.json()
        assert data["correct"] is False
        assert data["finished"] is True


# ── Edge case tests ─────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases for E19 features."""

    def test_single_move_solution_with_depth_1(self):
        """Single-move solution with evaluate_depth=1 should work."""
        ex = TacticExercise(
            id="game:test:edge:1",
            fen=SIMPLE_FEN,
            tags=["own_game"],
            source="test",
            difficulty=1000.0,
            solution=["d4d1"],
            themes=[],
            acceptable_first_moves=["d4e3"],
            evaluate_depth=1,
        )
        result = ex.evaluate([chess.Move.from_uci("d4e3")], 0)
        assert result.correct is True

    def test_no_acceptable_moves_requires_exact(self):
        """Without acceptable moves, only exact match works."""
        ex = TacticExercise(
            id="game:test:edge:2",
            fen=SIMPLE_FEN,
            tags=["own_game"],
            source="test",
            difficulty=1000.0,
            solution=["d4d1"],
            themes=[],
            acceptable_first_moves=[],
            evaluate_depth=1,
        )
        result = ex.evaluate([chess.Move.from_uci("d4e3")], 0)
        assert result.correct is False

    def test_exercise_without_e19_fields_still_works(self):
        """Legacy exercises without new fields should evaluate normally."""
        ex = TacticExercise(
            id="lichess:abc",
            fen=SIMPLE_FEN,
            tags=["tactic"],
            source="lichess",
            difficulty=1500.0,
            solution=["d4d1"],
            themes=["fork"],
        )
        # No acceptable_first_moves, no evaluate_depth
        assert ex.acceptable_first_moves == []
        assert ex.best_move_eval is None
        assert ex.evaluate_depth is None

        result = ex.evaluate([chess.Move.from_uci("d4d1")], 0)
        assert result.correct is True

    def test_evaluate_depth_with_single_move_solution(self):
        """evaluate_depth=1 with 1-move solution — trivially correct."""
        ex = _make_own_game_exercise(
            solution=["d4d1"],
            evaluate_depth=1,
        )
        result = ex.evaluate([chess.Move.from_uci("d4d1")], 0)
        assert result.correct is True

    def test_evaluate_depth_2_checks_two_user_moves(self):
        """evaluate_depth=2 should check both user moves in the solution."""
        ex = _make_own_game_exercise(evaluate_depth=2)
        # Solution: d4d1 e1f2 d1d2 — user moves: d4d1, d1d2
        # Playing both correctly
        user_moves = [chess.Move.from_uci("d4d1"), chess.Move.from_uci("d1d2")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is True

    def test_evaluate_depth_2_first_wrong(self):
        """evaluate_depth=2 with wrong first move → incorrect."""
        ex = _make_own_game_exercise(evaluate_depth=2)
        user_moves = [chess.Move.from_uci("d4a4")]
        result = ex.evaluate(user_moves, 0)
        assert result.correct is False
        assert result.partial_credit == 0.0
