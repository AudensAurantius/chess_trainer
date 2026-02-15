"""Main CLI application using Typer."""

import time
from datetime import UTC, datetime
from pathlib import Path

import chess
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .. import __version__, configure_logging
from ..config import DEFAULT_CONFIG_PATH, AppConfig, load_config
from ..exercises import Exercise, ExerciseType
from ..importers import LichessPuzzleImporter
from ..scheduling.fsrs import Rating
from ..storage import Repository
from ..training import SessionConfig, TrainingSession
from .board import format_solution_line, render_board

app = typer.Typer(
    name="chess-trainer",
    help="Spaced repetition training for chess improvement",
    no_args_is_help=True,
)
console = Console()

# Loaded once on startup via the callback
_app_config: AppConfig | None = None


def _get_config() -> AppConfig:
    """Return the loaded app config, falling back to defaults."""
    return _app_config or load_config()


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"chess-trainer {__version__}")
        raise typer.Exit()


@app.callback()
def _main_callback(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config TOML"),
    version: bool = typer.Option(  # noqa: ARG001
        False,
        "--version",
        "-V",
        help="Show version and exit",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Global options applied before any subcommand."""
    global _app_config  # noqa: PLW0603
    _app_config = load_config(config)
    configure_logging(_app_config.logging.level)


def get_repo(db_path: Path | None = None) -> Repository:
    """Get repository with default or specified path."""
    cfg = _get_config()
    return Repository(db_path or Path(cfg.database.path))


@app.command()
def import_puzzles(
    count: int = typer.Option(20, "--count", "-n", help="Number of puzzles to import"),
    difficulty: str | None = typer.Option(
        None,
        "--difficulty",
        "-d",
        help="Difficulty filter (easiest, easier, normal, harder, hardest)",
    ),
    theme: str | None = typer.Option(None, "--theme", "-t", help="Tactical theme filter"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Import tactical puzzles from Lichess."""
    with get_repo(db) as repo:
        importer = LichessPuzzleImporter()

        themes = [theme] if theme else None

        with console.status(f"Importing {count} puzzles from Lichess..."):
            result = importer.import_to(
                repo.exercises,
                count=count,
                difficulty=difficulty,
                themes=themes,
            )

        console.print(f"\n[green]\u2713[/green] {result}")

        # Sync system tags to the normalized tags table
        if result.total_added > 0:
            _sync_system_tags(repo, source="lichess")

        if result.errors:
            console.print("[yellow]Errors:[/yellow]")
            for error in result.errors[:5]:
                console.print(f"  - {error}")


@app.command("import-chesscom-puzzles")
def import_chesscom_puzzles(
    count: int = typer.Option(10, "--count", "-n", help="Number of random puzzles to import"),
    daily: bool = typer.Option(True, "--daily/--no-daily", help="Include today's daily puzzle"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Import puzzles from Chess.com."""
    from ..importers.chesscom_puzzles import ChessComPuzzleImporter

    cfg = _get_config()
    importer = ChessComPuzzleImporter(user_agent=cfg.chesscom.user_agent)

    with get_repo(db) as repo:
        with console.status("Importing puzzles from Chess.com..."):
            result = importer.import_to(
                repo.exercises,
                count=count,
                include_daily=daily,
            )

        console.print(f"\n[green]\u2713[/green] {result}")

        # Create review cards for new exercises
        if result.total_added > 0:
            for exercise in repo.exercises.search(source="chesscom"):
                existing = repo.cards.get(exercise.id)
                if not existing:
                    repo.cards.get_or_create(exercise.id)
            _sync_system_tags(repo, source="chesscom")

        if result.errors:
            console.print("[yellow]Errors:[/yellow]")
            for error in result.errors[:5]:
                console.print(f"  - {error}")


@app.command("import-failed-puzzles")
def import_failed_puzzles(
    count: int = typer.Option(50, "--count", "-n", help="Maximum number of failed puzzles"),
    since: str | None = typer.Option(
        None,
        "--since",
        "-s",
        help='Time horizon: "3 months", "30 days", "2025-01-01"',
    ),
    no_tag: bool = typer.Option(False, "--no-tag", help="Skip auto-tagging"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Import puzzles you previously failed on Lichess.

    Requires a Lichess API token with puzzle:read scope.
    Set via LICHESS_TOKEN environment variable or config.
    """
    cfg = _get_config()

    # Use config default horizon if --since not provided
    effective_since = since or cfg.import_settings.failed_puzzle_default_horizon
    auto_tag = cfg.import_settings.failed_puzzle_auto_tag and not no_tag

    with get_repo(db) as repo:
        importer = LichessPuzzleImporter()

        with console.status(f"Importing failed puzzles from Lichess (since {effective_since})..."):
            result = importer.import_to_failed(
                repo.exercises,
                count=count,
                since=effective_since,
                auto_tag=auto_tag,
            )

        console.print(f"\n[green]\u2713[/green] {result}")

        if result.total_added > 0:
            _sync_system_tags(repo, source="lichess")

        if result.errors:
            console.print("[yellow]Errors:[/yellow]")
            for error in result.errors[:5]:
                console.print(f"  - {error}")


@app.command()
def stats(
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Show training statistics."""
    with get_repo(db) as repo:
        # Exercise counts
        table = Table(title="Exercise Library")
        table.add_column("Type", style="cyan")
        table.add_column("Count", justify="right")

        for ex_type in ExerciseType:
            count = repo.exercises.count(ex_type)
            if count > 0:
                table.add_row(ex_type.name.title(), str(count))

        total = repo.exercises.count()
        table.add_row("Total", str(total), style="bold")
        console.print(table)

        # Card statistics
        card_stats = repo.cards.get_stats()
        if card_stats["total_cards"] > 0:
            console.print()
            table = Table(title="Review Cards")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right")

            table.add_row("Total cards", str(card_stats["total_cards"]))
            table.add_row("Due now", str(card_stats["due_count"]))
            table.add_row("Total reviews", str(card_stats["total_reviews"]))
            table.add_row("Avg stability", f"{card_stats['average_stability_days']:.1f} days")

            for state, count in card_stats["state_counts"].items():
                table.add_row(f"  {state}", str(count))

            console.print(table)


def _sync_system_tags(repo: Repository, source: str) -> None:
    """Sync exercise JSON tags into the normalized tags table."""
    from ..storage.tag_store import EntityType, TagSource

    for exercise in repo.exercises.search(source=source):
        if exercise.tags:
            repo.tags.add_tags(EntityType.EXERCISE, exercise.id, exercise.tags, TagSource.SYSTEM)


def _parse_move(board: chess.Board, text: str) -> chess.Move | None:
    """Parse a move from user input (SAN or UCI notation)."""
    text = text.strip()
    if not text:
        return None

    # Try SAN first (e.g. "Nf3", "exd5", "O-O")
    try:
        return board.parse_san(text)
    except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
        pass

    # Try UCI (e.g. "e2e4", "g1f3")
    try:
        move = chess.Move.from_uci(text)
        if move in board.legal_moves:
            return move
    except chess.InvalidMoveError:
        pass

    return None


def _format_next_review(due: datetime) -> str:
    """Format the next review time relative to now."""
    delta = due - datetime.now()
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "now"
    elif delta.days > 0:
        return f"{delta.days} days"
    elif total_seconds > 3600:
        return f"{total_seconds // 3600} hours"
    else:
        return f"{max(1, total_seconds // 60)} minutes"


def _collect_moves(exercise: Exercise) -> tuple[list[chess.Move], int]:
    """Collect move(s) from the user for the current exercise.

    For tactics, the solution alternates user/opponent moves. We collect
    user moves one at a time, playing opponent responses automatically.

    Returns:
        Tuple of (moves_played, time_taken_ms).
    """
    board = exercise.position.copy()
    solution = exercise.get_solution()

    # For tactics: user plays odd moves (0, 2, 4...), opponent plays even (1, 3, 5...)
    user_move_indices = list(range(0, len(solution), 2))
    moves_played = []
    start_time = time.monotonic()

    for step, move_idx in enumerate(user_move_indices):
        if step > 0:
            # Show the board after opponent's response
            console.print()
            console.print(render_board(board, flipped=board.turn == chess.BLACK))

        # Prompt for user's move
        expected = solution[move_idx]
        prompt_text = "Your move" if len(user_move_indices) == 1 else f"Move {step + 1}"
        console.print(f"\n[bold]{prompt_text}:[/bold] ", end="")

        while True:
            text = input().strip()

            if text.lower() in ("q", "quit"):
                elapsed = int((time.monotonic() - start_time) * 1000)
                return moves_played, elapsed

            if text.lower() in ("h", "hint"):
                # Show which piece to move (source square)
                hint_sq = chess.square_name(expected.from_square)
                piece = board.piece_at(expected.from_square)
                piece_name = chess.piece_name(piece.piece_type) if piece else "piece"
                console.print(f"[yellow]Hint: move the {piece_name} on {hint_sq}[/yellow]")
                console.print(f"[bold]{prompt_text}:[/bold] ", end="")
                continue

            if text == "":
                # Empty input = give up, skip to reveal
                elapsed = int((time.monotonic() - start_time) * 1000)
                return moves_played, elapsed

            move = _parse_move(board, text)
            if move is None:
                console.print(
                    "[red]Invalid move. Use notation like Nf3, e4, or e2e4."
                    " 'h' for hint, Enter to give up.[/red]"
                )
                console.print(f"[bold]{prompt_text}:[/bold] ", end="")
                continue

            moves_played.append(move)

            if move != expected:
                # Wrong move - stop collecting
                elapsed = int((time.monotonic() - start_time) * 1000)
                return moves_played, elapsed

            # Correct move - apply it
            board.push(move)

            # Play opponent's response if there is one
            response_idx = move_idx + 1
            if response_idx < len(solution):
                response = solution[response_idx]
                response_san = board.san(response)
                board.push(response)
                console.print(f"[dim]Opponent plays: {response_san}[/dim]")
            break

    elapsed = int((time.monotonic() - start_time) * 1000)
    return moves_played, elapsed


@app.command()
def train(
    new_cards: int = typer.Option(10, "--new", "-n", help="Max new cards"),
    reviews: int = typer.Option(50, "--reviews", "-r", help="Max reviews"),
    exercise_type: str | None = typer.Option(None, "--type", "-t", help="Exercise type filter"),
    include_tag: list[str] | None = typer.Option(None, "--tag", help="Filter by tag (repeatable)"),
    exclude_tag: list[str] | None = typer.Option(
        None, "--exclude-tag", help="Exclude by tag (repeatable)"
    ),
    self_report: bool = typer.Option(
        False, "--self-report", "-s", help="Self-report mode (no move input)"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Start a training session."""
    with get_repo(db) as repo:
        # Parse exercise type filter
        type_filter = None
        if exercise_type:
            try:
                type_filter = [ExerciseType[exercise_type.upper()]]
            except KeyError:
                console.print(f"[red]Unknown exercise type: {exercise_type}[/red]")
                raise typer.Exit(1)

        cfg = _get_config()
        session_config = SessionConfig(
            max_new_cards=new_cards,
            max_reviews=reviews,
            exercise_types=type_filter,
            include_tags=include_tag or None,
            exclude_tags=exclude_tag or None,
            interleave_new=cfg.training.interleave_new,
        )

        session = TrainingSession(repo, session_config)
        session.start()

        if session.remaining == 0:
            console.print("[yellow]No cards due for review![/yellow]")
            console.print("Try importing some puzzles first: chess-trainer import-puzzles")
            return

        total = session.remaining
        console.print(f"\n[bold]Training Session[/bold] \u2014 {total} cards")
        if not self_report:
            console.print(
                "[dim]Type moves in SAN (Nf3) or UCI (g1f3)."
                " 'h' for hint, Enter to give up, 'q' to quit.[/dim]"
            )
        console.print()

        while True:
            exercise = session.next()
            if not exercise:
                break

            board = exercise.position
            num = session.stats.exercises_shown
            progress = f"Exercise {num}/{total}"

            # Show the board
            flipped = board.turn == chess.BLACK
            console.print(
                Panel.fit(
                    render_board(board, flipped=flipped),
                    title=progress,
                    subtitle=(
                        f"[dim]{exercise.exercise_type.name}"
                        f" | {', '.join(exercise.tags[:3]) or 'untagged'}[/dim]"
                    ),
                )
            )
            console.print(f"[bold]{exercise.get_challenge()}[/bold]")

            if self_report:
                # Self-report mode
                console.print("\n[dim]Think about your answer, then press Enter to reveal.[/dim]")
                input()

                console.print(f"\n[bold]Solution:[/bold] {exercise.get_explanation()}")

                # Show post-solution board
                post_board = board.copy()
                for move in exercise.get_solution():
                    post_board.push(move)
                console.print()
                console.print(
                    render_board(
                        post_board,
                        flipped=flipped,
                        last_move=(
                            exercise.get_solution()[-1] if exercise.get_solution() else None
                        ),
                    )
                )

                # Get self-rating
                while True:
                    rating_input = typer.prompt(
                        "\nHow did you do? [1=Again, 2=Hard, 3=Good, 4=Easy]",
                        type=int,
                        default=3,
                    )
                    if 1 <= rating_input <= 4:
                        break
                    console.print("[red]Please enter 1-4.[/red]")

                rating = Rating(rating_input)

                # Update stats based on self-report
                if rating >= Rating.GOOD:
                    session.stats.correct += 1
                elif rating == Rating.HARD:
                    session.stats.partial += 1
                else:
                    session.stats.incorrect += 1

            else:
                # Interactive mode: collect actual moves
                moves, time_ms = _collect_moves(exercise)

                if moves:
                    # Evaluate via the session
                    result, scheduling = session.submit(moves, time_ms)
                    rating = session.auto_rate(result)

                    # Show feedback
                    if result.correct:
                        console.print(f"\n[green bold]Correct![/green bold] {result.feedback}")
                    elif result.partial_credit > 0:
                        console.print(f"\n[yellow]Partially correct.[/yellow] {result.feedback}")
                    else:
                        console.print(f"\n[red]Incorrect.[/red] {result.feedback}")
                else:
                    # User gave up (empty input or quit)
                    result, scheduling = session.submit([], 0)
                    rating = Rating.AGAIN

                # Show solution and explanation
                solution_line = format_solution_line(board, exercise.get_solution())
                console.print(f"\n[bold]Solution:[/bold] {solution_line}")
                explanation = exercise.get_explanation()
                if explanation != f"Solution: {solution_line}":
                    console.print(f"[dim]{explanation}[/dim]")

                # Show board after solution
                post_board = board.copy()
                last_move = None
                for move in exercise.get_solution():
                    last_move = move
                    post_board.push(move)
                console.print()
                console.print(render_board(post_board, flipped=flipped, last_move=last_move))

                # Let user override the auto-rating
                console.print(
                    f"[dim]Auto-rated: {rating.name} "
                    f"(press Enter to accept, or type 1-4 to override)[/dim]"
                )
                override = input().strip()
                if override in ("1", "2", "3", "4"):
                    rating = Rating(int(override))

            updated_card = session.rate(rating)

            next_review = _format_next_review(updated_card.due)
            console.print(f"[green]\u2192 Next review in: {next_review}[/green]\n")

            if session.remaining > 0:
                continue_training = typer.confirm("Continue?", default=True)
                if not continue_training:
                    break

        # End session and show stats
        final_stats = session.end()

        console.print("\n" + "=" * 40)
        console.print(
            Panel(
                f"Exercises: {final_stats.exercises_shown}\n"
                f"Correct: {final_stats.correct}"
                f" | Partial: {final_stats.partial}"
                f" | Incorrect: {final_stats.incorrect}\n"
                f"Accuracy: {final_stats.accuracy:.1f}%\n"
                f"Duration: {final_stats.duration_minutes:.1f} minutes",
                title="Session Complete",
            )
        )


@app.command()
def init_cards(
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Create review cards for all exercises that don't have one."""
    with get_repo(db) as repo:
        created = 0
        # Materialize the list first to avoid DuckDB cursor corruption
        # when card queries run inside the loop on the same connection.
        exercises = list(repo.exercises.iterate_all())
        for exercise in exercises:
            existing = repo.cards.get(exercise.id)
            if not existing:
                repo.cards.get_or_create(exercise.id)
                created += 1

        console.print(f"[green]\u2713[/green] Created {created} new review cards")


@app.command()
def progress(
    accuracy: bool = typer.Option(False, "--accuracy", "-a", help="Show accuracy trend"),
    weak: bool = typer.Option(False, "--weak", "-w", help="Show weak areas"),
    streaks: bool = typer.Option(False, "--streaks", "-s", help="Show streaks"),
    retention: bool = typer.Option(False, "--retention", "-r", help="Show retention curve"),
    exercise_type: str | None = typer.Option(None, "--type", "-t", help="Filter by exercise type"),
    days: int = typer.Option(30, "--days", "-d", help="Lookback period in days"),
    granularity: str = typer.Option("day", "--granularity", "-g", help="Granularity: day or week"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Show training progress and analytics."""
    from ..analytics import AnalyticsStore

    show_all = not (accuracy or weak or streaks or retention)

    with get_repo(db) as repo:
        store = AnalyticsStore(repo.conn)

        if show_all or accuracy:
            _show_accuracy(store, granularity=granularity, exercise_type=exercise_type, days=days)

        if show_all or weak:
            _show_weak_areas(store)

        if show_all or streaks:
            _show_streaks(store)

        if show_all or retention:
            _show_retention(store)


def _show_accuracy(
    store,
    *,
    granularity: str = "day",
    exercise_type: str | None = None,
    days: int = 30,
) -> None:
    """Display accuracy trend as a Rich table."""
    trend = store.accuracy_trend(granularity=granularity, exercise_type=exercise_type, days=days)

    if not trend.points:
        console.print("[yellow]No review data yet.[/yellow]")
        return

    table = Table(title=f"Accuracy Trend ({trend.granularity}, last {days} days)")
    table.add_column("Period", style="cyan")
    table.add_column("Reviews", justify="right")
    table.add_column("Correct", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Trend", justify="center")

    prev_acc = None
    for point in trend.points:
        if prev_acc is not None:
            if point.accuracy > prev_acc:
                arrow = "[green]\u2191[/green]"
            elif point.accuracy < prev_acc:
                arrow = "[red]\u2193[/red]"
            else:
                arrow = "[yellow]\u2192[/yellow]"
        else:
            arrow = ""

        acc_style = "green" if point.accuracy >= 70 else "yellow" if point.accuracy >= 50 else "red"
        table.add_row(
            str(point.period),
            str(point.total_reviews),
            str(point.correct_count),
            f"[{acc_style}]{point.accuracy:.1f}%[/{acc_style}]",
            arrow,
        )
        prev_acc = point.accuracy

    console.print(table)
    console.print(
        f"[bold]Overall:[/bold] {trend.overall_accuracy:.1f}% ({trend.total_reviews} reviews)\n"
    )


def _show_weak_areas(store) -> None:
    """Display weak areas as a color-coded Rich table."""
    areas = store.weak_areas()

    if not areas:
        console.print("[yellow]No review data yet.[/yellow]")
        return

    table = Table(title="Weak Areas (lowest accuracy first)")
    table.add_column("Area", style="bold")
    table.add_column("Category", style="dim")
    table.add_column("Reviews", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Lapses", justify="right")
    table.add_column("Cards", justify="right")

    for area in areas:
        acc_style = "green" if area.accuracy >= 70 else "yellow" if area.accuracy >= 50 else "red"
        table.add_row(
            area.name,
            area.category,
            str(area.total_reviews),
            f"[{acc_style}]{area.accuracy:.1f}%[/{acc_style}]",
            f"{area.avg_lapses:.1f}",
            str(area.card_count),
        )

    console.print(table)
    console.print()


def _show_streaks(store) -> None:
    """Display streak info as a Rich panel with activity bar."""
    info = store.streaks()

    if info.total_active_days == 0:
        console.print("[yellow]No review data yet.[/yellow]")
        return

    # Build a 14-day activity bar
    today = __import__("datetime").date.today()
    activity_map = {a.day: a.review_count for a in info.daily_activity}
    bar_chars = []
    for i in range(13, -1, -1):
        day = today - __import__("datetime").timedelta(days=i)
        count = activity_map.get(day, 0)
        if count == 0:
            bar_chars.append("[dim]\u2581[/dim]")
        elif count < 5:
            bar_chars.append("[green]\u2583[/green]")
        elif count < 15:
            bar_chars.append("[green]\u2585[/green]")
        else:
            bar_chars.append("[green bold]\u2588[/green bold]")

    bar = "".join(bar_chars)

    console.print(
        Panel(
            f"[bold]Current streak:[/bold] {info.current_streak} days\n"
            f"[bold]Longest streak:[/bold] {info.longest_streak} days\n"
            f"[bold]Active days:[/bold] {info.total_active_days}\n\n"
            f"Last 14 days: {bar}",
            title="Streaks",
        )
    )
    console.print()


def _show_retention(store) -> None:
    """Display retention curve as a Rich table."""
    points = store.retention_curve()

    if not points:
        console.print("[yellow]No review data yet.[/yellow]")
        return

    table = Table(title="Retention Curve (by repetition count)")
    table.add_column("Reps", justify="right", style="cyan")
    table.add_column("Cards", justify="right")
    table.add_column("Stability", justify="right")
    table.add_column("Recall", justify="right")
    table.add_column("Predicted", justify="right")

    for point in points:
        recall_style = (
            "green"
            if point.actual_recall_rate >= 80
            else "yellow"
            if point.actual_recall_rate >= 60
            else "red"
        )
        table.add_row(
            str(point.reps),
            str(point.card_count),
            f"{point.avg_stability_days:.1f}d",
            f"[{recall_style}]{point.actual_recall_rate:.1f}%[/{recall_style}]",
            f"{point.predicted_retrievability:.1f}%",
        )

    console.print(table)
    console.print()


# ── Tag subcommand group ──────────────────────────────────────────────────────

tag_app = typer.Typer(help="Manage custom tags on exercises and openings")
app.add_typer(tag_app, name="tag")


@tag_app.command("add")
def tag_add(
    entity_id: str = typer.Argument(help="Exercise or opening ID"),
    tags: list[str] = typer.Argument(help="Tags to add"),
    entity_type: str = typer.Option(
        "exercise", "--type", "-t", help="Entity type: exercise or opening"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Add custom tags to an exercise or opening."""
    from ..storage.tag_store import EntityType, TagSource

    try:
        etype = EntityType(entity_type.lower())
    except ValueError:
        console.print(f"[red]Invalid type: {entity_type}. Use 'exercise' or 'opening'.[/red]")
        raise typer.Exit(1)

    with get_repo(db) as repo:
        # Validate entity exists
        if etype == EntityType.EXERCISE:
            if not repo.exercises.get(entity_id):
                console.print(f"[red]Exercise not found: {entity_id}[/red]")
                raise typer.Exit(1)
        elif etype == EntityType.OPENING:
            if not repo.openings.get_line(entity_id):
                console.print(f"[red]Opening line not found: {entity_id}[/red]")
                raise typer.Exit(1)

        count = repo.tags.add_tags(etype, entity_id, tags, TagSource.USER)
        console.print(f"[green]\u2713[/green] Added {count} tag(s) to {entity_id}")


@tag_app.command("remove")
def tag_remove(
    entity_id: str = typer.Argument(help="Exercise or opening ID"),
    tags: list[str] = typer.Argument(help="Tags to remove"),
    entity_type: str = typer.Option(
        "exercise", "--type", "-t", help="Entity type: exercise or opening"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Remove tags from an exercise or opening."""
    from ..storage.tag_store import EntityType

    try:
        etype = EntityType(entity_type.lower())
    except ValueError:
        console.print(f"[red]Invalid type: {entity_type}. Use 'exercise' or 'opening'.[/red]")
        raise typer.Exit(1)

    with get_repo(db) as repo:
        count = repo.tags.remove_tags(etype, entity_id, tags)
        console.print(f"[green]\u2713[/green] Removed {count} tag(s) from {entity_id}")


@tag_app.command("list")
def tag_list(
    entity_type: str | None = typer.Option(None, "--type", "-t", help="Filter by entity type"),
    source: str | None = typer.Option(
        None, "--source", "-s", help="Filter by source: user or system"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """List all tags with their usage counts."""
    from ..storage.tag_store import EntityType

    etype = None
    if entity_type:
        try:
            etype = EntityType(entity_type.lower())
        except ValueError:
            console.print(f"[red]Invalid type: {entity_type}[/red]")
            raise typer.Exit(1)

    with get_repo(db) as repo:
        all_tags = repo.tags.list_all_tags(entity_type=etype)

        if not all_tags:
            console.print("[yellow]No tags found.[/yellow]")
            return

        # Filter by source if requested (post-filter since list_all_tags doesn't take source)
        if source:
            # Re-query with source filter
            if etype is not None:
                rows = repo.conn.execute(
                    "SELECT tag, COUNT(*) AS cnt FROM tags WHERE entity_type = ? AND source = ? GROUP BY tag ORDER BY cnt DESC, tag",
                    [etype.value, source.lower()],
                ).fetchall()
            else:
                rows = repo.conn.execute(
                    "SELECT tag, COUNT(*) AS cnt FROM tags WHERE source = ? GROUP BY tag ORDER BY cnt DESC, tag",
                    [source.lower()],
                ).fetchall()
            from ..storage.tag_store import TagInfo

            all_tags = [TagInfo(tag=r[0], count=int(r[1])) for r in rows]

        if not all_tags:
            console.print("[yellow]No tags found.[/yellow]")
            return

        table = Table(title="Tags")
        table.add_column("Tag", style="bold")
        table.add_column("Count", justify="right")

        for t in all_tags:
            table.add_row(t.tag, str(t.count))

        console.print(table)


@tag_app.command("show")
def tag_show(
    entity_id: str = typer.Argument(help="Exercise or opening ID"),
    entity_type: str = typer.Option("exercise", "--type", "-t", help="Entity type"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Show tags for a specific exercise or opening, grouped by source."""
    from ..storage.tag_store import EntityType, TagSource

    try:
        etype = EntityType(entity_type.lower())
    except ValueError:
        console.print(f"[red]Invalid type: {entity_type}[/red]")
        raise typer.Exit(1)

    with get_repo(db) as repo:
        user_tags = repo.tags.get_tags(etype, entity_id, source=TagSource.USER)
        system_tags = repo.tags.get_tags(etype, entity_id, source=TagSource.SYSTEM)

        if not user_tags and not system_tags:
            console.print(f"[yellow]No tags for {entity_id}[/yellow]")
            return

        console.print(f"[bold]Tags for {entity_id}[/bold]\n")
        if user_tags:
            console.print(f"[cyan]User:[/cyan] {', '.join(user_tags)}")
        if system_tags:
            console.print(f"[dim]System:[/dim] {', '.join(system_tags)}")


@tag_app.command("search")
def tag_search(
    query: str = typer.Argument(help="Substring to search for"),
    entity_type: str | None = typer.Option(None, "--type", "-t", help="Filter by entity type"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Search tags by substring match."""
    from ..storage.tag_store import EntityType

    etype = None
    if entity_type:
        try:
            etype = EntityType(entity_type.lower())
        except ValueError:
            console.print(f"[red]Invalid type: {entity_type}[/red]")
            raise typer.Exit(1)

    with get_repo(db) as repo:
        matches = repo.tags.search_tags(query, entity_type=etype)

        if not matches:
            console.print(f"[yellow]No tags matching '{query}'[/yellow]")
            return

        table = Table(title=f"Tags matching '{query}'")
        table.add_column("Tag", style="bold")
        table.add_column("Count", justify="right")

        for t in matches:
            table.add_row(t.tag, str(t.count))

        console.print(table)


# ── Bundle subcommand group ──────────────────────────────────────────────────

bundle_app = typer.Typer(help="Manage exercise bundles and Woodpecker training")
app.add_typer(bundle_app, name="bundle")


@bundle_app.command("create")
def bundle_create(
    slug: str = typer.Argument(help="Bundle slug (lowercase, hyphens, 2-64 chars)"),
    name: str = typer.Option(None, "--name", "-n", help="Display name (defaults to slug)"),
    description: str = typer.Option("", "--desc", "-d", help="Bundle description"),
    woodpecker: bool = typer.Option(False, "--woodpecker", "-w", help="Enable Woodpecker mode"),
    threshold: float = typer.Option(None, "--threshold", help="Pass threshold (0.0-1.0)"),
    shuffle: bool = typer.Option(None, "--shuffle", help="Shuffle exercise order"),
    time_limit: int | None = typer.Option(
        None, "--time-limit", help="Per-exercise time limit in seconds"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Create a new exercise bundle."""
    from ..exercises.bundle import (
        BundleConfig,
        ExerciseBundle,
        WoodpeckerCycle,
        generate_bundle_id,
        validate_slug,
    )

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    cfg = _get_config()
    pass_thresh = threshold if threshold is not None else cfg.bundles.default_pass_threshold
    do_shuffle = shuffle if shuffle is not None else cfg.bundles.default_shuffle

    # Default Woodpecker cycles if mode enabled
    woodpecker_cycles = []
    if woodpecker:
        woodpecker_cycles = [
            WoodpeckerCycle(cycle_number=1, rest_days=0, time_limit_seconds=None),
            WoodpeckerCycle(cycle_number=2, rest_days=1, time_limit_seconds=None),
            WoodpeckerCycle(cycle_number=3, rest_days=3, time_limit_seconds=60),
            WoodpeckerCycle(cycle_number=4, rest_days=7, time_limit_seconds=30),
        ]

    bundle = ExerciseBundle(
        id=generate_bundle_id(validated),
        name=name or validated.replace("-", " ").title(),
        description=description,
        config=BundleConfig(
            woodpecker_mode=woodpecker,
            woodpecker_cycles=woodpecker_cycles,
            pass_threshold=pass_thresh,
            shuffle=do_shuffle,
            time_limit_seconds=time_limit,
        ),
    )

    with get_repo(db) as repo:
        try:
            repo.bundles.create(bundle)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    console.print(f"[green]\u2713[/green] Created bundle: {bundle.name} ({bundle.id})")
    if woodpecker:
        console.print("[dim]Woodpecker mode enabled with 4 default cycles[/dim]")


@bundle_app.command("list")
def bundle_list(
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """List all exercise bundles."""
    with get_repo(db) as repo:
        bundles = repo.bundles.list_all()

        if not bundles:
            console.print("[yellow]No bundles found.[/yellow]")
            console.print("Create one with: chess-trainer bundle create <slug>")
            return

        table = Table(title=f"Exercise Bundles ({len(bundles)})")
        table.add_column("Slug", style="bold")
        table.add_column("Name")
        table.add_column("Exercises", justify="right")
        table.add_column("Mode", style="dim")
        table.add_column("Cycle", justify="right")

        for b in bundles:
            mode = "Woodpecker" if b.config.woodpecker_mode else "Standard"
            progress = repo.bundles.get_progress(b.id)
            cycle_str = str(progress.current_cycle) if progress else "-"
            table.add_row(b.slug, b.name, str(b.exercise_count), mode, cycle_str)

        console.print(table)


@bundle_app.command("show")
def bundle_show(
    slug: str = typer.Argument(help="Bundle slug"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Show details of an exercise bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        bundle = repo.bundles.get(bundle_id)
        if not bundle:
            console.print(f"[red]Bundle not found: {slug}[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]{bundle.name}[/bold] ({bundle.id})")
        if bundle.description:
            console.print(f"  {bundle.description}")
        console.print(f"  Exercises: {bundle.exercise_count}")
        console.print(f"  Mode: {'Woodpecker' if bundle.config.woodpecker_mode else 'Standard'}")
        console.print(f"  Pass threshold: {bundle.config.pass_threshold:.0%}")
        console.print(f"  Shuffle: {bundle.config.shuffle}")
        if bundle.config.time_limit_seconds:
            console.print(f"  Time limit: {bundle.config.time_limit_seconds}s")
        if bundle.auto_tags:
            console.print(f"  Auto-tags: {', '.join(bundle.auto_tags)}")

        if bundle.config.woodpecker_cycles:
            console.print("\n  [bold]Woodpecker Cycles:[/bold]")
            for c in bundle.config.woodpecker_cycles:
                limit = f"{c.time_limit_seconds}s" if c.time_limit_seconds else "unlimited"
                console.print(f"    Cycle {c.cycle_number}: rest {c.rest_days}d, time {limit}")

        # Show progress
        progress = repo.bundles.get_progress(bundle_id)
        if progress:
            console.print(f"\n  [bold]Progress:[/bold] Cycle {progress.current_cycle}")
            if progress.completed_cycles:
                for cr in progress.completed_cycles:
                    status = "[green]PASS[/green]" if cr.passed else "[red]FAIL[/red]"
                    console.print(f"    Cycle {cr.cycle_number}: {cr.accuracy:.0%} {status}")

        # Show first few exercise IDs
        if bundle.exercise_ids:
            shown = bundle.exercise_ids[:10]
            console.print(f"\n  [bold]Exercises ({bundle.exercise_count}):[/bold]")
            for eid in shown:
                console.print(f"    {eid}")
            if bundle.exercise_count > 10:
                console.print(f"    ... and {bundle.exercise_count - 10} more")


@bundle_app.command("add")
def bundle_add(
    slug: str = typer.Argument(help="Bundle slug"),
    exercise_ids: list[str] = typer.Argument(help="Exercise IDs to add"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Add exercises to a bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        try:
            count = repo.bundles.add_exercises(bundle_id, exercise_ids)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]\u2713[/green] Added {count} exercise(s) to {slug}")


@bundle_app.command("remove")
def bundle_remove(
    slug: str = typer.Argument(help="Bundle slug"),
    exercise_ids: list[str] = typer.Argument(help="Exercise IDs to remove"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Remove exercises from a bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        try:
            count = repo.bundles.remove_exercises(bundle_id, exercise_ids)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]\u2713[/green] Removed {count} exercise(s) from {slug}")


@bundle_app.command("delete")
def bundle_delete(
    slug: str = typer.Argument(help="Bundle slug"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Delete an exercise bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not force:
        if not typer.confirm(f"Delete bundle '{slug}'?", default=False):
            raise typer.Abort()

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        deleted = repo.bundles.delete(bundle_id)
        if deleted:
            console.print(f"[green]\u2713[/green] Deleted bundle: {slug}")
        else:
            console.print(f"[red]Bundle not found: {slug}[/red]")
            raise typer.Exit(1)


@bundle_app.command("import")
def bundle_import(
    slug: str = typer.Argument(help="Bundle slug"),
    tag: list[str] = typer.Option(..., "--tag", help="Tag(s) to import exercises from"),
    match_all: bool = typer.Option(False, "--all", help="Require all tags (AND logic)"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Import exercises into a bundle by tag."""
    from ..exercises.bundle import generate_bundle_id, validate_slug
    from ..storage.tag_store import EntityType

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        bundle = repo.bundles.get(bundle_id)
        if not bundle:
            console.print(f"[red]Bundle not found: {slug}[/red]")
            raise typer.Exit(1)

        exercise_ids = repo.tags.find_by_tags(EntityType.EXERCISE, tag, match_all=match_all)
        if not exercise_ids:
            console.print(f"[yellow]No exercises found with tag(s): {', '.join(tag)}[/yellow]")
            return

        try:
            count = repo.bundles.add_exercises(bundle_id, exercise_ids)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

        console.print(
            f"[green]\u2713[/green] Added {count} exercise(s) to {slug} "
            f"(from {len(exercise_ids)} matching)"
        )


@bundle_app.command("train")
def bundle_train(
    slug: str = typer.Argument(help="Bundle slug"),
    self_report: bool = typer.Option(
        False, "--self-report", "-s", help="Self-report mode (no move input)"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Train exercises from a bundle (Woodpecker mode if configured)."""
    from ..exercises.bundle import generate_bundle_id, validate_slug
    from ..training.woodpecker import WoodpeckerSession

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        bundle = repo.bundles.get(bundle_id)
        if not bundle:
            console.print(f"[red]Bundle not found: {slug}[/red]")
            raise typer.Exit(1)

        if not bundle.exercise_ids:
            console.print(f"[yellow]Bundle '{slug}' has no exercises.[/yellow]")
            return

        progress = repo.bundles.get_progress(bundle_id)
        session = WoodpeckerSession(repo, bundle, progress)
        session.start()

        total = session.remaining
        cycle = session.progress.current_cycle
        limit_str = f" ({session.time_limit}s per exercise)" if session.time_limit else ""

        console.print(
            f"\n[bold]{bundle.name}[/bold] \u2014 Cycle {cycle}, {total} exercises{limit_str}"
        )
        if not self_report:
            console.print(
                "[dim]Type moves in SAN (Nf3) or UCI (g1f3)."
                " 'h' for hint, Enter to give up, 'q' to quit.[/dim]"
            )
        console.print()

        while True:
            exercise = session.next()
            if not exercise:
                break

            board = exercise.position
            num = session.stats.exercises_shown if session.stats else 0
            progress_str = f"Exercise {num}/{total}"

            flipped = board.turn == chess.BLACK
            console.print(
                Panel.fit(
                    render_board(board, flipped=flipped),
                    title=progress_str,
                    subtitle=(f"[dim]{exercise.exercise_type.name} | Cycle {cycle}[/dim]"),
                )
            )
            console.print(f"[bold]{exercise.get_challenge()}[/bold]")

            if self_report:
                console.print("\n[dim]Think about your answer, then press Enter to reveal.[/dim]")
                input()
                console.print(f"\n[bold]Solution:[/bold] {exercise.get_explanation()}")

                while True:
                    rating_input = typer.prompt(
                        "\nHow did you do? [1=Again, 2=Hard, 3=Good, 4=Easy]",
                        type=int,
                        default=3,
                    )
                    if 1 <= rating_input <= 4:
                        break
                    console.print("[red]Please enter 1-4.[/red]")

                rating = Rating(rating_input)
                # Simulate result for progress tracking
                is_correct = rating >= Rating.GOOD
                if is_correct:
                    session.progress.exercises_correct += 1
                session.progress.exercises_attempted += 1
                if session.stats:
                    session.stats.exercises_shown += 0  # Already counted in next()
                    if is_correct:
                        session.stats.correct += 1
                    else:
                        session.stats.incorrect += 1
            else:
                moves, time_ms = _collect_moves(exercise)

                if moves:
                    result, over_time = session.submit(moves, time_ms)
                    rating = session.auto_rate_woodpecker(result, over_time)

                    if over_time:
                        console.print(
                            f"\n[yellow]Over time![/yellow] "
                            f"({time_ms / 1000:.1f}s > {session.time_limit}s limit)"
                        )
                    elif result.correct:
                        console.print(f"\n[green bold]Correct![/green bold] {result.feedback}")
                    elif result.partial_credit > 0:
                        console.print(f"\n[yellow]Partially correct.[/yellow] {result.feedback}")
                    else:
                        console.print(f"\n[red]Incorrect.[/red] {result.feedback}")
                else:
                    result, over_time = session.submit([], 0)
                    rating = Rating.AGAIN

                # Show solution
                solution_line = format_solution_line(board, exercise.get_solution())
                console.print(f"\n[bold]Solution:[/bold] {solution_line}")

                # Let user override
                console.print(
                    f"[dim]Auto-rated: {rating.name} "
                    f"(press Enter to accept, or type 1-4 to override)[/dim]"
                )
                override = input().strip()
                if override in ("1", "2", "3", "4"):
                    rating = Rating(int(override))

            session.rate(rating)
            console.print()

        # End cycle
        cycle_result = session.end_cycle()

        status = "[green]PASSED[/green]" if cycle_result.passed else "[red]FAILED[/red]"
        console.print("\n" + "=" * 40)
        console.print(
            Panel(
                f"Cycle {cycle_result.cycle_number}: {status}\n"
                f"Accuracy: {cycle_result.accuracy:.1%} "
                f"(threshold: {bundle.config.pass_threshold:.0%})\n"
                f"Exercises: {cycle_result.exercises_correct}/{cycle_result.exercises_attempted}",
                title=f"Cycle Complete \u2014 {bundle.name}",
            )
        )
        if cycle_result.passed:
            console.print("[green]Advancing to next cycle![/green]")
        else:
            console.print("[yellow]Repeat this cycle to improve.[/yellow]")


@bundle_app.command("progress")
def bundle_progress(
    slug: str = typer.Argument(help="Bundle slug"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Show training progress for a bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        bundle = repo.bundles.get(bundle_id)
        if not bundle:
            console.print(f"[red]Bundle not found: {slug}[/red]")
            raise typer.Exit(1)

        progress = repo.bundles.get_progress(bundle_id)
        if not progress:
            console.print(f"[yellow]No training progress for '{slug}'.[/yellow]")
            console.print(f"Start training: chess-trainer bundle train {slug}")
            return

        console.print(f"[bold]{bundle.name}[/bold] \u2014 Progress")
        console.print(f"  Current cycle: {progress.current_cycle}")

        if progress.completed_cycles:
            table = Table(title="Completed Cycles")
            table.add_column("Cycle", justify="right")
            table.add_column("Accuracy", justify="right")
            table.add_column("Result")
            table.add_column("Exercises", justify="right")
            table.add_column("Time Limit")
            table.add_column("Completed")

            for cr in progress.completed_cycles:
                status = "[green]PASS[/green]" if cr.passed else "[red]FAIL[/red]"
                limit = f"{cr.time_limit_seconds}s" if cr.time_limit_seconds else "-"
                table.add_row(
                    str(cr.cycle_number),
                    f"{cr.accuracy:.0%}",
                    status,
                    f"{cr.exercises_correct}/{cr.exercises_attempted}",
                    limit,
                    cr.completed_at.strftime("%Y-%m-%d %H:%M"),
                )
            console.print(table)
        else:
            console.print("[dim]  No completed cycles yet.[/dim]")


@bundle_app.command("reset")
def bundle_reset(
    slug: str = typer.Argument(help="Bundle slug"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Reset training progress for a bundle."""
    from ..exercises.bundle import generate_bundle_id, validate_slug

    try:
        validated = validate_slug(slug)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not force:
        if not typer.confirm(f"Reset progress for '{slug}'?", default=False):
            raise typer.Abort()

    bundle_id = generate_bundle_id(validated)

    with get_repo(db) as repo:
        bundle = repo.bundles.get(bundle_id)
        if not bundle:
            console.print(f"[red]Bundle not found: {slug}[/red]")
            raise typer.Exit(1)

        repo.bundles.reset_progress(bundle_id)
        console.print(f"[green]\u2713[/green] Reset progress for: {slug}")


config_app = typer.Typer(help="Configuration management")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init(
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Run setup wizard"),
) -> None:
    """Generate a default config file at ~/.chess-trainer/config.toml."""
    from ..config import _secure_file, generate_default_config, set_config_value

    if DEFAULT_CONFIG_PATH.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {DEFAULT_CONFIG_PATH}")
        overwrite = typer.confirm("Overwrite?", default=False)
        if not overwrite:
            raise typer.Abort()

    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CONFIG_PATH.write_text(generate_default_config())
    _secure_file(DEFAULT_CONFIG_PATH)
    console.print(f"[green]\u2713[/green] Config written to {DEFAULT_CONFIG_PATH}")

    if interactive:
        console.print("\n[bold]Setup Wizard[/bold]\n")
        wizard_prompts = [
            ("database.path", "Database path", "~/.chess-trainer/trainer.db"),
            ("lichess.token", "Lichess API token (leave empty to skip)", ""),
            ("engine.path", "Engine path (leave empty for auto-detect)", ""),
            ("training.max_new_cards", "Max new cards per session", "20"),
            ("training.max_reviews", "Max reviews per session", "100"),
        ]
        for key, prompt_text, default in wizard_prompts:
            answer = typer.prompt(prompt_text, default=default, show_default=True)
            if answer != default and answer != "":
                try:
                    set_config_value(key, answer)
                except (KeyError, ValueError) as e:
                    console.print(f"[yellow]Skipping {key}: {e}[/yellow]")
            elif answer == "" and default != "":
                # User cleared a field that had a default — skip
                pass
        console.print("\n[green]\u2713[/green] Setup complete!")


@config_app.command("show")
def config_show() -> None:
    """Show the current effective configuration."""
    cfg = _get_config()
    console.print(
        Panel(
            f"[bold]database.path[/bold] = {cfg.database.path}\n"
            f"[bold]lichess.api_url[/bold] = {cfg.lichess.api_url}\n"
            f"[bold]lichess.token[/bold] = {'***' if cfg.lichess.token else '(not set)'}\n"
            f"[bold]scheduler.request_retention[/bold] = {cfg.scheduler.request_retention}\n"
            f"[bold]training.max_new_cards[/bold] = {cfg.training.max_new_cards}\n"
            f"[bold]training.max_reviews[/bold] = {cfg.training.max_reviews}\n"
            f"[bold]training.interleave_new[/bold] = {cfg.training.interleave_new}\n"
            f"[bold]logging.level[/bold] = {cfg.logging.level}\n"
            f"[bold]web.host[/bold] = {cfg.web.host}\n"
            f"[bold]web.port[/bold] = {cfg.web.port}\n"
            f"[bold]engine.path[/bold] = {cfg.engine.path or '(auto-detect)'}\n"
            f"[bold]engine.hash_mb[/bold] = {cfg.engine.hash_mb}\n"
            f"[bold]engine.threads[/bold] = {cfg.engine.threads}\n"
            f"[bold]engine.default_depth[/bold] = {cfg.engine.default_depth}\n"
            f"[bold]engine.default_multipv[/bold] = {cfg.engine.default_multipv}\n"
            f"[bold]openings.explorer_source[/bold] = {cfg.openings.explorer_source}\n"
            f"[bold]openings.cache_ttl_hours[/bold] = {cfg.openings.cache_ttl_hours}\n"
            f"[bold]openings.min_games[/bold] = {cfg.openings.min_games}\n"
            f"[bold]game_analysis.analysis_depth[/bold] = {cfg.game_analysis.analysis_depth}\n"
            f"[bold]game_analysis.min_classification[/bold] = {cfg.game_analysis.min_classification}\n"
            f"[bold]game_analysis.max_exercises_per_game[/bold] = {cfg.game_analysis.max_exercises_per_game}\n"
            f"[bold]game_analysis.skip_first_plies[/bold] = {cfg.game_analysis.skip_first_plies}\n"
            f"[bold]chesscom.user_agent[/bold] = {cfg.chesscom.user_agent}\n"
            f"[bold]chesscom.request_delay[/bold] = {cfg.chesscom.request_delay}\n"
            f"[bold]tablebase.syzygy_path[/bold] = {cfg.tablebase.syzygy_path or '(not set)'}\n"
            f"[bold]tablebase.use_lichess_fallback[/bold] = {cfg.tablebase.use_lichess_fallback}\n"
            f"[bold]tablebase.max_pieces[/bold] = {cfg.tablebase.max_pieces}\n"
            f"[bold]experimental.enabled[/bold] = {cfg.experimental.enabled}\n"
            f"[bold]experimental.vision[/bold] = {cfg.experimental.vision}\n"
            f"[bold]experimental.vision_backend[/bold] = {cfg.experimental.vision_backend}\n"
            f"[bold]experimental.claude_api_key[/bold] = {'***' if cfg.experimental.claude_api_key else '(not set)'}\n"
            f"[bold]experimental.openai_api_key[/bold] = {'***' if cfg.experimental.openai_api_key else '(not set)'}\n"
            f"[bold]experimental.local_model_path[/bold] = {cfg.experimental.local_model_path or '(not set)'}",
            title="Effective Configuration",
        )
    )


@config_app.command("get")
def config_get(
    key: str = typer.Argument(help="Config key, e.g. web.port"),
) -> None:
    """Get a single configuration value."""
    from ..config import get_config_keys, get_config_value

    cfg = _get_config()
    try:
        value = get_config_value(cfg, key)
    except KeyError:
        console.print(f"[red]Unknown key: {key}[/red]\n")
        console.print("[bold]Valid keys:[/bold]")
        for k in sorted(get_config_keys()):
            console.print(f"  {k}")
        raise typer.Exit(1)

    # Mask sensitive values
    sensitive_keys = {"lichess.token", "experimental.claude_api_key", "experimental.openai_api_key"}
    if key in sensitive_keys and value is not None:
        display = "***"
    elif value is None:
        display = "(not set)"
    else:
        display = str(value)

    console.print(f"{key} = {display}")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Config key, e.g. web.port"),
    value: str = typer.Argument(help="Value to set"),
) -> None:
    """Set a configuration value."""
    from ..config import set_config_value

    try:
        result = set_config_value(key, value)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]\u2713[/green] {key} = {result}")


@config_app.command("reset")
def config_reset(
    key: str = typer.Argument(None, help="Config key to reset (omit to reset all)"),
) -> None:
    """Reset a config key to default, or reset the entire config file."""
    from ..config import get_config_value, reset_config_value

    if key is None:
        if not typer.confirm("Reset ALL config to defaults?", default=False):
            raise typer.Abort()
        reset_config_value(config_path=DEFAULT_CONFIG_PATH)
        console.print("[green]\u2713[/green] Config reset to defaults.")
        return

    try:
        reset_config_value(key, config_path=DEFAULT_CONFIG_PATH)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Show the effective default
    cfg = load_config(DEFAULT_CONFIG_PATH)
    try:
        default_val = get_config_value(cfg, key)
    except KeyError:
        default_val = "(unknown)"
    console.print(f"[green]\u2713[/green] {key} reset to default: {default_val}")


def _parse_pgn_to_board(pgn_text: str) -> chess.Board:
    """Parse a PGN string into a board at the final position.

    Accepts either a file path or inline PGN text.

    Raises:
        typer.BadParameter: If the PGN cannot be parsed.
    """
    import io

    import chess.pgn

    pgn_input = pgn_text
    pgn_path = Path(pgn_text)
    if pgn_path.is_file():
        pgn_input = pgn_path.read_text()

    game = chess.pgn.read_game(io.StringIO(pgn_input))
    if game is None:
        raise typer.BadParameter(f"Could not parse PGN: {pgn_text[:80]}")

    board = game.board()
    for move in game.mainline_moves():
        board.push(move)
    return board


def _format_score(line) -> str:
    """Format an AnalysisLine score for display."""
    if line.score_mate is not None:
        return f"M{line.score_mate}" if line.score_mate > 0 else f"-M{abs(line.score_mate)}"
    cp = line.score_cp or 0
    return f"{cp / 100:+.2f}"


def _static_analysis(board: chess.Board, result, *, flipped: bool = False) -> None:
    """Display board and analysis lines as a Rich table."""
    console.print(render_board(board, flipped=flipped))
    console.print()

    table = Table(title=f"Analysis (depth {result.depth})")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", justify="right", style="bold")
    table.add_column("Line", no_wrap=False)

    for line in result.lines:
        # Format the PV in SAN
        temp = board.copy()
        san_moves = []
        for move in line.pv[:12]:  # Show up to 12 half-moves
            if temp.turn == chess.WHITE:
                san_moves.append(f"{temp.fullmove_number}. {temp.san(move)}")
            else:
                if not san_moves:
                    san_moves.append(f"{temp.fullmove_number}... {temp.san(move)}")
                else:
                    san_moves.append(temp.san(move))
            temp.push(move)

        score_str = _format_score(line)
        pv_str = " ".join(san_moves)

        # Color-code the score
        if line.score_mate is not None:
            score_style = "green" if line.score_mate > 0 else "red"
        elif (line.score_cp or 0) > 50:
            score_style = "green"
        elif (line.score_cp or 0) < -50:
            score_style = "red"
        else:
            score_style = "yellow"

        table.add_row(
            str(line.multipv_rank),
            f"[{score_style}]{score_str}[/{score_style}]",
            pv_str,
        )

    console.print(table)


def _interactive_analysis(board: chess.Board, engine_mgr) -> None:
    """Interactive analysis REPL: play moves to explore, 'back' to undo, 'quit' to exit."""
    from ..analysis import EngineError

    cfg = _get_config()
    depth = cfg.engine.default_depth
    multipv = cfg.engine.default_multipv
    move_stack: list[chess.Move] = []

    while True:
        flipped = board.turn == chess.BLACK
        try:
            result = engine_mgr.analyze(board, depth=depth, multipv=multipv)
        except EngineError as e:
            console.print(f"[red]Analysis error: {e}[/red]")
            break

        _static_analysis(board, result, flipped=flipped)

        console.print("\n[dim]Enter a move (SAN/UCI), 'back' to undo, 'quit' to exit:[/dim]")
        text = input("> ").strip()

        if text.lower() in ("q", "quit", "exit"):
            break
        elif text.lower() in ("b", "back", "undo"):
            if move_stack:
                board.pop()
                move_stack.pop()
                console.print("[dim]Move undone.[/dim]\n")
            else:
                console.print("[yellow]No moves to undo.[/yellow]\n")
            continue

        move = _parse_move(board, text)
        if move is None:
            console.print("[red]Invalid move. Try again.[/red]\n")
            continue

        board.push(move)
        move_stack.append(move)
        console.print()


@app.command()
def analyze(
    fen: str = typer.Argument(None, help="FEN string to analyze (starting position if omitted)"),
    pgn: str = typer.Option(None, "--pgn", help="PGN string or file path to analyze"),
    depth: int | None = typer.Option(None, "--depth", "-d", help="Search depth"),
    multipv: int | None = typer.Option(
        None, "--multipv", "-m", help="Number of principal variations"
    ),
    engine_path: str | None = typer.Option(
        None, "--engine", "-e", help="Path to UCI engine binary"
    ),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Interactive exploration mode"
    ),
):
    """Analyze a chess position with a UCI engine."""
    from ..analysis import EngineError, EngineManager

    cfg = _get_config()
    analysis_depth = depth or cfg.engine.default_depth
    analysis_multipv = multipv or cfg.engine.default_multipv
    engine = engine_path or cfg.engine.path

    # Determine the board position
    if pgn:
        try:
            board = _parse_pgn_to_board(pgn)
        except typer.BadParameter as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    elif fen:
        try:
            board = chess.Board(fen)
        except ValueError:
            console.print(f"[red]Invalid FEN: {fen}[/red]")
            raise typer.Exit(1)
    else:
        board = chess.Board()

    try:
        with EngineManager(
            path=engine,
            hash_mb=cfg.engine.hash_mb,
            threads=cfg.engine.threads,
        ) as engine_mgr:
            if interactive:
                _interactive_analysis(board, engine_mgr)
            else:
                result = engine_mgr.analyze(board, depth=analysis_depth, multipv=analysis_multipv)
                flipped = board.turn == chess.BLACK
                _static_analysis(board, result, flipped=flipped)
    except EngineError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@app.command()
def explore(
    fen: str = typer.Argument(None, help="FEN to explore (starting position if omitted)"),
    source: str = typer.Option(
        None, "--source", "-s", help="Explorer source: lichess, masters, player"
    ),
    player: str | None = typer.Option(
        None, "--player", "-p", help="Lichess username (for player source)"
    ),
    color: str = typer.Option("white", "--color", help="Side for player source"),
    speeds: str | None = typer.Option(
        None, "--speeds", help="Comma-separated speed filters (blitz,rapid,classical)"
    ),
    ratings: str | None = typer.Option(
        None, "--ratings", help="Comma-separated rating brackets (1600,1800,2000)"
    ),
    min_white_pct: float | None = typer.Option(
        None, "--min-white-pct", help="Min white win %% to show a move (0-100)"
    ),
    min_draw_pct: float | None = typer.Option(
        None, "--min-draw-pct", help="Min draw %% to show a move (0-100)"
    ),
    max_draw_pct: float | None = typer.Option(
        None, "--max-draw-pct", help="Max draw %% to show a move (0-100)"
    ),
    min_black_pct: float | None = typer.Option(
        None, "--min-black-pct", help="Min black win %% to show a move (0-100)"
    ),
    repertoire: bool = typer.Option(
        False, "--repertoire", "-R", help="Show repertoire overlay column"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Explore opening statistics from the Lichess explorer."""
    from ..openings.explorer import OpeningExplorer
    from ..openings.models import ExplorerFilter, ExplorerSource

    cfg = _get_config()
    source_str = source or cfg.openings.explorer_source
    try:
        explorer_source = ExplorerSource(source_str)
    except ValueError:
        console.print(f"[red]Unknown source: {source_str}. Use lichess, masters, or player.[/red]")
        raise typer.Exit(1)

    board = chess.Board()
    if fen:
        try:
            board = chess.Board(fen)
        except ValueError:
            console.print(f"[red]Invalid FEN: {fen}[/red]")
            raise typer.Exit(1)

    # Build ExplorerFilter from CLI options
    parsed_speeds = tuple(s.strip() for s in speeds.split(",")) if speeds else None
    parsed_ratings = tuple(int(r.strip()) for r in ratings.split(",")) if ratings else None

    has_filter = (
        any(
            v is not None
            for v in (
                parsed_speeds,
                parsed_ratings,
                min_white_pct,
                min_draw_pct,
                max_draw_pct,
                min_black_pct,
            )
        )
        or repertoire
    )

    explorer_filter = None
    if has_filter:
        explorer_filter = ExplorerFilter(
            speeds=parsed_speeds,
            ratings=parsed_ratings,
            min_white_pct=min_white_pct,
            min_draw_pct=min_draw_pct,
            max_draw_pct=max_draw_pct,
            min_black_pct=min_black_pct,
            show_repertoire=repertoire,
        )

    with get_repo(db) as repo:
        explorer = OpeningExplorer(
            repo.openings,
            cache_ttl_hours=cfg.openings.cache_ttl_hours,
            min_games=cfg.openings.min_games,
        )
        _interactive_explore(
            board,
            explorer,
            explorer_source,
            player=player,
            color=color,
            explorer_filter=explorer_filter,
            store=repo.openings if repertoire else None,
        )


def _interactive_explore(
    board: chess.Board,
    explorer,
    source,
    *,
    player: str | None = None,
    color: str = "white",
    explorer_filter=None,
    store=None,
) -> None:
    """Interactive explorer REPL: view stats, play moves to go deeper."""
    from ..openings.explorer import ExplorerError, get_repertoire_moves
    from .board import render_board

    move_stack: list[chess.Move] = []

    while True:
        flipped = board.turn == chess.BLACK

        try:
            result = explorer.explore(
                board.fen(),
                source,
                player=player,
                color=color,
                explorer_filter=explorer_filter,
            )
        except ExplorerError as e:
            console.print(f"[red]Explorer error: {e}[/red]")
            break

        # Get repertoire info if requested
        rep_info = None
        if explorer_filter and explorer_filter.show_repertoire and store is not None:
            rep_info = get_repertoire_moves(board.fen(), result.moves, store)

        # Display board
        console.print(render_board(board, flipped=flipped))
        console.print()

        # Show opening name if available
        if result.opening_name:
            eco = f" ({result.opening_eco})" if result.opening_eco else ""
            console.print(f"[bold]{result.opening_name}{eco}[/bold]")

        if result.total_games > 0:
            console.print(f"[dim]{result.total_games:,} games[/dim]")

        # Build move stats table
        if result.moves:
            table = Table(title="Move Statistics")
            table.add_column("Move", style="bold")
            table.add_column("Games", justify="right")
            table.add_column("White", justify="right", style="green")
            table.add_column("Draw", justify="right", style="yellow")
            table.add_column("Black", justify="right", style="red")
            table.add_column("Avg Elo", justify="right", style="dim")

            if rep_info is not None:
                table.add_column("Book", justify="center")

            for m in result.moves:
                row = [
                    m.san,
                    f"{m.total_games:,}",
                    f"{m.white_pct:.0f}%",
                    f"{m.draw_pct:.0f}%",
                    f"{m.black_pct:.0f}%",
                    str(m.average_rating) if m.average_rating else "-",
                ]
                if rep_info is not None:
                    in_book = m.uci in rep_info.book_moves
                    row.append("[green]\u2713[/green]" if in_book else "-")
                table.add_row(*row)

            console.print(table)

            if rep_info is not None:
                book_count = sum(1 for m in result.moves if m.uci in rep_info.book_moves)
                console.print(
                    f"[dim]Repertoire: {book_count}/{len(result.moves)} moves covered[/dim]"
                )
        else:
            console.print("[yellow]No moves found in database.[/yellow]")

        # Prompt for input
        console.print("\n[dim]Enter a move (SAN/UCI), 'back' to undo, 'quit' to exit:[/dim]")
        text = input("> ").strip()

        if text.lower() in ("q", "quit", "exit"):
            break
        elif text.lower() in ("b", "back", "undo"):
            if move_stack:
                board.pop()
                move_stack.pop()
                console.print("[dim]Move undone.[/dim]\n")
            else:
                console.print("[yellow]No moves to undo.[/yellow]\n")
            continue

        move = _parse_move(board, text)
        if move is None:
            console.print("[red]Invalid move. Try again.[/red]\n")
            continue

        board.push(move)
        move_stack.append(move)
        console.print()


# ── Book subcommand group ─────────────────────────────────────────────────────

book_app = typer.Typer(help="Personal opening book management")
app.add_typer(book_app, name="book")


@book_app.command("add")
def book_add(
    pgn: str = typer.Option(..., "--pgn", help='PGN moves (e.g. "1.e4 e5 2.Nf3 Nc6")'),
    color: str = typer.Option(..., "--color", help="Side: white or black"),
    name: str = typer.Option("", "--name", "-n", help="Opening name"),
    variation: str = typer.Option("", "--variation", "-v", help="Variation name"),
    eco: str = typer.Option("", "--eco", help="ECO code"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Add a new opening line to your book."""
    from ..openings.book import BookError, create_line, parse_pgn_to_uci
    from ..openings.models import BookColor

    try:
        book_color = BookColor(color.lower())
    except ValueError:
        console.print(f"[red]Invalid color: {color}. Use 'white' or 'black'.[/red]")
        raise typer.Exit(1)

    try:
        uci_moves = parse_pgn_to_uci(pgn)
    except BookError as e:
        console.print(f"[red]PGN error: {e}[/red]")
        raise typer.Exit(1)

    try:
        line = create_line(book_color, uci_moves, name=name, variation=variation, eco_code=eco)
    except BookError as e:
        console.print(f"[red]Error creating line: {e}[/red]")
        raise typer.Exit(1)

    with get_repo(db) as repo:
        repo.openings.add_line(line)

    console.print(f"[green]\u2713[/green] Added line: {line.san_line}")
    console.print(f"  ID: {line.id}")
    if name:
        console.print(f"  Name: {name}")


@book_app.command("list")
def book_list(
    color: str | None = typer.Option(None, "--color", help="Filter by side: white or black"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """List opening lines in your book."""
    from ..openings.models import BookColor

    book_color = None
    if color:
        try:
            book_color = BookColor(color.lower())
        except ValueError:
            console.print(f"[red]Invalid color: {color}. Use 'white' or 'black'.[/red]")
            raise typer.Exit(1)

    with get_repo(db) as repo:
        lines = repo.openings.list_lines(color=book_color)

        if not lines:
            console.print("[yellow]No lines in your opening book.[/yellow]")
            console.print(
                "Add one with: chess-trainer book add --pgn '1.e4 e5' --color white --name 'Open Game'"
            )
            return

        table = Table(title=f"Opening Book ({len(lines)} lines)")
        table.add_column("ID", style="dim")
        table.add_column("Color", style="bold")
        table.add_column("Name")
        table.add_column("Variation")
        table.add_column("ECO", style="dim")
        table.add_column("Moves", justify="right")
        table.add_column("Line")

        for line in lines:
            table.add_row(
                line.id,
                line.color.value,
                line.name or "-",
                line.variation or "-",
                line.eco_code or "-",
                str(len(line.moves)),
                line.san_line[:40] + ("..." if len(line.san_line) > 40 else ""),
            )

        console.print(table)


@book_app.command("delete")
def book_delete(
    line_id: str = typer.Argument(help="ID of the line to delete"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Delete an opening line from your book."""
    with get_repo(db) as repo:
        deleted = repo.openings.delete_line(line_id)
        if deleted:
            console.print(f"[green]\u2713[/green] Deleted line {line_id}")
        else:
            console.print(f"[red]Line not found: {line_id}[/red]")
            raise typer.Exit(1)


@book_app.command("import-pgn")
def book_import_pgn(
    filepath: str = typer.Argument(help="Path to PGN file"),
    color: str = typer.Option(..., "--color", help="Side: white or black"),
    name: str = typer.Option("", "--name", "-n", help="Opening name for all imported lines"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Import opening lines from a PGN file."""
    from ..openings.book import BookError, create_line, parse_pgn_file
    from ..openings.models import BookColor

    try:
        book_color = BookColor(color.lower())
    except ValueError:
        console.print(f"[red]Invalid color: {color}. Use 'white' or 'black'.[/red]")
        raise typer.Exit(1)

    try:
        games = parse_pgn_file(filepath)
    except BookError as e:
        console.print(f"[red]Import error: {e}[/red]")
        raise typer.Exit(1)

    if not games:
        console.print("[yellow]No games found in file.[/yellow]")
        return

    with get_repo(db) as repo:
        added = 0
        for game_moves in games:
            try:
                line = create_line(book_color, game_moves, name=name)
                repo.openings.add_line(line)
                added += 1
            except (BookError, Exception) as e:
                console.print(f"[yellow]Skipping game: {e}[/yellow]")

    console.print(f"[green]\u2713[/green] Imported {added}/{len(games)} lines")


@book_app.command("import-study")
def book_import_study(
    url_or_id: str = typer.Argument(help="Lichess study URL or 8-char ID"),
    color: str = typer.Option(..., "--color", help="Side: white or black"),
    name: str = typer.Option("", "--name", "-n", help="Override opening name"),
    sync: bool = typer.Option(True, "--sync/--no-sync", help="Auto-sync exercises after import"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Import opening lines from a Lichess study."""
    from ..lichess.api import LichessError, get_study_pgn
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
        console.print(f"[red]Invalid color: {color}. Use 'white' or 'black'.[/red]")
        raise typer.Exit(1)

    try:
        study_id = parse_study_id(url_or_id)
    except BookError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    with console.status(f"Fetching study {study_id}..."):
        try:
            pgn_text = get_study_pgn(study_id)
        except LichessError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    chapters = parse_study_pgn(pgn_text)
    if not chapters:
        console.print("[yellow]No chapters found in study.[/yellow]")
        return

    lines = import_study_lines(study_id, chapters, book_color, name=name)
    if not lines:
        console.print("[yellow]No lines extracted (all chapters may have custom FEN).[/yellow]")
        return

    skipped = sum(1 for ch in chapters if ch.skipped)

    with get_repo(db) as repo:
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

        console.print(
            f"[green]\u2713[/green] Imported {len(lines)} lines "
            f"({added} new, {updated} updated) "
            f"from {len(chapters)} chapters" + (f" ({skipped} skipped)" if skipped else "")
        )

        if sync:
            # Generate exercises from all book lines and sync
            exercises_added = 0
            for line in lines:
                for exercise in generate_exercises(line):
                    existing_ex = repo.exercises.get(exercise.id)
                    if not existing_ex:
                        repo.exercises.add(exercise)
                        repo.cards.get_or_create(exercise.id)
                        exercises_added += 1
            console.print(f"  Synced {exercises_added} new exercises")


@book_app.command("sync")
def book_sync(
    with_explorer: bool = typer.Option(
        False, "--with-explorer", help="Fetch alternative moves from explorer"
    ),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Sync opening book lines into training exercises."""
    from ..openings.book import generate_exercises, get_alternatives_from_explorer
    from ..openings.explorer import OpeningExplorer

    cfg = _get_config()

    with get_repo(db) as repo:
        lines = repo.openings.list_lines()

        if not lines:
            console.print("[yellow]No lines in your opening book. Add some first.[/yellow]")
            return

        # Collect expected exercise IDs
        expected_ids: set[str] = set()
        exercises_to_add = []

        explorer = None
        if with_explorer:
            explorer = OpeningExplorer(
                repo.openings,
                cache_ttl_hours=cfg.openings.cache_ttl_hours,
                min_games=cfg.openings.min_games,
            )

        for line in lines:
            alternatives = None
            if explorer:
                with console.status(f"Fetching alternatives for {line.name or line.id}..."):
                    alternatives = get_alternatives_from_explorer(
                        line, explorer, min_games=cfg.openings.min_games
                    )

            for exercise in generate_exercises(line, alternatives):
                expected_ids.add(exercise.id)
                exercises_to_add.append(exercise)

        # Delete stale book exercises
        existing_book = repo.exercises.search(source="book")
        stale = [e for e in existing_book if e.id not in expected_ids]
        for ex in stale:
            repo.cards.delete(ex.id)
            repo.exercises.delete(ex.id)

        # Add new exercises
        added = 0
        for exercise in exercises_to_add:
            existing = repo.exercises.get(exercise.id)
            if not existing:
                repo.exercises.add(exercise)
                repo.cards.get_or_create(exercise.id)
                added += 1

        console.print(
            f"[green]\u2713[/green] Synced: {added} new exercises, "
            f"{len(stale)} stale removed, "
            f"{len(expected_ids)} total"
        )


@book_app.command("train")
def book_train(
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Start a training session with opening exercises."""
    # Delegate to the main train command with --type OPENING
    train(exercise_type="OPENING", db=db)


@app.command("import-games")
def import_games(
    pgn: Path | None = typer.Option(None, "--pgn", help="Path to PGN file"),
    user: str | None = typer.Option(None, "--user", "-u", help="Lichess username"),
    chesscom_user: str | None = typer.Option(None, "--chesscom-user", help="Chess.com username"),
    max_games: int = typer.Option(10, "--max-games", "-n", help="Max games to import"),
    server_evals: bool = typer.Option(
        False, "--server-evals", help="Use Lichess server evaluations (no engine needed)"
    ),
    color: str | None = typer.Option(None, "--color", help="Only exercises for white or black"),
    time_class: str | None = typer.Option(
        None, "--time-class", help="Filter by time class (bullet, blitz, rapid, daily)"
    ),
    min_severity: str = typer.Option(
        None, "--min-severity", help="Minimum severity: INACCURACY, MISTAKE, or BLUNDER"
    ),
    max_exercises: int | None = typer.Option(
        None, "--max-exercises", help="Max exercises per game"
    ),
    depth: int | None = typer.Option(None, "--depth", "-d", help="Engine analysis depth"),
    engine_path: str | None = typer.Option(
        None, "--engine", "-e", help="Path to UCI engine binary"
    ),
    since: str | None = typer.Option(None, "--since", help="Only games since (YYYY-MM-DD)"),
    until: str | None = typer.Option(None, "--until", help="Only games until (YYYY-MM-DD)"),
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Import own games and generate exercises from mistakes."""
    from ..analysis import EngineError, EngineManager, MoveClassification

    sources = sum(1 for s in (pgn, user, chesscom_user) if s is not None)
    if sources == 0:
        console.print("[red]Specify --pgn, --user (Lichess), or --chesscom-user.[/red]")
        raise typer.Exit(1)
    if sources > 1:
        console.print("[red]--pgn, --user, and --chesscom-user are mutually exclusive.[/red]")
        raise typer.Exit(1)

    if chesscom_user and server_evals:
        console.print(
            "[yellow]--server-evals is not available for Chess.com. Using engine.[/yellow]"
        )
        server_evals = False

    cfg = _get_config()
    ga = cfg.game_analysis

    analysis_depth = depth or ga.analysis_depth
    severity = min_severity or ga.min_classification
    max_ex = max_exercises or ga.max_exercises_per_game

    try:
        min_class = MoveClassification[severity.upper()]
    except KeyError:
        console.print(
            f"[red]Invalid severity: {severity}. Use INACCURACY, MISTAKE, or BLUNDER.[/red]"
        )
        raise typer.Exit(1)

    # Parse date filters to Unix ms timestamps
    since_ms = _parse_date_to_ms(since) if since else None
    until_ms = _parse_date_to_ms(until) if until else None

    # Determine if we need an engine
    need_engine = not server_evals
    engine_mgr = None

    if need_engine:
        engine_bin = engine_path or cfg.engine.path
        try:
            engine_mgr = EngineManager(
                path=engine_bin,
                hash_mb=cfg.engine.hash_mb,
                threads=cfg.engine.threads,
            )
            engine_mgr.open()
        except EngineError as e:
            if server_evals:
                console.print("[yellow]Engine not available, using server evals only.[/yellow]")
                engine_mgr = None
            else:
                console.print(f"[red]{e}[/red]")
                raise typer.Exit(1)

    try:
        if chesscom_user:
            from ..importers.chesscom_games import ChessComGameImporter

            importer = ChessComGameImporter(
                engine_mgr,
                depth=analysis_depth,
                min_classification=min_class,
                max_exercises=max_ex,
                skip_first_plies=ga.skip_first_plies,
            )

            fetch_kwargs: dict = {
                "username": chesscom_user,
                "max_games": max_games,
                "user_agent": cfg.chesscom.user_agent,
                "request_delay": cfg.chesscom.request_delay,
            }
            if color:
                fetch_kwargs["color"] = color.lower()
            if time_class:
                fetch_kwargs["time_class"] = time_class
            if since:
                # Parse YYYY-MM-DD into year/month for Chess.com
                parts = since.split("-")
                if len(parts) >= 2:
                    fetch_kwargs["since_year"] = int(parts[0])
                    fetch_kwargs["since_month"] = int(parts[1])

            source_tag = "chesscom"
        else:
            from ..importers.games import GameImporter

            importer = GameImporter(
                engine_mgr,
                depth=analysis_depth,
                min_classification=min_class,
                max_exercises=max_ex,
                skip_first_plies=ga.skip_first_plies,
            )

            fetch_kwargs = {}
            if pgn:
                fetch_kwargs["pgn_path"] = pgn
            else:
                fetch_kwargs["username"] = user
                fetch_kwargs["use_server_evals"] = server_evals
                fetch_kwargs["max_games"] = max_games
                fetch_kwargs["since"] = since_ms
                fetch_kwargs["until"] = until_ms

            if color:
                fetch_kwargs["color"] = color.lower()

            source_tag = "game_analysis"

        with get_repo(db) as repo:
            with console.status("Analyzing games and generating exercises..."):
                result = importer.import_to(repo.exercises, **fetch_kwargs)

            console.print(f"\n[green]\u2713[/green] {result}")

            # Create review cards for new exercises
            if result.total_added > 0:
                for exercise in repo.exercises.search(source=source_tag):
                    existing = repo.cards.get(exercise.id)
                    if not existing:
                        repo.cards.get_or_create(exercise.id)
                _sync_system_tags(repo, source=source_tag)

            if result.errors:
                console.print("[yellow]Errors:[/yellow]")
                for error in result.errors[:5]:
                    console.print(f"  - {error}")
    finally:
        if engine_mgr:
            engine_mgr.close()


@app.command("analyze-game")
def analyze_game(
    pgn: Path | None = typer.Option(None, "--pgn", help="Path to PGN file"),
    game_id: str | None = typer.Option(None, "--game-id", help="Lichess game ID"),
    chesscom_game: str | None = typer.Option(
        None, "--chesscom-game", help="Chess.com game URL or ID"
    ),
    server_evals: bool = typer.Option(
        False, "--server-evals", help="Use Lichess server evaluations"
    ),
    depth: int | None = typer.Option(None, "--depth", "-d", help="Engine analysis depth"),
    engine_path: str | None = typer.Option(
        None, "--engine", "-e", help="Path to UCI engine binary"
    ),
    color: str | None = typer.Option(None, "--color", help="Show only white or black moves"),
):
    """Analyze a game and display a move-by-move quality report."""
    from ..analysis import EngineError, EngineManager, MoveClassification
    from ..analysis.mistakes import (
        EnginePositionAnalyzer,
        LichessServerAnalyzer,
        MistakeDetector,
    )
    from ..importers.games import parse_pgn_games

    sources = sum(1 for s in (pgn, game_id, chesscom_game) if s is not None)
    if sources == 0:
        console.print("[red]Specify --pgn, --game-id (Lichess), or --chesscom-game.[/red]")
        raise typer.Exit(1)
    if sources > 1:
        console.print("[red]--pgn, --game-id, and --chesscom-game are mutually exclusive.[/red]")
        raise typer.Exit(1)

    if chesscom_game and server_evals:
        console.print(
            "[yellow]--server-evals is not available for Chess.com. Using engine.[/yellow]"
        )
        server_evals = False

    cfg = _get_config()
    analysis_depth = depth or cfg.game_analysis.analysis_depth

    import io

    import chess.pgn

    game = None
    source_url = None
    lichess_evals = None

    if pgn:
        games = parse_pgn_games(pgn)
        if not games:
            console.print("[red]No games found in PGN file.[/red]")
            raise typer.Exit(1)
        game = games[0]
    elif chesscom_game:
        from ..chesscom.api import ChessComError, get_chesscom

        # Extract game ID from URL if needed
        cc_game_id = chesscom_game.rstrip("/").split("/")[-1]

        try:
            # Chess.com provides PGN via the game callback endpoint
            # For monthly archive games, we can fetch by the URL or we fetch the PGN directly
            game_data = get_chesscom(
                f"callback/{cc_game_id}",
                user_agent=cfg.chesscom.user_agent,
            )
            pgn_text = game_data.get("pgn", "")
        except ChessComError:
            # Fallback: try to interpret chesscom_game as a full URL and inform user
            console.print(
                "[red]Could not fetch game from Chess.com. "
                "Try exporting the PGN manually and use --pgn instead.[/red]"
            )
            raise typer.Exit(1)

        if not pgn_text:
            console.print("[red]No PGN data in Chess.com game response.[/red]")
            raise typer.Exit(1)

        game = chess.pgn.read_game(io.StringIO(pgn_text))
        source_url = chesscom_game if chesscom_game.startswith("http") else None
    elif game_id:
        from ..lichess.api import get_game

        game_data = get_game(game_id)
        pgn_text = game_data.get("pgn", "")
        if not pgn_text:
            console.print("[red]No PGN data in game response.[/red]")
            raise typer.Exit(1)

        game = chess.pgn.read_game(io.StringIO(pgn_text))
        source_url = f"https://lichess.org/{game_id}"

        if server_evals and "analysis" in game_data:
            lichess_evals = game_data.get("analysis", [])

    if game is None:
        console.print("[red]Could not parse game.[/red]")
        raise typer.Exit(1)

    engine_mgr = None
    try:
        if lichess_evals is not None or server_evals:
            if lichess_evals:
                evals = [{"cp": 0}]
                for entry in lichess_evals:
                    if entry and "eval" in entry:
                        evals.append(entry["eval"])
                    elif entry:
                        evals.append(entry)
                    else:
                        evals.append(None)
                analyzer = LichessServerAnalyzer(evals)
            else:
                console.print("[yellow]No server evals available, falling back to engine.[/yellow]")
                server_evals = False

        if not server_evals and lichess_evals is None:
            engine_bin = engine_path or cfg.engine.path
            try:
                engine_mgr = EngineManager(
                    path=engine_bin,
                    hash_mb=cfg.engine.hash_mb,
                    threads=cfg.engine.threads,
                )
                engine_mgr.open()
                analyzer = EnginePositionAnalyzer(engine_mgr, depth=analysis_depth)
            except EngineError as e:
                console.print(f"[red]{e}[/red]")
                raise typer.Exit(1)

        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.BEST,
            skip_first_plies=0,
        )

        with console.status("Analyzing game..."):
            analysis = detector.analyze_game(game, game_id=game_id, source_url=source_url)

        # Display results
        console.print(
            f"\n[bold]{analysis.white}[/bold] vs [bold]{analysis.black}[/bold] — {analysis.result}"
        )
        if analysis.source_url:
            console.print(f"[dim]{analysis.source_url}[/dim]")

        # Move table
        table = Table(title="Move-by-Move Analysis")
        table.add_column("#", style="dim", width=4)
        table.add_column("Move", width=8)
        table.add_column("Quality", width=12)
        table.add_column("CP Loss", justify="right", width=8)
        table.add_column("Eval", justify="right", width=8)

        for am in analysis.moves:
            if color and am.color != color.lower():
                continue

            # Color-code the quality
            cls = am.classification
            if cls == MoveClassification.BLUNDER:
                style = "red bold"
            elif cls == MoveClassification.MISTAKE:
                style = "red"
            elif cls == MoveClassification.INACCURACY:
                style = "yellow"
            elif cls in (MoveClassification.BEST, MoveClassification.EXCELLENT):
                style = "green"
            else:
                style = ""

            board_at = chess.Board(am.fen_before)
            san = board_at.san(am.move)
            move_label = f"{am.move_number}{'.' if am.color == 'white' else '...'}{san}"

            eval_cp = am.eval_before.score_cp / 100
            eval_str = f"{eval_cp:+.1f}"

            table.add_row(
                str(am.ply),
                move_label,
                f"[{style}]{cls.name}[/{style}]",
                str(am.cp_loss) if am.cp_loss > 0 else "",
                eval_str,
            )

        console.print(table)

        # Summary
        mistakes = analysis.filter_by_classification(MoveClassification.MISTAKE)
        blunders = analysis.filter_by_classification(MoveClassification.BLUNDER)
        inaccuracies = analysis.filter_by_classification(MoveClassification.INACCURACY)

        console.print(
            f"\n[bold]Summary:[/bold] "
            f"[yellow]{len(inaccuracies)} inaccuracies[/yellow], "
            f"[red]{len(mistakes)} mistakes[/red], "
            f"[red bold]{len(blunders)} blunders[/red bold]"
        )
    finally:
        if engine_mgr:
            engine_mgr.close()


def _parse_date_to_ms(date_str: str) -> int:
    """Parse a YYYY-MM-DD date string to Unix milliseconds."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0


@app.command()
def tablebase(
    fen: str = typer.Argument(None, help="FEN string to probe"),
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Interactive exploration mode"
    ),
    syzygy_path: str | None = typer.Option(None, "--syzygy", help="Path to Syzygy tablebase files"),
):
    """Probe endgame tablebases for a position."""
    from ..tablebase import TablebaseError, TablebaseManager

    cfg = _get_config()
    tb_path = syzygy_path or cfg.tablebase.syzygy_path

    if not fen and not interactive:
        console.print("[red]Provide a FEN string or use --interactive.[/red]")
        raise typer.Exit(1)

    # Build initial board
    if fen:
        try:
            board = chess.Board(fen)
        except ValueError:
            console.print(f"[red]Invalid FEN: {fen}[/red]")
            raise typer.Exit(1)
    else:
        board = chess.Board()

    try:
        with TablebaseManager(
            syzygy_path=tb_path,
            use_lichess_fallback=cfg.tablebase.use_lichess_fallback,
            max_pieces=cfg.tablebase.max_pieces,
        ) as tb_mgr:
            if interactive:
                _interactive_tablebase(board, tb_mgr)
            else:
                _static_tablebase(board, tb_mgr)
    except TablebaseError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def _piece_description(board: chess.Board) -> str:
    """Generate a short piece description like 'KPK'."""
    piece_names = {
        chess.KING: "K",
        chess.QUEEN: "Q",
        chess.ROOK: "R",
        chess.BISHOP: "B",
        chess.KNIGHT: "N",
        chess.PAWN: "P",
    }
    white_pieces = ""
    black_pieces = ""
    for piece_type in [chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]:
        white_count = len(board.pieces(piece_type, chess.WHITE))
        black_count = len(board.pieces(piece_type, chess.BLACK))
        white_pieces += piece_names[piece_type] * white_count
        black_pieces += piece_names[piece_type] * black_count
    return f"{white_pieces}v{black_pieces}"


def _wdl_style(wdl: int) -> str:
    """Get Rich style string for a WDL value."""
    if wdl >= 2:
        return "green bold"
    elif wdl == 1:
        return "green"
    elif wdl == 0:
        return "yellow"
    elif wdl == -1:
        return "red"
    else:
        return "red bold"


def _static_tablebase(board: chess.Board, tb_mgr) -> None:
    """Display tablebase probe results."""
    from ..tablebase import TablebaseError

    flipped = board.turn == chess.BLACK
    console.print(render_board(board, flipped=flipped))
    console.print()

    try:
        result = tb_mgr.probe(board)
    except TablebaseError as e:
        console.print(f"[red]{e}[/red]")
        return

    pieces = _piece_description(board)
    side = "White" if board.turn == chess.WHITE else "Black"
    style = _wdl_style(result.wdl)
    dtz_str = f" (DTZ: {result.dtz})" if result.dtz is not None else ""

    console.print(f"[bold]{pieces}[/bold] ({side} to move)")
    console.print(f"Result: [{style}]{result.category.upper()}{dtz_str}[/{style}]")

    if result.checkmate:
        console.print("[red bold]Checkmate![/red bold]")
        return
    if result.stalemate:
        console.print("[yellow]Stalemate![/yellow]")
        return

    if result.moves:
        console.print()
        table = Table(title="Moves")
        table.add_column("#", style="dim", width=4)
        table.add_column("Move", style="bold", width=8)
        table.add_column("Result", width=14)
        table.add_column("DTZ", justify="right", width=6)

        for i, m in enumerate(result.moves, 1):
            move_style = _wdl_style(m.wdl)
            dtz_val = str(m.dtz) if m.dtz is not None else "-"
            flags = ""
            if m.checkmate:
                flags = " #"
            elif m.zeroing:
                flags = " *"
            table.add_row(
                str(i),
                m.san,
                f"[{move_style}]{m.category.upper()}[/{move_style}]",
                dtz_val + flags,
            )

        console.print(table)
        console.print("[dim]* = zeroing move (capture/pawn), # = checkmate[/dim]")


def _interactive_tablebase(board: chess.Board, tb_mgr) -> None:
    """Interactive tablebase REPL: play moves, probe each position."""
    move_stack: list[chess.Move] = []

    while True:
        _static_tablebase(board, tb_mgr)

        console.print("\n[dim]Enter a move (SAN/UCI), 'back' to undo, 'quit' to exit:[/dim]")
        text = input("> ").strip()

        if text.lower() in ("q", "quit", "exit"):
            break
        elif text.lower() in ("b", "back", "undo"):
            if move_stack:
                board.pop()
                move_stack.pop()
                console.print("[dim]Move undone.[/dim]\n")
            else:
                console.print("[yellow]No moves to undo.[/yellow]\n")
            continue
        elif text.lower() in ("f", "fen"):
            console.print(f"[dim]{board.fen()}[/dim]\n")
            continue

        move = _parse_move(board, text)
        if move is None:
            console.print("[red]Invalid move. Try again.[/red]\n")
            continue

        board.push(move)
        move_stack.append(move)
        console.print()


@app.command("endgame-masters")
def endgame_masters(
    fen: str = typer.Argument(None, help="FEN to search from"),
    type_key: str = typer.Option(
        None, "--type", "-t", help="Endgame type (kpk, rook, bishop, etc.)"
    ),
    top_games: int = typer.Option(15, "--top-games", "-n"),
    replay: bool = typer.Option(False, "--replay", "-r", help="Interactive replay mode"),
    generate: bool = typer.Option(False, "--generate", "-g", help="Generate exercises"),
    max_exercises: int = typer.Option(5, "--max-exercises"),
    syzygy_path: str | None = typer.Option(None, "--syzygy"),
    db: Path | None = typer.Option(None, "--db"),
):
    """Browse master games with endgame tablebase evaluation."""
    from ..endgame_masters import (
        FetcherError,
        build_endgame_phase,
        find_endgame_games,
    )
    from ..tablebase import TablebaseError, TablebaseManager

    if not fen and not type_key:
        console.print("[red]Provide a FEN or use --type (kpk, rook, bishop, etc.).[/red]")
        raise typer.Exit(1)

    cfg = _get_config()
    tb_path = syzygy_path or cfg.tablebase.syzygy_path

    try:
        with console.status("Searching for master games with endgame phases..."):
            games = find_endgame_games(fen=fen, type_key=type_key, top_games=top_games)
    except (FetcherError, KeyError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not games:
        console.print("[yellow]No master games with endgames found.[/yellow]")
        return

    console.print(f"Found [bold]{len(games)}[/bold] games with endgame phases.\n")

    try:
        with TablebaseManager(
            syzygy_path=tb_path,
            use_lichess_fallback=cfg.tablebase.use_lichess_fallback,
            max_pieces=cfg.tablebase.max_pieces,
        ) as tb_mgr:
            # Build annotated phases
            phases: list = []
            with console.status("Annotating endgame positions with tablebase..."):
                for info, game_obj in games:
                    pgn_text = ""  # We already have the parsed game
                    phase = build_endgame_phase(info, pgn_text, game_obj, tb_mgr)
                    if phase is not None:
                        phases.append(phase)

            if not phases:
                console.print("[yellow]No tablebase-eligible endgame positions found.[/yellow]")
                return

            if replay:
                _replay_endgame(phases, tb_mgr)
            elif generate:
                _generate_endgame_exercises(phases, tb_mgr, db, max_exercises)
            else:
                _browse_endgame_masters(phases)

    except TablebaseError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


def _browse_endgame_masters(phases: list) -> None:
    """Display a summary table of master games with endgame phases."""
    from ..endgame_masters import classify_endgame_type

    table = Table(title="Master Games with Endgame Phases")
    table.add_column("#", style="dim", width=3)
    table.add_column("Players", style="bold")
    table.add_column("Year", justify="right")
    table.add_column("Result")
    table.add_column("Endgame Type")
    table.add_column("Critical", justify="right", style="yellow")
    table.add_column("Positions", justify="right")

    for i, phase in enumerate(phases, 1):
        info = phase.game_info
        result = "1-0" if info.winner == "white" else "0-1" if info.winner == "black" else "1/2"
        players = f"{info.white} ({info.white_rating}) vs {info.black} ({info.black_rating})"

        # Classify from the first annotated position
        eg_type = ""
        if phase.positions:
            board = chess.Board(phase.positions[0].fen)
            eg_type = classify_endgame_type(board)

        table.add_row(
            str(i),
            players,
            str(info.year),
            result,
            eg_type,
            str(len(phase.critical_moments)),
            str(len(phase.positions)),
        )

    console.print(table)


def _replay_endgame(phases: list, tb_mgr) -> None:
    """Interactive replay of endgame positions from a master game."""
    if not phases:
        return

    # Pick the first phase for replay (could prompt for selection)
    phase = phases[0]
    positions = phase.positions

    if not positions:
        console.print("[yellow]No annotated positions to replay.[/yellow]")
        return

    info = phase.game_info
    console.print(f"[bold]Replaying:[/bold] {info.white} vs {info.black} ({info.year})\n")

    idx = 0
    while 0 <= idx < len(positions):
        pos = positions[idx]
        board = chess.Board(pos.fen)
        flipped = board.turn == chess.BLACK

        console.print(render_board(board, flipped=flipped))
        console.print()

        wdl_style = _wdl_style(pos.wdl)
        console.print(f"[bold]Position {idx + 1}/{len(positions)}[/bold] (ply {pos.ply})")
        console.print(f"WDL: [{wdl_style}]{pos.category.upper()}[/{wdl_style}]", end="")
        if pos.dtz is not None:
            console.print(f" (DTZ: {pos.dtz})", end="")
        console.print()

        if pos.move_san:
            console.print(f"Master played: [bold]{pos.move_san}[/bold]", end="")
            if pos.wdl_after is not None:
                after_style = _wdl_style(pos.wdl_after)
                if pos.wdl_after < pos.wdl:
                    console.print(f" [{after_style}]WORSENED[/{after_style}]", end="")
                elif pos.wdl_after >= pos.wdl:
                    console.print(f" [{after_style}]OK[/{after_style}]", end="")
            console.print()

        if pos.is_critical:
            console.print("[yellow bold]** Critical moment **[/yellow bold]")

        console.print("\n[dim]Enter: next, 'b': back, 'q': quit[/dim]")
        text = input("> ").strip().lower()

        if text in ("q", "quit", "exit"):
            break
        elif text in ("b", "back"):
            idx = max(0, idx - 1)
        else:
            idx += 1

        console.print()


def _generate_endgame_exercises(phases: list, tb_mgr, db_path, max_exercises: int) -> None:
    """Generate and store EndgameExercise items from annotated phases."""
    from ..endgame_masters import generate_endgame_exercises

    all_exercises = []
    for phase in phases:
        for exercise in generate_endgame_exercises(phase, tb_mgr, max_exercises=max_exercises):
            all_exercises.append(exercise)

    if not all_exercises:
        console.print("[yellow]No critical moments found for exercise generation.[/yellow]")
        return

    with get_repo(db_path) as repo:
        added = 0
        for exercise in all_exercises:
            existing = repo.exercises.get(exercise.id)
            if not existing:
                repo.exercises.add(exercise)
                repo.cards.get_or_create(exercise.id)
                added += 1

    console.print(
        f"[green]\u2713[/green] Generated {added} new exercises "
        f"({len(all_exercises)} total, {len(all_exercises) - added} already existed)"
    )


@app.command()
def scan(
    image_path: Path = typer.Argument(help="Path to a chess board image (PNG, JPG, etc.)"),
    backend: str | None = typer.Option(
        None, "--backend", "-b", help="Vision backend: claude, openai, or local"
    ),
    analyze_pos: bool = typer.Option(
        False, "--analyze", "-a", help="Run engine analysis on the recognized position"
    ),
    depth: int | None = typer.Option(None, "--depth", "-d", help="Engine analysis depth"),
):
    """Scan a chess board image and recognize the position (experimental)."""
    from ..config import is_experimental_enabled
    from ..vision import VisionError, get_backend

    cfg = _get_config()

    # Gate check
    if not is_experimental_enabled(cfg, "vision"):
        console.print(
            "[red]Vision import is an experimental feature.[/red]\n\n"
            "To enable it, set both flags in your config:\n"
            "  chess-trainer config set experimental.enabled true\n"
            "  chess-trainer config set experimental.vision true\n\n"
            "Then configure a backend:\n"
            "  chess-trainer config set experimental.vision_backend claude\n"
            "  chess-trainer config set experimental.claude_api_key YOUR_KEY\n\n"
            "Or set the ANTHROPIC_API_KEY / OPENAI_API_KEY environment variable."
        )
        raise typer.Exit(1)

    # Validate image exists
    if not image_path.is_file():
        console.print(f"[red]Image file not found: {image_path}[/red]")
        raise typer.Exit(1)

    # Override backend if CLI flag provided
    if backend:
        cfg.experimental.vision_backend = backend

    # Get backend
    try:
        vision_backend = get_backend(cfg)
    except VisionError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Recognize
    try:
        with console.status(f"Recognizing board with {vision_backend.name} backend..."):
            result = vision_backend.recognize(image_path)
    except VisionError as e:
        console.print(f"[red]Recognition failed: {e}[/red]")
        raise typer.Exit(1)

    # Validate FEN with python-chess
    try:
        board = chess.Board(result.fen)
    except ValueError:
        console.print(f"[red]Invalid FEN returned: {result.fen!r}[/red]")
        raise typer.Exit(1)

    # Display result
    flipped = board.turn == chess.BLACK
    console.print(render_board(board, flipped=flipped))
    console.print()
    console.print(f"[bold]FEN:[/bold] {result.fen}")
    console.print(f"[dim]Confidence: {result.confidence:.0%} | Backend: {result.backend}[/dim]")

    # Ask for confirmation
    if not typer.confirm("\nDoes this look correct?", default=True):
        corrected = typer.prompt("Enter the correct FEN (or press Ctrl+C to cancel)")
        try:
            board = chess.Board(corrected)
            result = type(result)(fen=corrected, confidence=1.0, backend="manual")
        except ValueError:
            console.print(f"[red]Invalid FEN: {corrected}[/red]")
            raise typer.Exit(1)

        console.print()
        console.print(render_board(board, flipped=board.turn == chess.BLACK))
        console.print(f"[bold]FEN:[/bold] {result.fen}")

    # Optional engine analysis
    if analyze_pos:
        from ..analysis import EngineError, EngineManager

        analysis_depth = depth or cfg.engine.default_depth

        try:
            with EngineManager(
                path=cfg.engine.path,
                hash_mb=cfg.engine.hash_mb,
                threads=cfg.engine.threads,
            ) as engine_mgr:
                analysis_result = engine_mgr.analyze(
                    board,
                    depth=analysis_depth,
                    multipv=cfg.engine.default_multipv,
                )
                console.print()
                _static_analysis(board, analysis_result, flipped=flipped)
        except EngineError as e:
            console.print(f"[red]Analysis error: {e}[/red]")
            raise typer.Exit(1)


@app.command()
def web(
    host: str = typer.Option(None, "--host", "-H", help="Bind host"),
    port: int = typer.Option(None, "--port", "-p", help="Bind port"),
):
    """Launch the web training interface."""
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Web dependencies not installed.[/red]\n"
            "Install with: pip install chess-trainer[web]"
        )
        raise typer.Exit(1)

    from ..web import create_app

    cfg = _get_config()
    bind_host = host or cfg.web.host
    bind_port = port or cfg.web.port

    web_app = create_app(cfg)
    console.print(f"[green]Starting web server at http://{bind_host}:{bind_port}[/green]")
    uvicorn.run(web_app, host=bind_host, port=bind_port)


# ── Auth subcommand group ────────────────────────────────────────────────────

auth_app = typer.Typer(help="Manage user authentication")
app.add_typer(auth_app, name="auth")


@auth_app.command("create-invite")
def auth_create_invite(
    count: int = typer.Option(1, "--count", "-n", help="Number of invite codes to generate"),
):
    """Generate invite codes for user registration."""
    from ..auth.service import AuthService
    from ..auth.store import AuthStore

    cfg = _get_config()
    with AuthStore(cfg.auth.database_path) as store:
        svc = AuthService(store, cfg.auth.session_expiry_hours)
        for _ in range(count):
            code = svc.create_invite_code()
            console.print(code)


@auth_app.command("list-invites")
def auth_list_invites():
    """Show all invite codes with usage status."""
    from ..auth.store import AuthStore

    cfg = _get_config()
    with AuthStore(cfg.auth.database_path) as store:
        invites = store.list_invites()
        if not invites:
            console.print("[dim]No invite codes found.[/dim]")
            return
        table = Table(title="Invite Codes")
        table.add_column("Code", style="cyan")
        table.add_column("Created")
        table.add_column("Used By")
        table.add_column("Used At")
        for inv in invites:
            table.add_row(
                inv.code,
                str(inv.created_at)[:19],
                inv.used_by or "",
                str(inv.used_at)[:19] if inv.used_at else "",
            )
        console.print(table)


@auth_app.command("list-users")
def auth_list_users():
    """Show all registered users."""
    from ..auth.store import AuthStore

    cfg = _get_config()
    with AuthStore(cfg.auth.database_path) as store:
        users = store.list_users()
        if not users:
            console.print("[dim]No users found.[/dim]")
            return
        table = Table(title="Users")
        table.add_column("ID", style="cyan")
        table.add_column("Username")
        table.add_column("Created")
        table.add_column("Active")
        for u in users:
            table.add_row(
                u.id,
                u.username,
                str(u.created_at)[:19],
                "[green]Yes[/green]" if u.is_active else "[red]No[/red]",
            )
        console.print(table)


@auth_app.command("deactivate")
def auth_deactivate(
    username: str = typer.Argument(help="Username to deactivate"),
):
    """Deactivate a user account."""
    from ..auth.store import AuthStore

    cfg = _get_config()
    with AuthStore(cfg.auth.database_path) as store:
        user = store.get_user_by_username(username)
        if not user:
            console.print(f"[red]User '{username}' not found.[/red]")
            raise typer.Exit(1)
        store.deactivate_user(user.id)
        store.delete_user_sessions(user.id)
        console.print(f"[yellow]Deactivated user '{username}' and cleared sessions.[/yellow]")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
