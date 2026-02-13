"""Tests for exercise bundles and Woodpecker method: model, store, session, CLI, web."""

from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from src.cli.app import app
from src.exercises import TacticExercise
from src.exercises.bundle import (
    BundleConfig,
    BundleProgress,
    CycleResult,
    ExerciseBundle,
    WoodpeckerCycle,
    generate_bundle_id,
    validate_slug,
)
from src.scheduling.fsrs import Rating
from src.storage import Repository
from src.storage.bundle_store import BundleStore
from src.training.woodpecker import WoodpeckerSession, WoodpeckerStats

runner = CliRunner()

SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tactic(
    id: str,
    tags: list[str] | None = None,
    source: str = "test",
) -> TacticExercise:
    return TacticExercise(
        id=id,
        fen=SAMPLE_FEN,
        tags=tags or [],
        source=source,
        difficulty=1500.0,
        solution=["g7g6"],
        themes=tags or [],
    )


def _seed_exercises(repo: Repository, count: int = 5) -> list[TacticExercise]:
    """Create `count` exercises in the repo."""
    exercises = [
        _make_tactic(f"ex:{i:03d}", tags=["fork"] if i % 2 == 0 else ["pin"])
        for i in range(1, count + 1)
    ]
    for ex in exercises:
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex.id)
    return exercises


def _make_bundle(
    slug: str = "test-bundle",
    exercise_ids: list[str] | None = None,
    woodpecker: bool = False,
    **kwargs,
) -> ExerciseBundle:
    config = BundleConfig(
        woodpecker_mode=woodpecker,
        **{
            k: v
            for k, v in kwargs.items()
            if k in ("pass_threshold", "shuffle", "time_limit_seconds")
        },
    )
    if woodpecker and "woodpecker_cycles" not in kwargs:
        config.woodpecker_cycles = [
            WoodpeckerCycle(cycle_number=1, rest_days=0),
            WoodpeckerCycle(cycle_number=2, rest_days=1, time_limit_seconds=60),
        ]
    return ExerciseBundle(
        id=generate_bundle_id(slug),
        name=kwargs.get("name", "Test Bundle"),
        description=kwargs.get("description", ""),
        exercise_ids=exercise_ids or [],
        config=config,
    )


# ===========================================================================
# Phase A: Model Tests
# ===========================================================================


class TestSlugValidation:
    def test_valid_slug(self):
        assert validate_slug("knight-forks") == "knight-forks"

    def test_slug_normalized_to_lowercase(self):
        assert validate_slug("Knight-Forks") == "knight-forks"

    def test_slug_stripped(self):
        assert validate_slug("  test  ") == "test"

    def test_slug_minimum_length(self):
        assert validate_slug("ab") == "ab"

    def test_slug_single_char_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            validate_slug("a")

    def test_slug_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_slug("")

    def test_slug_too_long_raises(self):
        with pytest.raises(ValueError, match="at most 64"):
            validate_slug("a" * 65)

    def test_slug_leading_hyphen_raises(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("-bad-slug")

    def test_slug_trailing_hyphen_raises(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("bad-slug-")

    def test_slug_special_chars_raises(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            validate_slug("bad slug!")

    def test_slug_with_digits(self):
        assert validate_slug("v2-drills") == "v2-drills"

    def test_slug_64_chars(self):
        slug = "a" * 64
        assert validate_slug(slug) == slug


class TestBundleId:
    def test_generate_bundle_id(self):
        assert generate_bundle_id("knight-forks") == "bundle:knight-forks"

    def test_slug_property(self):
        bundle = _make_bundle("my-test")
        assert bundle.slug == "my-test"


class TestBundleConfigSerialization:
    def test_default_config_roundtrip(self):
        config = BundleConfig()
        data = config.to_dict()
        restored = BundleConfig.from_dict(data)
        assert restored.woodpecker_mode is False
        assert restored.pass_threshold == 0.9
        assert restored.shuffle is False
        assert restored.woodpecker_cycles == []
        assert restored.time_limit_seconds is None

    def test_woodpecker_config_roundtrip(self):
        config = BundleConfig(
            woodpecker_mode=True,
            woodpecker_cycles=[
                WoodpeckerCycle(1, 0, None),
                WoodpeckerCycle(2, 3, 60),
            ],
            pass_threshold=0.85,
            shuffle=True,
            time_limit_seconds=120,
        )
        data = config.to_dict()
        restored = BundleConfig.from_dict(data)
        assert restored.woodpecker_mode is True
        assert restored.pass_threshold == 0.85
        assert restored.shuffle is True
        assert restored.time_limit_seconds == 120
        assert len(restored.woodpecker_cycles) == 2
        assert restored.woodpecker_cycles[1].time_limit_seconds == 60

    def test_from_dict_empty(self):
        config = BundleConfig.from_dict({})
        assert config.woodpecker_mode is False
        assert config.pass_threshold == 0.9


class TestExerciseBundleSerialization:
    def test_roundtrip(self):
        bundle = _make_bundle(exercise_ids=["ex:001", "ex:002"])
        data = bundle.to_dict()
        restored = ExerciseBundle.from_dict(data)
        assert restored.id == bundle.id
        assert restored.name == bundle.name
        assert restored.exercise_ids == ["ex:001", "ex:002"]
        assert restored.exercise_count == 2
        assert restored.slug == "test-bundle"

    def test_exercise_count(self):
        bundle = _make_bundle(exercise_ids=["a", "b", "c"])
        assert bundle.exercise_count == 3


class TestCycleResultSerialization:
    def test_roundtrip(self):
        now = datetime.now()
        result = CycleResult(
            cycle_number=1,
            accuracy=0.92,
            passed=True,
            started_at=now,
            completed_at=now + timedelta(minutes=30),
            time_limit_seconds=60,
            exercises_attempted=10,
            exercises_correct=9,
        )
        data = result.to_dict()
        restored = CycleResult.from_dict(data)
        assert restored.cycle_number == 1
        assert restored.accuracy == 0.92
        assert restored.passed is True
        assert restored.time_limit_seconds == 60
        assert restored.exercises_correct == 9


class TestBundleProgressSerialization:
    def test_roundtrip(self):
        now = datetime.now()
        progress = BundleProgress(
            bundle_id="bundle:test",
            current_cycle=2,
            cycle_started_at=now,
            exercises_attempted=5,
            exercises_correct=4,
            completed_cycles=[
                CycleResult(1, 0.9, True, now, now, None, 10, 9),
            ],
        )
        data = progress.to_dict()
        restored = BundleProgress.from_dict(data)
        assert restored.bundle_id == "bundle:test"
        assert restored.current_cycle == 2
        assert restored.exercises_attempted == 5
        assert len(restored.completed_cycles) == 1

    def test_cycle_accuracy(self):
        progress = BundleProgress(
            bundle_id="test",
            exercises_attempted=10,
            exercises_correct=8,
        )
        assert progress.cycle_accuracy == 0.8

    def test_cycle_accuracy_zero(self):
        progress = BundleProgress(bundle_id="test")
        assert progress.cycle_accuracy == 0.0

    def test_from_dict_defaults(self):
        progress = BundleProgress.from_dict({"bundle_id": "test"})
        assert progress.current_cycle == 1
        assert progress.exercises_attempted == 0
        assert progress.completed_cycles == []


# ===========================================================================
# Phase A: Storage Tests
# ===========================================================================


class TestBundleStore:
    def test_create_and_get(self, repo):
        bundle = _make_bundle(exercise_ids=["ex:001"])
        repo.bundles.create(bundle)
        found = repo.bundles.get(bundle.id)
        assert found is not None
        assert found.name == "Test Bundle"
        assert found.exercise_ids == ["ex:001"]

    def test_create_duplicate_raises(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        with pytest.raises(ValueError, match="already exists"):
            repo.bundles.create(bundle)

    def test_get_nonexistent(self, repo):
        assert repo.bundles.get("bundle:nope") is None

    def test_list_all_empty(self, repo):
        assert repo.bundles.list_all() == []

    def test_list_all_ordered_by_name(self, repo):
        repo.bundles.create(_make_bundle("zzz-bundle", name="Zzz"))
        repo.bundles.create(_make_bundle("aaa-bundle", name="Aaa"))
        bundles = repo.bundles.list_all()
        assert len(bundles) == 2
        assert bundles[0].name == "Aaa"
        assert bundles[1].name == "Zzz"

    def test_update(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        bundle.name = "Updated Name"
        bundle.exercise_ids = ["ex:001", "ex:002"]
        repo.bundles.update(bundle)
        found = repo.bundles.get(bundle.id)
        assert found.name == "Updated Name"
        assert found.exercise_ids == ["ex:001", "ex:002"]

    def test_delete(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        assert repo.bundles.delete(bundle.id) is True
        assert repo.bundles.get(bundle.id) is None

    def test_delete_nonexistent(self, repo):
        assert repo.bundles.delete("bundle:nope") is False

    def test_delete_cascades_progress(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        progress = BundleProgress(bundle_id=bundle.id, current_cycle=3)
        repo.bundles.save_progress(progress)
        repo.bundles.delete(bundle.id)
        assert repo.bundles.get_progress(bundle.id) is None

    def test_add_exercises(self, repo):
        exercises = _seed_exercises(repo, 3)
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        count = repo.bundles.add_exercises(bundle.id, [e.id for e in exercises])
        assert count == 3
        found = repo.bundles.get(bundle.id)
        assert len(found.exercise_ids) == 3

    def test_add_exercises_dedup(self, repo):
        bundle = _make_bundle(exercise_ids=["ex:001"])
        repo.bundles.create(bundle)
        count = repo.bundles.add_exercises(bundle.id, ["ex:001", "ex:002"])
        assert count == 1  # Only ex:002 is new
        found = repo.bundles.get(bundle.id)
        assert found.exercise_ids == ["ex:001", "ex:002"]

    def test_add_exercises_nonexistent_bundle(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.bundles.add_exercises("bundle:nope", ["ex:001"])

    def test_remove_exercises(self, repo):
        bundle = _make_bundle(exercise_ids=["ex:001", "ex:002", "ex:003"])
        repo.bundles.create(bundle)
        count = repo.bundles.remove_exercises(bundle.id, ["ex:002"])
        assert count == 1
        found = repo.bundles.get(bundle.id)
        assert found.exercise_ids == ["ex:001", "ex:003"]

    def test_remove_exercises_not_present(self, repo):
        bundle = _make_bundle(exercise_ids=["ex:001"])
        repo.bundles.create(bundle)
        count = repo.bundles.remove_exercises(bundle.id, ["ex:999"])
        assert count == 0

    def test_remove_exercises_nonexistent_bundle(self, repo):
        with pytest.raises(ValueError, match="not found"):
            repo.bundles.remove_exercises("bundle:nope", ["ex:001"])


class TestBundleProgress:
    def test_save_and_get_progress(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        progress = BundleProgress(
            bundle_id=bundle.id,
            current_cycle=2,
            exercises_attempted=10,
            exercises_correct=9,
        )
        repo.bundles.save_progress(progress)
        found = repo.bundles.get_progress(bundle.id)
        assert found is not None
        assert found.current_cycle == 2
        assert found.exercises_attempted == 10

    def test_get_progress_nonexistent(self, repo):
        assert repo.bundles.get_progress("bundle:nope") is None

    def test_save_progress_upsert(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        repo.bundles.save_progress(BundleProgress(bundle_id=bundle.id, current_cycle=1))
        repo.bundles.save_progress(BundleProgress(bundle_id=bundle.id, current_cycle=3))
        found = repo.bundles.get_progress(bundle.id)
        assert found.current_cycle == 3

    def test_save_progress_with_cycles(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        now = datetime.now()
        progress = BundleProgress(
            bundle_id=bundle.id,
            current_cycle=2,
            completed_cycles=[
                CycleResult(1, 0.95, True, now, now, None, 20, 19),
            ],
        )
        repo.bundles.save_progress(progress)
        found = repo.bundles.get_progress(bundle.id)
        assert len(found.completed_cycles) == 1
        assert found.completed_cycles[0].accuracy == 0.95

    def test_reset_progress(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)
        repo.bundles.save_progress(BundleProgress(bundle_id=bundle.id, current_cycle=5))
        repo.bundles.reset_progress(bundle.id)
        assert repo.bundles.get_progress(bundle.id) is None


class TestRepositoryBundleProperty:
    def test_lazy_init(self, repo):
        bundles = repo.bundles
        assert bundles is not None
        assert isinstance(bundles, BundleStore)

    def test_reuses_instance(self, repo):
        b1 = repo.bundles
        b2 = repo.bundles
        assert b1 is b2

    def test_close_resets(self):
        with Repository() as repo:
            _ = repo.bundles
            repo.close()
            assert repo._bundles is None


# ===========================================================================
# Phase B: WoodpeckerSession Tests
# ===========================================================================


class TestWoodpeckerSession:
    def test_start_builds_queue(self, repo):
        exercises = _seed_exercises(repo, 3)
        bundle = _make_bundle(exercise_ids=[e.id for e in exercises])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        assert session.remaining == 3

    def test_next_returns_exercises(self, repo):
        exercises = _seed_exercises(repo, 2)
        bundle = _make_bundle(exercise_ids=[e.id for e in exercises])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()

        ex1 = session.next()
        assert ex1 is not None
        ex2 = session.next()
        assert ex2 is not None
        ex3 = session.next()
        assert ex3 is None

    def test_next_skips_deleted_exercises(self, repo):
        exercises = _seed_exercises(repo, 2)
        bundle = _make_bundle(exercise_ids=[exercises[0].id, "deleted:001", exercises[1].id])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        assert session.remaining == 3  # Queue has 3 IDs

        ex1 = session.next()
        assert ex1 is not None
        ex2 = session.next()
        assert ex2 is not None
        assert session.next() is None  # deleted one skipped

    def test_shuffle(self, repo):
        exercises = _seed_exercises(repo, 10)
        bundle = _make_bundle(
            exercise_ids=[e.id for e in exercises],
            shuffle=True,
        )
        repo.bundles.create(bundle)

        # Run multiple times to check shuffle produces different orders
        orders = set()
        for _ in range(5):
            session = WoodpeckerSession(repo, bundle)
            session.start()
            order = []
            while True:
                ex = session.next()
                if ex is None:
                    break
                order.append(ex.id)
                session.submit([], 0)
                session.rate(Rating.AGAIN)
            orders.add(tuple(order))

        # With 10 exercises, at least 2 different orders across 5 runs is expected
        assert len(orders) >= 2

    def test_submit_correct(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(exercise_ids=[e.id for e in exercises])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        exercise = session.next()
        solution_moves = exercise.get_solution()

        # Submit the correct answer
        result, over_time = session.submit(solution_moves, 1000)
        assert result.correct is True
        assert over_time is False
        assert session.stats.correct == 1

    def test_submit_incorrect(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(exercise_ids=[e.id for e in exercises])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        session.next()

        result, over_time = session.submit([], 500)
        assert result.correct is False
        assert session.stats.incorrect == 1

    def test_submit_over_time(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(
            exercise_ids=[e.id for e in exercises],
            time_limit_seconds=5,
        )
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        exercise = session.next()
        solution = exercise.get_solution()

        # Submit correct but over time (5s limit, 10s taken)
        result, over_time = session.submit(solution, 10_000)
        assert result.correct is True  # The answer itself is correct
        assert over_time is True  # But it's over the time limit
        assert session.stats.over_time == 1

    def test_submit_no_active_exercise_raises(self, repo):
        bundle = _make_bundle()
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        with pytest.raises(RuntimeError, match="No active exercise"):
            session.submit([], 0)

    def test_time_limit_from_cycle_config(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(
            exercise_ids=[e.id for e in exercises],
            woodpecker=True,
        )
        # Cycle 1 has no time limit, cycle 2 has 60s
        repo.bundles.create(bundle)

        progress = BundleProgress(bundle_id=bundle.id, current_cycle=1)
        session = WoodpeckerSession(repo, bundle, progress)
        assert session.time_limit is None

        progress2 = BundleProgress(bundle_id=bundle.id, current_cycle=2)
        session2 = WoodpeckerSession(repo, bundle, progress2)
        assert session2.time_limit == 60

    def test_rate_updates_fsrs(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(exercise_ids=[e.id for e in exercises])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        exercise = session.next()
        session.submit(exercise.get_solution(), 1000)
        session.rate(Rating.GOOD)

        # Card should be updated in DB
        card = repo.cards.get(exercise.id)
        assert card is not None
        assert card.reps > 0 or card.stability > 0

    def test_end_cycle_pass(self, repo):
        exercises = _seed_exercises(repo, 2)
        bundle = _make_bundle(
            exercise_ids=[e.id for e in exercises],
            pass_threshold=0.5,
        )
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()

        # Get both exercises, submit correct for both
        for _ in range(2):
            ex = session.next()
            session.submit(ex.get_solution(), 1000)
            session.rate(Rating.GOOD)

        result = session.end_cycle()
        assert result.passed is True
        assert result.accuracy == 1.0
        assert result.cycle_number == 1
        assert session.progress.current_cycle == 2  # Advanced

    def test_end_cycle_fail(self, repo):
        exercises = _seed_exercises(repo, 2)
        bundle = _make_bundle(
            exercise_ids=[e.id for e in exercises],
            pass_threshold=0.9,
        )
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()

        # Get first exercise, submit incorrect
        session.next()
        session.submit([], 1000)
        session.rate(Rating.AGAIN)

        # Get second, submit correct
        ex = session.next()
        session.submit(ex.get_solution(), 1000)
        session.rate(Rating.GOOD)

        result = session.end_cycle()
        assert result.passed is False
        assert result.accuracy == 0.5
        assert session.progress.current_cycle == 1  # NOT advanced

    def test_end_cycle_saves_progress(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(
            exercise_ids=[e.id for e in exercises],
            pass_threshold=0.5,
        )
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        ex = session.next()
        session.submit(ex.get_solution(), 1000)
        session.rate(Rating.GOOD)
        session.end_cycle()

        # Check progress in DB
        progress = repo.bundles.get_progress(bundle.id)
        assert progress is not None
        assert len(progress.completed_cycles) == 1

    def test_auto_rate_correct(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(exercise_ids=[e.id for e in exercises])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        ex = session.next()
        result, over_time = session.submit(ex.get_solution(), 1000)
        rating = session.auto_rate_woodpecker(result, over_time)
        assert rating in (Rating.GOOD, Rating.EASY)

    def test_auto_rate_over_time(self, repo):
        exercises = _seed_exercises(repo, 1)
        bundle = _make_bundle(exercise_ids=[e.id for e in exercises])
        repo.bundles.create(bundle)

        session = WoodpeckerSession(repo, bundle)
        session.start()
        ex = session.next()
        result, _ = session.submit(ex.get_solution(), 1000)
        rating = session.auto_rate_woodpecker(result, over_time=True)
        assert rating == Rating.HARD

    def test_stats_accuracy(self):
        stats = WoodpeckerStats(
            bundle_id="test",
            cycle_number=1,
            time_limit_seconds=None,
            correct=8,
            incorrect=1,
            over_time=1,
        )
        assert stats.accuracy == 0.8  # 8/10 (over_time counts as incorrect)
        assert stats.lenient_accuracy == 0.9  # (8+1)/10

    def test_stats_accuracy_zero(self):
        stats = WoodpeckerStats(
            bundle_id="test",
            cycle_number=1,
            time_limit_seconds=None,
        )
        assert stats.accuracy == 0.0
        assert stats.lenient_accuracy == 0.0


# ===========================================================================
# Phase B: CLI Tests
# ===========================================================================


class TestBundleCLICreate:
    def test_create_basic(self):
        result = runner.invoke(app, ["bundle", "create", "my-test", "--db", ":memory:"])
        assert result.exit_code == 0
        assert "Created bundle" in result.output

    def test_create_with_name(self):
        result = runner.invoke(
            app, ["bundle", "create", "my-test", "--name", "My Drills", "--db", ":memory:"]
        )
        assert result.exit_code == 0
        assert "My Drills" in result.output

    def test_create_woodpecker(self):
        result = runner.invoke(
            app, ["bundle", "create", "wp-test", "--woodpecker", "--db", ":memory:"]
        )
        assert result.exit_code == 0
        assert "Woodpecker" in result.output

    def test_create_invalid_slug(self):
        result = runner.invoke(app, ["bundle", "create", "!", "--db", ":memory:"])
        assert result.exit_code == 1

    def test_create_duplicate(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "dup", "--db", db])
        result = runner.invoke(app, ["bundle", "create", "dup", "--db", db])
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestBundleCLIList:
    def test_list_empty(self):
        result = runner.invoke(app, ["bundle", "list", "--db", ":memory:"])
        assert result.exit_code == 0
        assert "No bundles" in result.output

    def test_list_with_bundles(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "one", "--db", db])
        runner.invoke(app, ["bundle", "create", "two", "--db", db])
        result = runner.invoke(app, ["bundle", "list", "--db", db])
        assert result.exit_code == 0
        assert "one" in result.output
        assert "two" in result.output


class TestBundleCLIShow:
    def test_show(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "show-test", "--name", "Show Test", "--db", db])
        result = runner.invoke(app, ["bundle", "show", "show-test", "--db", db])
        assert result.exit_code == 0
        assert "Show Test" in result.output

    def test_show_not_found(self):
        result = runner.invoke(app, ["bundle", "show", "nope", "--db", ":memory:"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestBundleCLIAddRemove:
    def test_add_exercises(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "add-test", "--db", db])
        result = runner.invoke(app, ["bundle", "add", "add-test", "ex:001", "ex:002", "--db", db])
        assert result.exit_code == 0
        assert "Added 2" in result.output

    def test_remove_exercises(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "rm-test", "--db", db])
        runner.invoke(app, ["bundle", "add", "rm-test", "ex:001", "ex:002", "--db", db])
        result = runner.invoke(app, ["bundle", "remove", "rm-test", "ex:001", "--db", db])
        assert result.exit_code == 0
        assert "Removed 1" in result.output

    def test_add_nonexistent_bundle(self):
        result = runner.invoke(app, ["bundle", "add", "nope", "ex:001", "--db", ":memory:"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestBundleCLIDelete:
    def test_delete(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "del-test", "--db", db])
        result = runner.invoke(app, ["bundle", "delete", "del-test", "--force", "--db", db])
        assert result.exit_code == 0
        assert "Deleted" in result.output

    def test_delete_not_found(self):
        result = runner.invoke(app, ["bundle", "delete", "nope", "--force", "--db", ":memory:"])
        assert result.exit_code == 1


class TestBundleCLIImport:
    def test_import_by_tag(self, tmp_path):
        db = str(tmp_path / "test.db")
        # Create bundle
        runner.invoke(app, ["bundle", "create", "imp-test", "--db", db])
        # Seed exercises with tags
        with Repository(db) as repo:
            exercises = _seed_exercises(repo, 3)
            from src.storage.tag_store import EntityType, TagSource

            for ex in exercises:
                repo.tags.add_tags(EntityType.EXERCISE, ex.id, ex.tags, TagSource.SYSTEM)
        # Import by tag
        result = runner.invoke(app, ["bundle", "import", "imp-test", "--tag", "fork", "--db", db])
        assert result.exit_code == 0
        assert "Added" in result.output

    def test_import_no_matches(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "imp-test2", "--db", db])
        result = runner.invoke(
            app, ["bundle", "import", "imp-test2", "--tag", "nonexistent", "--db", db]
        )
        assert result.exit_code == 0
        assert "No exercises found" in result.output


class TestBundleCLIProgress:
    def test_progress_no_data(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "prog-test", "--db", db])
        result = runner.invoke(app, ["bundle", "progress", "prog-test", "--db", db])
        assert result.exit_code == 0
        assert "No training progress" in result.output

    def test_progress_with_data(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "prog-test2", "--db", db])
        # Seed progress
        with Repository(db) as repo:
            now = datetime.now()
            progress = BundleProgress(
                bundle_id="bundle:prog-test2",
                current_cycle=2,
                completed_cycles=[
                    CycleResult(1, 0.95, True, now, now, None, 20, 19),
                ],
            )
            repo.bundles.save_progress(progress)
        result = runner.invoke(app, ["bundle", "progress", "prog-test2", "--db", db])
        assert result.exit_code == 0
        assert "Cycle" in result.output


class TestBundleCLIReset:
    def test_reset(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "rst-test", "--db", db])
        with Repository(db) as repo:
            repo.bundles.save_progress(BundleProgress(bundle_id="bundle:rst-test", current_cycle=3))
        result = runner.invoke(app, ["bundle", "reset", "rst-test", "--force", "--db", db])
        assert result.exit_code == 0
        assert "Reset" in result.output


class TestBundleCLITrain:
    def test_train_empty_bundle(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(app, ["bundle", "create", "train-test", "--db", db])
        result = runner.invoke(app, ["bundle", "train", "train-test", "--db", db])
        assert result.exit_code == 0
        assert "no exercises" in result.output

    def test_train_not_found(self):
        result = runner.invoke(app, ["bundle", "train", "nope", "--db", ":memory:"])
        assert result.exit_code == 1
        assert "not found" in result.output


# ===========================================================================
# Phase B: Config Tests
# ===========================================================================


class TestBundlesConfig:
    def test_default_config(self):
        from src.config import AppConfig

        config = AppConfig()
        assert config.bundles.default_pass_threshold == 0.9
        assert config.bundles.default_shuffle is False

    def test_config_from_toml(self, tmp_path):
        from src.config import load_config

        config_path = tmp_path / "config.toml"
        config_path.write_text("[bundles]\ndefault_pass_threshold = 0.75\ndefault_shuffle = true\n")
        config = load_config(config_path)
        assert config.bundles.default_pass_threshold == 0.75
        assert config.bundles.default_shuffle is True

    def test_config_validation_range(self):
        from src.config import _validate_value

        _validate_value("bundles.default_pass_threshold", 0.5)  # OK
        with pytest.raises(ValueError):
            _validate_value("bundles.default_pass_threshold", 1.5)

    def test_config_in_default_config(self):
        from src.config import generate_default_config

        text = generate_default_config()
        assert "bundles" in text
        assert "default_pass_threshold" in text


# ===========================================================================
# Phase C: Web Tests
# ===========================================================================


class TestBundleWeb:
    @pytest.fixture
    def web_client(self):
        """TestClient for the web app."""
        from src.config import AppConfig
        from src.web import create_app

        config = AppConfig()
        config.database.path = ":memory:"
        web_app = create_app(config)
        from starlette.testclient import TestClient

        client = TestClient(web_app)
        return client

    def test_bundles_page(self, web_client):
        resp = web_client.get("/bundles")
        assert resp.status_code == 200
        assert "Bundles" in resp.text

    def test_api_bundles_list_empty(self, web_client):
        resp = web_client.get("/api/bundles")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bundles"] == []

    def test_api_bundles_create(self, web_client):
        resp = web_client.post(
            "/api/bundles",
            json={"slug": "web-test", "name": "Web Test Bundle"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"

    def test_api_bundles_create_invalid_slug(self, web_client):
        resp = web_client.post("/api/bundles", json={"slug": "!"})
        assert resp.status_code == 400

    def test_api_bundles_create_duplicate(self, web_client):
        web_client.post("/api/bundles", json={"slug": "dup-web"})
        resp = web_client.post("/api/bundles", json={"slug": "dup-web"})
        assert resp.status_code == 409

    def test_api_bundles_detail(self, web_client):
        web_client.post("/api/bundles", json={"slug": "detail-test", "name": "Detail"})
        resp = web_client.get("/api/bundles/detail-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Detail"

    def test_api_bundles_detail_not_found(self, web_client):
        resp = web_client.get("/api/bundles/nope")
        assert resp.status_code == 404

    def test_api_bundles_delete(self, web_client):
        web_client.post("/api/bundles", json={"slug": "del-web"})
        resp = web_client.delete("/api/bundles/del-web")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_api_bundles_delete_not_found(self, web_client):
        resp = web_client.delete("/api/bundles/nope")
        assert resp.status_code == 404

    def test_api_bundles_train_empty(self, web_client):
        web_client.post("/api/bundles", json={"slug": "train-web"})
        resp = web_client.post("/api/bundles/train-web/train")
        assert resp.status_code == 400
        assert "no exercises" in resp.json()["error"].lower()

    def test_api_bundles_progress(self, web_client):
        web_client.post("/api/bundles", json={"slug": "prog-web"})
        resp = web_client.get("/api/bundles/prog-web/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_cycle"] == 1
        assert data["cycles"] == []

    def test_api_bundles_train_not_found(self, web_client):
        resp = web_client.post("/api/bundles/nonexistent/train")
        assert resp.status_code == 400
