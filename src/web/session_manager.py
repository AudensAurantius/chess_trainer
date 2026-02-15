"""Server-side training session state management."""

from dataclasses import dataclass, field
from datetime import datetime
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
    used_my_move_hint: bool = False
    used_notes_hint: bool = False

    def __post_init__(self) -> None:
        """Initialize the working board from FEN."""
        if self.board is None:
            self.board = chess.Board(self.fen)


class SessionManager:
    """Manages the training session lifecycle for the web interface.

    Each instance is tied to a single database file. In multi-tenant
    mode, the ManagerPool creates one per authenticated user.
    """

    def __init__(self, config: AppConfig, db_path: Path | None = None) -> None:
        """Initialize session manager with app config.

        Args:
            config: Application configuration.
            db_path: Override database path. Uses ``config.database.path`` if None.
        """
        self.config = config
        self._db_path = db_path or Path(config.database.path)
        self._session: TrainingSession | None = None
        self._woodpecker_session = None
        self._repo: Repository | None = None
        self._exercise_state: ExerciseState | None = None
        self._hook_manager = None
        self._daily_goal_fired = False

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

    @property
    def hide_exercise_type(self) -> bool:
        """Whether exercise type labels are hidden."""
        return getattr(self, "_hide_exercise_type", False)

    @property
    def elapsed_minutes(self) -> float | None:
        """Minutes elapsed since session start, or None if no session."""
        start = getattr(self, "_session_start_time", None)
        if start is None:
            return None
        return (datetime.now() - start).total_seconds() / 60

    @property
    def remaining_minutes(self) -> float | None:
        """Minutes remaining in a duration-limited session, or None if unlimited."""
        limit = getattr(self, "_max_duration_minutes", None)
        if limit is None:
            return None
        elapsed = self.elapsed_minutes
        if elapsed is None:
            return None
        return max(0.0, limit - elapsed)

    def _open_repo(self) -> Repository:
        """Open (or reuse) the repository connection."""
        if self._repo is None:
            self._repo = Repository(self._db_path)
            self._repo.__enter__()
        return self._repo

    def _close_repo(self) -> None:
        """Close the repository connection."""
        if self._repo is not None:
            self._repo.__exit__(None, None, None)
            self._repo = None

    @property
    def hooks(self):
        """Lazy-initialized HookManager."""
        if self._hook_manager is None:
            from ..hooks import HookManager

            self._hook_manager = HookManager(self.config.hooks)
        return self._hook_manager

    def _fire_hook(self, event, payload: dict) -> None:
        """Fire a hook, swallowing all errors to never block training."""
        try:
            self.hooks.fire(event, payload)
        except Exception:  # noqa: BLE001
            pass  # Hook failures must never block the session

    def _check_daily_goal(self) -> None:
        """Check if the daily review goal has been met and fire hook once."""
        goal = self.config.training.daily_review_goal
        if goal is None or self._daily_goal_fired:
            return

        from datetime import date

        from ..hooks.events import HookEvent, daily_goal_met_payload

        try:
            store = self._get_analytics_store()
            streak_info = store.streaks(lookback_days=1)
            today = date.today()
            today_count = 0
            for day_activity in streak_info.daily_activity:
                if day_activity.day == today:
                    today_count = day_activity.review_count
                    break
            if today_count >= goal:
                self._daily_goal_fired = True
                self._fire_hook(
                    HookEvent.ON_DAILY_GOAL_MET,
                    daily_goal_met_payload(reviews_today=today_count, goal=goal),
                )
        except Exception:  # noqa: BLE001
            pass

    def _check_streak_milestone(self) -> None:
        """Check if a streak milestone has been reached and fire hook."""
        from ..hooks.events import STREAK_MILESTONES, HookEvent, streak_milestone_payload

        try:
            store = self._get_analytics_store()
            streak_info = store.streaks(lookback_days=400)
            current = streak_info.current_streak
            if current in STREAK_MILESTONES:
                self._fire_hook(
                    HookEvent.ON_STREAK_MILESTONE,
                    streak_milestone_payload(streak_days=current),
                )
        except Exception:  # noqa: BLE001
            pass

    @property
    def training_mode(self) -> str:
        """Current training mode ('study' or 'test')."""
        return getattr(self, "_training_mode", "study")

    def start_session(
        self,
        max_new: int | None = None,
        max_reviews: int | None = None,
        include_tags: list[str] | None = None,
        adapt_difficulty: bool | None = None,
        hide_exercise_type: bool = False,
        exercise_types: list[str] | None = None,
        max_duration_minutes: int | None = None,
        training_mode: str | None = None,
    ) -> int:
        """Start a new training session.

        Args:
            max_new: Override max new cards (uses config default if None).
            max_reviews: Override max reviews (uses config default if None).
            include_tags: Optional list of tags to filter exercises by.
            adapt_difficulty: Override difficulty adaptation (uses config default if None).
            hide_exercise_type: Whether to hide exercise type labels.
            exercise_types: Optional list of exercise type names to filter by.
            max_duration_minutes: Session duration limit in minutes (None = unlimited).
            training_mode: 'study' or 'test' (uses config default if None).

        Returns:
            Number of cards in the queue.
        """
        from ..exercises import ExerciseType

        # Close any existing session
        self.end_session()

        self._hide_exercise_type = hide_exercise_type
        self._session_start_time = datetime.now()
        self._max_duration_minutes = max_duration_minutes
        self._training_mode = training_mode or self.config.training.default_mode

        # Parse exercise type names to enum values
        type_filter = None
        if exercise_types:
            type_filter = []
            for name in exercise_types:
                try:
                    type_filter.append(ExerciseType[name.upper()])
                except KeyError:
                    pass  # Silently skip unknown types
            type_filter = type_filter or None

        repo = self._open_repo()
        session_config = SessionConfig(
            max_new_cards=max_new or self.config.training.max_new_cards,
            max_reviews=max_reviews or self.config.training.max_reviews,
            interleave_new=self.config.training.interleave_new,
            include_tags=include_tags,
            exercise_types=type_filter,
            max_duration_minutes=max_duration_minutes,
            hide_exercise_type=hide_exercise_type,
        )

        # Apply difficulty adaptation if enabled
        should_adapt = (
            adapt_difficulty if adapt_difficulty is not None else (self.config.difficulty.enabled)
        )
        if should_adapt:
            from ..training.difficulty import DifficultyAdapter

            adapter = DifficultyAdapter(repo.conn, self.config.difficulty)
            difficulty_range = adapter.compute_range()
            if difficulty_range is not None:
                session_config.min_difficulty = difficulty_range.min_difficulty
                session_config.max_difficulty = difficulty_range.max_difficulty

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

        # For own-game exercises: accept near-optimal first moves
        from ..exercises.tactics import TacticExercise

        if not is_correct_move and user_step == 0:
            ex = state.exercise
            if isinstance(ex, TacticExercise) and move_uci in ex.acceptable_first_moves:
                is_correct_move = True

        # Determine effective number of user moves to check
        effective_user_moves = len(user_move_indices)
        if isinstance(state.exercise, TacticExercise) and state.exercise.evaluate_depth is not None:
            effective_user_moves = min(effective_user_moves, state.exercise.evaluate_depth)
        is_last_user_move = user_step == effective_user_moves - 1

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
            user_moves = [solution[i] for i in user_move_indices[:effective_user_moves]]
            result, _ = self._session.submit(user_moves, 0)

            # Apply hint penalties: demote correct → partial (max one demotion)
            if result.correct and (state.used_my_move_hint or state.used_notes_hint):
                self._session.stats.correct -= 1
                self._session.stats.partial += 1

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

        # Fire on_exercise_complete hook
        if self._exercise_state:
            from ..hooks.events import HookEvent, exercise_complete_payload

            ex = self._exercise_state.exercise
            self._fire_hook(
                HookEvent.ON_EXERCISE_COMPLETE,
                exercise_complete_payload(
                    exercise_id=ex.id,
                    exercise_type=ex.exercise_type.name,
                    rating=rating_value,
                    correct=rating >= Rating.GOOD,
                ),
            )
        self._check_daily_goal()

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

    def get_played_move(self) -> dict | None:
        """Get the user's original played move for own-game exercises.

        Returns the move from ``played_move_uci`` in exercise metadata, or
        ``None`` if unavailable. Marks the exercise state so a scoring
        penalty is applied on submit.
        """
        if not self._exercise_state:
            return None
        ex = self._exercise_state.exercise
        played_uci = ex.metadata.get("played_move_uci")
        if not played_uci:
            return None

        # Mark the hint as used (scoring penalty applied on submit)
        self._exercise_state.used_my_move_hint = True

        # Build SAN and from/to for UI highlighting
        board = chess.Board(ex.fen)
        try:
            move = chess.Move.from_uci(played_uci)
            played_san = board.san(move)
        except (chess.InvalidMoveError, ValueError):
            played_san = played_uci

        return {
            "played_move_uci": played_uci,
            "played_move_san": played_san,
            "from": played_uci[:2],
            "to": played_uci[2:4],
        }

    def get_exercise_notes(self) -> dict:
        """Get notes for the current exercise.

        In study mode, returns the notes text directly. In test mode,
        only indicates whether notes exist (must call ``reveal_notes``
        to view them).

        Returns:
            Dict with ``has_notes`` and optionally ``notes`` text.
        """
        if not self._exercise_state:
            return {"has_notes": False}
        notes = self._exercise_state.exercise.notes
        has = notes is not None and notes != ""
        result: dict = {"has_notes": has}
        if has and self.training_mode == "study":
            result["notes"] = notes
        return result

    def reveal_notes(self) -> dict:
        """Reveal notes in test mode, marking the hint as used.

        Returns:
            Dict with ``notes`` text (or ``None``).
        """
        if not self._exercise_state:
            return {"notes": None}
        notes = self._exercise_state.exercise.notes
        if notes is not None and notes != "":
            self._exercise_state.used_notes_hint = True
        return {"notes": notes}

    def save_exercise_notes(self, exercise_id: str, notes: str | None) -> bool:
        """Persist notes to the database and update in-memory state.

        Args:
            exercise_id: The exercise ID to annotate.
            notes: Notes text, or ``None`` to clear.

        Returns:
            True if the exercise was found and updated.
        """
        repo = self._open_repo()
        result = repo.exercises.update_notes(exercise_id, notes)
        # Also update in-memory exercise if it's the current one
        if result and self._exercise_state:
            if self._exercise_state.exercise.id == exercise_id:
                self._exercise_state.exercise.notes = notes
        return result

    def end_session(self) -> SessionStats | None:
        """End the current session and return stats."""
        stats = None
        if self._session:
            stats = self._session.end()

            # Fire on_session_end hook
            from ..hooks.events import HookEvent, session_end_payload

            total = stats.correct + stats.incorrect + stats.partial
            accuracy = stats.correct / total if total > 0 else 0.0
            elapsed = self.elapsed_minutes
            self._fire_hook(
                HookEvent.ON_SESSION_END,
                session_end_payload(
                    total_reviewed=total,
                    correct=stats.correct,
                    incorrect=stats.incorrect,
                    partial=stats.partial,
                    accuracy=accuracy,
                    duration_seconds=elapsed * 60 if elapsed else None,
                ),
            )
            self._check_streak_milestone()

        self._session = None
        self._exercise_state = None
        self._daily_goal_fired = False
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

    # ── Import support ──────────────────────────────────────────────────────

    def _create_cards_and_tags(self, source: str) -> int:
        """Create review cards and sync tags for exercises from a source.

        Iterates all exercises matching the given source, ensures each has a
        review card, and syncs any tags from the exercise to the tag store.

        Args:
            source: Exercise source name to filter by.

        Returns:
            Number of new cards created (cards with reps == 0).
        """
        from ..storage.tag_store import EntityType, TagSource

        repo = self._open_repo()
        cards_created = 0
        for exercise in repo.exercises.search(source=source):
            card = repo.cards.get_or_create(exercise.id)
            if card.reps == 0:
                cards_created += 1
            if exercise.tags:
                repo.tags.add_tags(
                    EntityType.EXERCISE, exercise.id, exercise.tags, TagSource.SYSTEM
                )
        return cards_created

    def _import_result(self, result, source: str) -> dict:
        """Build a standard import result dict with card creation."""
        cards_created = self._create_cards_and_tags(source)

        # Fire on_import_complete hook
        from ..hooks.events import HookEvent, import_complete_payload

        self._fire_hook(
            HookEvent.ON_IMPORT_COMPLETE,
            import_complete_payload(
                source=source,
                added=result.total_added,
                skipped=result.total_skipped,
                errors=len(result.errors),
            ),
        )

        return {
            "added": result.total_added,
            "skipped": result.total_skipped,
            "errors": len(result.errors),
            "cards_created": cards_created,
        }

    def import_lichess_puzzles(
        self,
        count: int = 20,
        difficulty: str | None = None,
        themes: list[str] | None = None,
    ) -> dict:
        """Import puzzles from Lichess, create cards, and sync tags.

        Args:
            count: Number of puzzles to fetch (max 100).
            difficulty: Optional difficulty filter.
            themes: Optional list of tactical themes.

        Returns:
            Dict with added, skipped, errors, cards_created counts.
        """
        from ..importers.lichess_puzzles import LichessPuzzleImporter

        count = min(count, 100)
        repo = self._open_repo()
        importer = LichessPuzzleImporter()
        result = importer.import_to(
            repo.exercises, count=count, difficulty=difficulty, themes=themes
        )
        return self._import_result(result, "lichess")

    def import_lichess_failed_puzzles(
        self,
        count: int = 50,
        since: str | None = None,
        auto_tag: bool = True,
    ) -> dict:
        """Import previously failed Lichess puzzles, create cards, and sync tags.

        Requires a Lichess API token with puzzle:read scope.

        Args:
            count: Number of failed puzzles to fetch (max 100).
            since: Time horizon string (e.g. "3 months", "30 days").
            auto_tag: Whether to auto-tag with failed-puzzle/needs-review.

        Returns:
            Dict with added, skipped, errors, cards_created counts.
        """
        from ..importers.lichess_puzzles import LichessPuzzleImporter

        count = min(count, 100)
        repo = self._open_repo()
        importer = LichessPuzzleImporter()
        result = importer.import_to_failed(
            repo.exercises, count=count, since=since, auto_tag=auto_tag
        )
        return self._import_result(result, "lichess")

    def has_lichess_token(self) -> bool:
        """Check whether a Lichess API token is configured."""
        from ..lichess.constants import LICHESS_TOKEN

        return bool(self.config.lichess.token or LICHESS_TOKEN)

    def import_lichess_games(
        self,
        username: str,
        max_games: int = 10,
        color: str | None = None,
        perf_type: str | None = None,
        rated: bool | None = None,
    ) -> dict:
        """Import exercises from Lichess game analysis using server evals.

        No local engine required — uses Lichess server-side evaluations.

        Args:
            username: Lichess username to fetch games for.
            max_games: Maximum number of games to process (max 50).
            color: Only analyze games where user played this color.
            perf_type: Filter by speed (blitz, rapid, classical, etc.).
            rated: Filter for rated/unrated games.

        Returns:
            Dict with added, skipped, errors, cards_created counts.
        """
        from ..analysis.classification import MoveClassification
        from ..importers.games import GameImporter

        max_games = min(max_games, 50)
        ga = self.config.game_analysis
        oge = self.config.own_game_eval

        importer = GameImporter(
            engine=None,
            depth=ga.analysis_depth,
            min_classification=MoveClassification[ga.min_classification.upper()],
            max_exercises=ga.max_exercises_per_game,
            skip_first_plies=ga.skip_first_plies,
            cp_tolerance=oge.cp_tolerance,
            multipv_count=oge.multipv_count,
            evaluate_depth=oge.evaluate_depth,
        )

        repo = self._open_repo()
        result = importer.import_to(
            repo.exercises,
            username=username,
            use_server_evals=True,
            max_games=max_games,
            color=color,
            perf_type=perf_type,
            rated=rated,
        )
        return self._import_result(result, "game_analysis")

    def import_chesscom_puzzles(
        self,
        count: int = 20,
        include_daily: bool = True,
    ) -> dict:
        """Import puzzles from Chess.com, create cards, and sync tags.

        Args:
            count: Number of puzzles to fetch (max 100).
            include_daily: Whether to include the daily puzzle.

        Returns:
            Dict with added, skipped, errors, cards_created counts.
        """
        from ..importers.chesscom_puzzles import ChessComPuzzleImporter

        count = min(count, 100)
        repo = self._open_repo()
        importer = ChessComPuzzleImporter()
        result = importer.import_to(repo.exercises, count=count, include_daily=include_daily)
        return self._import_result(result, "chesscom")

    def import_lichess_study(self, study_url: str, color: str) -> dict:
        """Import opening lines from a Lichess study, sync exercises.

        Args:
            study_url: Lichess study URL or 8-char ID.
            color: Side: "white" or "black".

        Returns:
            Dict with lines_added, lines_updated, chapters, skipped_chapters,
            exercises_created counts.

        Raises:
            ValueError: If color is invalid or study URL cannot be parsed.
        """
        from ..lichess.api import get_study_pgn
        from ..openings.book import (
            BookError,
            generate_exercises,
            import_study_lines,
            parse_study_id,
            parse_study_pgn,
        )
        from ..openings.models import BookColor

        try:
            book_color = BookColor(color.lower())
        except ValueError:
            raise ValueError(f"Invalid color: {color}. Use 'white' or 'black'.") from None

        try:
            study_id = parse_study_id(study_url)
        except BookError as e:
            raise ValueError(str(e)) from e

        pgn_text = get_study_pgn(study_id)
        chapters = parse_study_pgn(pgn_text)

        if not chapters:
            return {
                "lines_added": 0,
                "lines_updated": 0,
                "chapters": 0,
                "skipped_chapters": 0,
                "exercises_created": 0,
            }

        lines = import_study_lines(study_id, chapters, book_color)
        skipped = sum(1 for ch in chapters if ch.skipped)

        repo = self._open_repo()
        added = 0
        updated = 0
        for line in lines:
            existing = repo.openings.get_line(line.id)
            if existing:
                repo.openings.update_line(line)
                updated += 1
            else:
                repo.openings.add_line(line)
                added += 1

        # Sync exercises
        exercises_created = 0
        for line in lines:
            for exercise in generate_exercises(line):
                existing_ex = repo.exercises.get(exercise.id)
                if not existing_ex:
                    repo.exercises.add(exercise)
                    repo.cards.get_or_create(exercise.id)
                    exercises_created += 1

        return {
            "lines_added": added,
            "lines_updated": updated,
            "chapters": len(chapters),
            "skipped_chapters": skipped,
            "exercises_created": exercises_created,
        }

    # ── Bundle session support ─────────────────────────────────────────────

    def list_bundles(self) -> list[dict]:
        """List all bundles with progress info."""
        repo = self._open_repo()
        bundles = repo.bundles.list_all()
        result = []
        for b in bundles:
            progress = repo.bundles.get_progress(b.id)
            result.append(
                {
                    "id": b.id,
                    "slug": b.slug,
                    "name": b.name,
                    "description": b.description,
                    "exercise_count": b.exercise_count,
                    "woodpecker_mode": b.config.woodpecker_mode,
                    "current_cycle": progress.current_cycle if progress else 1,
                    "completed_cycles": len(progress.completed_cycles) if progress else 0,
                }
            )
        return result

    def start_bundle_session(self, slug: str) -> dict:
        """Start a bundle training session.

        Args:
            slug: The bundle slug.

        Returns:
            Dict with session info.
        """
        from ..exercises.bundle import generate_bundle_id, validate_slug
        from ..training.woodpecker import WoodpeckerSession

        # End any existing training session but keep the repo open
        self._session = None
        self._woodpecker_session = None
        self._exercise_state = None
        repo = self._open_repo()

        validated = validate_slug(slug)
        bundle_id = generate_bundle_id(validated)
        bundle = repo.bundles.get(bundle_id)
        if bundle is None:
            return {"error": f"Bundle not found: {slug}"}

        if not bundle.exercise_ids:
            return {"error": f"Bundle '{slug}' has no exercises"}

        progress = repo.bundles.get_progress(bundle_id)
        self._woodpecker_session = WoodpeckerSession(repo, bundle, progress)
        self._woodpecker_session.start()

        return {
            "status": "started",
            "bundle": bundle.name,
            "queue_size": self._woodpecker_session.remaining,
            "cycle": self._woodpecker_session.progress.current_cycle,
            "time_limit": self._woodpecker_session.time_limit,
        }

    def get_bundle_time_limit(self) -> int | None:
        """Get the current bundle session time limit."""
        if hasattr(self, "_woodpecker_session") and self._woodpecker_session:
            return self._woodpecker_session.time_limit
        return None

    def next_bundle_exercise(self) -> ExerciseState | None:
        """Get the next exercise from the bundle session."""
        if not hasattr(self, "_woodpecker_session") or not self._woodpecker_session:
            return None

        ws = self._woodpecker_session
        exercise = ws.next()
        if exercise is None:
            self._exercise_state = None
            return None

        solution = exercise.get_solution()
        solution_uci = [m.uci() for m in solution]

        self._exercise_state = ExerciseState(
            exercise=exercise,
            fen=exercise.fen,
            side_to_move=exercise.side_to_move,
            challenge=exercise.get_challenge(),
            solution_uci=solution_uci,
        )
        return self._exercise_state

    def submit_bundle_move(self, move_uci: str) -> dict:
        """Submit a move for the current bundle exercise."""
        if not hasattr(self, "_woodpecker_session") or not self._woodpecker_session:
            return {"valid": False, "feedback": "No active bundle session"}

        if not self._exercise_state:
            return {"valid": False, "feedback": "No active exercise"}

        state = self._exercise_state
        solution = state.exercise.get_solution()
        user_move_indices = list(range(0, len(solution), 2))

        user_step = state.move_index
        if user_step >= len(user_move_indices):
            return {"valid": False, "feedback": "Exercise already complete"}

        expected_idx = user_move_indices[user_step]
        expected_move = solution[expected_idx]

        try:
            move = chess.Move.from_uci(move_uci)
        except (chess.InvalidMoveError, ValueError):
            return {"valid": False, "feedback": "Invalid move format"}

        if move not in state.board.legal_moves:
            return {"valid": False, "feedback": "Illegal move"}

        state.board.push(move)
        is_correct_move = move == expected_move
        is_last_user_move = user_step == len(user_move_indices) - 1

        ws = self._woodpecker_session

        if not is_correct_move:
            state.submitted = True
            user_moves = [solution[user_move_indices[i]] for i in range(user_step)]
            user_moves.append(move)
            result, over_time = ws.submit(user_moves, 0)
            return {
                "valid": True,
                "correct": False,
                "finished": True,
                "over_time": over_time,
                "opponent_move": None,
                "feedback": result.feedback,
                "fen": state.board.fen(),
            }

        opponent_move = None
        opponent_idx = expected_idx + 1
        if opponent_idx < len(solution):
            opp = solution[opponent_idx]
            opponent_move = opp.uci()
            state.board.push(opp)

        state.move_index += 1

        if is_last_user_move:
            state.submitted = True
            user_moves = [solution[i] for i in user_move_indices]
            result, over_time = ws.submit(user_moves, 0)
            return {
                "valid": True,
                "correct": True,
                "finished": True,
                "over_time": over_time,
                "opponent_move": opponent_move,
                "feedback": result.feedback,
                "fen": state.board.fen(),
            }

        return {
            "valid": True,
            "correct": True,
            "finished": False,
            "over_time": False,
            "opponent_move": opponent_move,
            "feedback": "Correct! Keep going...",
            "fen": state.board.fen(),
        }

    def rate_bundle(self, rating_value: int) -> dict:
        """Apply a rating in the bundle session."""
        if not hasattr(self, "_woodpecker_session") or not self._woodpecker_session:
            return {"error": "No active bundle session"}

        from ..scheduling.fsrs import Rating

        rating = Rating(rating_value)
        ws = self._woodpecker_session
        ws.rate(rating)

        # Fire on_exercise_complete hook for bundle exercises
        if self._exercise_state:
            from ..hooks.events import HookEvent, exercise_complete_payload

            ex = self._exercise_state.exercise
            self._fire_hook(
                HookEvent.ON_EXERCISE_COMPLETE,
                exercise_complete_payload(
                    exercise_id=ex.id,
                    exercise_type=ex.exercise_type.name,
                    rating=rating_value,
                    correct=rating >= Rating.GOOD,
                ),
            )

        return {
            "remaining": ws.remaining,
            "cycle": ws.progress.current_cycle,
        }

    def end_bundle_session(self) -> dict | None:
        """End the bundle session and return cycle result."""
        if not hasattr(self, "_woodpecker_session") or not self._woodpecker_session:
            return None

        ws = self._woodpecker_session
        cycle_result = ws.end_cycle()
        self._woodpecker_session = None
        self._exercise_state = None

        # Fire on_bundle_cycle_complete hook
        from ..hooks.events import HookEvent, bundle_cycle_complete_payload

        bundle_id = ws.bundle.id if hasattr(ws, "bundle") else "unknown"
        self._fire_hook(
            HookEvent.ON_BUNDLE_CYCLE_COMPLETE,
            bundle_cycle_complete_payload(
                bundle_id=bundle_id,
                cycle_number=cycle_result.cycle_number,
                accuracy=cycle_result.accuracy,
                passed=cycle_result.passed,
            ),
        )

        return {
            "cycle_number": cycle_result.cycle_number,
            "accuracy": cycle_result.accuracy,
            "passed": cycle_result.passed,
            "exercises_attempted": cycle_result.exercises_attempted,
            "exercises_correct": cycle_result.exercises_correct,
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
