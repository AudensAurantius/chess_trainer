"""Main CLI application using Typer."""

import time
from datetime import datetime
from pathlib import Path

import chess
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .. import configure_logging
from ..config import AppConfig, load_config
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


@app.callback()
def _main_callback(
    config: Path | None = typer.Option(None, "--config", "-c", help="Path to config TOML"),
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
        for exercise in repo.exercises.iterate_all():
            existing = repo.cards.get(exercise.id)
            if not existing:
                repo.cards.get_or_create(exercise.id)
                created += 1

        console.print(f"[green]\u2713[/green] Created {created} new review cards")


config_app = typer.Typer(help="Configuration management")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init() -> None:
    """Generate a default config file at ~/.chess-trainer/config.toml."""
    from ..config import DEFAULT_CONFIG_PATH, generate_default_config

    if DEFAULT_CONFIG_PATH.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {DEFAULT_CONFIG_PATH}")
        overwrite = typer.confirm("Overwrite?", default=False)
        if not overwrite:
            raise typer.Abort()

    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CONFIG_PATH.write_text(generate_default_config())
    console.print(f"[green]\u2713[/green] Config written to {DEFAULT_CONFIG_PATH}")


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
            f"[bold]web.port[/bold] = {cfg.web.port}",
            title="Effective Configuration",
        )
    )


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
