"""Preset endgame type catalog with seed FENs for master game searches."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndgameCategory:
    """A named endgame category with seed FENs for explorer queries.

    Attributes:
        name: Human-readable category name.
        description: Short description of the endgame type.
        seed_fens: Representative FENs to seed master game searches.
    """

    name: str
    description: str
    seed_fens: list[str] = field(default_factory=list)


ENDGAME_TYPES: dict[str, EndgameCategory] = {
    "kpk": EndgameCategory(
        name="King and Pawn vs King",
        description="Fundamental pawn endgame technique: opposition, key squares.",
        seed_fens=[
            "8/8/4k3/8/4P3/4K3/8/8 w - - 0 1",
            "8/4k3/8/4P3/4K3/8/8/8 w - - 0 1",
        ],
    ),
    "rook": EndgameCategory(
        name="Rook Endgames",
        description="Rook endings: Lucena, Philidor, rook activity, passed pawns.",
        seed_fens=[
            "8/1k6/8/8/8/8/1KR5/1r6 w - - 0 1",
            "2r5/8/8/3kp3/8/5K2/5P2/5R2 w - - 0 1",
            "8/8/4k3/2R5/4p3/4K3/8/4r3 w - - 0 1",
        ],
    ),
    "bishop": EndgameCategory(
        name="Bishop Endgames",
        description="Bishop endings: same-color, opposite-color, good vs bad bishop.",
        seed_fens=[
            "8/8/3k4/8/2B5/8/4K3/3b4 w - - 0 1",
            "8/5k2/4p3/8/3B4/8/4K3/8 w - - 0 1",
        ],
    ),
    "knight": EndgameCategory(
        name="Knight Endgames",
        description="Knight endings: centralization, pawn races, knight forks.",
        seed_fens=[
            "8/8/4k3/8/4N3/8/4K3/4n3 w - - 0 1",
            "8/5k2/8/4p3/4N3/8/4K3/8 w - - 0 1",
        ],
    ),
    "queen": EndgameCategory(
        name="Queen Endgames",
        description="Queen endings: queen vs pawn, perpetual checks, technique.",
        seed_fens=[
            "8/8/8/3k4/8/8/6P1/4K2Q w - - 0 1",
            "8/8/8/3k4/8/5q2/8/4K2Q w - - 0 1",
        ],
    ),
    "pawn": EndgameCategory(
        name="Pawn Endgames",
        description="Pure pawn endings: opposition, triangulation, breakthroughs.",
        seed_fens=[
            "8/8/4k3/4p3/4P3/4K3/8/8 w - - 0 1",
            "8/5k2/5p2/5P2/5K2/8/8/8 w - - 0 1",
        ],
    ),
    "krk": EndgameCategory(
        name="King and Rook vs King",
        description="Basic checkmate technique with king and rook.",
        seed_fens=[
            "8/8/8/4k3/8/8/8/R3K3 w - - 0 1",
        ],
    ),
}


def get_category(key: str) -> EndgameCategory:
    """Look up an endgame category by key.

    Args:
        key: Category key (e.g. "rook", "kpk").

    Returns:
        The matching EndgameCategory.

    Raises:
        KeyError: If the key is not found.
    """
    normalized = key.lower().strip()
    if normalized not in ENDGAME_TYPES:
        valid = ", ".join(sorted(ENDGAME_TYPES.keys()))
        raise KeyError(f"Unknown endgame type '{key}'. Valid types: {valid}")
    return ENDGAME_TYPES[normalized]
