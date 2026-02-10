"""Analytics query layer for progress tracking.

Read-only queries against review_history, review_cards, and exercises tables.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

from .models import (
    AccuracyPoint,
    AccuracyTrend,
    DayActivity,
    ProgressReport,
    RetentionPoint,
    StreakInfo,
    WeakArea,
)


class AnalyticsStore:
    """Read-only analytics queries against the review database.

    Args:
        conn: Active DuckDB connection (from Repository.conn).
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Initialize with an active DuckDB connection."""
        self.conn = conn

    def accuracy_trend(
        self,
        granularity: str = "day",
        exercise_type: str | None = None,
        days: int = 30,
    ) -> AccuracyTrend:
        """Compute accuracy trend over time.

        Args:
            granularity: "day" or "week".
            exercise_type: Optional exercise type filter (e.g. "TACTIC").
            days: Lookback period in days.

        Returns:
            AccuracyTrend with per-period points and overall accuracy.
        """
        cutoff = date.today() - timedelta(days=days)

        if granularity == "week":
            date_expr = "DATE_TRUNC('week', CAST(rh.reviewed_at AS DATE))"
        else:
            date_expr = "CAST(rh.reviewed_at AS DATE)"

        join_clause = ""
        where_extra = ""
        params: list = [cutoff]

        if exercise_type:
            join_clause = "JOIN exercises e ON rh.exercise_id = e.id"
            where_extra = "AND e.exercise_type = ?"
            params.append(exercise_type)

        rows = self.conn.execute(
            f"""
            SELECT
                {date_expr} AS period,
                COUNT(*) AS total_reviews,
                SUM(CASE WHEN rh.correct THEN 1 ELSE 0 END) AS correct_count
            FROM review_history rh
            {join_clause}
            WHERE CAST(rh.reviewed_at AS DATE) >= ?
            {where_extra}
            GROUP BY period
            ORDER BY period
            """,
            params,
        ).fetchall()

        points = []
        total = 0
        correct = 0
        for row in rows:
            period_date = row[0] if isinstance(row[0], date) else row[0].date()
            total_reviews = int(row[1])
            correct_count = int(row[2])
            acc = (correct_count / total_reviews * 100) if total_reviews > 0 else 0.0
            points.append(
                AccuracyPoint(
                    period=period_date,
                    total_reviews=total_reviews,
                    correct_count=correct_count,
                    accuracy=round(acc, 1),
                )
            )
            total += total_reviews
            correct += correct_count

        overall = (correct / total * 100) if total > 0 else 0.0
        return AccuracyTrend(
            points=points,
            overall_accuracy=round(overall, 1),
            total_reviews=total,
            granularity=granularity,
        )

    def weak_areas(
        self,
        min_reviews: int = 5,
        limit: int = 20,
    ) -> list[WeakArea]:
        """Identify weak areas sorted by accuracy (worst first).

        Combines three dimensions: exercise type, theme tags, difficulty tier.

        Args:
            min_reviews: Minimum reviews to include an area.
            limit: Maximum number of weak areas to return.

        Returns:
            List of WeakArea sorted by accuracy ascending.
        """
        areas: list[WeakArea] = []

        # By exercise type
        rows = self.conn.execute(
            """
            SELECT
                e.exercise_type AS name,
                COUNT(*) AS total_reviews,
                SUM(CASE WHEN rh.correct THEN 1 ELSE 0 END) AS correct_count,
                COALESCE(AVG(rc.lapses), 0) AS avg_lapses,
                COUNT(DISTINCT e.id) AS card_count
            FROM review_history rh
            JOIN exercises e ON rh.exercise_id = e.id
            LEFT JOIN review_cards rc ON rh.exercise_id = rc.exercise_id
            GROUP BY e.exercise_type
            HAVING COUNT(*) >= ?
            """,
            [min_reviews],
        ).fetchall()

        for row in rows:
            total_reviews = int(row[1])
            correct_count = int(row[2])
            acc = (correct_count / total_reviews * 100) if total_reviews > 0 else 0.0
            areas.append(
                WeakArea(
                    name=str(row[0]),
                    category="type",
                    total_reviews=total_reviews,
                    correct_count=correct_count,
                    accuracy=round(acc, 1),
                    avg_lapses=round(float(row[3]), 1),
                    card_count=int(row[4]),
                )
            )

        # By theme (tags) — uses normalized tags table
        rows = self.conn.execute(
            """
            SELECT
                t.tag AS name,
                COUNT(*) AS total_reviews,
                SUM(CASE WHEN rh.correct THEN 1 ELSE 0 END) AS correct_count,
                COALESCE(AVG(rc.lapses), 0) AS avg_lapses,
                COUNT(DISTINCT e.id) AS card_count
            FROM review_history rh
            JOIN exercises e ON rh.exercise_id = e.id
            LEFT JOIN review_cards rc ON rh.exercise_id = rc.exercise_id
            JOIN tags t ON t.entity_type = 'exercise' AND t.entity_id = e.id
            GROUP BY t.tag
            HAVING COUNT(*) >= ?
            """,
            [min_reviews],
        ).fetchall()

        for row in rows:
            total_reviews = int(row[1])
            correct_count = int(row[2])
            acc = (correct_count / total_reviews * 100) if total_reviews > 0 else 0.0
            areas.append(
                WeakArea(
                    name=str(row[0]),
                    category="theme",
                    total_reviews=total_reviews,
                    correct_count=correct_count,
                    accuracy=round(acc, 1),
                    avg_lapses=round(float(row[3]), 1),
                    card_count=int(row[4]),
                )
            )

        # By difficulty tier
        rows = self.conn.execute(
            """
            SELECT
                CASE
                    WHEN e.difficulty < 1200 THEN 'Easy (<1200)'
                    WHEN e.difficulty < 1600 THEN 'Medium (1200-1600)'
                    WHEN e.difficulty < 2000 THEN 'Hard (1600-2000)'
                    ELSE 'Expert (2000+)'
                END AS tier,
                COUNT(*) AS total_reviews,
                SUM(CASE WHEN rh.correct THEN 1 ELSE 0 END) AS correct_count,
                COALESCE(AVG(rc.lapses), 0) AS avg_lapses,
                COUNT(DISTINCT e.id) AS card_count
            FROM review_history rh
            JOIN exercises e ON rh.exercise_id = e.id
            LEFT JOIN review_cards rc ON rh.exercise_id = rc.exercise_id
            WHERE e.difficulty IS NOT NULL
            GROUP BY tier
            HAVING COUNT(*) >= ?
            """,
            [min_reviews],
        ).fetchall()

        for row in rows:
            total_reviews = int(row[1])
            correct_count = int(row[2])
            acc = (correct_count / total_reviews * 100) if total_reviews > 0 else 0.0
            areas.append(
                WeakArea(
                    name=str(row[0]),
                    category="difficulty",
                    total_reviews=total_reviews,
                    correct_count=correct_count,
                    accuracy=round(acc, 1),
                    avg_lapses=round(float(row[3]), 1),
                    card_count=int(row[4]),
                )
            )

        # Sort by accuracy ascending (worst first), limit
        areas.sort(key=lambda a: a.accuracy)
        return areas[:limit]

    def streaks(self, lookback_days: int = 90) -> StreakInfo:
        """Compute streak information and daily activity.

        Args:
            lookback_days: How far back to look for activity.

        Returns:
            StreakInfo with current/longest streaks and daily activity.
        """
        cutoff = date.today() - timedelta(days=lookback_days)

        rows = self.conn.execute(
            """
            SELECT
                CAST(reviewed_at AS DATE) AS review_date,
                COUNT(*) AS review_count
            FROM review_history
            WHERE CAST(reviewed_at AS DATE) >= ?
            GROUP BY review_date
            ORDER BY review_date
            """,
            [cutoff],
        ).fetchall()

        if not rows:
            return StreakInfo(
                current_streak=0,
                longest_streak=0,
                total_active_days=0,
                daily_activity=[],
            )

        daily_activity = []
        active_dates: list[date] = []
        for row in rows:
            day = row[0] if isinstance(row[0], date) else row[0].date()
            daily_activity.append(DayActivity(day=day, review_count=int(row[1])))
            active_dates.append(day)

        today = date.today()
        total_active_days = len(active_dates)

        # Compute current streak (consecutive days ending today or yesterday)
        current_streak = 0
        check_date = today
        if check_date not in active_dates:
            check_date = today - timedelta(days=1)
        while check_date in active_dates:
            current_streak += 1
            check_date -= timedelta(days=1)

        # Compute longest streak
        longest_streak = 0
        if active_dates:
            streak = 1
            for i in range(1, len(active_dates)):
                if active_dates[i] - active_dates[i - 1] == timedelta(days=1):
                    streak += 1
                else:
                    longest_streak = max(longest_streak, streak)
                    streak = 1
            longest_streak = max(longest_streak, streak)

        return StreakInfo(
            current_streak=current_streak,
            longest_streak=longest_streak,
            total_active_days=total_active_days,
            daily_activity=daily_activity,
        )

    def retention_curve(self) -> list[RetentionPoint]:
        """Compute retention curve grouped by repetition count.

        Joins review_cards with the most recent review_history entry
        to compute actual recall rates per rep count.

        Returns:
            List of RetentionPoint sorted by reps ascending.
        """
        rows = self.conn.execute(
            """
            WITH latest_review AS (
                SELECT
                    exercise_id,
                    correct,
                    ROW_NUMBER() OVER (
                        PARTITION BY exercise_id ORDER BY reviewed_at DESC
                    ) AS rn
                FROM review_history
            )
            SELECT
                rc.reps,
                COUNT(*) AS card_count,
                AVG(rc.stability) AS avg_stability,
                AVG(CASE WHEN lr.correct THEN 1.0 ELSE 0.0 END) AS actual_recall,
                AVG(rc.retrievability) AS avg_retrievability
            FROM review_cards rc
            JOIN latest_review lr
                ON rc.exercise_id = lr.exercise_id AND lr.rn = 1
            WHERE rc.reps > 0
            GROUP BY rc.reps
            ORDER BY rc.reps
            """
        ).fetchall()

        points = []
        for row in rows:
            points.append(
                RetentionPoint(
                    reps=int(row[0]),
                    card_count=int(row[1]),
                    avg_stability_days=round(float(row[2]), 1),
                    actual_recall_rate=round(float(row[3]) * 100, 1),
                    predicted_retrievability=round(float(row[4]) * 100, 1),
                )
            )
        return points

    def full_report(
        self,
        granularity: str = "day",
        exercise_type: str | None = None,
        days: int = 30,
        min_reviews: int = 5,
        lookback_days: int = 90,
    ) -> ProgressReport:
        """Generate a complete progress report.

        Args:
            granularity: "day" or "week" for accuracy trend.
            exercise_type: Optional exercise type filter for accuracy.
            days: Lookback period for accuracy trend.
            min_reviews: Minimum reviews for weak areas.
            lookback_days: Lookback period for streaks.

        Returns:
            ProgressReport combining all analytics.
        """
        return ProgressReport(
            accuracy=self.accuracy_trend(
                granularity=granularity,
                exercise_type=exercise_type,
                days=days,
            ),
            weak_areas=self.weak_areas(min_reviews=min_reviews),
            streaks=self.streaks(lookback_days=lookback_days),
            retention=self.retention_curve(),
        )
