"""Tablebase manager with local Syzygy and Lichess API backends.

Probe strategy:
1. Check piece count — raise if > max_pieces.
2. Try local Syzygy tables if a path is configured.
3. Fall back to Lichess tablebase API if enabled.
4. Raise TablebaseError if both fail.
"""

from __future__ import annotations

import logging

import chess
import chess.syzygy
import requests

from .models import TablebaseMove, TablebaseResult

logger = logging.getLogger(__name__)

LICHESS_TABLEBASE_API = "https://tablebase.lichess.ovh/standard"


class TablebaseError(Exception):
    """Error probing endgame tablebases."""


def _wdl_to_category(wdl: int) -> str:
    """Convert a WDL integer to a human-readable category string."""
    return {
        2: "win",
        1: "cursed-win",
        0: "draw",
        -1: "blessed-loss",
        -2: "loss",
    }.get(wdl, "unknown")


def _negate_wdl(wdl: int) -> int:
    """Negate a WDL value (flip perspective after a move)."""
    return -wdl


class TablebaseManager:
    """Manages endgame tablebase probing with dual backends.

    Can be used as a context manager::

        with TablebaseManager(syzygy_path="/path/to/syzygy") as tb:
            result = tb.probe(board)

    Args:
        syzygy_path: Path to local Syzygy tablebase directory.
        use_lichess_fallback: Whether to use Lichess API as a fallback.
        max_pieces: Maximum number of pieces for tablebase probing.
    """

    def __init__(  # noqa: D107
        self,
        syzygy_path: str | None = None,
        use_lichess_fallback: bool = True,
        max_pieces: int = 7,
    ) -> None:
        self._syzygy_path = syzygy_path
        self._use_lichess_fallback = use_lichess_fallback
        self._max_pieces = max_pieces
        self._syzygy: chess.syzygy.Tablebase | None = None

        if syzygy_path:
            self._open_syzygy(syzygy_path)

    def _open_syzygy(self, path: str) -> None:
        """Open local Syzygy tablebase files."""
        try:
            self._syzygy = chess.syzygy.open_tablebase(path)
        except Exception as e:
            logger.warning("Failed to open Syzygy tablebase at %s: %s", path, e)
            self._syzygy = None

    @property
    def has_local(self) -> bool:
        """Whether local Syzygy tables are available."""
        return self._syzygy is not None

    @property
    def has_lichess(self) -> bool:
        """Whether Lichess API fallback is enabled."""
        return self._use_lichess_fallback

    def is_tablebase_position(self, board: chess.Board) -> bool:
        """Check if a position has few enough pieces for tablebase probing."""
        return len(board.piece_map()) <= self._max_pieces

    def probe_wdl(self, board: chess.Board) -> int:
        """Probe only WDL for a position (quick check).

        Args:
            board: Position to probe.

        Returns:
            WDL value from -2 to 2 (side-to-move's perspective).

        Raises:
            TablebaseError: If probing fails.
        """
        result = self.probe(board)
        return result.wdl

    def best_moves(self, board: chess.Board) -> list[TablebaseMove]:
        """Get all optimal moves for a position.

        Args:
            board: Position to probe.

        Returns:
            List of moves that maintain the best possible outcome.

        Raises:
            TablebaseError: If probing fails.
        """
        result = self.probe(board)
        return result.best_moves

    def probe(self, board: chess.Board) -> TablebaseResult:
        """Probe the tablebase for full WDL + DTZ + move data.

        Tries local Syzygy first, then Lichess API fallback.

        Args:
            board: Position to probe.

        Returns:
            Complete tablebase result with ranked moves.

        Raises:
            TablebaseError: If piece count exceeds max or both backends fail.
        """
        piece_count = len(board.piece_map())
        if piece_count > self._max_pieces:
            raise TablebaseError(
                f"Too many pieces ({piece_count}); tablebase supports up to {self._max_pieces}"
            )

        # Check for terminal positions
        if board.is_checkmate():
            return TablebaseResult(
                wdl=-2,
                dtz=0,
                category="loss",
                checkmate=True,
                stalemate=False,
            )
        if board.is_stalemate():
            return TablebaseResult(
                wdl=0,
                dtz=0,
                category="draw",
                checkmate=False,
                stalemate=True,
            )

        # Try local Syzygy
        if self._syzygy is not None:
            try:
                return self._probe_syzygy(board)
            except chess.syzygy.MissingTableError:
                logger.debug("Syzygy table not found, trying Lichess API fallback")
            except Exception as e:
                logger.debug("Syzygy probe failed: %s", e)

        # Try Lichess API fallback
        if self._use_lichess_fallback:
            try:
                return self._probe_lichess(board)
            except Exception as e:
                raise TablebaseError(f"Lichess tablebase API failed: {e}") from e

        raise TablebaseError("No tablebase backend available for this position")

    def _probe_syzygy(self, board: chess.Board) -> TablebaseResult:
        """Probe local Syzygy tables.

        Raises:
            chess.syzygy.MissingTableError: If the table is not found.
        """
        assert self._syzygy is not None

        wdl = self._syzygy.probe_wdl(board)
        dtz = self._syzygy.get_dtz(board)
        category = _wdl_to_category(wdl)

        # Probe each legal move to build the move list
        moves = []
        for move in board.legal_moves:
            san = board.san(move)
            # Detect zeroing moves (captures or pawn moves) before pushing
            is_capture = board.is_capture(move)
            piece = board.piece_at(move.from_square)
            is_pawn_move = piece is not None and piece.piece_type == chess.PAWN
            zeroing = is_capture or is_pawn_move

            board.push(move)
            try:
                is_checkmate = board.is_checkmate()

                if is_checkmate:
                    move_wdl = 2  # Delivering checkmate = winning
                    move_dtz = 1
                else:
                    # After the move, it's the opponent's turn.
                    # Negate to get WDL from original side's perspective.
                    move_wdl_raw = self._syzygy.probe_wdl(board)
                    move_wdl = _negate_wdl(move_wdl_raw)
                    move_dtz_raw = self._syzygy.get_dtz(board)
                    move_dtz = -move_dtz_raw if move_dtz_raw is not None else None

                moves.append(
                    TablebaseMove(
                        uci=move.uci(),
                        san=san,
                        wdl=move_wdl,
                        dtz=move_dtz,
                        category=_wdl_to_category(move_wdl),
                        zeroing=zeroing,
                        checkmate=is_checkmate,
                    )
                )
            except chess.syzygy.MissingTableError:
                # Can't probe this move's resulting position
                pass
            finally:
                board.pop()

        # Sort: best WDL first, then smallest |DTZ| for wins
        moves.sort(key=lambda m: (-m.wdl, abs(m.dtz) if m.dtz is not None else 9999))

        return TablebaseResult(
            wdl=wdl,
            dtz=dtz,
            category=category,
            checkmate=False,
            stalemate=False,
            moves=moves,
        )

    def _probe_lichess(self, board: chess.Board) -> TablebaseResult:
        """Probe the Lichess tablebase API.

        Raises:
            TablebaseError: On network or parsing errors.
        """
        fen = board.fen()
        try:
            resp = requests.get(LICHESS_TABLEBASE_API, params={"fen": fen}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise TablebaseError(f"Lichess tablebase request failed: {e}") from e

        return self._parse_lichess_response(data, board)

    def _parse_lichess_response(self, data: dict, board: chess.Board) -> TablebaseResult:
        """Parse a Lichess tablebase API response into a TablebaseResult."""
        category = data.get("category", "unknown")
        checkmate = data.get("checkmate", False)
        stalemate = data.get("stalemate", False)

        wdl = self._category_to_wdl(category, checkmate, stalemate)
        dtz = data.get("dtz")

        # Parse moves — note: Lichess gives categories from opponent's POV
        moves = []
        for m in data.get("moves", []):
            # The move's category is from opponent's POV (after the move).
            # Negate to get from the current side's perspective.
            move_category = m.get("category", "unknown")
            move_wdl = _negate_wdl(
                self._category_to_wdl(move_category, m.get("checkmate", False), False)
            )

            moves.append(
                TablebaseMove(
                    uci=m.get("uci", ""),
                    san=m.get("san", ""),
                    wdl=move_wdl,
                    dtz=-m["dtz"] if m.get("dtz") is not None else None,
                    category=_wdl_to_category(move_wdl),
                    zeroing=m.get("zeroing", False),
                    checkmate=m.get("checkmate", False),
                )
            )

        # Sort: best WDL first, then smallest |DTZ| for wins
        moves.sort(key=lambda m: (-m.wdl, abs(m.dtz) if m.dtz is not None else 9999))

        return TablebaseResult(
            wdl=wdl,
            dtz=dtz,
            category=category,
            checkmate=checkmate,
            stalemate=stalemate,
            moves=moves,
        )

    @staticmethod
    def _category_to_wdl(category: str, checkmate: bool, stalemate: bool) -> int:
        """Convert a category string to a WDL integer."""
        if checkmate:
            return -2  # Checkmated = losing
        if stalemate:
            return 0
        return {
            "win": 2,
            "cursed-win": 1,
            "draw": 0,
            "blessed-loss": -1,
            "loss": -2,
        }.get(category, 0)

    def close(self) -> None:
        """Close the local Syzygy tablebase."""
        if self._syzygy is not None:
            self._syzygy.close()
            self._syzygy = None

    def __enter__(self) -> TablebaseManager:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
