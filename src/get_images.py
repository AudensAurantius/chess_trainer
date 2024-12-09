import chess, chess.svg
from pathlib import Path
from .constants import PIECE_SYMBOLS


def get_piece_svgs():
    for piece_type in chess.PIECE_TYPES:
        for color in chess.COLORS:
            piece = chess.Piece(piece_type, color)
            dest = Path("assets/pieces")
            if piece.color:
                dest /= "white"
            else:
                dest /= "black"
            dest /= f"{PIECE_SYMBOLS[piece.symbol().upper()]}.svg"
            with dest.open("w") as f:
                f.write(chess.svg.piece(piece))
