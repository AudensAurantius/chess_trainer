"""UCI engine management and position analysis.

Works with any UCI-compatible engine (Stockfish, Leela, etc.).
Uses python-chess's chess.engine module for subprocess management.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

import chess
import chess.engine

from .classification import MoveEvaluation, classify_move

# Score used for mate-vs-cp comparisons (100 pawns)
MATE_SCORE = 100_000


class EngineError(Exception):
    """Raised when the engine is not found or analysis fails."""


@dataclass(frozen=True)
class AnalysisLine:
    """A single line from multi-PV analysis.

    Attributes:
        score_cp: Centipawn score from the side to move's perspective, or None if mate.
        score_mate: Mate distance (positive = winning, negative = losing), or None if cp.
        pv: Principal variation (list of moves).
        depth: Search depth reached.
        seldepth: Selective search depth.
        nodes: Number of nodes searched.
        nps: Nodes per second.
        multipv_rank: Rank in multi-PV output (1 = best).
    """

    score_cp: int | None
    score_mate: int | None
    pv: list[chess.Move]
    depth: int
    seldepth: int = 0
    nodes: int = 0
    nps: int = 0
    multipv_rank: int = 1

    @property
    def score_value(self) -> int:
        """Unified score as centipawns, with mate mapped to ±MATE_SCORE."""
        if self.score_mate is not None:
            return MATE_SCORE if self.score_mate > 0 else -MATE_SCORE
        return self.score_cp or 0


@dataclass(frozen=True)
class AnalysisResult:
    """Complete analysis result for a position.

    Attributes:
        fen: FEN of the analyzed position.
        lines: Analysis lines ordered by rank (best first).
        depth: Requested depth for the analysis.
    """

    fen: str
    lines: list[AnalysisLine]
    depth: int

    @property
    def best_line(self) -> AnalysisLine | None:
        """The highest-ranked analysis line, or None if no lines."""
        return self.lines[0] if self.lines else None

    @property
    def evaluation(self) -> int:
        """Score of the best line in centipawns (mate mapped to ±MATE_SCORE)."""
        best = self.best_line
        return best.score_value if best else 0


def _find_engine() -> str:
    """Auto-detect a UCI engine on PATH.

    Returns:
        Path to the engine binary.

    Raises:
        EngineError: If no engine is found.
    """
    for name in ("stockfish", "lc0"):
        path = shutil.which(name)
        if path:
            return path
    raise EngineError(
        "No UCI engine found on PATH.\n"
        "Install Stockfish:\n"
        "  Ubuntu/Debian: sudo apt install stockfish\n"
        "  macOS:         brew install stockfish\n"
        "  Windows:       https://stockfishchess.org/download/\n"
        "Or specify a path with --engine or [engine].path in config.toml"
    )


def _parse_info(info: chess.engine.InfoDict, multipv_rank: int = 1) -> AnalysisLine:
    """Convert a python-chess InfoDict to an AnalysisLine.

    Args:
        info: Engine info dictionary from analysis.
        multipv_rank: The multi-PV rank of this line.

    Returns:
        Parsed AnalysisLine.
    """
    score: chess.engine.PovScore | None = info.get("score")
    score_cp = None
    score_mate = None

    if score is not None:
        cp = score.relative.score(mate_score=MATE_SCORE)
        mate = score.relative.mate()
        if mate is not None:
            score_mate = mate
        else:
            score_cp = cp

    pv = list(info.get("pv", []))
    depth = info.get("depth", 0)
    seldepth = info.get("seldepth", 0)
    nodes = info.get("nodes", 0)
    nps = info.get("nps", 0)

    return AnalysisLine(
        score_cp=score_cp,
        score_mate=score_mate,
        pv=pv,
        depth=depth,
        seldepth=seldepth,
        nodes=nodes,
        nps=nps,
        multipv_rank=multipv_rank,
    )


class EngineManager:
    """Manages a UCI engine subprocess.

    Can be used as a context manager::

        with EngineManager() as engine:
            result = engine.analyze(board, depth=20)

    Args:
        path: Path to the UCI engine binary. Auto-detects if None.
        hash_mb: Hash table size in MB.
        threads: Number of search threads.
    """

    def __init__(
        self,
        path: str | None = None,
        hash_mb: int = 256,
        threads: int = 2,
    ) -> None:
        """Initialize the engine manager."""
        self._path = path
        self._hash_mb = hash_mb
        self._threads = threads
        self._engine: chess.engine.SimpleEngine | None = None

    @property
    def is_open(self) -> bool:
        """Whether the engine subprocess is running."""
        return self._engine is not None

    def open(self) -> None:
        """Start the engine subprocess.

        Raises:
            EngineError: If the engine binary is not found or fails to start.
        """
        if self._engine is not None:
            return

        path = self._path or _find_engine()
        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(path)
        except FileNotFoundError:
            raise EngineError(f"Engine not found at: {path}")
        except chess.engine.EngineTerminatedError as e:
            raise EngineError(f"Engine failed to start: {e}")

        self._engine.configure({
            "Hash": self._hash_mb,
            "Threads": self._threads,
        })

    def close(self) -> None:
        """Stop the engine subprocess."""
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def __enter__(self) -> EngineManager:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def analyze(
        self,
        board: chess.Board,
        *,
        depth: int = 20,
        multipv: int = 1,
        time_limit: float | None = None,
    ) -> AnalysisResult:
        """Analyze a position.

        Args:
            board: Position to analyze.
            depth: Search depth limit.
            multipv: Number of principal variations to compute.
            time_limit: Time limit in seconds (overrides depth if set).

        Returns:
            AnalysisResult with the analysis lines.

        Raises:
            EngineError: If the engine is not open or analysis fails.
        """
        if self._engine is None:
            raise EngineError("Engine is not open. Call open() first.")

        limit = chess.engine.Limit(
            depth=depth if time_limit is None else None,
            time=time_limit,
        )

        try:
            # Always pass multipv to get consistent list[InfoDict] return type
            infos = self._engine.analyse(board, limit, multipv=multipv)
        except chess.engine.EngineTerminatedError as e:
            raise EngineError(f"Engine terminated during analysis: {e}")

        lines = [_parse_info(info, rank + 1) for rank, info in enumerate(infos)]

        return AnalysisResult(
            fen=board.fen(),
            lines=lines,
            depth=depth,
        )

    def evaluate_move(
        self,
        board: chess.Board,
        move: chess.Move,
        *,
        depth: int = 20,
    ) -> MoveEvaluation:
        """Evaluate the quality of a specific move.

        Computes centipawn loss by comparing the position before and after the
        move. The loss is measured from the side-to-move's perspective.

        Args:
            board: Position before the move.
            move: The move to evaluate.
            depth: Analysis depth.

        Returns:
            MoveEvaluation with classification and cp loss.

        Raises:
            EngineError: If the engine is not open or analysis fails.
        """
        # Analyze position before the move to get best line
        before = self.analyze(board, depth=depth, multipv=1)
        score_before = before.evaluation

        best_move = before.best_line.pv[0] if before.best_line and before.best_line.pv else move

        # Play the move and analyze the resulting position
        after_board = board.copy()
        after_board.push(move)
        after_result = self.analyze(after_board, depth=depth, multipv=1)
        # Negate because the side to move has changed
        score_after = -after_result.evaluation

        # CP loss is how much worse the played move is compared to the position's eval
        cp_loss = max(0, score_before - score_after)
        classification = classify_move(cp_loss)

        return MoveEvaluation(
            move=move,
            classification=classification,
            cp_loss=cp_loss,
            best_move=best_move,
            score_before=score_before,
            score_after=score_after,
        )
