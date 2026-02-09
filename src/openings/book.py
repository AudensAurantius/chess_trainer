"""Personal opening book management and exercise generation."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import datetime
from typing import TYPE_CHECKING

import chess
import chess.pgn

from ..exercises.openings import OpeningExercise
from .models import BookColor, OpeningLine

if TYPE_CHECKING:
    from .explorer import OpeningExplorer


class BookError(Exception):
    """Error in opening book operations."""


def parse_pgn_to_uci(pgn_text: str) -> list[str]:
    """Parse a PGN move string into a list of UCI move strings.

    Accepts move text like "1.e4 e5 2.Nf3 Nc6" or just "e4 e5 Nf3 Nc6".

    Args:
        pgn_text: PGN-formatted move text.

    Returns:
        List of UCI move strings.

    Raises:
        BookError: If the PGN cannot be parsed or contains illegal moves.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise BookError(f"Could not parse PGN: {pgn_text[:80]}")

    board = game.board()
    uci_moves: list[str] = []
    for move in game.mainline_moves():
        if move not in board.legal_moves:
            raise BookError(f"Illegal move {move.uci()} in position {board.fen()}")
        uci_moves.append(move.uci())
        board.push(move)

    return uci_moves


def parse_pgn_file(filepath: str) -> list[list[str]]:
    """Parse a PGN file into multiple lines of UCI moves.

    Each game in the file becomes one list of UCI moves.

    Args:
        filepath: Path to a PGN file.

    Returns:
        List of UCI move lists, one per game.

    Raises:
        BookError: If the file cannot be read.
    """
    try:
        with open(filepath) as f:
            pgn_text = f.read()
    except OSError as e:
        raise BookError(f"Cannot read file: {e}") from e

    games: list[list[str]] = []
    stream = io.StringIO(pgn_text)

    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break

        board = game.board()
        uci_moves: list[str] = []
        for move in game.mainline_moves():
            uci_moves.append(move.uci())
            board.push(move)

        if uci_moves:
            games.append(uci_moves)

    return games


def create_line(
    color: BookColor,
    moves: list[str],
    name: str = "",
    variation: str = "",
    eco_code: str = "",
) -> OpeningLine:
    """Create a new opening line, validating all moves are legal.

    Args:
        color: Which side this line is for.
        moves: UCI move strings from the starting position.
        name: Opening name (e.g. "Sicilian Najdorf").
        variation: Variation name (e.g. "English Attack").
        eco_code: ECO classification code (e.g. "B90").

    Returns:
        A new OpeningLine with a generated ID.

    Raises:
        BookError: If any move is illegal.
    """
    board = chess.Board()
    for uci in moves:
        try:
            move = chess.Move.from_uci(uci)
        except chess.InvalidMoveError as e:
            raise BookError(f"Invalid UCI move: {uci}") from e
        if move not in board.legal_moves:
            raise BookError(f"Illegal move {uci} in position {board.fen()}")
        board.push(move)

    now = datetime.now()
    return OpeningLine(
        id=OpeningLine.generate_id(),
        color=color,
        eco_code=eco_code,
        name=name,
        variation=variation,
        moves=moves,
        created_at=now,
        updated_at=now,
    )


def generate_exercises(
    line: OpeningLine,
    alternative_moves: dict[int, list[str]] | None = None,
) -> Iterator[OpeningExercise]:
    """Generate opening exercises from a book line.

    Creates one exercise per position where it's the user's color to move.

    Args:
        line: The opening line to generate exercises from.
        alternative_moves: Optional dict mapping move index to alternative
            UCI move strings (e.g. from explorer statistics).

    Yields:
        OpeningExercise for each position in the line where the user moves.
    """
    alternative_moves = alternative_moves or {}
    board = chess.Board()
    user_is_white = line.color == BookColor.WHITE

    for i, uci in enumerate(line.moves):
        is_user_turn = (board.turn == chess.WHITE) == user_is_white

        if is_user_turn:
            exercise_id = f"{line.id}:m{i}"
            alts = alternative_moves.get(i, [])

            yield OpeningExercise(
                id=exercise_id,
                fen=board.fen(),
                tags=["opening", line.color.value],
                source="book",
                difficulty=None,
                line=line.moves,
                current_move_index=i,
                eco_code=line.eco_code,
                opening_name=line.name,
                variation_name=line.variation,
                alternative_moves=alts,
            )

        board.push(chess.Move.from_uci(uci))


def get_alternatives_from_explorer(
    line: OpeningLine,
    explorer: OpeningExplorer,
    min_games: int = 5,
) -> dict[int, list[str]]:
    """Query the explorer at each user-turn position for alternative moves.

    Args:
        line: The opening line to query alternatives for.
        explorer: An OpeningExplorer instance.
        min_games: Minimum games for a move to be considered.

    Returns:
        Dict mapping move index to list of alternative UCI moves.
    """
    alternatives: dict[int, list[str]] = {}
    board = chess.Board()
    user_is_white = line.color == BookColor.WHITE

    for i, uci in enumerate(line.moves):
        is_user_turn = (board.turn == chess.WHITE) == user_is_white

        if is_user_turn:
            try:
                result = explorer.explore(board.fen())
                main_move = uci
                alts = [
                    m.uci for m in result.moves if m.uci != main_move and m.total_games >= min_games
                ]
                if alts:
                    alternatives[i] = alts
            except Exception:
                pass  # Skip positions where explorer fails

        board.push(chess.Move.from_uci(uci))

    return alternatives
