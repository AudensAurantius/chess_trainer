"""Tablebase data types for endgame probing results."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TablebaseMove:
    """A single legal move with its tablebase evaluation.

    Attributes:
        uci: Move in UCI notation (e.g. "h7h8q").
        san: Move in SAN notation (e.g. "h8=Q").
        wdl: WDL value from side-to-move's POV after this move (-2 to 2).
        dtz: Distance to zeroing move in plies, or None if unavailable.
        category: Human-readable category ("win", "loss", "draw",
            "cursed-win", "blessed-loss").
        zeroing: Whether this is a capture or pawn move.
        checkmate: Whether this move delivers checkmate.
    """

    uci: str
    san: str
    wdl: int
    dtz: int | None = None
    category: str = ""
    zeroing: bool = False
    checkmate: bool = False


@dataclass(frozen=True)
class TablebaseResult:
    """Complete tablebase probe result for a position.

    WDL values (from side-to-move's perspective):
        2  = win (unconditional)
        1  = cursed win (win but DTZ > 50-move rule)
        0  = draw
        -1 = blessed loss (loss but opponent can't win within 50-move)
        -2 = loss (unconditional)

    Attributes:
        wdl: WDL value from side-to-move's perspective (-2 to 2).
        dtz: Distance to zeroing move in plies, or None.
        category: Human-readable category.
        checkmate: Whether the position is checkmate.
        stalemate: Whether the position is stalemate.
        moves: All legal moves ranked by optimality (best first).
    """

    wdl: int
    dtz: int | None = None
    category: str = ""
    checkmate: bool = False
    stalemate: bool = False
    moves: list[TablebaseMove] = field(default_factory=list)

    @property
    def is_winning(self) -> bool:
        """Whether the side to move is winning (WDL >= 1)."""
        return self.wdl >= 1

    @property
    def is_losing(self) -> bool:
        """Whether the side to move is losing (WDL <= -1)."""
        return self.wdl <= -1

    @property
    def is_draw(self) -> bool:
        """Whether the position is a draw (WDL == 0)."""
        return self.wdl == 0

    @property
    def best_moves(self) -> list[TablebaseMove]:
        """Moves that maintain or achieve the best possible outcome."""
        if not self.moves:
            return []
        best_wdl = self.moves[0].wdl
        return [m for m in self.moves if m.wdl == best_wdl]
