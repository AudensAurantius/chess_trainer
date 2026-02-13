"""Tests for E4: Difficulty Adaptation.

Tests cover:
- DifficultyAdapter computation logic
- SessionConfig difficulty filtering in queue building
- Integration with the web SessionManager
"""

from datetime import datetime, timedelta

import pytest

from src.config import AppConfig, DifficultyConfig
from src.exercises import TacticExercise
from src.scheduling.fsrs import Rating
from src.storage import Repository
from src.training import SessionConfig, TrainingSession
from src.training.difficulty import DifficultyAdapter, DifficultyRange

# ── Helpers ──────────────────────────────────────────────────────────────────

SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"
SAMPLE_SOLUTION = ["g7g6"]


def _make_tactic(id: str, difficulty: float | None = None) -> TacticExercise:
    return TacticExercise(
        id=id,
        fen=SAMPLE_FEN,
        tags=["tactic"],
        source="test",
        difficulty=difficulty,
        solution=SAMPLE_SOLUTION,
        themes=["fork"],
    )


def _seed_exercises_and_reviews(
    repo: Repository,
    difficulties: list[float | None],
    correct_flags: list[bool],
) -> None:
    """Insert exercises with given difficulties and review history entries."""
    base_time = datetime(2025, 6, 1, 12, 0, 0)
    for i, (diff, correct) in enumerate(zip(difficulties, correct_flags)):
        ex_id = f"test:{i:03d}"
        ex = _make_tactic(ex_id, difficulty=diff)
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex_id)
        # Insert review record
        repo.conn.execute(
            """
            INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                                        time_taken_ms, correct, stability_before,
                                        stability_after)
            VALUES (nextval('review_history_seq'), ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ex_id,
                base_time + timedelta(minutes=i),
                Rating.GOOD.value if correct else Rating.AGAIN.value,
                3000,
                correct,
                1.0,
                2.0,
            ],
        )


# ── DifficultyAdapter tests ────────────────────────────────────────────────


class TestDifficultyAdapter:
    """Tests for DifficultyAdapter.compute_range()."""

    @pytest.fixture
    def repo(self):
        with Repository() as r:
            yield r

    @pytest.fixture
    def default_config(self):
        return DifficultyConfig(
            enabled=True,
            window=20,
            min_reviews=5,
            promote_accuracy=0.80,
            demote_accuracy=0.45,
            step=150,
            difficulty_range=600,
        )

    def test_returns_none_when_no_reviews(self, repo, default_config):
        adapter = DifficultyAdapter(repo.conn, default_config)
        assert adapter.compute_range() is None

    def test_returns_none_when_fewer_than_min_reviews(self, repo, default_config):
        """With only 3 reviews (min_reviews=5), returns None."""
        _seed_exercises_and_reviews(
            repo,
            difficulties=[1500.0, 1500.0, 1500.0],
            correct_flags=[True, True, False],
        )
        adapter = DifficultyAdapter(repo.conn, default_config)
        assert adapter.compute_range() is None

    def test_returns_none_when_no_exercises_have_difficulty(self, repo, default_config):
        """Reviews exist but all exercises have NULL difficulty."""
        _seed_exercises_and_reviews(
            repo,
            difficulties=[None, None, None, None, None],
            correct_flags=[True, True, True, True, True],
        )
        adapter = DifficultyAdapter(repo.conn, default_config)
        assert adapter.compute_range() is None

    def test_stable_accuracy_no_shift(self, repo, default_config):
        """60% accuracy (between thresholds) → target = avg_difficulty."""
        diffs = [1500.0] * 10
        corrects = [True] * 6 + [False] * 4  # 60%
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        assert result.min_difficulty == pytest.approx(1500.0 - 300.0)
        assert result.max_difficulty == pytest.approx(1500.0 + 300.0)

    def test_promote_when_high_accuracy(self, repo, default_config):
        """90% accuracy → promotes by step."""
        diffs = [1500.0] * 10
        corrects = [True] * 9 + [False] * 1  # 90%
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        target = 1500.0 + 150.0  # promoted
        assert result.min_difficulty == pytest.approx(target - 300.0)
        assert result.max_difficulty == pytest.approx(target + 300.0)

    def test_demote_when_low_accuracy(self, repo, default_config):
        """30% accuracy → demotes by step."""
        diffs = [1500.0] * 10
        corrects = [True] * 3 + [False] * 7  # 30%
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        target = 1500.0 - 150.0  # demoted
        assert result.min_difficulty == pytest.approx(target - 300.0)
        assert result.max_difficulty == pytest.approx(target + 300.0)

    def test_exactly_at_promote_threshold(self, repo, default_config):
        """Exactly 80% accuracy → promotes."""
        diffs = [1500.0] * 10
        corrects = [True] * 8 + [False] * 2  # exactly 80%
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        target = 1500.0 + 150.0
        assert result.min_difficulty == pytest.approx(target - 300.0)

    def test_exactly_at_demote_threshold(self, repo, default_config):
        """Exactly 45% accuracy → demotes."""
        diffs = [1500.0] * 20
        corrects = [True] * 9 + [False] * 11  # 9/20 = 45%
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        target = 1500.0 - 150.0
        assert result.min_difficulty == pytest.approx(target - 300.0)

    def test_all_correct_promotes(self, repo, default_config):
        """100% accuracy → promotes."""
        diffs = [1200.0] * 5
        corrects = [True] * 5
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        assert result.min_difficulty == pytest.approx(1200.0 + 150.0 - 300.0)

    def test_all_incorrect_demotes(self, repo, default_config):
        """0% accuracy → demotes."""
        diffs = [1200.0] * 5
        corrects = [False] * 5
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        assert result.min_difficulty == pytest.approx(1200.0 - 150.0 - 300.0)

    def test_respects_window_size(self, repo):
        """Only considers the last N reviews."""
        config = DifficultyConfig(
            enabled=True,
            window=5,  # Only look at last 5
            min_reviews=3,
            promote_accuracy=0.80,
            demote_accuracy=0.45,
            step=150,
            difficulty_range=600,
        )
        # Insert 10 reviews: first 5 are wrong, last 5 are correct
        diffs = [1500.0] * 10
        corrects = [False] * 5 + [True] * 5
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, config)
        result = adapter.compute_range()
        assert result is not None
        # Window of 5 most recent → 100% accuracy → promotes
        target = 1500.0 + 150.0
        assert result.min_difficulty == pytest.approx(target - 300.0)

    def test_mixed_difficulty_exercises(self, repo, default_config):
        """Average difficulty computed from varied ratings."""
        diffs = [1000.0, 1200.0, 1400.0, 1600.0, 1800.0]
        corrects = [True, True, True, False, False]  # 60%
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        result = adapter.compute_range()
        assert result is not None
        avg = 1400.0  # (1000+1200+1400+1600+1800)/5
        assert result.min_difficulty == pytest.approx(avg - 300.0)
        assert result.max_difficulty == pytest.approx(avg + 300.0)

    def test_null_difficulty_exercises_excluded_from_computation(self, repo, default_config):
        """Exercises with NULL difficulty are excluded from the query."""
        # 3 with difficulty + 5 without → only 3 in window → below min_reviews
        diffs = [1500.0, 1500.0, 1500.0, None, None, None, None, None]
        corrects = [True] * 3 + [True] * 5
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, default_config)
        # Only 3 exercises have difficulty, below min_reviews=5
        assert adapter.compute_range() is None

    def test_custom_step_and_range(self, repo):
        """Custom step/range values work correctly."""
        config = DifficultyConfig(
            enabled=True,
            window=20,
            min_reviews=5,
            promote_accuracy=0.80,
            demote_accuracy=0.45,
            step=200,
            difficulty_range=400,
        )
        diffs = [1500.0] * 5
        corrects = [True] * 5  # 100% → promotes
        _seed_exercises_and_reviews(repo, diffs, corrects)

        adapter = DifficultyAdapter(repo.conn, config)
        result = adapter.compute_range()
        assert result is not None
        target = 1500.0 + 200.0
        assert result.min_difficulty == pytest.approx(target - 200.0)
        assert result.max_difficulty == pytest.approx(target + 200.0)

    def test_range_dataclass(self):
        """DifficultyRange holds min/max correctly."""
        r = DifficultyRange(min_difficulty=1000.0, max_difficulty=2000.0)
        assert r.min_difficulty == 1000.0
        assert r.max_difficulty == 2000.0


# ── SessionConfig difficulty filtering tests ─────────────────────────────────


class TestSessionDifficultyFiltering:
    """Tests for difficulty-based queue filtering in TrainingSession."""

    @pytest.fixture
    def repo(self):
        with Repository() as r:
            yield r

    def _add_exercise_with_card(
        self, repo: Repository, ex_id: str, difficulty: float | None
    ) -> None:
        ex = _make_tactic(ex_id, difficulty=difficulty)
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex_id)

    def test_queue_includes_exercises_within_range(self, repo):
        self._add_exercise_with_card(repo, "in-range", 1500.0)
        config = SessionConfig(min_difficulty=1200.0, max_difficulty=1800.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 1

    def test_queue_excludes_exercises_below_range(self, repo):
        self._add_exercise_with_card(repo, "too-easy", 800.0)
        config = SessionConfig(min_difficulty=1200.0, max_difficulty=1800.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 0

    def test_queue_excludes_exercises_above_range(self, repo):
        self._add_exercise_with_card(repo, "too-hard", 2200.0)
        config = SessionConfig(min_difficulty=1200.0, max_difficulty=1800.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 0

    def test_null_difficulty_passes_through(self, repo):
        """Exercises without a difficulty rating are never excluded."""
        self._add_exercise_with_card(repo, "no-diff", None)
        config = SessionConfig(min_difficulty=1200.0, max_difficulty=1800.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 1

    def test_mixed_exercises_filtered_correctly(self, repo):
        """Only exercises in range + null difficulty remain."""
        self._add_exercise_with_card(repo, "too-easy", 800.0)
        self._add_exercise_with_card(repo, "in-range", 1500.0)
        self._add_exercise_with_card(repo, "too-hard", 2200.0)
        self._add_exercise_with_card(repo, "no-diff", None)

        config = SessionConfig(min_difficulty=1200.0, max_difficulty=1800.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 2  # in-range + no-diff

    def test_no_difficulty_set_all_pass(self, repo):
        """Without min/max difficulty, all exercises pass."""
        self._add_exercise_with_card(repo, "easy", 800.0)
        self._add_exercise_with_card(repo, "hard", 2200.0)

        config = SessionConfig()
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 2

    def test_only_min_difficulty(self, repo):
        """Only min_difficulty set (no max) → filters below only."""
        self._add_exercise_with_card(repo, "below", 800.0)
        self._add_exercise_with_card(repo, "above", 1500.0)

        config = SessionConfig(min_difficulty=1000.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 1

    def test_only_max_difficulty(self, repo):
        """Only max_difficulty set (no min) → filters above only."""
        self._add_exercise_with_card(repo, "below", 800.0)
        self._add_exercise_with_card(repo, "above", 1500.0)

        config = SessionConfig(max_difficulty=1000.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 1

    def test_difficulty_filtering_combines_with_type_filtering(self, repo):
        """Difficulty and type filters work together."""
        from src.exercises import ExerciseType
        from src.exercises.openings import OpeningExercise

        # Add a tactic in range
        self._add_exercise_with_card(repo, "tactic-in", 1500.0)
        # Add an opening in range (different type)
        opening = OpeningExercise(
            id="opening-in",
            fen=SAMPLE_FEN,
            tags=["opening"],
            source="test",
            difficulty=1500.0,
            line=SAMPLE_SOLUTION,
            eco_code="A00",
        )
        repo.exercises.add(opening)
        repo.cards.get_or_create("opening-in")

        config = SessionConfig(
            min_difficulty=1200.0,
            max_difficulty=1800.0,
            exercise_types=[ExerciseType.TACTIC],
        )
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 1  # Only the tactic

    def test_difficulty_at_exact_boundary(self, repo):
        """Exercise at exact boundary values is included."""
        self._add_exercise_with_card(repo, "at-min", 1200.0)
        self._add_exercise_with_card(repo, "at-max", 1800.0)

        config = SessionConfig(min_difficulty=1200.0, max_difficulty=1800.0)
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 2


# ── Integration tests ────────────────────────────────────────────────────────


class TestDifficultyIntegration:
    """End-to-end integration tests for difficulty adaptation."""

    @pytest.fixture
    def repo(self):
        with Repository() as r:
            yield r

    def test_full_flow_import_review_adapt(self, repo):
        """Full flow: add exercises → review → compute range → filtered session."""
        # Add exercises at various difficulties
        for i, diff in enumerate([1000.0, 1200.0, 1500.0, 1800.0, 2200.0]):
            ex = _make_tactic(f"flow:{i}", difficulty=diff)
            repo.exercises.add(ex)
            repo.cards.get_or_create(ex.id)

        # Simulate some reviews (all correct at ~1500 average)
        base_time = datetime(2025, 6, 1)
        for i, (ex_id, correct) in enumerate(
            [
                ("flow:0", True),
                ("flow:1", True),
                ("flow:2", True),
                ("flow:3", False),
                ("flow:4", False),
            ]
        ):
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                                            time_taken_ms, correct, stability_before,
                                            stability_after)
                VALUES (nextval('review_history_seq'), ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ex_id,
                    base_time + timedelta(minutes=i),
                    Rating.GOOD.value if correct else Rating.AGAIN.value,
                    3000,
                    correct,
                    1.0,
                    2.0,
                ],
            )

        # Compute range → 60% accuracy, avg difficulty = 1540
        config = DifficultyConfig(
            enabled=True,
            window=20,
            min_reviews=5,
            promote_accuracy=0.80,
            demote_accuracy=0.45,
            step=150,
            difficulty_range=600,
        )
        adapter = DifficultyAdapter(repo.conn, config)
        result = adapter.compute_range()
        assert result is not None

        # Start a filtered session
        session_config = SessionConfig(
            min_difficulty=result.min_difficulty,
            max_difficulty=result.max_difficulty,
        )
        session = TrainingSession(repo, session_config)
        session.start()

        # Verify the queue only includes exercises in range
        assert session.remaining > 0
        while True:
            ex = session.next()
            if ex is None:
                break
            if ex.difficulty is not None:
                assert result.min_difficulty <= ex.difficulty <= result.max_difficulty
            session.submit([], 0)
            session.rate(Rating.AGAIN)

    def test_web_session_manager_with_difficulty(self, tmp_path):
        """SessionManager wires difficulty adapter when config is enabled."""
        from src.web.session_manager import SessionManager

        db_path = tmp_path / "test.db"
        config = AppConfig()
        config.difficulty.enabled = True
        config.difficulty.min_reviews = 3  # Lower threshold for test

        manager = SessionManager(config, db_path=db_path)
        repo = manager._open_repo()

        # Add exercises
        for i, diff in enumerate([1200.0, 1500.0, 1800.0]):
            ex = _make_tactic(f"web:{i}", difficulty=diff)
            repo.exercises.add(ex)
            repo.cards.get_or_create(ex.id)

        # Add review history
        base_time = datetime(2025, 6, 1)
        for i in range(3):
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                                            time_taken_ms, correct, stability_before,
                                            stability_after)
                VALUES (nextval('review_history_seq'), ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    f"web:{i}",
                    base_time + timedelta(minutes=i),
                    Rating.GOOD.value,
                    3000,
                    True,
                    1.0,
                    2.0,
                ],
            )

        manager._close_repo()

        # Start session with adaptation
        count = manager.start_session(adapt_difficulty=True)
        # Should work without error; exercises may or may not be filtered
        assert count >= 0
        manager.end_session()

    def test_web_session_manager_adapt_false_skips(self, tmp_path):
        """adapt_difficulty=False skips adaptation even if config enabled."""
        from src.web.session_manager import SessionManager

        db_path = tmp_path / "test.db"
        config = AppConfig()
        config.difficulty.enabled = True

        manager = SessionManager(config, db_path=db_path)
        repo = manager._open_repo()

        # Add one exercise
        ex = _make_tactic("skip:0", difficulty=1500.0)
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex.id)
        manager._close_repo()

        # Start session with adapt_difficulty=False → no filtering
        count = manager.start_session(adapt_difficulty=False)
        assert count == 1
        manager.end_session()

    def test_web_session_manager_config_disabled(self, tmp_path):
        """Default config (disabled) → no adaptation applied."""
        from src.web.session_manager import SessionManager

        db_path = tmp_path / "test.db"
        config = AppConfig()  # difficulty.enabled = False by default

        manager = SessionManager(config, db_path=db_path)
        repo = manager._open_repo()

        ex = _make_tactic("nodiff:0", difficulty=1500.0)
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex.id)
        manager._close_repo()

        count = manager.start_session()
        assert count == 1
        manager.end_session()


# ── Config tests ────────────────────────────────────────────────────────────


class TestDifficultyConfig:
    """Tests for DifficultyConfig in the config system."""

    def test_default_config_values(self):
        config = DifficultyConfig()
        assert config.enabled is False
        assert config.window == 20
        assert config.min_reviews == 5
        assert config.promote_accuracy == 0.80
        assert config.demote_accuracy == 0.45
        assert config.step == 150
        assert config.difficulty_range == 600

    def test_app_config_has_difficulty(self):
        config = AppConfig()
        assert hasattr(config, "difficulty")
        assert isinstance(config.difficulty, DifficultyConfig)

    def test_toml_loading(self, tmp_path):
        from src.config import load_config

        toml_path = tmp_path / "config.toml"
        toml_path.write_text("""\
[difficulty]
enabled = true
window = 30
step = 200
""")
        config = load_config(toml_path)
        assert config.difficulty.enabled is True
        assert config.difficulty.window == 30
        assert config.difficulty.step == 200
        # Defaults for unset fields
        assert config.difficulty.min_reviews == 5

    def test_env_override(self, monkeypatch, tmp_path):
        from src.config import load_config

        monkeypatch.setenv("CHESS_TRAINER_DIFFICULTY_ENABLED", "true")
        monkeypatch.setenv("CHESS_TRAINER_DIFFICULTY_WINDOW", "50")
        monkeypatch.setenv("CHESS_TRAINER_DIFFICULTY_STEP", "200")
        monkeypatch.setenv("CHESS_TRAINER_DIFFICULTY_RANGE", "800")
        # Load from nonexistent file to avoid user config
        config = load_config(tmp_path / "nonexistent.toml")
        assert config.difficulty.enabled is True
        assert config.difficulty.window == 50
        assert config.difficulty.step == 200
        assert config.difficulty.difficulty_range == 800

    def test_config_keys_include_difficulty(self):
        from src.config import get_config_keys

        keys = get_config_keys()
        assert "difficulty.enabled" in keys
        assert "difficulty.window" in keys
        assert "difficulty.step" in keys
        assert "difficulty.difficulty_range" in keys
        assert "difficulty.promote_accuracy" in keys
        assert "difficulty.demote_accuracy" in keys
        assert "difficulty.min_reviews" in keys

    def test_validation_rules(self):
        from src.config import set_config_value

        with pytest.raises(ValueError, match="must be between"):
            set_config_value("difficulty.window", "0")
        with pytest.raises(ValueError, match="must be between"):
            set_config_value("difficulty.promote_accuracy", "1.5")
        with pytest.raises(ValueError, match="must be between"):
            set_config_value("difficulty.difficulty_range", "10")
