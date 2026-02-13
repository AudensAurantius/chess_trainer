"""Unicode chess board rendering for the terminal.

Uses Rich for styled output with colored squares and piece symbols.
Squares are 4 chars wide x 2 lines tall for a visually square aspect ratio.
"""

import chess
from rich.text import Text

# Use outline (white) Unicode symbols for ALL pieces.
# Color differentiation is handled via Rich foreground styles, avoiding the
# rendering inconsistency where U+265F (black pawn) shows as an emoji.
PIECE_SYMBOLS = {
    (chess.PAWN, chess.WHITE): "\u2659",
    (chess.KNIGHT, chess.WHITE): "\u2658",
    (chess.BISHOP, chess.WHITE): "\u2657",
    (chess.ROOK, chess.WHITE): "\u2656",
    (chess.QUEEN, chess.WHITE): "\u2655",
    (chess.KING, chess.WHITE): "\u2654",
    (chess.PAWN, chess.BLACK): "\u2659",
    (chess.KNIGHT, chess.BLACK): "\u2658",
    (chess.BISHOP, chess.BLACK): "\u2657",
    (chess.ROOK, chess.BLACK): "\u2656",
    (chess.QUEEN, chess.BLACK): "\u2655",
    (chess.KING, chess.BLACK): "\u2654",
}

# Foreground colors for pieces — high contrast on both square colors
WHITE_PIECE_FG = "#ffffff"
BLACK_PIECE_FG = "#1a1a1a"

LIGHT_BG = "on #f0d9b5"
DARK_BG = "on #b58863"
HIGHLIGHT_BG = "on #aaca44"
FILE_LABELS = "abcdefgh"

# Square dimensions (chars)
SQUARE_WIDTH = 4  # characters per square
SQUARE_HEIGHT = 2  # lines per square


def _piece_style(color: chess.Color, bg: str) -> str:
    """Build a Rich style string for a piece: foreground + background."""
    fg = WHITE_PIECE_FG if color == chess.WHITE else BLACK_PIECE_FG
    return f"bold {fg} {bg}"


def render_board(
    board: chess.Board,
    *,
    flipped: bool = False,
    highlight_squares: set[int] | None = None,
    last_move: chess.Move | None = None,
) -> Text:
    """Render a chess board as a Rich Text object.

    Each square is 4 chars wide x 2 lines tall for a visually square
    aspect ratio in monospace terminals.

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

    empty_cell = " " * SQUARE_WIDTH
    text = Text()

    for rank in ranks:
        # Line 1: rank label + piece symbols
        text.append(f" {rank + 1} ", style="bold")
        for file in files:
            square = chess.square(file, rank)
            bg = _square_bg(square, highlights)
            piece = board.piece_at(square)

            if piece:
                symbol = PIECE_SYMBOLS[(piece.piece_type, piece.color)]
                style = _piece_style(piece.color, bg)
                cell = symbol.center(SQUARE_WIDTH)
                text.append(cell, style=style)
            else:
                text.append(empty_cell, style=bg)
        text.append("\n")

        # Line 2: blank colored row (gives vertical height)
        text.append("   ")
        for file in files:
            square = chess.square(file, rank)
            bg = _square_bg(square, highlights)
            text.append(empty_cell, style=bg)
        text.append("\n")

    # File labels — centered under each 4-char column
    text.append("   ")
    for file in files:
        text.append(FILE_LABELS[file].center(SQUARE_WIDTH), style="bold")
    text.append("\n")

    return text


def _square_bg(square: int, highlights: set[int]) -> str:
    """Return the background style for a square."""
    if square in highlights:
        return HIGHLIGHT_BG
    rank = chess.square_rank(square)
    file = chess.square_file(square)
    is_light = (rank + file) % 2 == 1
    return LIGHT_BG if is_light else DARK_BG


def render_board_simple(board: chess.Board, *, flipped: bool = False) -> str:
    """Render a plain-text board (no Rich styling).

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
                line += " \u00b7 " if is_light else " . "
        lines.append(line)

    file_line = "   " + "".join(f" {FILE_LABELS[f]} " for f in files)
    lines.append(file_line)

    return "\n".join(lines)


def format_move_san(board: chess.Board, move: chess.Move) -> str:
    """Format a move in standard algebraic notation."""
    return board.san(move)


def format_solution_line(board: chess.Board, moves: list[chess.Move]) -> str:
    """Format a sequence of moves as a readable line.

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
