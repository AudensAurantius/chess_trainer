"""Game analysis and mistake detection for exercise generation.

Analyzes complete games to find mistakes (inaccuracies, mistakes, blunders)
and generates TacticExercise objects from the worst positions.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

import chess
import chess.pgn

from ..exercises.tactics import TacticExercise
from .classification import MoveClassification, classify_move
from .engine import MATE_SCORE, EngineManager


@dataclass(frozen=True)
class PositionEval:
    """Evaluation of a single position.

    Attributes:
        score_cp: Centipawns from side-to-move's perspective.
        best_move: Engine's best move for this position.
        pv: Principal variation (list of moves).
    """

    score_cp: int
    best_move: chess.Move | None = None
    pv: list[chess.Move] = field(default_factory=list)


@runtime_checkable
class PositionAnalyzer(Protocol):
    """Protocol for analyzing chess positions."""

    def analyze_position(self, board: chess.Board) -> PositionEval:
        """Analyze a position and return its evaluation."""
        ...


@runtime_checkable
class MultiPVAnalyzer(Protocol):
    """Protocol for analyzers that support multi-PV analysis."""

    def analyze_multipv(self, board: chess.Board, multipv: int) -> list[PositionEval]:
        """Analyze a position with multiple principal variations.

        Args:
            board: Position to analyze.
            multipv: Number of lines to compute.

        Returns:
            List of PositionEval, one per line, ordered by score descending.
        """
        ...


class EnginePositionAnalyzer:
    """Wraps EngineManager.analyze() to produce PositionEval objects.

    Args:
        engine: An open EngineManager instance.
        depth: Search depth for analysis.
    """

    def __init__(self, engine: EngineManager, depth: int = 20) -> None:
        """Initialize with an engine and depth."""
        self._engine = engine
        self._depth = depth

    def analyze_position(self, board: chess.Board) -> PositionEval:
        """Analyze a position using the UCI engine.

        Args:
            board: Position to analyze.

        Returns:
            PositionEval with score and best move.
        """
        result = self._engine.analyze(board, depth=self._depth, multipv=1)
        best_line = result.best_line

        score_cp = result.evaluation
        best_move = best_line.pv[0] if best_line and best_line.pv else None
        pv = list(best_line.pv) if best_line and best_line.pv else []

        return PositionEval(score_cp=score_cp, best_move=best_move, pv=pv)

    def analyze_multipv(self, board: chess.Board, multipv: int) -> list[PositionEval]:
        """Analyze a position with multiple principal variations.

        Args:
            board: Position to analyze.
            multipv: Number of lines to compute.

        Returns:
            List of PositionEval ordered by score descending.
        """
        result = self._engine.analyze(board, depth=self._depth, multipv=multipv)
        evals = []
        for line in result.lines:
            best_move = line.pv[0] if line.pv else None
            pv = list(line.pv) if line.pv else []
            evals.append(PositionEval(score_cp=line.score_value, best_move=best_move, pv=pv))
        return evals


class LichessServerAnalyzer:
    """Wraps Lichess per-ply eval data as a PositionAnalyzer.

    Lichess games fetched with ``evals=true`` include server-side evaluations
    for each ply. This class maps those evaluations to the PositionAnalyzer
    protocol so MistakeDetector can use them without a local engine.

    Args:
        evals: List of per-ply eval dicts from Lichess JSON. Each dict has
            ``cp`` (centipawns) or ``mate`` (mate distance), or None for
            missing evals.
    """

    def __init__(self, evals: list[dict | None]) -> None:
        """Initialize with a list of per-ply eval dicts."""
        self._evals = evals
        self._ply = 0

    def analyze_position(self, board: chess.Board) -> PositionEval:
        """Return the pre-computed eval for the current ply.

        Args:
            board: Current position (used only for ply tracking).

        Returns:
            PositionEval from the Lichess evaluation data.
        """
        ply = self._ply
        self._ply += 1

        if ply >= len(self._evals) or self._evals[ply] is None:
            return PositionEval(score_cp=0)

        eval_data = self._evals[ply]

        if "mate" in eval_data:
            mate = eval_data["mate"]
            score_cp = MATE_SCORE if mate > 0 else -MATE_SCORE
        elif "cp" in eval_data:
            score_cp = eval_data["cp"]
        else:
            score_cp = 0

        return PositionEval(score_cp=score_cp)


@dataclass(frozen=True)
class AnalyzedMove:
    """A single analyzed move from a game.

    Attributes:
        move_number: 1-indexed full move number.
        ply: 0-indexed half-move count.
        color: "white" or "black".
        move: The move that was played.
        fen_before: FEN of the position before the move.
        eval_before: Evaluation at this position.
        eval_after: Evaluation at the next position.
        cp_loss: Centipawn loss from playing this move.
        classification: Quality classification based on cp_loss.
    """

    move_number: int
    ply: int
    color: str
    move: chess.Move
    fen_before: str
    eval_before: PositionEval
    eval_after: PositionEval
    cp_loss: int
    classification: MoveClassification


@dataclass(frozen=True)
class GameAnalysis:
    """Complete analysis of a game.

    Attributes:
        game_id: Identifier for the game.
        white: White player name.
        black: Black player name.
        result: Game result string (1-0, 0-1, 1/2-1/2).
        moves: All analyzed moves.
        source_url: URL to the game on Lichess (if applicable).
    """

    game_id: str
    white: str
    black: str
    result: str
    moves: list[AnalyzedMove]
    source_url: str | None = None

    @property
    def mistakes(self) -> list[AnalyzedMove]:
        """All moves classified as MISTAKE or worse."""
        return [m for m in self.moves if m.classification >= MoveClassification.MISTAKE]

    @property
    def blunders(self) -> list[AnalyzedMove]:
        """All moves classified as BLUNDER."""
        return [m for m in self.moves if m.classification >= MoveClassification.BLUNDER]

    def filter_by_classification(
        self, min_classification: MoveClassification
    ) -> list[AnalyzedMove]:
        """Return moves at or above the given severity level."""
        return [m for m in self.moves if m.classification >= min_classification]

    def mistakes_by_color(self, color: str) -> list[AnalyzedMove]:
        """Return mistakes for a specific color."""
        return [m for m in self.mistakes if m.color == color]


class MistakeDetector:
    """Analyzes games to find mistakes and generate exercises.

    Uses a PositionAnalyzer to evaluate each position once (N+1 evals for
    N moves), then computes cp_loss from consecutive evaluations. This is
    twice as efficient as analyzing before+after for each move.

    Args:
        analyzer: Position analyzer (engine or Lichess server evals).
        min_classification: Minimum severity to include in exercises.
        max_exercises: Maximum exercises to generate per game.
        skip_first_plies: Number of opening plies to skip.
        cp_tolerance: Centipawns within best to accept as alternative first move.
        multipv_count: Number of multi-PV lines for acceptable move computation.
        evaluate_depth: User moves to evaluate per exercise (1 = first move only).
    """

    def __init__(
        self,
        analyzer: PositionAnalyzer,
        *,
        min_classification: MoveClassification = MoveClassification.MISTAKE,
        max_exercises: int = 10,
        skip_first_plies: int = 6,
        cp_tolerance: int = 0,
        multipv_count: int = 1,
        evaluate_depth: int | None = None,
    ) -> None:
        """Initialize the detector with analysis parameters."""
        self._analyzer = analyzer
        self._min_classification = min_classification
        self._max_exercises = max_exercises
        self._skip_first_plies = skip_first_plies
        self._cp_tolerance = cp_tolerance
        self._multipv_count = multipv_count
        self._evaluate_depth = evaluate_depth

    def analyze_game(
        self,
        game: chess.pgn.Game,
        *,
        game_id: str | None = None,
        source_url: str | None = None,
    ) -> GameAnalysis:
        """Analyze all moves in a game.

        Evaluates each position once and computes cp_loss from consecutive
        evaluations. Score perspective is normalized to the side-to-move.

        Args:
            game: A parsed PGN game.
            game_id: Override for the game identifier.
            source_url: URL to the game source.

        Returns:
            GameAnalysis with all analyzed moves.
        """
        site = game.headers.get("Site", "")
        site_id = site.split("/")[-1] if "/" in site else ""
        gid = game_id or site_id or "unknown"
        white = game.headers.get("White", "?")
        black = game.headers.get("Black", "?")
        result = game.headers.get("Result", "*")

        board = game.board()
        moves_list = list(game.mainline_moves())

        if not moves_list:
            return GameAnalysis(
                game_id=gid,
                white=white,
                black=black,
                result=result,
                moves=[],
                source_url=source_url,
            )

        # Evaluate each position: N moves → N+1 positions
        evals: list[PositionEval] = []
        eval_board = board.copy()
        for i in range(len(moves_list) + 1):
            ev = self._analyzer.analyze_position(eval_board)
            evals.append(ev)
            if i < len(moves_list):
                eval_board.push(moves_list[i])

        # Compute analyzed moves from consecutive evals
        analyzed_moves: list[AnalyzedMove] = []
        for i, move in enumerate(moves_list):
            color = "white" if board.turn == chess.WHITE else "black"
            fen_before = board.fen()
            move_number = board.fullmove_number

            eval_before = evals[i]
            eval_after = evals[i + 1]

            # cp_loss = score_before - (-score_after)
            # score_before is from side-to-move's POV
            # score_after is from opponent's POV (next side to move), so negate
            cp_loss = max(0, eval_before.score_cp - (-eval_after.score_cp))
            classification = classify_move(cp_loss)

            analyzed_moves.append(
                AnalyzedMove(
                    move_number=move_number,
                    ply=i,
                    color=color,
                    move=move,
                    fen_before=fen_before,
                    eval_before=eval_before,
                    eval_after=eval_after,
                    cp_loss=cp_loss,
                    classification=classification,
                )
            )

            board.push(move)

        return GameAnalysis(
            game_id=gid,
            white=white,
            black=black,
            result=result,
            moves=analyzed_moves,
            source_url=source_url,
        )

    def _compute_acceptable_moves(self, fen: str, best_score: int) -> tuple[list[str], int | None]:
        """Compute acceptable first moves via multi-PV analysis.

        Args:
            fen: Position to analyze.
            best_score: Best move's centipawn score from the single-PV eval.

        Returns:
            Tuple of (acceptable UCI move list, best move eval in cp).
        """
        if self._cp_tolerance <= 0 or self._multipv_count <= 1:
            return [], best_score

        if not isinstance(self._analyzer, MultiPVAnalyzer):
            return [], best_score

        board = chess.Board(fen)
        multipv_evals = self._analyzer.analyze_multipv(board, self._multipv_count)
        if not multipv_evals:
            return [], best_score

        top_score = multipv_evals[0].score_cp
        acceptable = []
        for ev in multipv_evals:
            if ev.best_move is None:
                continue
            if abs(top_score - ev.score_cp) <= self._cp_tolerance:
                acceptable.append(ev.best_move.uci())

        return acceptable, top_score

    def generate_exercises(
        self,
        game: chess.pgn.Game,
        *,
        game_id: str | None = None,
        source_url: str | None = None,
        color: str | None = None,
        game_context: dict | None = None,
    ) -> Iterator[TacticExercise]:
        """Analyze a game and generate exercises from mistakes.

        Args:
            game: A parsed PGN game.
            game_id: Override for the game identifier.
            source_url: URL to the game source.
            color: Only generate exercises for this color ("white" or "black").
            game_context: Optional dict with game_date, opponent, time_control, player_color.

        Yields:
            TacticExercise objects for each qualifying mistake.
        """
        analysis = self.analyze_game(game, game_id=game_id, source_url=source_url)

        # Filter by severity
        candidates = analysis.filter_by_classification(self._min_classification)

        # Filter by color
        if color:
            candidates = [m for m in candidates if m.color == color]

        # Skip opening plies
        candidates = [m for m in candidates if m.ply >= self._skip_first_plies]

        # Sort by cp_loss descending (worst mistakes first)
        candidates.sort(key=lambda m: m.cp_loss, reverse=True)

        # Limit count
        candidates = candidates[: self._max_exercises]

        for am in candidates:
            # Build solution: best_move + PV continuation
            solution: list[str] = []
            if am.eval_before.best_move:
                solution.append(am.eval_before.best_move.uci())
                # Add PV continuation (skip the best move itself)
                for pv_move in am.eval_before.pv[1:]:
                    solution.append(pv_move.uci())

            if not solution:
                continue

            # Compute acceptable first moves via multi-PV
            acceptable_moves, best_eval = self._compute_acceptable_moves(
                am.fen_before, am.eval_before.score_cp
            )

            # Build source URL with ply anchor
            ex_source_url = None
            if analysis.source_url:
                ex_source_url = f"{analysis.source_url}#{am.ply}"

            # Build metadata
            metadata: dict = {
                "cp_loss": am.cp_loss,
                "score_before": am.eval_before.score_cp,
                "score_after": am.eval_after.score_cp,
                "played_move_uci": am.move.uci(),
            }
            if game_context:
                metadata["game_context"] = game_context

            yield TacticExercise(
                id=f"game:{analysis.game_id}:m{am.move_number}",
                fen=am.fen_before,
                tags=[am.classification.name.lower(), "own_game"],
                source="game_analysis",
                source_url=ex_source_url,
                difficulty=None,
                created_at=datetime.now(),
                metadata=metadata,
                solution=solution,
                themes=[am.classification.name.lower(), "own_game"],
                game_id=analysis.game_id,
                acceptable_first_moves=acceptable_moves,
                best_move_eval=best_eval,
                evaluate_depth=self._evaluate_depth,
            )
