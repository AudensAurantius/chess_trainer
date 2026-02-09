"""Data models for endgame master game analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import chess


@dataclass(frozen=True)
class MasterGameInfo:
    """Metadata for a game from the Lichess Masters database.

    Attributes:
        game_id: Explorer DB identifier (e.g. "boLujJkB").
        white: White player name ("Carlsen, M.").
        white_rating: White player rating at time of game.
        black: Black player name.
        black_rating: Black player rating at time of game.
        winner: "white", "black", or None (draw).
        year: Year the game was played.
        uci: Move played from the queried position.
    """

    game_id: str
    white: str
    white_rating: int
    black: str
    black_rating: int
    winner: str | None
    year: int
    uci: str


@dataclass(frozen=True)
class AnnotatedPosition:
    """A single endgame position annotated with tablebase evaluation.

    Attributes:
        fen: Position in FEN notation.
        ply: Half-move number in the game.
        move_played: The move played (None at game end).
        move_san: SAN notation of the move played.
        wdl: Tablebase WDL from side-to-move perspective.
        dtz: Distance to zeroing, or None if unavailable.
        category: Human-readable WDL category ("win", "draw", "loss", etc.).
        is_critical: True if this is a critical teaching moment.
        wdl_after: WDL after the move was played (negated for perspective), or None.
    """

    fen: str
    ply: int
    move_played: chess.Move | None
    move_san: str
    wdl: int
    dtz: int | None
    category: str
    is_critical: bool
    wdl_after: int | None


@dataclass
class EndgamePhase:
    """An annotated endgame phase extracted from a master game.

    Attributes:
        game_info: Metadata about the source game.
        pgn_text: Full PGN text of the game.
        endgame_start_ply: Ply at which the endgame phase begins.
        positions: Annotated positions from endgame start onward.
    """

    game_info: MasterGameInfo
    pgn_text: str
    endgame_start_ply: int
    positions: list[AnnotatedPosition] = field(default_factory=list)

    @property
    def critical_moments(self) -> list[AnnotatedPosition]:
        """Return only positions flagged as critical teaching moments."""
        return [p for p in self.positions if p.is_critical]
