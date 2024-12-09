import chess.pgn as pgn
from io import StringIO


def from_string(pgn_str: str) -> pgn.Game | None:
    with StringIO(pgn_str) as stream:
        return pgn.read_game(stream)
