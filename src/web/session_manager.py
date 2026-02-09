"""Server-side training session state management."""

from dataclasses import dataclass, field
from pathlib import Path

import chess

from ..config import AppConfig
from ..exercises import Exercise
from ..scheduling.fsrs import Rating
from ..storage import Repository
from ..training import SessionConfig, SessionStats, TrainingSession


@dataclass
class ExerciseState:
    """State for the current exercise being presented."""

    exercise: Exercise
    fen: str
    side_to_move: str
    challenge: str
    solution_uci: list[str]
    move_index: int = 0
    board: chess.Board = field(default=None, repr=False)
    submitted: bool = False

    def __post_init__(self) -> None:
        """Initialize the working board from FEN."""
        if self.board is None:
            self.board = chess.Board(self.fen)


class SessionManager:
    """Manages the training session lifecycle for the web interface.

    Single-user model: one active session at a time.
    """

    def __init__(self, config: AppConfig) -> None:
        """Initialize session manager with app config."""
        self.config = config
        self._session: TrainingSession | None = None
        self._repo: Repository | None = None
        self._exercise_state: ExerciseState | None = None

    @property
    def is_active(self) -> bool:
        """Whether a training session is currently active."""
        return self._session is not None

    @property
    def exercise_state(self) -> ExerciseState | None:
        """Current exercise state."""
        return self._exercise_state

    @property
    def stats(self) -> SessionStats | None:
        """Current session stats."""
        return self._session.stats if self._session else None

    @property
    def remaining(self) -> int:
        """Cards remaining in the queue."""
        return self._session.remaining if self._session else 0

    def _open_repo(self) -> Repository:
        """Open (or reuse) the repository connection."""
        if self._repo is None:
            self._repo = Repository(Path(self.config.database.path))
            self._repo.__enter__()
        return self._repo

    def _close_repo(self) -> None:
        """Close the repository connection."""
        if self._repo is not None:
            self._repo.__exit__(None, None, None)
            self._repo = None

    def start_session(
        self,
        max_new: int | None = None,
        max_reviews: int | None = None,
    ) -> int:
        """Start a new training session.

        Args:
            max_new: Override max new cards (uses config default if None).
            max_reviews: Override max reviews (uses config default if None).

        Returns:
            Number of cards in the queue.
        """
        # Close any existing session
        self.end_session()

        repo = self._open_repo()
        session_config = SessionConfig(
            max_new_cards=max_new or self.config.training.max_new_cards,
            max_reviews=max_reviews or self.config.training.max_reviews,
            interleave_new=self.config.training.interleave_new,
        )
        self._session = TrainingSession(repo, session_config)
        self._session.start()
        return self._session.remaining

    def next_exercise(self) -> ExerciseState | None:
        """Advance to the next exercise.

        Returns:
            ExerciseState for the new exercise, or None if session is complete.
        """
        if not self._session:
            return None

        exercise = self._session.next()
        if exercise is None:
            self._exercise_state = None
            return None

        solution = exercise.get_solution()
        # Solution alternates user/opponent moves.
        # Build the full UCI sequence for client-side replay.
        solution_uci = [m.uci() for m in solution]

        self._exercise_state = ExerciseState(
            exercise=exercise,
            fen=exercise.fen,
            side_to_move=exercise.side_to_move,
            challenge=exercise.get_challenge(),
            solution_uci=solution_uci,
        )
        return self._exercise_state

    def submit_move(self, move_uci: str) -> dict:
        """Submit a single move from the user.

        Args:
            move_uci: Move in UCI format (e.g. "e2e4").

        Returns:
            Dict with keys: valid, correct, finished, opponent_move, feedback.
        """
        if not self._session or not self._exercise_state:
            return {"valid": False, "feedback": "No active exercise"}

        state = self._exercise_state
        solution = state.exercise.get_solution()

        # Determine which solution move the user should play
        # User plays moves at indices 0, 2, 4, ... (even indices)
        user_move_indices = list(range(0, len(solution), 2))

        # Find which user move we're expecting
        user_step = state.move_index  # How many user moves have been made
        if user_step >= len(user_move_indices):
            return {"valid": False, "feedback": "Exercise already complete"}

        expected_idx = user_move_indices[user_step]
        expected_move = solution[expected_idx]

        # Validate the move
        try:
            move = chess.Move.from_uci(move_uci)
        except (chess.InvalidMoveError, ValueError):
            return {"valid": False, "feedback": "Invalid move format"}

        if move not in state.board.legal_moves:
            return {"valid": False, "feedback": "Illegal move"}

        # Apply the user's move to the working board
        state.board.push(move)

        is_correct_move = move == expected_move
        is_last_user_move = user_step == len(user_move_indices) - 1

        if not is_correct_move:
            # Wrong move — exercise is done
            state.submitted = True
            # Build the moves list for evaluation (all user moves so far)
            user_moves = []
            eval_board = chess.Board(state.fen)
            for i in range(user_step):
                idx = user_move_indices[i]
                eval_board.push(solution[idx])
                user_moves.append(solution[idx])
                # Also push opponent response
                if idx + 1 < len(solution):
                    eval_board.push(solution[idx + 1])
            user_moves.append(move)

            result, _ = self._session.submit(user_moves, 0)
            return {
                "valid": True,
                "correct": False,
                "finished": True,
                "opponent_move": None,
                "feedback": result.feedback,
                "fen": state.board.fen(),
            }

        # Correct move
        opponent_move = None
        opponent_idx = expected_idx + 1
        if opponent_idx < len(solution):
            opp = solution[opponent_idx]
            opponent_move = opp.uci()
            state.board.push(opp)

        state.move_index += 1

        if is_last_user_move:
            # All moves correct — build full user_moves for submit
            state.submitted = True
            user_moves = [solution[i] for i in user_move_indices]
            result, _ = self._session.submit(user_moves, 0)
            return {
                "valid": True,
                "correct": True,
                "finished": True,
                "opponent_move": opponent_move,
                "feedback": result.feedback,
                "fen": state.board.fen(),
            }

        # More moves to go
        return {
            "valid": True,
            "correct": True,
            "finished": False,
            "opponent_move": opponent_move,
            "feedback": "Correct! Keep going...",
            "fen": state.board.fen(),
        }

    def rate(self, rating_value: int) -> dict:
        """Apply a rating to the current exercise.

        Args:
            rating_value: FSRS rating (1=Again, 2=Hard, 3=Good, 4=Easy).

        Returns:
            Dict with next_review and card state info.
        """
        if not self._session:
            return {"error": "No active session"}

        rating = Rating(rating_value)

        # If no submit was done (self-report mode), update stats
        if self._exercise_state and not self._exercise_state.submitted:
            if rating >= Rating.GOOD:
                self._session.stats.correct += 1
            elif rating == Rating.HARD:
                self._session.stats.partial += 1
            else:
                self._session.stats.incorrect += 1

        updated_card = self._session.rate(rating)

        from datetime import datetime

        delta = updated_card.due - datetime.now()
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            next_review = "now"
        elif delta.days > 0:
            next_review = f"{delta.days} days"
        elif total_seconds > 3600:
            next_review = f"{total_seconds // 3600} hours"
        else:
            next_review = f"{max(1, total_seconds // 60)} minutes"

        return {
            "next_review": next_review,
            "card_state": updated_card.state.name,
            "remaining": self._session.remaining,
        }

    def get_solution_info(self) -> dict | None:
        """Get solution info for the current exercise."""
        if not self._exercise_state:
            return None
        ex = self._exercise_state.exercise
        solution = ex.get_solution()
        # Build SAN solution line
        board = chess.Board(ex.fen)
        san_moves = []
        for move in solution:
            san_moves.append(board.san(move))
            board.push(move)
        return {
            "solution_san": " ".join(san_moves),
            "explanation": ex.get_explanation(),
            "solution_uci": [m.uci() for m in solution],
            "final_fen": board.fen(),
        }

    def end_session(self) -> SessionStats | None:
        """End the current session and return stats."""
        stats = None
        if self._session:
            stats = self._session.end()
        self._session = None
        self._exercise_state = None
        self._close_repo()
        return stats

    def get_stats(self) -> dict:
        """Get overall statistics from the database."""
        repo = self._open_repo()
        exercise_count = repo.exercises.count()
        card_stats = repo.cards.get_stats()
        return {
            "exercise_count": exercise_count,
            **card_stats,
        }

    def _get_analytics_store(self):
        """Get an AnalyticsStore instance."""
        from ..analytics import AnalyticsStore

        repo = self._open_repo()
        return AnalyticsStore(repo.conn)

    def get_accuracy_trend(
        self,
        days: int = 30,
        granularity: str = "day",
        exercise_type: str | None = None,
    ) -> dict:
        """Get accuracy trend data for the web API."""
        store = self._get_analytics_store()
        trend = store.accuracy_trend(
            granularity=granularity, exercise_type=exercise_type, days=days
        )
        return {
            "labels": [str(p.period) for p in trend.points],
            "datasets": [
                {
                    "total_reviews": p.total_reviews,
                    "correct_count": p.correct_count,
                    "accuracy": p.accuracy,
                }
                for p in trend.points
            ],
            "overall_accuracy": trend.overall_accuracy,
            "total_reviews": trend.total_reviews,
        }

    def get_weak_areas(self, min_reviews: int = 5, limit: int = 20) -> dict:
        """Get weak areas data for the web API."""
        store = self._get_analytics_store()
        areas = store.weak_areas(min_reviews=min_reviews, limit=limit)
        return {
            "areas": [
                {
                    "name": a.name,
                    "category": a.category,
                    "total_reviews": a.total_reviews,
                    "correct_count": a.correct_count,
                    "accuracy": a.accuracy,
                    "avg_lapses": a.avg_lapses,
                    "card_count": a.card_count,
                }
                for a in areas
            ]
        }

    def get_streaks(self, lookback_days: int = 90) -> dict:
        """Get streak data for the web API."""
        store = self._get_analytics_store()
        info = store.streaks(lookback_days=lookback_days)
        return {
            "current_streak": info.current_streak,
            "longest_streak": info.longest_streak,
            "total_active_days": info.total_active_days,
            "daily_activity": [
                {"day": str(a.day), "review_count": a.review_count} for a in info.daily_activity
            ],
        }

    def get_retention_curve(self) -> dict:
        """Get retention curve data for the web API."""
        store = self._get_analytics_store()
        points = store.retention_curve()
        return {
            "labels": [str(p.reps) for p in points],
            "datasets": [
                {
                    "reps": p.reps,
                    "card_count": p.card_count,
                    "avg_stability_days": p.avg_stability_days,
                    "actual_recall_rate": p.actual_recall_rate,
                    "predicted_retrievability": p.predicted_retrievability,
                }
                for p in points
            ],
        }
