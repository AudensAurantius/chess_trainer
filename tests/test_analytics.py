"""Tests for progress analytics: models, queries, CLI, and web endpoints."""

import json
from datetime import date, datetime, timedelta

import pytest
from typer.testing import CliRunner

from src.analytics import (
    AccuracyPoint,
    AccuracyTrend,
    AnalyticsStore,
    DayActivity,
    ProgressReport,
    RetentionPoint,
    StreakInfo,
    WeakArea,
)
from src.cli.app import app
from src.storage import Repository

runner = CliRunner()

SAMPLE_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_analytics_data(repo: Repository) -> None:
    """Insert exercises, cards, and review history for analytics testing.

    Creates:
    - 3 TACTIC exercises with tags ["fork", "pin"], difficulty 1000, 1500, 2100
    - 2 OPENING exercises with tags ["opening"], difficulty 800, 1300
    - 1 ENDGAME exercise with tags ["endgame"], difficulty 1700
    - Review history spanning 35 days with gaps (for streak testing)
    - Varying correctness patterns for weak-area detection
    """
    today = date.today()

    exercises = [
        ("tac:001", "TACTIC", ["fork", "pin"], 1000.0),
        ("tac:002", "TACTIC", ["fork"], 1500.0),
        ("tac:003", "TACTIC", ["pin", "sacrifice"], 2100.0),
        ("open:001", "OPENING", ["opening"], 800.0),
        ("open:002", "OPENING", ["opening", "sicilian"], 1300.0),
        ("end:001", "ENDGAME", ["endgame"], 1700.0),
    ]

    for ex_id, ex_type, tags, difficulty in exercises:
        repo.conn.execute(
            """
            INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
            VALUES (?, ?, ?, ?, 'test', ?, ?, '{}', '{}')
            """,
            [ex_id, ex_type, SAMPLE_FEN, json.dumps(tags), difficulty, datetime.now()],
        )

    # Create review cards with varying reps/lapses/stability
    cards = [
        ("tac:001", "REVIEW", 0.5, 10.0, 0.9, 5, 1),
        ("tac:002", "REVIEW", 0.5, 20.0, 0.85, 8, 2),
        ("tac:003", "LEARNING", 0.6, 1.0, 0.5, 2, 3),
        ("open:001", "REVIEW", 0.4, 15.0, 0.92, 5, 0),
        ("open:002", "REVIEW", 0.5, 5.0, 0.7, 3, 1),
        ("end:001", "REVIEW", 0.5, 8.0, 0.8, 3, 0),
    ]

    for ex_id, state, diff, stab, retr, reps, lapses in cards:
        repo.conn.execute(
            """
            INSERT INTO review_cards (exercise_id, state, difficulty, stability,
                retrievability, due, reps, lapses, step_index, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            [ex_id, state, diff, stab, retr, datetime.now(), reps, lapses, datetime.now()],
        )

    # Build review history over 35 days with gaps
    # Days with reviews: today, yesterday, 2 days ago, 4 days ago, 5 days ago,
    # 7 days ago, 10 days ago, 20 days ago, 30 days ago, 34 days ago
    review_days = [0, 1, 2, 4, 5, 7, 10, 20, 30, 34]

    review_id = 1
    for days_ago in review_days:
        review_date = datetime.combine(today - timedelta(days=days_ago), datetime.min.time())

        # For each review day, add reviews for different exercises
        # Tactics: mostly correct
        for ex_id in ["tac:001", "tac:002"]:
            correct = days_ago % 3 != 0  # ~66% correct
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                    time_taken_ms, correct, stability_before, stability_after)
                VALUES (?, ?, ?, ?, 5000, ?, 5.0, 10.0)
                """,
                [review_id, ex_id, review_date, 3 if correct else 1, correct],
            )
            review_id += 1

        # tac:003: always wrong (hard exercise)
        repo.conn.execute(
            """
            INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                time_taken_ms, correct, stability_before, stability_after)
            VALUES (?, 'tac:003', ?, 1, 8000, false, 1.0, 0.5)
            """,
            [review_id, review_date],
        )
        review_id += 1

        # Opening exercises: mostly correct
        if days_ago < 20:
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                    time_taken_ms, correct, stability_before, stability_after)
                VALUES (?, 'open:001', ?, 3, 3000, true, 10.0, 15.0)
                """,
                [review_id, review_date],
            )
            review_id += 1

        # Endgame: sporadic
        if days_ago in [0, 5, 10, 30]:
            correct = days_ago < 10
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                    time_taken_ms, correct, stability_before, stability_after)
                VALUES (?, 'end:001', ?, ?, 6000, ?, 5.0, 8.0)
                """,
                [review_id, review_date, 3 if correct else 1, correct],
            )
            review_id += 1


@pytest.fixture
def repo(tmp_path):
    """Repository with seeded analytics data."""
    with Repository(tmp_path / "analytics_test.db") as r:
        _seed_analytics_data(r)
        yield r


@pytest.fixture
def empty_repo(tmp_path):
    """Empty repository with no data."""
    with Repository(tmp_path / "empty_test.db") as r:
        yield r


@pytest.fixture
def store(repo):
    """AnalyticsStore backed by seeded repository."""
    return AnalyticsStore(repo.conn)


@pytest.fixture
def empty_store(empty_repo):
    """AnalyticsStore backed by empty repository."""
    return AnalyticsStore(empty_repo.conn)


# ---------------------------------------------------------------------------
# Model construction tests
# ---------------------------------------------------------------------------


class TestModels:
    def test_accuracy_point(self):
        p = AccuracyPoint(period=date.today(), total_reviews=10, correct_count=7, accuracy=70.0)
        assert p.total_reviews == 10
        assert p.accuracy == 70.0

    def test_accuracy_point_frozen(self):
        p = AccuracyPoint(period=date.today(), total_reviews=10, correct_count=7, accuracy=70.0)
        with pytest.raises(AttributeError):
            p.accuracy = 80.0

    def test_accuracy_trend(self):
        t = AccuracyTrend(points=[], overall_accuracy=0.0, total_reviews=0, granularity="day")
        assert t.granularity == "day"
        assert t.points == []

    def test_weak_area(self):
        w = WeakArea(
            name="fork",
            category="theme",
            total_reviews=20,
            correct_count=10,
            accuracy=50.0,
            avg_lapses=1.5,
            card_count=3,
        )
        assert w.name == "fork"
        assert w.category == "theme"

    def test_day_activity(self):
        d = DayActivity(day=date.today(), review_count=5)
        assert d.review_count == 5

    def test_streak_info(self):
        s = StreakInfo(current_streak=3, longest_streak=7, total_active_days=20)
        assert s.daily_activity == []

    def test_streak_info_with_activity(self):
        activity = [DayActivity(day=date.today(), review_count=10)]
        s = StreakInfo(
            current_streak=1, longest_streak=1, total_active_days=1, daily_activity=activity
        )
        assert len(s.daily_activity) == 1

    def test_retention_point(self):
        r = RetentionPoint(
            reps=5,
            card_count=10,
            avg_stability_days=15.0,
            actual_recall_rate=85.0,
            predicted_retrievability=90.0,
        )
        assert r.reps == 5

    def test_progress_report(self):
        report = ProgressReport(
            accuracy=AccuracyTrend(
                points=[], overall_accuracy=0.0, total_reviews=0, granularity="day"
            ),
            weak_areas=[],
            streaks=StreakInfo(current_streak=0, longest_streak=0, total_active_days=0),
            retention=[],
        )
        assert report.accuracy.total_reviews == 0
        assert report.weak_areas == []


# ---------------------------------------------------------------------------
# Accuracy trend tests
# ---------------------------------------------------------------------------


class TestAccuracyTrend:
    def test_daily_granularity(self, store):
        trend = store.accuracy_trend(granularity="day", days=35)
        assert trend.granularity == "day"
        assert len(trend.points) > 0
        assert trend.total_reviews > 0

    def test_weekly_granularity(self, store):
        trend = store.accuracy_trend(granularity="week", days=35)
        assert trend.granularity == "week"
        # Weeks should be fewer than days
        daily = store.accuracy_trend(granularity="day", days=35)
        assert len(trend.points) <= len(daily.points)

    def test_points_ordered_by_date(self, store):
        trend = store.accuracy_trend(days=35)
        dates = [p.period for p in trend.points]
        assert dates == sorted(dates)

    def test_overall_accuracy_matches(self, store):
        trend = store.accuracy_trend(days=35)
        total = sum(p.total_reviews for p in trend.points)
        correct = sum(p.correct_count for p in trend.points)
        expected = round(correct / total * 100, 1) if total > 0 else 0.0
        assert trend.overall_accuracy == expected
        assert trend.total_reviews == total

    def test_filter_by_exercise_type(self, store):
        tactic_trend = store.accuracy_trend(exercise_type="TACTIC", days=35)
        opening_trend = store.accuracy_trend(exercise_type="OPENING", days=35)
        assert tactic_trend.total_reviews > 0
        assert opening_trend.total_reviews > 0
        # They shouldn't be the same since we have different patterns
        assert tactic_trend.total_reviews != opening_trend.total_reviews

    def test_days_filter(self, store):
        short = store.accuracy_trend(days=3)
        long = store.accuracy_trend(days=35)
        assert long.total_reviews >= short.total_reviews

    def test_accuracy_per_point_in_range(self, store):
        trend = store.accuracy_trend(days=35)
        for point in trend.points:
            assert 0 <= point.accuracy <= 100
            assert point.correct_count <= point.total_reviews

    def test_empty_database(self, empty_store):
        trend = empty_store.accuracy_trend()
        assert trend.points == []
        assert trend.total_reviews == 0
        assert trend.overall_accuracy == 0.0

    def test_nonexistent_exercise_type(self, store):
        trend = store.accuracy_trend(exercise_type="NONEXISTENT", days=35)
        assert trend.total_reviews == 0
        assert trend.points == []


# ---------------------------------------------------------------------------
# Weak areas tests
# ---------------------------------------------------------------------------


class TestWeakAreas:
    def test_returns_weak_areas(self, store):
        areas = store.weak_areas(min_reviews=1)
        assert len(areas) > 0

    def test_sorted_by_accuracy_ascending(self, store):
        areas = store.weak_areas(min_reviews=1)
        accuracies = [a.accuracy for a in areas]
        assert accuracies == sorted(accuracies)

    def test_has_type_category(self, store):
        areas = store.weak_areas(min_reviews=1)
        type_areas = [a for a in areas if a.category == "type"]
        assert len(type_areas) > 0

    def test_has_theme_category(self, store):
        areas = store.weak_areas(min_reviews=1)
        theme_areas = [a for a in areas if a.category == "theme"]
        assert len(theme_areas) > 0

    def test_has_difficulty_category(self, store):
        areas = store.weak_areas(min_reviews=1)
        diff_areas = [a for a in areas if a.category == "difficulty"]
        assert len(diff_areas) > 0

    def test_min_reviews_filter(self, store):
        many = store.weak_areas(min_reviews=1)
        few = store.weak_areas(min_reviews=100)
        assert len(many) >= len(few)

    def test_limit(self, store):
        areas = store.weak_areas(min_reviews=1, limit=3)
        assert len(areas) <= 3

    def test_accuracy_in_range(self, store):
        areas = store.weak_areas(min_reviews=1)
        for area in areas:
            assert 0 <= area.accuracy <= 100
            assert area.correct_count <= area.total_reviews
            assert area.card_count >= 0
            assert area.avg_lapses >= 0

    def test_empty_database(self, empty_store):
        areas = empty_store.weak_areas()
        assert areas == []

    def test_tactic_type_present(self, store):
        areas = store.weak_areas(min_reviews=1)
        type_names = [a.name for a in areas if a.category == "type"]
        assert "TACTIC" in type_names

    def test_fork_theme_present(self, store):
        areas = store.weak_areas(min_reviews=1)
        theme_names = [a.name for a in areas if a.category == "theme"]
        assert "fork" in theme_names

    def test_difficulty_tiers(self, store):
        areas = store.weak_areas(min_reviews=1)
        diff_names = [a.name for a in areas if a.category == "difficulty"]
        # At least some difficulty tiers should appear
        assert len(diff_names) > 0


# ---------------------------------------------------------------------------
# Streaks tests
# ---------------------------------------------------------------------------


class TestStreaks:
    def test_has_current_streak(self, store):
        info = store.streaks()
        # We seeded today and yesterday, so current streak >= 2
        assert info.current_streak >= 2

    def test_has_longest_streak(self, store):
        info = store.streaks()
        assert info.longest_streak >= info.current_streak

    def test_has_total_active_days(self, store):
        info = store.streaks()
        assert info.total_active_days > 0

    def test_daily_activity_populated(self, store):
        info = store.streaks()
        assert len(info.daily_activity) > 0

    def test_daily_activity_ordered(self, store):
        info = store.streaks()
        dates = [a.day for a in info.daily_activity]
        assert dates == sorted(dates)

    def test_daily_activity_positive_counts(self, store):
        info = store.streaks()
        for activity in info.daily_activity:
            assert activity.review_count > 0

    def test_empty_database(self, empty_store):
        info = empty_store.streaks()
        assert info.current_streak == 0
        assert info.longest_streak == 0
        assert info.total_active_days == 0
        assert info.daily_activity == []

    def test_lookback_filter(self, store):
        short = store.streaks(lookback_days=3)
        long = store.streaks(lookback_days=90)
        assert long.total_active_days >= short.total_active_days

    def test_current_streak_consecutive(self, store):
        """Current streak should count consecutive days from today/yesterday."""
        info = store.streaks()
        # Our seeded data has reviews today, yesterday, 2 days ago (consecutive)
        # then a gap at 3 days ago, so current streak should be exactly 3
        assert info.current_streak == 3


# ---------------------------------------------------------------------------
# Retention curve tests
# ---------------------------------------------------------------------------


class TestRetentionCurve:
    def test_returns_points(self, store):
        points = store.retention_curve()
        assert len(points) > 0

    def test_grouped_by_reps(self, store):
        points = store.retention_curve()
        reps = [p.reps for p in points]
        assert reps == sorted(set(reps))

    def test_positive_values(self, store):
        points = store.retention_curve()
        for p in points:
            assert p.card_count > 0
            assert p.avg_stability_days >= 0
            assert 0 <= p.actual_recall_rate <= 100
            assert 0 <= p.predicted_retrievability <= 100

    def test_excludes_zero_reps(self, store):
        points = store.retention_curve()
        for p in points:
            assert p.reps > 0

    def test_empty_database(self, empty_store):
        points = empty_store.retention_curve()
        assert points == []


# ---------------------------------------------------------------------------
# Full report tests
# ---------------------------------------------------------------------------


class TestFullReport:
    def test_returns_progress_report(self, store):
        report = store.full_report(days=35)
        assert isinstance(report, ProgressReport)

    def test_all_sections_populated(self, store):
        report = store.full_report(days=35)
        assert report.accuracy.total_reviews > 0
        assert len(report.weak_areas) > 0
        assert report.streaks.total_active_days > 0
        assert len(report.retention) > 0

    def test_empty_database(self, empty_store):
        report = empty_store.full_report()
        assert report.accuracy.total_reviews == 0
        assert report.weak_areas == []
        assert report.streaks.total_active_days == 0
        assert report.retention == []

    def test_passes_parameters(self, store):
        report = store.full_report(granularity="week", days=7)
        assert report.accuracy.granularity == "week"


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestProgressCLI:
    def _seeded_db(self, tmp_path):
        db_path = tmp_path / "cli_test.db"
        with Repository(db_path) as repo:
            _seed_analytics_data(repo)
        return str(db_path)

    def test_progress_default(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--db", db])
        assert result.exit_code == 0
        assert "Accuracy" in result.output

    def test_progress_accuracy_only(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--accuracy", "--db", db])
        assert result.exit_code == 0
        assert "Accuracy" in result.output

    def test_progress_weak_only(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--weak", "--db", db])
        assert result.exit_code == 0

    def test_progress_streaks_only(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--streaks", "--db", db])
        assert result.exit_code == 0
        assert "Streaks" in result.output

    def test_progress_retention_only(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--retention", "--db", db])
        assert result.exit_code == 0
        assert "Retention" in result.output

    def test_progress_empty_db(self, tmp_path):
        db_path = tmp_path / "empty.db"
        with Repository(db_path):
            pass
        result = runner.invoke(app, ["progress", "--db", str(db_path)])
        assert result.exit_code == 0
        assert "No review data" in result.output

    def test_progress_weekly_granularity(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--accuracy", "--granularity", "week", "--db", db])
        assert result.exit_code == 0
        assert "week" in result.output

    def test_progress_type_filter(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--accuracy", "--type", "TACTIC", "--db", db])
        assert result.exit_code == 0

    def test_progress_days_filter(self, tmp_path):
        db = self._seeded_db(tmp_path)
        result = runner.invoke(app, ["progress", "--accuracy", "--days", "7", "--db", db])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Web API tests
# ---------------------------------------------------------------------------


class TestWebAnalytics:
    @pytest.fixture
    def seeded_app(self, tmp_path):
        from src.config import AppConfig
        from src.web import create_app

        config = AppConfig()
        db_path = tmp_path / "web_analytics.db"
        config.database.path = str(db_path)
        with Repository(db_path) as repo:
            _seed_analytics_data(repo)
        return create_app(config)

    @pytest.fixture
    def client(self, seeded_app):
        from fastapi.testclient import TestClient

        return TestClient(seeded_app)

    @pytest.fixture
    def empty_client(self, tmp_path):
        from src.config import AppConfig
        from src.web import create_app

        config = AppConfig()
        config.database.path = str(tmp_path / "empty_web.db")
        with Repository(tmp_path / "empty_web.db"):
            pass
        return __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(
            create_app(config)
        )

    def test_accuracy_endpoint(self, client):
        res = client.get("/api/analytics/accuracy")
        assert res.status_code == 200
        data = res.json()
        assert "labels" in data
        assert "datasets" in data
        assert "overall_accuracy" in data
        assert "total_reviews" in data

    def test_accuracy_with_params(self, client):
        res = client.get("/api/analytics/accuracy?days=7&granularity=week&exercise_type=TACTIC")
        assert res.status_code == 200
        data = res.json()
        assert data["total_reviews"] > 0

    def test_accuracy_empty(self, empty_client):
        res = empty_client.get("/api/analytics/accuracy")
        assert res.status_code == 200
        data = res.json()
        assert data["total_reviews"] == 0

    def test_weak_areas_endpoint(self, client):
        res = client.get("/api/analytics/weak-areas")
        assert res.status_code == 200
        data = res.json()
        assert "areas" in data

    def test_weak_areas_with_params(self, client):
        res = client.get("/api/analytics/weak-areas?min_reviews=1&limit=5")
        assert res.status_code == 200
        data = res.json()
        assert len(data["areas"]) <= 5

    def test_weak_areas_empty(self, empty_client):
        res = empty_client.get("/api/analytics/weak-areas")
        assert res.status_code == 200
        assert res.json()["areas"] == []

    def test_streaks_endpoint(self, client):
        res = client.get("/api/analytics/streaks")
        assert res.status_code == 200
        data = res.json()
        assert "current_streak" in data
        assert "longest_streak" in data
        assert "daily_activity" in data

    def test_streaks_with_params(self, client):
        res = client.get("/api/analytics/streaks?lookback_days=7")
        assert res.status_code == 200

    def test_streaks_empty(self, empty_client):
        res = empty_client.get("/api/analytics/streaks")
        assert res.status_code == 200
        data = res.json()
        assert data["current_streak"] == 0

    def test_retention_endpoint(self, client):
        res = client.get("/api/analytics/retention")
        assert res.status_code == 200
        data = res.json()
        assert "labels" in data
        assert "datasets" in data

    def test_retention_empty(self, empty_client):
        res = empty_client.get("/api/analytics/retention")
        assert res.status_code == 200
        assert res.json()["datasets"] == []

    def test_accuracy_labels_match_datasets(self, client):
        res = client.get("/api/analytics/accuracy")
        data = res.json()
        assert len(data["labels"]) == len(data["datasets"])

    def test_weak_areas_structure(self, client):
        res = client.get("/api/analytics/weak-areas?min_reviews=1")
        data = res.json()
        if data["areas"]:
            area = data["areas"][0]
            assert "name" in area
            assert "category" in area
            assert "accuracy" in area
            assert "total_reviews" in area
            assert "correct_count" in area
            assert "avg_lapses" in area
            assert "card_count" in area

    def test_streaks_activity_structure(self, client):
        res = client.get("/api/analytics/streaks")
        data = res.json()
        if data["daily_activity"]:
            act = data["daily_activity"][0]
            assert "day" in act
            assert "review_count" in act


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_all_correct_reviews(self, tmp_path):
        """All reviews correct should give 100% accuracy."""
        with Repository(tmp_path / "all_correct.db") as repo:
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES ('ex:1', 'TACTIC', ?, '["fork"]', 'test', 1500, ?, '{}', '{}')
                """,
                [SAMPLE_FEN, datetime.now()],
            )
            repo.conn.execute(
                """
                INSERT INTO review_cards (exercise_id, state, difficulty, stability,
                    retrievability, due, reps, lapses, step_index, created_at)
                VALUES ('ex:1', 'REVIEW', 0.5, 10.0, 0.9, ?, 5, 0, 0, ?)
                """,
                [datetime.now(), datetime.now()],
            )
            for i in range(10):
                repo.conn.execute(
                    """
                    INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                        time_taken_ms, correct, stability_before, stability_after)
                    VALUES (?, 'ex:1', ?, 3, 5000, true, 5.0, 10.0)
                    """,
                    [i + 1, datetime.now() - timedelta(days=i)],
                )

            store = AnalyticsStore(repo.conn)
            trend = store.accuracy_trend(days=30)
            assert trend.overall_accuracy == 100.0

    def test_all_incorrect_reviews(self, tmp_path):
        """All reviews incorrect should give 0% accuracy."""
        with Repository(tmp_path / "all_wrong.db") as repo:
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES ('ex:1', 'TACTIC', ?, '["fork"]', 'test', 1500, ?, '{}', '{}')
                """,
                [SAMPLE_FEN, datetime.now()],
            )
            repo.conn.execute(
                """
                INSERT INTO review_cards (exercise_id, state, difficulty, stability,
                    retrievability, due, reps, lapses, step_index, created_at)
                VALUES ('ex:1', 'REVIEW', 0.5, 1.0, 0.3, ?, 5, 5, 0, ?)
                """,
                [datetime.now(), datetime.now()],
            )
            for i in range(10):
                repo.conn.execute(
                    """
                    INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                        time_taken_ms, correct, stability_before, stability_after)
                    VALUES (?, 'ex:1', ?, 1, 5000, false, 1.0, 0.5)
                    """,
                    [i + 1, datetime.now() - timedelta(days=i)],
                )

            store = AnalyticsStore(repo.conn)
            trend = store.accuracy_trend(days=30)
            assert trend.overall_accuracy == 0.0

    def test_single_day_streak(self, tmp_path):
        """A single day of reviews should give streak of 1 (if today)."""
        with Repository(tmp_path / "single_day.db") as repo:
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES ('ex:1', 'TACTIC', ?, '["fork"]', 'test', 1500, ?, '{}', '{}')
                """,
                [SAMPLE_FEN, datetime.now()],
            )
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                    time_taken_ms, correct, stability_before, stability_after)
                VALUES (1, 'ex:1', ?, 3, 5000, true, 5.0, 10.0)
                """,
                [datetime.now()],
            )

            store = AnalyticsStore(repo.conn)
            info = store.streaks()
            assert info.current_streak == 1
            assert info.longest_streak == 1

    def test_streak_from_yesterday_only(self, tmp_path):
        """Reviews only yesterday should give current streak of 1."""
        with Repository(tmp_path / "yesterday.db") as repo:
            yesterday = datetime.now() - timedelta(days=1)
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES ('ex:1', 'TACTIC', ?, '["fork"]', 'test', 1500, ?, '{}', '{}')
                """,
                [SAMPLE_FEN, datetime.now()],
            )
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                    time_taken_ms, correct, stability_before, stability_after)
                VALUES (1, 'ex:1', ?, 3, 5000, true, 5.0, 10.0)
                """,
                [yesterday],
            )

            store = AnalyticsStore(repo.conn)
            info = store.streaks()
            assert info.current_streak == 1

    def test_streak_broken_two_days_ago(self, tmp_path):
        """Reviews only 2 days ago (with no today/yesterday) should give streak 0."""
        with Repository(tmp_path / "old.db") as repo:
            two_days_ago = datetime.now() - timedelta(days=2)
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES ('ex:1', 'TACTIC', ?, '["fork"]', 'test', 1500, ?, '{}', '{}')
                """,
                [SAMPLE_FEN, datetime.now()],
            )
            repo.conn.execute(
                """
                INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                    time_taken_ms, correct, stability_before, stability_after)
                VALUES (1, 'ex:1', ?, 3, 5000, true, 5.0, 10.0)
                """,
                [two_days_ago],
            )

            store = AnalyticsStore(repo.conn)
            info = store.streaks()
            assert info.current_streak == 0

    def test_no_tags_exercise_weak_areas(self, tmp_path):
        """Exercises with no tags should still appear in type/difficulty weak areas."""
        with Repository(tmp_path / "no_tags.db") as repo:
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES ('ex:1', 'TACTIC', ?, '[]', 'test', 1500, ?, '{}', '{}')
                """,
                [SAMPLE_FEN, datetime.now()],
            )
            repo.conn.execute(
                """
                INSERT INTO review_cards (exercise_id, state, difficulty, stability,
                    retrievability, due, reps, lapses, step_index, created_at)
                VALUES ('ex:1', 'REVIEW', 0.5, 10.0, 0.9, ?, 5, 0, 0, ?)
                """,
                [datetime.now(), datetime.now()],
            )
            for i in range(10):
                repo.conn.execute(
                    """
                    INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                        time_taken_ms, correct, stability_before, stability_after)
                    VALUES (?, 'ex:1', ?, 3, 5000, true, 5.0, 10.0)
                    """,
                    [i + 1, datetime.now()],
                )

            store = AnalyticsStore(repo.conn)
            areas = store.weak_areas(min_reviews=1)
            type_areas = [a for a in areas if a.category == "type"]
            assert len(type_areas) > 0
            # No theme areas since no tags
            theme_areas = [a for a in areas if a.category == "theme"]
            assert len(theme_areas) == 0

    def test_null_difficulty_excluded_from_tier(self, tmp_path):
        """Exercises with null difficulty should not appear in difficulty tiers."""
        with Repository(tmp_path / "null_diff.db") as repo:
            repo.conn.execute(
                """
                INSERT INTO exercises (id, exercise_type, fen, tags, source, difficulty, created_at, metadata, type_data)
                VALUES ('ex:1', 'TACTIC', ?, '["fork"]', 'test', NULL, ?, '{}', '{}')
                """,
                [SAMPLE_FEN, datetime.now()],
            )
            repo.conn.execute(
                """
                INSERT INTO review_cards (exercise_id, state, difficulty, stability,
                    retrievability, due, reps, lapses, step_index, created_at)
                VALUES ('ex:1', 'REVIEW', 0.5, 10.0, 0.9, ?, 5, 0, 0, ?)
                """,
                [datetime.now(), datetime.now()],
            )
            for i in range(10):
                repo.conn.execute(
                    """
                    INSERT INTO review_history (id, exercise_id, reviewed_at, rating,
                        time_taken_ms, correct, stability_before, stability_after)
                    VALUES (?, 'ex:1', ?, 3, 5000, true, 5.0, 10.0)
                    """,
                    [i + 1, datetime.now()],
                )

            store = AnalyticsStore(repo.conn)
            areas = store.weak_areas(min_reviews=1)
            diff_areas = [a for a in areas if a.category == "difficulty"]
            assert len(diff_areas) == 0
