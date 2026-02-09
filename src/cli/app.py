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
        # Materialize the list first to avoid DuckDB cursor corruption
        # when card queries run inside the loop on the same connection.
        exercises = list(repo.exercises.iterate_all())
        for exercise in exercises:
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
            f"[bold]game_analysis.skip_first_plies[/bold] = {cfg.game_analysis.skip_first_plies}",
            title="Effective Configuration",
        )
    )


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
    db: Path | None = typer.Option(None, "--db", help="Database path"),
):
    """Explore opening statistics from the Lichess explorer."""
    from ..openings.explorer import OpeningExplorer
    from ..openings.models import ExplorerSource

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

    with get_repo(db) as repo:
        explorer = OpeningExplorer(
            repo.openings,
            cache_ttl_hours=cfg.openings.cache_ttl_hours,
            min_games=cfg.openings.min_games,
        )
        _interactive_explore(board, explorer, explorer_source, player=player, color=color)


def _interactive_explore(
    board: chess.Board,
    explorer,
    source,
    *,
    player: str | None = None,
    color: str = "white",
) -> None:
    """Interactive explorer REPL: view stats, play moves to go deeper."""
    from ..openings.explorer import ExplorerError
    from .board import render_board

    move_stack: list[chess.Move] = []

    while True:
        flipped = board.turn == chess.BLACK

        try:
            result = explorer.explore(board.fen(), source, player=player, color=color)
        except ExplorerError as e:
            console.print(f"[red]Explorer error: {e}[/red]")
            break

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

            for m in result.moves:
                table.add_row(
                    m.san,
                    f"{m.total_games:,}",
                    f"{m.white_pct:.0f}%",
                    f"{m.draw_pct:.0f}%",
                    f"{m.black_pct:.0f}%",
                    str(m.average_rating) if m.average_rating else "-",
                )

            console.print(table)
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
    max_games: int = typer.Option(10, "--max-games", "-n", help="Max games to import"),
    server_evals: bool = typer.Option(
        False, "--server-evals", help="Use Lichess server evaluations (no engine needed)"
    ),
    color: str | None = typer.Option(None, "--color", help="Only exercises for white or black"),
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
    from ..importers.games import GameImporter

    if not pgn and not user:
        console.print("[red]Specify either --pgn or --user.[/red]")
        raise typer.Exit(1)

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

    if need_engine and not pgn:
        # For Lichess without server evals, we need an engine
        need_engine = True

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
        importer = GameImporter(
            engine_mgr,
            depth=analysis_depth,
            min_classification=min_class,
            max_exercises=max_ex,
            skip_first_plies=ga.skip_first_plies,
        )

        with get_repo(db) as repo:
            fetch_kwargs: dict = {}
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

            with console.status("Analyzing games and generating exercises..."):
                result = importer.import_to(repo.exercises, **fetch_kwargs)

            console.print(f"\n[green]\u2713[/green] {result}")

            # Create review cards for new exercises
            if result.total_added > 0:
                for exercise in repo.exercises.search(source="game_analysis"):
                    existing = repo.cards.get(exercise.id)
                    if not existing:
                        repo.cards.get_or_create(exercise.id)

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

    if not pgn and not game_id:
        console.print("[red]Specify either --pgn or --game-id.[/red]")
        raise typer.Exit(1)

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


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
