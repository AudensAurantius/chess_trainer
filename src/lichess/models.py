from datetime import datetime
from ..model import Model, dataclass, timestamp


@dataclass
class Theme(Model):
    name: str
    description: str
    summary: str | None = None


@dataclass
class LichessPlayer(Model):
    name: str | None = None
    id: str | None = None
    rating: int | None = None
    rating_diff: int | None = None

    def __post_init__(self):
        if self._properties is not None:
            user = self._properties.pop("user")
            self.name = user["name"]
            self.id = user["id"]


@dataclass
class LichessPuzzle(Model):
    game_id: str | None = None
    game_to_puzzle: str | None = None
    id: str | None = None
    rating: int | None = None
    plays: int | None = None
    solution: list[str] | None = None
    themes: list[str] | None = None
    initial_ply: int | None = None

    def __post_init__(self):
        if self._properties is not None:
            game_details, puzzle_details = (
                self._properties.pop("game", {}),
                self._properties.pop("puzzle", {}),
            )
            self.game_id = game_details.get("id")
            self.game_to_puzzle = game_details.get("pgn")
            self.id = puzzle_details.get("id")
            self.rating = puzzle_details.get("rating")
            self.plays = puzzle_details.get("plays")
            self.solution = puzzle_details.get("solution")
            self.themes = puzzle_details.get("themes")
            self.initial_ply = puzzle_details.get("initialPly")


@dataclass
class LichessTimeControl(Model):
    initial: int
    total_time: int
    increment: int | None = None


@dataclass
class LichessGame(Model):
    id: str
    rated: bool
    variant: str
    speed: str
    perf: str
    created_at: datetime = timestamp()
    last_move_at: datetime = timestamp()
    status: str
    source: str
    clock: LichessTimeControl
    moves: str | None = None
    pgn: str | None = None
    white: LichessPlayer | None = None
    black: LichessPlayer | None = None

    def __post_init__(self):
        if self._properties is not None:
            players = self._properties.pop("players")
            self.white = LichessPlayer.from_dict(players["white"])
            self.black = LichessPlayer.from_dict(players["black"])
