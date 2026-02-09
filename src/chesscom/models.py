"""Data models for Chess.com API responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ChessComPlayer:
    """A player in a Chess.com game."""

    username: str
    rating: int
    result: str  # e.g. "win", "resigned", "timeout", "checkmated", etc.

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChessComPlayer:
        """Parse a player from the nested game dict.

        Args:
            data: Player dict with ``username``, ``rating``, ``result`` keys.

        Returns:
            ChessComPlayer instance.
        """
        return cls(
            username=data.get("username", ""),
            rating=data.get("rating", 0),
            result=data.get("result", ""),
        )


@dataclass
class ChessComGame:
    """A game from the Chess.com API."""

    url: str
    pgn: str
    time_control: str  # e.g. "600" or "180+2"
    time_class: str  # bullet, blitz, rapid, daily
    rated: bool
    rules: str  # "chess", "chess960", "bughouse", etc.
    white: ChessComPlayer
    black: ChessComPlayer
    end_time: int  # Unix timestamp

    @property
    def game_id(self) -> str:
        """Extract the game ID from the URL.

        Chess.com URLs are like: https://www.chess.com/game/live/12345
        """
        return self.url.rstrip("/").split("/")[-1]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChessComGame:
        """Parse a game from the API response dict.

        Args:
            data: Game dict from the monthly archive endpoint.

        Returns:
            ChessComGame instance.
        """
        return cls(
            url=data.get("url", ""),
            pgn=data.get("pgn", ""),
            time_control=data.get("time_control", ""),
            time_class=data.get("time_class", ""),
            rated=data.get("rated", False),
            rules=data.get("rules", "chess"),
            white=ChessComPlayer.from_dict(data.get("white", {})),
            black=ChessComPlayer.from_dict(data.get("black", {})),
            end_time=data.get("end_time", 0),
        )


@dataclass
class ChessComPuzzle:
    """A puzzle from the Chess.com API."""

    title: str
    url: str
    publish_time: int  # Unix timestamp
    fen: str
    pgn: str  # Solution PGN
    image: str  # URL to puzzle image

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChessComPuzzle:
        """Parse a puzzle from the API response dict.

        Args:
            data: Puzzle dict from /puzzle or /puzzle/random.

        Returns:
            ChessComPuzzle instance.
        """
        return cls(
            title=data.get("title", ""),
            url=data.get("url", ""),
            publish_time=data.get("publish_time", 0),
            fen=data.get("fen", ""),
            pgn=data.get("pgn", ""),
            image=data.get("image", ""),
        )
