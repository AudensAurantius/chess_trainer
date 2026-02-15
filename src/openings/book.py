"""Personal opening book management and exercise generation."""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import chess
import chess.pgn

from ..exercises.openings import OpeningExercise
from .models import BookColor, OpeningLine

if TYPE_CHECKING:
    from .explorer import OpeningExplorer


class BookError(Exception):
    """Error in opening book operations."""


# ── Lichess Study Support ────────────────────────────────────────────────────

# Matches 8-char Lichess study ID in a lichess.org/study/ URL
_STUDY_URL_RE = re.compile(r"lichess\.org/study/([A-Za-z0-9]{8})")

MAX_LINES_PER_CHAPTER = 50


@dataclass
class StudyChapter:
    """Parsed chapter from a Lichess study."""

    study_name: str = ""
    chapter_name: str = ""
    site_url: str = ""
    lines: list[list[str]] = field(default_factory=list)
    annotations: list[dict[int, str]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


def parse_study_id(url_or_id: str) -> str:
    """Extract the 8-character study ID from a URL or bare string.

    Args:
        url_or_id: A Lichess study URL or bare 8-char ID.

    Returns:
        The 8-character study ID.

    Raises:
        BookError: If no valid study ID can be found.
    """
    text = url_or_id.strip()
    # Try URL pattern first
    m = _STUDY_URL_RE.search(text)
    if m:
        return m.group(1)
    # Try bare 8-char alphanumeric
    if re.fullmatch(r"[A-Za-z0-9]{8}", text):
        return text
    raise BookError(f"Cannot extract study ID from: {url_or_id!r}")


def _extract_lines(
    node: chess.pgn.ChildNode,
    moves: list[str],
    annotations: dict[int, str],
    max_lines: int = MAX_LINES_PER_CHAPTER,
) -> list[tuple[list[str], dict[int, str]]]:
    """Recursively extract all root-to-leaf paths from a game tree.

    Each path through the variation tree becomes one line. Comments on
    moves are captured as annotations keyed by move index.

    Args:
        node: Current PGN game node.
        moves: UCI moves accumulated so far.
        annotations: Comments accumulated so far (move_index -> text).
        max_lines: Maximum number of lines to extract.

    Returns:
        List of (moves, annotations) tuples, one per leaf path.
    """
    results: list[tuple[list[str], dict[int, str]]] = []

    if node.is_end():
        # Leaf node — emit this path
        return [(list(moves), dict(annotations))]

    for i, variation in enumerate(node.variations):
        if len(results) >= max_lines:
            break

        move_uci = variation.move.uci()
        move_idx = len(moves)
        new_moves = moves + [move_uci]
        new_annotations = dict(annotations)

        # Capture comment if present
        if variation.comment:
            new_annotations[move_idx] = variation.comment.strip()

        sub_results = _extract_lines(
            variation, new_moves, new_annotations, max_lines - len(results)
        )
        results.extend(sub_results)

    return results


def parse_study_pgn(pgn_text: str) -> list[StudyChapter]:
    """Parse multi-game PGN from a Lichess study into chapters.

    Chapters with custom FEN starting positions are skipped since
    OpeningLine assumes the standard starting position.

    Args:
        pgn_text: Raw PGN text (may contain multiple games/chapters).

    Returns:
        List of StudyChapter objects, one per chapter in the PGN.
    """
    chapters: list[StudyChapter] = []
    stream = io.StringIO(pgn_text)

    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break

        study_name = game.headers.get("Event", "")
        chapter_name = game.headers.get("White", "")
        site_url = game.headers.get("Site", "")
        fen = game.headers.get("FEN", "")

        chapter = StudyChapter(
            study_name=study_name,
            chapter_name=chapter_name,
            site_url=site_url,
        )

        # Skip chapters with custom FEN (not standard starting position)
        if fen and fen != chess.STARTING_FEN:
            chapter.skipped = True
            chapter.skip_reason = "Custom FEN starting position"
            chapters.append(chapter)
            continue

        # Extract all lines from the game tree
        lines_with_annotations = _extract_lines(game, [], {})
        for line_moves, line_annotations in lines_with_annotations:
            if line_moves:
                chapter.lines.append(line_moves)
                chapter.annotations.append(line_annotations)

        chapters.append(chapter)

    return chapters


def import_study_lines(
    study_id: str,
    chapters: list[StudyChapter],
    color: BookColor,
    name: str = "",
) -> list[OpeningLine]:
    """Build OpeningLine objects from parsed study chapters.

    Uses deterministic IDs of the form ``study:{study_id}:{n}`` so that
    re-importing the same study updates existing lines rather than
    creating duplicates.

    Args:
        study_id: The Lichess study ID (for deterministic line IDs).
        chapters: Parsed study chapters from :func:`parse_study_pgn`.
        color: Which side these lines are for.
        name: Optional override for the opening name.

    Returns:
        List of OpeningLine objects ready for storage.
    """
    lines: list[OpeningLine] = []
    line_num = 0

    for chapter in chapters:
        if chapter.skipped:
            continue

        for i, line_moves in enumerate(chapter.lines):
            line_id = f"study:{study_id}:{line_num}"
            line_name = name or chapter.study_name
            variation = chapter.chapter_name

            now = datetime.now()
            line = OpeningLine(
                id=line_id,
                color=color,
                name=line_name,
                variation=variation,
                moves=line_moves,
                annotations=chapter.annotations[i] if i < len(chapter.annotations) else {},
                created_at=now,
                updated_at=now,
            )
            lines.append(line)
            line_num += 1

    return lines


def parse_pgn_to_uci(pgn_text: str) -> list[str]:
    """Parse a PGN move string into a list of UCI move strings.

    Accepts move text like "1.e4 e5 2.Nf3 Nc6" or just "e4 e5 Nf3 Nc6".

    Args:
        pgn_text: PGN-formatted move text.

    Returns:
        List of UCI move strings.

    Raises:
        BookError: If the PGN cannot be parsed or contains illegal moves.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise BookError(f"Could not parse PGN: {pgn_text[:80]}")

    board = game.board()
    uci_moves: list[str] = []
    for move in game.mainline_moves():
        if move not in board.legal_moves:
            raise BookError(f"Illegal move {move.uci()} in position {board.fen()}")
        uci_moves.append(move.uci())
        board.push(move)

    return uci_moves


def parse_pgn_file(filepath: str) -> list[list[str]]:
    """Parse a PGN file into multiple lines of UCI moves.

    Each game in the file becomes one list of UCI moves.

    Args:
        filepath: Path to a PGN file.

    Returns:
        List of UCI move lists, one per game.

    Raises:
        BookError: If the file cannot be read.
    """
    try:
        with open(filepath) as f:
            pgn_text = f.read()
    except OSError as e:
        raise BookError(f"Cannot read file: {e}") from e

    games: list[list[str]] = []
    stream = io.StringIO(pgn_text)

    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break

        board = game.board()
        uci_moves: list[str] = []
        for move in game.mainline_moves():
            uci_moves.append(move.uci())
            board.push(move)

        if uci_moves:
            games.append(uci_moves)

    return games


def create_line(
    color: BookColor,
    moves: list[str],
    name: str = "",
    variation: str = "",
    eco_code: str = "",
) -> OpeningLine:
    """Create a new opening line, validating all moves are legal.

    Args:
        color: Which side this line is for.
        moves: UCI move strings from the starting position.
        name: Opening name (e.g. "Sicilian Najdorf").
        variation: Variation name (e.g. "English Attack").
        eco_code: ECO classification code (e.g. "B90").

    Returns:
        A new OpeningLine with a generated ID.

    Raises:
        BookError: If any move is illegal.
    """
    board = chess.Board()
    for uci in moves:
        try:
            move = chess.Move.from_uci(uci)
        except chess.InvalidMoveError as e:
            raise BookError(f"Invalid UCI move: {uci}") from e
        if move not in board.legal_moves:
            raise BookError(f"Illegal move {uci} in position {board.fen()}")
        board.push(move)

    now = datetime.now()
    return OpeningLine(
        id=OpeningLine.generate_id(),
        color=color,
        eco_code=eco_code,
        name=name,
        variation=variation,
        moves=moves,
        created_at=now,
        updated_at=now,
    )


def generate_exercises(
    line: OpeningLine,
    alternative_moves: dict[int, list[str]] | None = None,
) -> Iterator[OpeningExercise]:
    """Generate opening exercises from a book line.

    Creates one exercise per position where it's the user's color to move.

    Args:
        line: The opening line to generate exercises from.
        alternative_moves: Optional dict mapping move index to alternative
            UCI move strings (e.g. from explorer statistics).

    Yields:
        OpeningExercise for each position in the line where the user moves.
    """
    alternative_moves = alternative_moves or {}
    board = chess.Board()
    user_is_white = line.color == BookColor.WHITE

    for i, uci in enumerate(line.moves):
        is_user_turn = (board.turn == chess.WHITE) == user_is_white

        if is_user_turn:
            exercise_id = f"{line.id}:m{i}"
            alts = alternative_moves.get(i, [])

            yield OpeningExercise(
                id=exercise_id,
                fen=board.fen(),
                tags=["opening", line.color.value],
                source="book",
                difficulty=None,
                line=line.moves,
                current_move_index=i,
                eco_code=line.eco_code,
                opening_name=line.name,
                variation_name=line.variation,
                alternative_moves=alts,
            )

        board.push(chess.Move.from_uci(uci))


def get_alternatives_from_explorer(
    line: OpeningLine,
    explorer: OpeningExplorer,
    min_games: int = 5,
) -> dict[int, list[str]]:
    """Query the explorer at each user-turn position for alternative moves.

    Args:
        line: The opening line to query alternatives for.
        explorer: An OpeningExplorer instance.
        min_games: Minimum games for a move to be considered.

    Returns:
        Dict mapping move index to list of alternative UCI moves.
    """
    alternatives: dict[int, list[str]] = {}
    board = chess.Board()
    user_is_white = line.color == BookColor.WHITE

    for i, uci in enumerate(line.moves):
        is_user_turn = (board.turn == chess.WHITE) == user_is_white

        if is_user_turn:
            try:
                result = explorer.explore(board.fen())
                main_move = uci
                alts = [
                    m.uci for m in result.moves if m.uci != main_move and m.total_games >= min_games
                ]
                if alts:
                    alternatives[i] = alts
            except Exception:
                pass  # Skip positions where explorer fails

        board.push(chess.Move.from_uci(uci))

    return alternatives
