"""Data models for the opening explorer and personal opening book."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import chess


class BookColor(Enum):
    """Side of the board for an opening repertoire line."""

    WHITE = "white"
    BLACK = "black"


class ExplorerSource(Enum):
    """Database source for the Lichess Explorer API."""

    LICHESS = "lichess"
    MASTERS = "masters"
    PLAYER = "player"


@dataclass(frozen=True)
class MoveStats:
    """Statistics for a single move in a position from the explorer."""

    uci: str
    san: str
    white_wins: int
    draws: int
    black_wins: int
    average_rating: int = 0

    @property
    def total_games(self) -> int:
        """Total number of games in which this move was played."""
        return self.white_wins + self.draws + self.black_wins

    @property
    def white_pct(self) -> float:
        """Percentage of games won by white."""
        return (self.white_wins / self.total_games * 100) if self.total_games else 0.0

    @property
    def draw_pct(self) -> float:
        """Percentage of games drawn."""
        return (self.draws / self.total_games * 100) if self.total_games else 0.0

    @property
    def black_pct(self) -> float:
        """Percentage of games won by black."""
        return (self.black_wins / self.total_games * 100) if self.total_games else 0.0


@dataclass(frozen=True)
class ExplorerResult:
    """Aggregated explorer statistics for a position."""

    fen: str
    white_wins: int
    draws: int
    black_wins: int
    moves: list[MoveStats]
    opening_eco: str = ""
    opening_name: str = ""
    source: ExplorerSource = ExplorerSource.LICHESS

    @property
    def total_games(self) -> int:
        """Total number of games reaching this position."""
        return self.white_wins + self.draws + self.black_wins


@dataclass
class OpeningLine:
    """A single line in the user's personal opening book."""

    id: str
    color: BookColor
    eco_code: str = ""
    name: str = ""
    variation: str = ""
    moves: list[str] = field(default_factory=list)  # UCI strings
    annotations: dict[int, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @property
    def fen_at_end(self) -> str:
        """FEN of the position after all moves have been played."""
        board = chess.Board()
        for uci in self.moves:
            board.push(chess.Move.from_uci(uci))
        return board.fen()

    @property
    def san_line(self) -> str:
        """The move line formatted in Standard Algebraic Notation."""
        board = chess.Board()
        san_parts: list[str] = []
        for i, uci in enumerate(self.moves):
            move = chess.Move.from_uci(uci)
            if board.turn == chess.WHITE:
                san_parts.append(f"{board.fullmove_number}. {board.san(move)}")
            else:
                if i == 0:
                    san_parts.append(f"{board.fullmove_number}... {board.san(move)}")
                else:
                    san_parts.append(board.san(move))
            board.push(move)
        return " ".join(san_parts)

    def to_dict(self) -> dict:
        """Serialize to a dictionary for storage."""
        return {
            "id": self.id,
            "color": self.color.value,
            "eco_code": self.eco_code,
            "name": self.name,
            "variation": self.variation,
            "moves": self.moves,
            "annotations": {str(k): v for k, v in self.annotations.items()},
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OpeningLine":
        """Deserialize from a dictionary."""
        annotations_raw = data.get("annotations", {})
        annotations = {int(k): v for k, v in annotations_raw.items()} if annotations_raw else {}

        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now()

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()

        return cls(
            id=data["id"],
            color=BookColor(data["color"]),
            eco_code=data.get("eco_code", ""),
            name=data.get("name", ""),
            variation=data.get("variation", ""),
            moves=data.get("moves", []),
            annotations=annotations,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def generate_id() -> str:
        """Generate a unique line ID."""
        return f"book:{uuid.uuid4().hex[:12]}"
