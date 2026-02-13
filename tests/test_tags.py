"""Tests for the custom tags feature: TagStore, migration, training filter, CLI, web, analytics."""

import json
from datetime import datetime, timedelta

import pytest
from typer.testing import CliRunner

from src.cli.app import app
from src.exercises import TacticExercise
from src.storage import Repository
from src.storage.tag_store import EntityType, TagSource, TagStore

runner = CliRunner()

SAMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tactic(
    id: str,
    tags: list[str] | None = None,
    source: str = "test",
    difficulty: float = 1500.0,
) -> TacticExercise:
    return TacticExercise(
        id=id,
        fen=SAMPLE_FEN,
        tags=tags or [],
        source=source,
        difficulty=difficulty,
        solution=["g7g6"],
        themes=tags or [],
    )


def _seed_exercises(repo: Repository, count: int = 3) -> list[TacticExercise]:
    """Create `count` exercises with varied tags in the repo."""
    exercises = [
        _make_tactic("ex:001", tags=["fork", "tactic", "short"]),
        _make_tactic("ex:002", tags=["pin", "tactic"]),
        _make_tactic("ex:003", tags=["endgame", "rook"]),
    ][:count]
    for ex in exercises:
        repo.exercises.add(ex)
        repo.cards.get_or_create(ex.id)
    return exercises


# ---------------------------------------------------------------------------
# TagStore normalization
# ---------------------------------------------------------------------------


class TestTagNormalization:
    def test_normalize_lowercase(self):
        assert TagStore._normalize_tag("Fork") == "fork"

    def test_normalize_strip(self):
        assert TagStore._normalize_tag("  pin  ") == "pin"

    def test_normalize_lowercase_and_strip(self):
        assert TagStore._normalize_tag("  TACTIC  ") == "tactic"

    def test_normalize_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            TagStore._normalize_tag("")

    def test_normalize_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            TagStore._normalize_tag("   ")

    def test_normalize_special_characters(self):
        assert TagStore._normalize_tag("my-tag_v2") == "my-tag_v2"


# ---------------------------------------------------------------------------
# TagStore CRUD
# ---------------------------------------------------------------------------


class TestTagStoreCRUD:
    def test_add_single_tag(self, repo):
        store = repo.tags
        count = store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        assert count == 1
        assert store.get_tags(EntityType.EXERCISE, "ex:001") == ["fork"]

    def test_add_multiple_tags(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "pin", "sacrifice"])
        tags = store.get_tags(EntityType.EXERCISE, "ex:001")
        assert tags == ["fork", "pin", "sacrifice"]

    def test_add_tags_idempotent(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        tags = store.get_tags(EntityType.EXERCISE, "ex:001")
        assert tags == ["fork"]

    def test_add_tags_normalizes(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["  FORK  ", "Pin"])
        tags = store.get_tags(EntityType.EXERCISE, "ex:001")
        assert tags == ["fork", "pin"]

    def test_add_tags_skips_empty(self, repo):
        store = repo.tags
        count = store.add_tags(EntityType.EXERCISE, "ex:001", ["", "fork", "  "])
        assert count == 1  # Only "fork" is valid
        tags = store.get_tags(EntityType.EXERCISE, "ex:001")
        assert tags == ["fork"]

    def test_add_tags_with_source(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"], TagSource.SYSTEM)
        store.add_tags(EntityType.EXERCISE, "ex:001", ["my-tag"], TagSource.USER)
        system = store.get_tags(EntityType.EXERCISE, "ex:001", source=TagSource.SYSTEM)
        user = store.get_tags(EntityType.EXERCISE, "ex:001", source=TagSource.USER)
        assert system == ["fork"]
        assert user == ["my-tag"]

    def test_add_tags_dedup_in_batch(self, repo):
        store = repo.tags
        count = store.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "FORK", " fork "])
        assert count == 1

    def test_remove_tags(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "pin"])
        removed = store.remove_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        assert removed == 1
        assert store.get_tags(EntityType.EXERCISE, "ex:001") == ["pin"]

    def test_remove_nonexistent_tag(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        removed = store.remove_tags(EntityType.EXERCISE, "ex:001", ["nonexistent"])
        assert removed == 0
        assert store.get_tags(EntityType.EXERCISE, "ex:001") == ["fork"]

    def test_remove_multiple_tags(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "pin", "sacrifice"])
        removed = store.remove_tags(EntityType.EXERCISE, "ex:001", ["fork", "sacrifice"])
        assert removed == 2
        assert store.get_tags(EntityType.EXERCISE, "ex:001") == ["pin"]

    def test_get_tags_empty(self, repo):
        store = repo.tags
        assert store.get_tags(EntityType.EXERCISE, "nonexistent") == []

    def test_get_tags_sorted(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["zebra", "alpha", "middle"])
        tags = store.get_tags(EntityType.EXERCISE, "ex:001")
        assert tags == ["alpha", "middle", "zebra"]


# ---------------------------------------------------------------------------
# TagStore queries
# ---------------------------------------------------------------------------


class TestTagStoreQueries:
    def test_find_by_tags_and(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "tactic"])
        store.add_tags(EntityType.EXERCISE, "ex:002", ["fork"])
        # AND: must have both
        result = store.find_by_tags(EntityType.EXERCISE, ["fork", "tactic"], match_all=True)
        assert result == ["ex:001"]

    def test_find_by_tags_or(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        store.add_tags(EntityType.EXERCISE, "ex:002", ["pin"])
        store.add_tags(EntityType.EXERCISE, "ex:003", ["endgame"])
        # OR: either
        result = store.find_by_tags(EntityType.EXERCISE, ["fork", "pin"], match_all=False)
        assert sorted(result) == ["ex:001", "ex:002"]

    def test_find_by_tags_no_match(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        result = store.find_by_tags(EntityType.EXERCISE, ["nonexistent"])
        assert result == []

    def test_find_by_tags_empty_input(self, repo):
        store = repo.tags
        result = store.find_by_tags(EntityType.EXERCISE, [])
        assert result == []

    def test_list_all_tags(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "tactic"])
        store.add_tags(EntityType.EXERCISE, "ex:002", ["fork", "pin"])
        all_tags = store.list_all_tags()
        # fork appears 2x, others 1x
        assert all_tags[0].tag == "fork"
        assert all_tags[0].count == 2

    def test_list_all_tags_with_type_filter(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        store.add_tags(EntityType.OPENING, "open:001", ["sicilian"])
        exercise_tags = store.list_all_tags(entity_type=EntityType.EXERCISE)
        assert len(exercise_tags) == 1
        assert exercise_tags[0].tag == "fork"

    def test_list_all_tags_empty(self, repo):
        store = repo.tags
        assert store.list_all_tags() == []

    def test_search_tags(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "pin", "pinned-piece"])
        matches = store.search_tags("pin")
        tag_names = [t.tag for t in matches]
        assert "pin" in tag_names
        assert "pinned-piece" in tag_names
        assert "fork" not in tag_names

    def test_search_tags_no_match(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        assert store.search_tags("zzz") == []


# ---------------------------------------------------------------------------
# Tag migration (backfill from JSON)
# ---------------------------------------------------------------------------


class TestTagMigration:
    def test_fresh_schema_no_migration(self):
        """Empty DB: migration runs but adds nothing."""
        with Repository() as repo:
            count = repo.conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
            assert count == 0

    def test_backfill_from_json(self, tmp_path):
        """Exercises with JSON tags get backfilled into tags table on open."""
        db_path = tmp_path / "migrate.db"
        # First: create a DB *without* tags table, add exercises
        import duckdb

        conn = duckdb.connect(str(db_path))
        conn.execute("""
            CREATE TABLE exercises (
                id VARCHAR PRIMARY KEY,
                exercise_type VARCHAR NOT NULL,
                fen VARCHAR NOT NULL,
                tags JSON,
                source VARCHAR,
                source_url VARCHAR,
                difficulty DOUBLE,
                created_at TIMESTAMP,
                metadata JSON,
                type_data JSON
            )
        """)
        conn.execute(
            "INSERT INTO exercises VALUES (?, 'TACTIC', ?, ?, 'test', NULL, 1500.0, CURRENT_TIMESTAMP, '{}', '{}')",
            ["ex:001", SAMPLE_FEN, json.dumps(["fork", "Pin"])],
        )
        conn.execute(
            "INSERT INTO exercises VALUES (?, 'TACTIC', ?, ?, 'test', NULL, 1500.0, CURRENT_TIMESTAMP, '{}', '{}')",
            ["ex:002", SAMPLE_FEN, json.dumps(["fork"])],
        )
        conn.close()

        # Now open with Repository — tags table + migration should happen
        with Repository(db_path) as repo:
            tags = repo.tags.get_tags(EntityType.EXERCISE, "ex:001")
            assert "fork" in tags
            assert "pin" in tags  # normalized to lowercase

            tags2 = repo.tags.get_tags(EntityType.EXERCISE, "ex:002")
            assert tags2 == ["fork"]

    def test_migration_idempotent(self, tmp_path):
        """Running migration twice doesn't duplicate tags."""
        db_path = tmp_path / "idempotent.db"
        # Create DB with exercises
        with Repository(db_path) as repo:
            ex = _make_tactic("ex:001", tags=["fork", "pin"])
            repo.exercises.add(ex)

        # Manually clear tags to force re-migration
        import duckdb

        conn = duckdb.connect(str(db_path))
        conn.execute("DELETE FROM tags")
        conn.close()

        # Re-open — migration runs again
        with Repository(db_path) as repo:
            tags = repo.tags.get_tags(EntityType.EXERCISE, "ex:001")
            assert sorted(tags) == ["fork", "pin"]

    def test_migration_skips_empty_tags(self, tmp_path):
        """Exercises with empty or null tags don't produce tags."""
        db_path = tmp_path / "empty_tags.db"
        with Repository(db_path) as repo:
            ex = _make_tactic("ex:001", tags=[])
            repo.exercises.add(ex)

        # Re-open
        with Repository(db_path) as repo:
            tags = repo.tags.get_tags(EntityType.EXERCISE, "ex:001")
            assert tags == []


# ---------------------------------------------------------------------------
# Repository tags property
# ---------------------------------------------------------------------------


class TestRepositoryTagsProperty:
    def test_lazy_init(self, repo):
        assert repo._tags is None
        _ = repo.tags
        assert repo._tags is not None

    def test_connection_sharing(self, repo):
        """Tags store shares the same connection as exercises."""
        assert repo.tags.conn is repo.exercises.conn

    def test_close_cleanup(self, repo):
        _ = repo.tags
        repo.close()
        assert repo._tags is None


# ---------------------------------------------------------------------------
# Training session tag filtering
# ---------------------------------------------------------------------------


class TestTrainingSessionTagFilter:
    def test_include_tags_filters_queue(self, repo):
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        # Tag ex:001 with "my-set"
        repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["my-set"])

        config = SessionConfig(include_tags=["my-set"])
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 1

        ex = session.next()
        assert ex is not None
        assert ex.id == "ex:001"

    def test_exclude_tags_filters_queue(self, repo):
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["skip-me"])

        config = SessionConfig(exclude_tags=["skip-me"])
        session = TrainingSession(repo, config)
        session.start()
        # ex:001 excluded, ex:002 and ex:003 remain
        assert session.remaining == 2

    def test_include_and_exclude_combined(self, repo):
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["study"])
        repo.tags.add_tags(EntityType.EXERCISE, "ex:002", ["study", "hard"])
        repo.tags.add_tags(EntityType.EXERCISE, "ex:003", ["study"])

        config = SessionConfig(include_tags=["study"], exclude_tags=["hard"])
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 2  # ex:001 and ex:003

    def test_include_no_matches(self, repo):
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        config = SessionConfig(include_tags=["nonexistent"])
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 0

    def test_no_tag_filter(self, repo):
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        config = SessionConfig()
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 3

    def test_tag_filter_with_type_filter(self, repo):
        """Tag filter works alongside exercise_type filter."""
        from src.exercises import ExerciseType
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["study"])
        repo.tags.add_tags(EntityType.EXERCISE, "ex:002", ["study"])

        config = SessionConfig(
            exercise_types=[ExerciseType.TACTIC],
            include_tags=["study"],
        )
        session = TrainingSession(repo, config)
        session.start()
        # All are TACTIC with "study" => ex:001 and ex:002
        assert session.remaining == 2

    def test_include_or_logic(self, repo):
        """Include uses OR logic: exercise matches if it has ANY of the tags."""
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["fork-theme"])
        repo.tags.add_tags(EntityType.EXERCISE, "ex:002", ["pin-theme"])

        config = SessionConfig(include_tags=["fork-theme", "pin-theme"])
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 2

    def test_exclude_or_logic(self, repo):
        """Exclude uses OR logic: exercise is excluded if it has ANY of the tags."""
        from src.training import SessionConfig, TrainingSession

        _seed_exercises(repo)
        repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["a"])
        repo.tags.add_tags(EntityType.EXERCISE, "ex:002", ["b"])

        config = SessionConfig(exclude_tags=["a", "b"])
        session = TrainingSession(repo, config)
        session.start()
        assert session.remaining == 1  # Only ex:003


# ---------------------------------------------------------------------------
# CLI tag commands
# ---------------------------------------------------------------------------


class TestTagCLI:
    def test_tag_add(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            repo.exercises.add(_make_tactic("ex:001"))

        result = runner.invoke(app, ["tag", "add", "ex:001", "my-tag", "--db", str(db)])
        assert result.exit_code == 0
        assert "Added" in result.output

        with Repository(db) as repo:
            assert "my-tag" in repo.tags.get_tags(EntityType.EXERCISE, "ex:001")

    def test_tag_add_nonexistent_exercise(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as _:
            pass  # Init DB
        result = runner.invoke(app, ["tag", "add", "ex:999", "my-tag", "--db", str(db)])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_tag_remove(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            repo.exercises.add(_make_tactic("ex:001"))
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["my-tag", "other"])

        result = runner.invoke(app, ["tag", "remove", "ex:001", "my-tag", "--db", str(db)])
        assert result.exit_code == 0
        assert "Removed" in result.output

        with Repository(db) as repo:
            assert "my-tag" not in repo.tags.get_tags(EntityType.EXERCISE, "ex:001")
            assert "other" in repo.tags.get_tags(EntityType.EXERCISE, "ex:001")

    def test_tag_list(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            repo.exercises.add(_make_tactic("ex:001"))
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "pin"])

        result = runner.invoke(app, ["tag", "list", "--db", str(db)])
        assert result.exit_code == 0
        assert "fork" in result.output
        assert "pin" in result.output

    def test_tag_list_empty(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as _:
            pass
        result = runner.invoke(app, ["tag", "list", "--db", str(db)])
        assert result.exit_code == 0
        assert "No tags" in result.output

    def test_tag_show(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            repo.exercises.add(_make_tactic("ex:001"))
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["fork"], TagSource.SYSTEM)
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["my-tag"], TagSource.USER)

        result = runner.invoke(app, ["tag", "show", "ex:001", "--db", str(db)])
        assert result.exit_code == 0
        assert "my-tag" in result.output
        assert "fork" in result.output

    def test_tag_show_empty(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as _:
            pass
        result = runner.invoke(app, ["tag", "show", "ex:999", "--db", str(db)])
        assert result.exit_code == 0
        assert "No tags" in result.output

    def test_tag_search(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            repo.exercises.add(_make_tactic("ex:001"))
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["fork", "pin", "pinned-piece"])

        result = runner.invoke(app, ["tag", "search", "pin", "--db", str(db)])
        assert result.exit_code == 0
        assert "pin" in result.output
        assert "pinned-piece" in result.output

    def test_tag_search_no_match(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            repo.exercises.add(_make_tactic("ex:001"))
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])

        result = runner.invoke(app, ["tag", "search", "zzz", "--db", str(db)])
        assert result.exit_code == 0
        assert "No tags" in result.output

    def test_tag_add_invalid_type(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as _:
            pass
        result = runner.invoke(
            app, ["tag", "add", "ex:001", "my-tag", "--type", "invalid", "--db", str(db)]
        )
        assert result.exit_code != 0
        assert "Invalid type" in result.output

    def test_tag_list_with_source_filter(self, tmp_path):
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            repo.exercises.add(_make_tactic("ex:001"))
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["fork"], TagSource.SYSTEM)
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["my-tag"], TagSource.USER)

        result = runner.invoke(app, ["tag", "list", "--source", "user", "--db", str(db)])
        assert result.exit_code == 0
        assert "my-tag" in result.output
        # System tag should not appear with user source filter
        # (fork is a system tag in this context)


# ---------------------------------------------------------------------------
# CLI train --tag / --exclude-tag
# ---------------------------------------------------------------------------


class TestTrainWithTags:
    def test_train_tag_filters_session(self, tmp_path):
        """--tag limits the queue to matching exercises."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo)
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["study"])

        # Provide enough input for: move prompt (empty=give up) + rating override + continue prompt
        result = runner.invoke(app, ["train", "--tag", "study", "--db", str(db)], input="\n\nn\n")
        assert result.exit_code == 0
        assert "1 cards" in result.output  # Only 1 card matched

    def test_train_exclude_tag_filters_session(self, tmp_path):
        """--exclude-tag removes matching exercises from the queue."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo)
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["skip"])
            repo.tags.add_tags(EntityType.EXERCISE, "ex:002", ["skip"])
            repo.tags.add_tags(EntityType.EXERCISE, "ex:003", ["skip"])

        result = runner.invoke(app, ["train", "--exclude-tag", "skip", "--db", str(db)], input="\n")
        assert result.exit_code == 0
        assert "No cards due" in result.output  # All excluded

    def test_train_tag_no_match_shows_empty(self, tmp_path):
        """--tag with no matching exercises shows empty queue message."""
        db = tmp_path / "test.db"
        with Repository(db) as repo:
            _seed_exercises(repo)

        result = runner.invoke(app, ["train", "--tag", "nonexistent", "--db", str(db)], input="\n")
        assert result.exit_code == 0
        assert "No cards due" in result.output


# ---------------------------------------------------------------------------
# Web integration
# ---------------------------------------------------------------------------


class TestTagWeb:
    @pytest.fixture
    def web_app(self, tmp_path):
        from src.config import AppConfig
        from src.web import create_app

        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")
        return create_app(config)

    @pytest.fixture
    def seeded_web(self, web_app, tmp_path):
        from fastapi.testclient import TestClient

        with Repository(tmp_path / "test.db") as repo:
            _seed_exercises(repo)
            repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["study"])
        return TestClient(web_app)

    def test_session_start_with_tags(self, seeded_web):
        res = seeded_web.post(
            "/api/session/start",
            json={"include_tags": ["study"]},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["queue_size"] == 1  # Only ex:001 has "study"

    def test_session_start_without_tags(self, seeded_web):
        res = seeded_web.post("/api/session/start", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["queue_size"] == 3  # All exercises

    def test_train_page_has_tags_input(self, web_app):
        from fastapi.testclient import TestClient

        client = TestClient(web_app)
        res = client.get("/train")
        assert res.status_code == 200
        assert 'id="include-tags"' in res.text

    def test_training_js_sends_tags(self, web_app):
        from fastapi.testclient import TestClient

        client = TestClient(web_app)
        res = client.get("/static/js/training.js")
        assert res.status_code == 200
        assert "include_tags" in res.text


# ---------------------------------------------------------------------------
# Analytics with tags table
# ---------------------------------------------------------------------------


class TestAnalyticsWithTags:
    def _seed_analytics(self, repo: Repository) -> None:
        """Seed data with exercises, cards, review history, and tags."""
        exercises = [
            ("tac:001", "TACTIC", ["fork", "pin"], 1500.0),
            ("tac:002", "TACTIC", ["fork"], 1500.0),
        ]
        for ex_id, ex_type, tags, difficulty in exercises:
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES (?, ?, ?, ?, 'test', ?, ?, '{}', '{}')
                """,
                [ex_id, ex_type, SAMPLE_FEN, json.dumps(tags), difficulty, datetime.now()],
            )
            # Sync tags to normalized table
            repo.tags.add_tags(EntityType.EXERCISE, ex_id, tags, TagSource.SYSTEM)

        # Create review cards
        for ex_id in ["tac:001", "tac:002"]:
            repo.conn.execute(
                """
                INSERT INTO review_cards (exercise_id, state, difficulty, stability,
                    retrievability, due, reps, lapses, step_index, created_at)
                VALUES (?, 'REVIEW', 0.5, 10.0, 0.9, ?, 5, 1, 0, ?)
                """,
                [ex_id, datetime.now(), datetime.now()],
            )

        # Add review history
        seq = 1
        for ex_id, correct in [("tac:001", True), ("tac:001", False), ("tac:002", True)]:
            reviewed = datetime.now() - timedelta(days=1)
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating, time_taken_ms, correct)
                VALUES (?, ?, ?, 3, 5000, ?)
                """,
                [seq, ex_id, reviewed, correct],
            )
            seq += 1

    def test_weak_areas_includes_tags(self, repo):
        from src.analytics import AnalyticsStore

        self._seed_analytics(repo)
        store = AnalyticsStore(repo.conn)
        areas = store.weak_areas(min_reviews=1)
        theme_areas = [a for a in areas if a.category == "theme"]
        tag_names = {a.name for a in theme_areas}
        assert "fork" in tag_names  # Both exercises have "fork"

    def test_weak_areas_includes_user_tags(self, repo):
        from src.analytics import AnalyticsStore

        self._seed_analytics(repo)
        # Add a user tag
        repo.tags.add_tags(EntityType.EXERCISE, "tac:001", ["my-category"], TagSource.USER)
        store = AnalyticsStore(repo.conn)
        areas = store.weak_areas(min_reviews=1)
        theme_areas = [a for a in areas if a.category == "theme"]
        tag_names = {a.name for a in theme_areas}
        assert "my-category" in tag_names

    def test_weak_areas_correct_counts(self, repo):
        from src.analytics import AnalyticsStore

        self._seed_analytics(repo)
        store = AnalyticsStore(repo.conn)
        areas = store.weak_areas(min_reviews=1)
        theme_areas = {a.name: a for a in areas if a.category == "theme"}
        # "fork" has 3 reviews (2 from tac:001, 1 from tac:002), 2 correct
        if "fork" in theme_areas:
            fork = theme_areas["fork"]
            assert fork.total_reviews == 3
            assert fork.correct_count == 2


# ---------------------------------------------------------------------------
# Importer integration
# ---------------------------------------------------------------------------


class TestImporterTagSync:
    def test_sync_system_tags_helper(self, repo):
        """_sync_system_tags populates the tags table from exercise JSON."""
        from src.cli.app import _sync_system_tags

        ex = _make_tactic("ex:001", tags=["fork", "pin"], source="lichess")
        repo.exercises.add(ex)

        _sync_system_tags(repo, source="lichess")

        tags = repo.tags.get_tags(EntityType.EXERCISE, "ex:001")
        assert sorted(tags) == ["fork", "pin"]

    def test_sync_system_tags_idempotent(self, repo):
        """Running sync twice doesn't duplicate tags."""
        from src.cli.app import _sync_system_tags

        ex = _make_tactic("ex:001", tags=["fork"], source="test")
        repo.exercises.add(ex)

        _sync_system_tags(repo, source="test")
        _sync_system_tags(repo, source="test")

        tags = repo.tags.get_tags(EntityType.EXERCISE, "ex:001")
        assert tags == ["fork"]

    def test_sync_system_tags_preserves_user_tags(self, repo):
        """Syncing system tags doesn't affect user tags."""
        from src.cli.app import _sync_system_tags

        ex = _make_tactic("ex:001", tags=["fork"], source="test")
        repo.exercises.add(ex)
        repo.tags.add_tags(EntityType.EXERCISE, "ex:001", ["my-tag"], TagSource.USER)

        _sync_system_tags(repo, source="test")

        user = repo.tags.get_tags(EntityType.EXERCISE, "ex:001", source=TagSource.USER)
        system = repo.tags.get_tags(EntityType.EXERCISE, "ex:001", source=TagSource.SYSTEM)
        assert user == ["my-tag"]
        assert system == ["fork"]


# ---------------------------------------------------------------------------
# Entity type isolation
# ---------------------------------------------------------------------------


class TestEntityTypeIsolation:
    def test_exercise_and_opening_tags_isolated(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "id:001", ["fork"])
        store.add_tags(EntityType.OPENING, "id:001", ["sicilian"])

        ex_tags = store.get_tags(EntityType.EXERCISE, "id:001")
        op_tags = store.get_tags(EntityType.OPENING, "id:001")
        assert ex_tags == ["fork"]
        assert op_tags == ["sicilian"]

    def test_find_by_tags_respects_entity_type(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "ex:001", ["fork"])
        store.add_tags(EntityType.OPENING, "op:001", ["fork"])

        result = store.find_by_tags(EntityType.EXERCISE, ["fork"])
        assert result == ["ex:001"]

    def test_remove_only_affects_correct_entity_type(self, repo):
        store = repo.tags
        store.add_tags(EntityType.EXERCISE, "id:001", ["fork"])
        store.add_tags(EntityType.OPENING, "id:001", ["fork"])

        store.remove_tags(EntityType.EXERCISE, "id:001", ["fork"])

        assert store.get_tags(EntityType.EXERCISE, "id:001") == []
        assert store.get_tags(EntityType.OPENING, "id:001") == ["fork"]
