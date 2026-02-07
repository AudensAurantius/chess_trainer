"""
Main CLI application using Typer.
"""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from ..storage import Repository
from ..exercises import ExerciseType
from ..importers import LichessPuzzleImporter
from ..training import TrainingSession, SessionConfig
from ..scheduling.fsrs import Rating

app = typer.Typer(
    name="chess-trainer",
    help="Spaced repetition training for chess improvement",
    no_args_is_help=True,
)
console = Console()

# Default database location
DEFAULT_DB = Path.home() / ".chess-trainer" / "trainer.db"


def get_repo(db_path: Path | None = None) -> Repository:
    """Get repository with default or specified path."""
    return Repository(db_path or DEFAULT_DB)


@app.command()
def import_puzzles(
    count: int = typer.Option(20, "--count", "-n", help="Number of puzzles to import"),
    difficulty: Optional[str] = typer.Option(
        None, "--difficulty", "-d",
        help="Difficulty filter (easiest, easier, normal, harder, hardest)"
    ),
    theme: Optional[str] = typer.Option(
        None, "--theme", "-t", help="Tactical theme filter"
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Database path"),
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

        console.print(f"\n[green]✓[/green] {result}")

        if result.errors:
            console.print(f"[yellow]Errors:[/yellow]")
            for error in result.errors[:5]:
                console.print(f"  - {error}")


@app.command()
def stats(
    db: Optional[Path] = typer.Option(None, "--db", help="Database path"),
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
            table.add_row(
                "Avg stability",
                f"{card_stats['average_stability_days']:.1f} days"
            )

            for state, count in card_stats["state_counts"].items():
                table.add_row(f"  {state}", str(count))

            console.print(table)


@app.command()
def train(
    new_cards: int = typer.Option(10, "--new", "-n", help="Max new cards"),
    reviews: int = typer.Option(50, "--reviews", "-r", help="Max reviews"),
    exercise_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Exercise type filter"
    ),
    db: Optional[Path] = typer.Option(None, "--db", help="Database path"),
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

        config = SessionConfig(
            max_new_cards=new_cards,
            max_reviews=reviews,
            exercise_types=type_filter,
        )

        session = TrainingSession(repo, config)
        session.start()

        if session.remaining == 0:
            console.print("[yellow]No cards due for review![/yellow]")
            console.print("Try importing some puzzles first: chess-trainer import-puzzles")
            return

        console.print(f"\n[bold]Training Session[/bold]")
        console.print(f"Cards to review: {session.remaining}\n")

        while True:
            exercise = session.next()
            if not exercise:
                break

            # Display the exercise
            console.print(Panel(
                f"[bold]{exercise.get_challenge()}[/bold]\n\n"
                f"FEN: {exercise.fen}\n"
                f"[dim]({exercise.exercise_type.name} | "
                f"Tags: {', '.join(exercise.tags) or 'none'})[/dim]",
                title=f"Exercise {session.stats.exercises_shown}/{session.remaining + session.stats.exercises_shown}",
            ))

            # In a real implementation, we'd have a chess board UI
            # For now, ask user to self-report
            console.print("\n[dim]View position and attempt the solution...[/dim]")
            console.print(f"Solution: {exercise.get_solution()}")

            # Get rating
            rating_input = typer.prompt(
                "\nHow did you do? [1=Again, 2=Hard, 3=Good, 4=Easy]",
                type=int,
                default=3,
            )

            if rating_input < 1 or rating_input > 4:
                rating_input = 3

            rating = Rating(rating_input)

            # Create a mock result for auto-rating (in real app, would evaluate actual moves)
            from ..exercises import ExerciseResult
            mock_result = ExerciseResult(
                correct=rating >= Rating.GOOD,
                partial_credit=1.0 if rating >= Rating.GOOD else 0.5 if rating == Rating.HARD else 0.0,
                time_taken_ms=5000,
                moves_played=[],
                expected_moves=exercise.get_solution(),
                feedback="Self-reported",
            )

            result, scheduling = session.submit([], 5000)
            updated_card = session.rate(rating)

            # Show next review time
            delta = updated_card.due - session.stats.started_at
            if delta.days > 0:
                next_review = f"{delta.days} days"
            elif delta.seconds > 3600:
                next_review = f"{delta.seconds // 3600} hours"
            else:
                next_review = f"{delta.seconds // 60} minutes"

            console.print(f"[green]→ Next review in: {next_review}[/green]\n")

            if session.remaining > 0:
                continue_training = typer.confirm("Continue?", default=True)
                if not continue_training:
                    break

        # End session and show stats
        stats = session.end()

        console.print("\n" + "=" * 40)
        console.print(Panel(
            f"Exercises: {stats.exercises_shown}\n"
            f"Correct: {stats.correct} | Partial: {stats.partial} | Incorrect: {stats.incorrect}\n"
            f"Accuracy: {stats.accuracy:.1f}%\n"
            f"Duration: {stats.duration_minutes:.1f} minutes",
            title="Session Complete",
        ))


@app.command()
def init_cards(
    db: Optional[Path] = typer.Option(None, "--db", help="Database path"),
):
    """Create review cards for all exercises that don't have one."""
    with get_repo(db) as repo:
        created = 0
        for exercise in repo.exercises.iterate_all():
            existing = repo.cards.get(exercise.id)
            if not existing:
                repo.cards.get_or_create(exercise.id)
                created += 1

        console.print(f"[green]✓[/green] Created {created} new review cards")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
