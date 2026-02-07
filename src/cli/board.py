"""
Unicode chess board rendering for the terminal.

Uses Rich for styled output with colored squares and piece symbols.
"""

import chess
from rich.text import Text


# Unicode chess pieces
PIECE_SYMBOLS = {
    (chess.PAWN, chess.WHITE): "\u2659",
    (chess.KNIGHT, chess.WHITE): "\u2658",
    (chess.BISHOP, chess.WHITE): "\u2657",
    (chess.ROOK, chess.WHITE): "\u2656",
    (chess.QUEEN, chess.WHITE): "\u2655",
    (chess.KING, chess.WHITE): "\u2654",
    (chess.PAWN, chess.BLACK): "\u265f",
    (chess.KNIGHT, chess.BLACK): "\u265e",
    (chess.BISHOP, chess.BLACK): "\u265d",
    (chess.ROOK, chess.BLACK): "\u265c",
    (chess.QUEEN, chess.BLACK): "\u265b",
    (chess.KING, chess.BLACK): "\u265a",
}

LIGHT_SQUARE = "#d4a76a"
DARK_SQUARE = "#8b5e3c"
LIGHT_BG = "on #f0d9b5"
DARK_BG = "on #b58863"
HIGHLIGHT_BG = "on #aaca44"
FILE_LABELS = "abcdefgh"


def render_board(
    board: chess.Board,
    *,
    flipped: bool = False,
    highlight_squares: set[int] | None = None,
    last_move: chess.Move | None = None,
) -> Text:
    """
    Render a chess board as a Rich Text object.

    Args:
        board: The chess.Board to render.
        flipped: If True, render from Black's perspective.
        highlight_squares: Squares to highlight (e.g. for hints).
        last_move: Last move played, highlights from/to squares.

    Returns:
        Rich Text object ready for console.print().
    """
    highlights = set(highlight_squares) if highlight_squares else set()
    if last_move:
        highlights.add(last_move.from_square)
        highlights.add(last_move.to_square)

    ranks = range(8) if flipped else range(7, -1, -1)
    files = range(7, -1, -1) if flipped else range(8)

    text = Text()

    for rank in ranks:
        # Rank label
        text.append(f" {rank + 1} ", style="bold")

        for file in files:
            square = chess.square(file, rank)
            is_light = (rank + file) % 2 == 1
            piece = board.piece_at(square)

            if square in highlights:
                bg = HIGHLIGHT_BG
            elif is_light:
                bg = LIGHT_BG
            else:
                bg = DARK_BG

            if piece:
                symbol = PIECE_SYMBOLS[(piece.piece_type, piece.color)]
                text.append(f" {symbol} ", style=bg)
            else:
                text.append("   ", style=bg)

        text.append("\n")

    # File labels
    text.append("   ")
    for file in files:
        text.append(f" {FILE_LABELS[file]} ", style="bold")
    text.append("\n")

    return text


def render_board_simple(board: chess.Board, *, flipped: bool = False) -> str:
    """
    Render a plain-text board (no Rich styling).

    Useful for environments without color support.
    """
    ranks = range(8) if flipped else range(7, -1, -1)
    files = range(7, -1, -1) if flipped else range(8)

    lines = []
    for rank in ranks:
        line = f" {rank + 1} "
        for file in files:
            square = chess.square(file, rank)
            piece = board.piece_at(square)
            if piece:
                line += f" {piece.symbol()} "
            else:
                is_light = (rank + file) % 2 == 1
                line += " · " if is_light else " . "
        lines.append(line)

    file_line = "   " + "".join(f" {FILE_LABELS[f]} " for f in files)
    lines.append(file_line)

    return "\n".join(lines)


def format_move_san(board: chess.Board, move: chess.Move) -> str:
    """Format a move in standard algebraic notation."""
    return board.san(move)


def format_solution_line(board: chess.Board, moves: list[chess.Move]) -> str:
    """
    Format a sequence of moves as a readable line.

    Shows move numbers and SAN notation, e.g. "1. e4 e5 2. Nf3"
    """
    temp = board.copy()
    parts = []
    for i, move in enumerate(moves):
        if temp.turn == chess.WHITE:
            move_num = temp.fullmove_number
            parts.append(f"{move_num}. {temp.san(move)}")
        else:
            if i == 0:
                move_num = temp.fullmove_number
                parts.append(f"{move_num}... {temp.san(move)}")
            else:
                parts.append(temp.san(move))
        temp.push(move)
    return " ".join(parts)
