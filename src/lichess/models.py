from datetime import datetime
from ..model import Model, dataclass, field, config, timestamp


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
                self._properties.pop("game"),
                self._properties.pop("puzzle"),
            )
            self.game_id = game_details["id"]
            self.game_to_puzzle = game_details["pgn"]
            self.id = puzzle_details["id"]
            self.rating = puzzle_details["rating"]
            self.plays = puzzle_details["plays"]
            self.solution = puzzle_details["solution"]
            self.themes = puzzle_details["themes"]
            self.initial_ply = puzzle_details["initialPly"]


@dataclass
class LichessTimeControl(Model):
    initial: int
    totalTime: int
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
