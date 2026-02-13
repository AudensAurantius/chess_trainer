"""Tests for game analysis mistake detection and exercise generation."""

import io
from unittest.mock import MagicMock

import chess
import chess.pgn
import pytest

from src.analysis.classification import MoveClassification
from src.analysis.engine import MATE_SCORE, EngineManager
from src.analysis.mistakes import (
    AnalyzedMove,
    EnginePositionAnalyzer,
    GameAnalysis,
    LichessServerAnalyzer,
    MistakeDetector,
    MultiPVAnalyzer,
    PositionAnalyzer,
    PositionEval,
)
from src.exercises.tactics import TacticExercise

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCHOLARS_MATE_PGN = """[Event "Test"]
[Site "?"]
[White "Alice"]
[Black "Bob"]
[Result "1-0"]

1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"""

SHORT_GAME_PGN = """[Event "Test"]
[Site "https://lichess.org/AbCdEfGh"]
[White "Player1"]
[Black "Player2"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0"""


def _make_game(pgn_text: str) -> chess.pgn.Game:
    """Parse a PGN string into a Game object."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    assert game is not None
    return game


class MockAnalyzer:
    """A mock PositionAnalyzer that returns predetermined evals per ply."""

    def __init__(self, evals: list[PositionEval]) -> None:
        self._evals = evals
        self._ply = 0

    def analyze_position(self, board: chess.Board) -> PositionEval:
        if self._ply < len(self._evals):
            ev = self._evals[self._ply]
        else:
            ev = PositionEval(score_cp=0)
        self._ply += 1
        return ev


# ---------------------------------------------------------------------------
# PositionEval tests
# ---------------------------------------------------------------------------


class TestPositionEval:
    def test_defaults(self):
        ev = PositionEval(score_cp=50)
        assert ev.score_cp == 50
        assert ev.best_move is None
        assert ev.pv == []

    def test_with_best_move(self):
        move = chess.Move.from_uci("e2e4")
        ev = PositionEval(score_cp=30, best_move=move, pv=[move])
        assert ev.best_move == move
        assert ev.pv == [move]

    def test_frozen(self):
        ev = PositionEval(score_cp=0)
        with pytest.raises(AttributeError):
            ev.score_cp = 100  # type: ignore[misc]

    def test_negative_score(self):
        ev = PositionEval(score_cp=-200)
        assert ev.score_cp == -200

    def test_mate_score(self):
        ev = PositionEval(score_cp=MATE_SCORE)
        assert ev.score_cp == MATE_SCORE


# ---------------------------------------------------------------------------
# LichessServerAnalyzer tests
# ---------------------------------------------------------------------------


class TestLichessServerAnalyzer:
    def test_cp_eval(self):
        evals = [{"cp": 50}, {"cp": -30}]
        analyzer = LichessServerAnalyzer(evals)
        board = chess.Board()

        ev1 = analyzer.analyze_position(board)
        assert ev1.score_cp == 50

        ev2 = analyzer.analyze_position(board)
        assert ev2.score_cp == -30

    def test_mate_eval_positive(self):
        evals = [{"mate": 3}]
        analyzer = LichessServerAnalyzer(evals)
        ev = analyzer.analyze_position(chess.Board())
        assert ev.score_cp == MATE_SCORE

    def test_mate_eval_negative(self):
        evals = [{"mate": -2}]
        analyzer = LichessServerAnalyzer(evals)
        ev = analyzer.analyze_position(chess.Board())
        assert ev.score_cp == -MATE_SCORE

    def test_none_eval(self):
        evals = [None]
        analyzer = LichessServerAnalyzer(evals)
        ev = analyzer.analyze_position(chess.Board())
        assert ev.score_cp == 0

    def test_empty_dict_eval(self):
        evals = [{}]
        analyzer = LichessServerAnalyzer(evals)
        ev = analyzer.analyze_position(chess.Board())
        assert ev.score_cp == 0

    def test_beyond_eval_list(self):
        evals = [{"cp": 10}]
        analyzer = LichessServerAnalyzer(evals)
        analyzer.analyze_position(chess.Board())  # consume the one eval
        ev = analyzer.analyze_position(chess.Board())
        assert ev.score_cp == 0

    def test_best_move_always_none(self):
        evals = [{"cp": 50}]
        analyzer = LichessServerAnalyzer(evals)
        ev = analyzer.analyze_position(chess.Board())
        assert ev.best_move is None

    def test_protocol_compliance(self):
        analyzer = LichessServerAnalyzer([])
        assert isinstance(analyzer, PositionAnalyzer)


# ---------------------------------------------------------------------------
# EnginePositionAnalyzer tests
# ---------------------------------------------------------------------------


class TestEnginePositionAnalyzer:
    def test_wraps_engine_manager(self):
        mock_engine = MagicMock(spec=EngineManager)
        mock_result = MagicMock()
        mock_result.evaluation = 42
        mock_line = MagicMock()
        e2e4 = chess.Move.from_uci("e2e4")
        mock_line.pv = [e2e4, chess.Move.from_uci("e7e5")]
        mock_result.best_line = mock_line
        mock_engine.analyze.return_value = mock_result

        analyzer = EnginePositionAnalyzer(mock_engine, depth=15)
        board = chess.Board()
        ev = analyzer.analyze_position(board)

        mock_engine.analyze.assert_called_once_with(board, depth=15, multipv=1)
        assert ev.score_cp == 42
        assert ev.best_move == e2e4
        assert len(ev.pv) == 2

    def test_no_pv(self):
        mock_engine = MagicMock(spec=EngineManager)
        mock_result = MagicMock()
        mock_result.evaluation = 0
        mock_line = MagicMock()
        mock_line.pv = []
        mock_result.best_line = mock_line
        mock_engine.analyze.return_value = mock_result

        analyzer = EnginePositionAnalyzer(mock_engine)
        ev = analyzer.analyze_position(chess.Board())
        assert ev.best_move is None
        assert ev.pv == []

    def test_no_best_line(self):
        mock_engine = MagicMock(spec=EngineManager)
        mock_result = MagicMock()
        mock_result.evaluation = 0
        mock_result.best_line = None
        mock_engine.analyze.return_value = mock_result

        analyzer = EnginePositionAnalyzer(mock_engine)
        ev = analyzer.analyze_position(chess.Board())
        assert ev.best_move is None
        assert ev.pv == []

    def test_protocol_compliance(self):
        mock_engine = MagicMock(spec=EngineManager)
        analyzer = EnginePositionAnalyzer(mock_engine)
        assert isinstance(analyzer, PositionAnalyzer)


# ---------------------------------------------------------------------------
# AnalyzedMove tests
# ---------------------------------------------------------------------------


class TestAnalyzedMove:
    def test_creation(self):
        move = chess.Move.from_uci("e2e4")
        am = AnalyzedMove(
            move_number=1,
            ply=0,
            color="white",
            move=move,
            fen_before=chess.STARTING_FEN,
            eval_before=PositionEval(score_cp=30),
            eval_after=PositionEval(score_cp=25),
            cp_loss=5,
            classification=MoveClassification.EXCELLENT,
        )
        assert am.move_number == 1
        assert am.ply == 0
        assert am.color == "white"
        assert am.cp_loss == 5

    def test_frozen(self):
        move = chess.Move.from_uci("e2e4")
        am = AnalyzedMove(
            move_number=1,
            ply=0,
            color="white",
            move=move,
            fen_before=chess.STARTING_FEN,
            eval_before=PositionEval(score_cp=0),
            eval_after=PositionEval(score_cp=0),
            cp_loss=0,
            classification=MoveClassification.BEST,
        )
        with pytest.raises(AttributeError):
            am.cp_loss = 100  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GameAnalysis tests
# ---------------------------------------------------------------------------


class TestGameAnalysis:
    def _make_analysis(self) -> GameAnalysis:
        """Build a GameAnalysis with mixed severity moves."""
        moves = [
            AnalyzedMove(
                move_number=1,
                ply=0,
                color="white",
                move=chess.Move.from_uci("e2e4"),
                fen_before=chess.STARTING_FEN,
                eval_before=PositionEval(score_cp=30),
                eval_after=PositionEval(score_cp=-25),
                cp_loss=5,
                classification=MoveClassification.EXCELLENT,
            ),
            AnalyzedMove(
                move_number=1,
                ply=1,
                color="black",
                move=chess.Move.from_uci("e7e5"),
                fen_before="fen2",
                eval_before=PositionEval(score_cp=25),
                eval_after=PositionEval(score_cp=-30),
                cp_loss=55,
                classification=MoveClassification.MISTAKE,
            ),
            AnalyzedMove(
                move_number=2,
                ply=2,
                color="white",
                move=chess.Move.from_uci("d2d4"),
                fen_before="fen3",
                eval_before=PositionEval(score_cp=80),
                eval_after=PositionEval(score_cp=10),
                cp_loss=150,
                classification=MoveClassification.BLUNDER,
            ),
            AnalyzedMove(
                move_number=2,
                ply=3,
                color="black",
                move=chess.Move.from_uci("d7d5"),
                fen_before="fen4",
                eval_before=PositionEval(score_cp=10),
                eval_after=PositionEval(score_cp=-5),
                cp_loss=15,
                classification=MoveClassification.GOOD,
            ),
        ]
        return GameAnalysis(
            game_id="test123",
            white="Alice",
            black="Bob",
            result="1-0",
            moves=moves,
            source_url="https://lichess.org/test123",
        )

    def test_mistakes(self):
        analysis = self._make_analysis()
        mistakes = analysis.mistakes
        assert len(mistakes) == 2  # MISTAKE + BLUNDER
        assert all(m.classification >= MoveClassification.MISTAKE for m in mistakes)

    def test_blunders(self):
        analysis = self._make_analysis()
        blunders = analysis.blunders
        assert len(blunders) == 1
        assert blunders[0].classification == MoveClassification.BLUNDER

    def test_filter_by_classification(self):
        analysis = self._make_analysis()
        inaccuracies = analysis.filter_by_classification(MoveClassification.INACCURACY)
        assert len(inaccuracies) == 2  # MISTAKE and BLUNDER are >= INACCURACY

    def test_filter_best_returns_all(self):
        analysis = self._make_analysis()
        all_moves = analysis.filter_by_classification(MoveClassification.BEST)
        assert len(all_moves) == 4

    def test_mistakes_by_color(self):
        analysis = self._make_analysis()
        white_mistakes = analysis.mistakes_by_color("white")
        assert len(white_mistakes) == 1
        assert white_mistakes[0].color == "white"

        black_mistakes = analysis.mistakes_by_color("black")
        assert len(black_mistakes) == 1
        assert black_mistakes[0].color == "black"

    def test_empty_analysis(self):
        analysis = GameAnalysis(
            game_id="empty",
            white="?",
            black="?",
            result="*",
            moves=[],
        )
        assert analysis.mistakes == []
        assert analysis.blunders == []


# ---------------------------------------------------------------------------
# MistakeDetector.analyze_game tests
# ---------------------------------------------------------------------------


class TestMistakeDetectorAnalyzeGame:
    def test_basic_analysis(self):
        game = _make_game(SHORT_GAME_PGN)
        # 6 moves → 7 evals needed
        e2e4 = chess.Move.from_uci("e2e4")
        evals = [
            PositionEval(score_cp=20, best_move=e2e4, pv=[e2e4]),  # initial
            PositionEval(score_cp=-15),  # after 1.e4
            PositionEval(score_cp=25),  # after 1...e5
            PositionEval(score_cp=-20),  # after 2.Nf3
            PositionEval(score_cp=30),  # after 2...Nc6
            PositionEval(score_cp=-25),  # after 3.Bb5
            PositionEval(score_cp=20),  # after 3...a6
        ]
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        assert analysis.game_id == "AbCdEfGh"
        assert analysis.white == "Player1"
        assert analysis.black == "Player2"
        assert analysis.result == "1-0"
        assert len(analysis.moves) == 6

    def test_custom_game_id(self):
        game = _make_game(SHORT_GAME_PGN)
        evals = [PositionEval(score_cp=0)] * 7
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game, game_id="custom_id")
        assert analysis.game_id == "custom_id"

    def test_source_url(self):
        game = _make_game(SHORT_GAME_PGN)
        evals = [PositionEval(score_cp=0)] * 7
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game, source_url="https://lichess.org/XYZ")
        assert analysis.source_url == "https://lichess.org/XYZ"

    def test_cp_loss_calculation(self):
        """cp_loss = score_before - (-score_after)."""
        game = _make_game(SHORT_GAME_PGN)
        # For move 0 (1.e4): eval_before=50, eval_after=-40
        # cp_loss = 50 - (-(-40)) = 50 - 40 = 10
        evals = [
            PositionEval(score_cp=50),
            PositionEval(score_cp=-40),
            PositionEval(score_cp=30),
            PositionEval(score_cp=-25),
            PositionEval(score_cp=20),
            PositionEval(score_cp=-15),
            PositionEval(score_cp=10),
        ]
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        assert analysis.moves[0].cp_loss == 10  # 50 - (-(-40)) = 50 - 40 = 10
        # Move 1 (1...e5): eval_before=-40 (black's POV), eval_after=30 (white's POV)
        # cp_loss = max(0, -40 - (-30)) = max(0, -10) = 0
        assert analysis.moves[1].cp_loss == 0

    def test_cp_loss_never_negative(self):
        """cp_loss is clamped to 0."""
        game = _make_game(SHORT_GAME_PGN)
        # Better eval after move → negative raw cp_loss → clamped to 0
        evals = [
            PositionEval(score_cp=10),  # before 1.e4
            PositionEval(score_cp=-30),  # after 1.e4 (from black's POV)
            # cp_loss = max(0, 10 - 30) < 0 → 0
            PositionEval(score_cp=10),
            PositionEval(score_cp=-10),
            PositionEval(score_cp=10),
            PositionEval(score_cp=-10),
            PositionEval(score_cp=10),
        ]
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        for m in analysis.moves:
            assert m.cp_loss >= 0

    def test_color_assignment(self):
        game = _make_game(SHORT_GAME_PGN)
        evals = [PositionEval(score_cp=0)] * 7
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        colors = [m.color for m in analysis.moves]
        assert colors == ["white", "black", "white", "black", "white", "black"]

    def test_move_numbers(self):
        game = _make_game(SHORT_GAME_PGN)
        evals = [PositionEval(score_cp=0)] * 7
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        move_numbers = [m.move_number for m in analysis.moves]
        assert move_numbers == [1, 1, 2, 2, 3, 3]

    def test_ply_assignment(self):
        game = _make_game(SHORT_GAME_PGN)
        evals = [PositionEval(score_cp=0)] * 7
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        plies = [m.ply for m in analysis.moves]
        assert plies == [0, 1, 2, 3, 4, 5]

    def test_empty_game(self):
        pgn = '[Event "?"]\n[Result "*"]\n\n*'
        game = _make_game(pgn)
        evals = [PositionEval(score_cp=0)]  # just the initial position
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        assert analysis.moves == []

    def test_blunder_detection(self):
        """A large eval swing should be classified as a blunder."""
        game = _make_game(SHORT_GAME_PGN)
        # Move 2 (ply=2, white's 2.Nf3): huge eval drop
        evals = [
            PositionEval(score_cp=30),  # pos 0
            PositionEval(score_cp=-25),  # pos 1
            PositionEval(score_cp=200),  # pos 2 (white to move, good position)
            PositionEval(score_cp=50),  # pos 3 (black to move, was bad for white)
            # cp_loss for ply 2: 200 - (-50) = 200 + 50 = 250 → BLUNDER
            PositionEval(score_cp=20),
            PositionEval(score_cp=-10),
            PositionEval(score_cp=5),
        ]
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        blunder = analysis.moves[2]
        assert blunder.cp_loss == 250
        assert blunder.classification == MoveClassification.BLUNDER

    def test_game_id_from_site_header(self):
        """Game ID is extracted from the Site header URL."""
        game = _make_game(SHORT_GAME_PGN)
        evals = [PositionEval(score_cp=0)] * 7
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        assert analysis.game_id == "AbCdEfGh"

    def test_game_id_unknown_fallback(self):
        pgn = '[Event "?"]\n[Result "*"]\n\n1. e4 *'
        game = _make_game(pgn)
        evals = [PositionEval(score_cp=0)] * 2
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(analyzer)

        analysis = detector.analyze_game(game)
        assert analysis.game_id == "unknown"


# ---------------------------------------------------------------------------
# MistakeDetector.generate_exercises tests
# ---------------------------------------------------------------------------


class TestMistakeDetectorGenerateExercises:
    def _make_blunder_game(self) -> tuple[chess.pgn.Game, list[PositionEval]]:
        """Create a game with one clear blunder at ply 6 (skipped) and ply 2."""
        game = _make_game(SHORT_GAME_PGN)
        best_move = chess.Move.from_uci("d2d4")
        evals = [
            PositionEval(score_cp=30),  # pos 0
            PositionEval(score_cp=-25),  # pos 1
            PositionEval(
                score_cp=200,
                best_move=best_move,
                pv=[best_move, chess.Move.from_uci("d7d5")],
            ),  # pos 2 — white has a great position
            PositionEval(score_cp=50),  # pos 3 — white blundered (cp_loss = 250)
            PositionEval(score_cp=20),  # pos 4
            PositionEval(score_cp=-15),  # pos 5
            PositionEval(score_cp=10),  # pos 6
        ]
        return game, evals

    def test_generates_exercises(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        assert len(exercises) >= 1
        assert all(isinstance(e, TacticExercise) for e in exercises)

    def test_exercise_id_format(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        assert any(ex.id.startswith("game:AbCdEfGh:m") for ex in exercises)

    def test_exercise_source(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        assert all(ex.source == "game_analysis" for ex in exercises)

    def test_exercise_themes(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert "own_game" in ex.themes

    def test_exercise_metadata(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert "cp_loss" in ex.metadata
            assert "played_move_uci" in ex.metadata
            assert "score_before" in ex.metadata
            assert "score_after" in ex.metadata

    def test_exercise_solution_from_pv(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        # The blunder at ply 2 should have d2d4 as the best move
        blunder_ex = [e for e in exercises if "m2" in e.id]
        assert len(blunder_ex) == 1
        assert blunder_ex[0].solution[0] == "d2d4"

    def test_skip_first_plies(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        # skip_first_plies=4 should skip the blunder at ply 2
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=4,
        )
        exercises = list(detector.generate_exercises(game))
        assert all("m2" not in ex.id for ex in exercises)

    def test_color_filter_white(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game, color="white"))
        # Verify all exercises are from white's perspective
        for ex in exercises:
            board = chess.Board(ex.fen)
            assert board.turn == chess.WHITE

    def test_color_filter_black(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.INACCURACY,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game, color="black"))
        for ex in exercises:
            board = chess.Board(ex.fen)
            assert board.turn == chess.BLACK

    def test_max_exercises_limit(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.BEST,  # Include everything
            max_exercises=1,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        assert len(exercises) <= 1

    def test_sorted_by_cp_loss_descending(self):
        """Exercises should be sorted by cp_loss descending (worst first)."""
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.BEST,
            max_exercises=10,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        if len(exercises) > 1:
            cp_losses = [ex.metadata["cp_loss"] for ex in exercises]
            assert cp_losses == sorted(cp_losses, reverse=True)

    def test_min_classification_blunder(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.BLUNDER,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert ex.metadata["cp_loss"] > 100  # BLUNDER threshold

    def test_source_url_with_ply_anchor(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(
            detector.generate_exercises(game, source_url="https://lichess.org/AbCdEfGh")
        )
        for ex in exercises:
            assert ex.source_url is not None
            assert "#" in ex.source_url

    def test_no_exercises_for_perfect_game(self):
        game = _make_game(SHORT_GAME_PGN)
        evals = [PositionEval(score_cp=0)] * 7  # All equal → no cp_loss
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        assert exercises == []

    def test_skip_moves_without_best_move(self):
        """If eval_before has no best_move, skip that exercise."""
        game = _make_game(SHORT_GAME_PGN)
        # Make one position a blunder but without a best_move in eval
        evals = [
            PositionEval(score_cp=200),  # No best_move!
            PositionEval(score_cp=50),  # cp_loss = 250
            PositionEval(score_cp=0),
            PositionEval(score_cp=0),
            PositionEval(score_cp=0),
            PositionEval(score_cp=0),
            PositionEval(score_cp=0),
        ]
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        # The blunder at ply 0 has no best_move → should be skipped
        assert all("m1" not in ex.id for ex in exercises)

    def test_exercise_fen_is_position_before_move(self):
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        blunder_ex = [e for e in exercises if "m2" in e.id]
        assert len(blunder_ex) == 1
        # The FEN should be the position before white's 2nd move
        board = chess.Board(blunder_ex[0].fen)
        assert board.turn == chess.WHITE


# ---------------------------------------------------------------------------
# MockAnalyzer protocol test
# ---------------------------------------------------------------------------


class TestMockAnalyzer:
    def test_protocol_compliance(self):
        analyzer = MockAnalyzer([])
        assert isinstance(analyzer, PositionAnalyzer)

    def test_returns_evals_in_order(self):
        evals = [PositionEval(score_cp=i * 10) for i in range(5)]
        analyzer = MockAnalyzer(evals)
        board = chess.Board()
        for i in range(5):
            ev = analyzer.analyze_position(board)
            assert ev.score_cp == i * 10

    def test_returns_zero_beyond_list(self):
        analyzer = MockAnalyzer([PositionEval(score_cp=42)])
        board = chess.Board()
        analyzer.analyze_position(board)
        ev = analyzer.analyze_position(board)
        assert ev.score_cp == 0


# ---------------------------------------------------------------------------
# MockMultiPVAnalyzer
# ---------------------------------------------------------------------------


class MockMultiPVAnalyzer:
    """A mock analyzer that supports both single-PV and multi-PV analysis."""

    def __init__(
        self,
        evals: list[PositionEval],
        multipv_results: dict[str, list[PositionEval]] | None = None,
    ) -> None:
        self._evals = evals
        self._ply = 0
        self._multipv_results = multipv_results or {}

    def analyze_position(self, board: chess.Board) -> PositionEval:
        if self._ply < len(self._evals):
            ev = self._evals[self._ply]
        else:
            ev = PositionEval(score_cp=0)
        self._ply += 1
        return ev

    def analyze_multipv(self, board: chess.Board, multipv: int) -> list[PositionEval]:
        fen = board.fen()
        if fen in self._multipv_results:
            return self._multipv_results[fen]
        return []


# ---------------------------------------------------------------------------
# MultiPVAnalyzer protocol tests
# ---------------------------------------------------------------------------


class TestMultiPVAnalyzer:
    def test_engine_position_analyzer_implements_multipv(self):
        mock_engine = MagicMock(spec=EngineManager)
        analyzer = EnginePositionAnalyzer(mock_engine)
        assert isinstance(analyzer, MultiPVAnalyzer)

    def test_lichess_does_not_implement_multipv(self):
        analyzer = LichessServerAnalyzer([])
        assert not isinstance(analyzer, MultiPVAnalyzer)

    def test_mock_multipv_protocol(self):
        analyzer = MockMultiPVAnalyzer([])
        assert isinstance(analyzer, MultiPVAnalyzer)

    def test_engine_analyze_multipv(self):
        mock_engine = MagicMock(spec=EngineManager)
        mock_result = MagicMock()

        line1 = MagicMock()
        line1.pv = [chess.Move.from_uci("e2e4")]
        line1.score_value = 30

        line2 = MagicMock()
        line2.pv = [chess.Move.from_uci("d2d4")]
        line2.score_value = 25

        line3 = MagicMock()
        line3.pv = [chess.Move.from_uci("g1f3")]
        line3.score_value = 15

        mock_result.lines = [line1, line2, line3]
        mock_engine.analyze.return_value = mock_result

        analyzer = EnginePositionAnalyzer(mock_engine, depth=20)
        board = chess.Board()
        results = analyzer.analyze_multipv(board, 3)

        mock_engine.analyze.assert_called_once_with(board, depth=20, multipv=3)
        assert len(results) == 3
        assert results[0].score_cp == 30
        assert results[0].best_move == chess.Move.from_uci("e2e4")
        assert results[1].score_cp == 25
        assert results[2].score_cp == 15


# ---------------------------------------------------------------------------
# MistakeDetector multi-PV exercise generation tests
# ---------------------------------------------------------------------------


class TestMistakeDetectorMultiPV:
    """Tests for multi-PV acceptable move computation in MistakeDetector."""

    def _make_blunder_game(self):
        """Create a game with a blunder at ply 2."""
        game = _make_game(SHORT_GAME_PGN)
        best_move = chess.Move.from_uci("d2d4")
        d7d5 = chess.Move.from_uci("d7d5")
        evals = [
            PositionEval(score_cp=30),  # pos 0
            PositionEval(score_cp=-25),  # pos 1
            PositionEval(
                score_cp=200,
                best_move=best_move,
                pv=[best_move, d7d5],
            ),  # pos 2 — white has a great position
            PositionEval(score_cp=50),  # pos 3 — cp_loss = 250
            PositionEval(score_cp=20),  # pos 4
            PositionEval(score_cp=-15),  # pos 5
            PositionEval(score_cp=10),  # pos 6
        ]
        return game, evals

    def _blunder_fen(self) -> str:
        """FEN after 1.e4 e5 (white to play move 2)."""
        board = chess.Board()
        board.push_uci("e2e4")
        board.push_uci("e7e5")
        return board.fen()

    def test_no_multipv_without_tolerance(self):
        """With cp_tolerance=0, acceptable_first_moves stays empty."""
        game, evals = self._make_blunder_game()
        analyzer = MockMultiPVAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
            cp_tolerance=0,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert ex.acceptable_first_moves == []

    def test_multipv_populates_acceptable_moves(self):
        """With cp_tolerance>0 and multipv analyzer, acceptable_first_moves is populated."""
        game, evals = self._make_blunder_game()
        fen = self._blunder_fen()

        multipv_results = {
            fen: [
                PositionEval(score_cp=200, best_move=chess.Move.from_uci("d2d4")),
                PositionEval(score_cp=190, best_move=chess.Move.from_uci("g1f3")),
                PositionEval(score_cp=120, best_move=chess.Move.from_uci("f1c4")),
            ]
        }
        analyzer = MockMultiPVAnalyzer(evals, multipv_results)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
            cp_tolerance=50,
            multipv_count=3,
        )
        exercises = list(detector.generate_exercises(game))
        blunder_ex = [e for e in exercises if "m2" in e.id]
        assert len(blunder_ex) == 1
        ex = blunder_ex[0]
        # d2d4 (200cp) and g1f3 (190cp) are within 50cp of best
        # f1c4 (120cp) is NOT within 50cp
        assert "d2d4" in ex.acceptable_first_moves
        assert "g1f3" in ex.acceptable_first_moves
        assert "f1c4" not in ex.acceptable_first_moves

    def test_multipv_best_move_eval_set(self):
        """best_move_eval is set from the multi-PV top score."""
        game, evals = self._make_blunder_game()
        fen = self._blunder_fen()
        multipv_results = {
            fen: [
                PositionEval(score_cp=200, best_move=chess.Move.from_uci("d2d4")),
            ]
        }
        analyzer = MockMultiPVAnalyzer(evals, multipv_results)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
            cp_tolerance=50,
            multipv_count=3,
        )
        exercises = list(detector.generate_exercises(game))
        blunder_ex = [e for e in exercises if "m2" in e.id]
        assert blunder_ex[0].best_move_eval == 200

    def test_evaluate_depth_set_on_exercises(self):
        """evaluate_depth from detector config is set on exercises."""
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
            evaluate_depth=1,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert ex.evaluate_depth == 1

    def test_evaluate_depth_none_by_default(self):
        """Without evaluate_depth, exercises have None."""
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert ex.evaluate_depth is None

    def test_fallback_without_multipv_support(self):
        """MockAnalyzer doesn't support multipv — acceptable_first_moves stays empty."""
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)  # No multipv support
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
            cp_tolerance=50,
            multipv_count=3,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert ex.acceptable_first_moves == []

    def test_game_context_stored_in_metadata(self):
        """game_context dict is stored in exercise metadata."""
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        context = {
            "game_date": "2026-01-15",
            "opponent": "BobChess",
            "time_control": "5+0",
            "player_color": "white",
        }
        exercises = list(detector.generate_exercises(game, game_context=context))
        for ex in exercises:
            assert ex.metadata["game_context"] == context

    def test_no_game_context_if_not_provided(self):
        """Without game_context, metadata has no game_context key."""
        game, evals = self._make_blunder_game()
        analyzer = MockAnalyzer(evals)
        detector = MistakeDetector(
            analyzer,
            min_classification=MoveClassification.MISTAKE,
            skip_first_plies=0,
        )
        exercises = list(detector.generate_exercises(game))
        for ex in exercises:
            assert "game_context" not in ex.metadata
