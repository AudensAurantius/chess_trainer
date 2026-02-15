"""Tests for the CLI create command."""

from typer.testing import CliRunner

from src.cli.app import app
from src.storage import Repository

runner = CliRunner()

AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
ENDGAME_FEN = "8/8/8/8/8/4K3/4P3/4k3 w - - 0 1"


class TestCreateCommand:
    def test_create_tactic(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "tactic",
                "--moves",
                "e7e5 d2d4",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0
        assert "Created TACTIC exercise" in result.output

        with Repository(tmp_path / "test.db") as repo:
            exercises = list(repo.exercises.iterate_all())
            assert len(exercises) == 1
            assert exercises[0].source == "custom"
            card = repo.cards.get(exercises[0].id)
            assert card is not None

    def test_create_with_slug(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "tactic",
                "--moves",
                "e7e5",
                "--id",
                "my-puzzle",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0
        assert "custom:my-puzzle" in result.output

    def test_create_with_tags_and_difficulty(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "tactic",
                "--moves",
                "e7e5",
                "--tags",
                "pin,middlegame",
                "--difficulty",
                "1500",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0

        with Repository(tmp_path / "test.db") as repo:
            exercises = list(repo.exercises.iterate_all())
            assert exercises[0].tags == ["pin", "middlegame"]
            assert exercises[0].difficulty == 1500.0

    def test_create_endgame(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                ENDGAME_FEN,
                "--type",
                "endgame",
                "--moves",
                "e3d4",
                "--technique",
                "King march",
                "--outcome",
                "win",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0
        assert "Created ENDGAME exercise" in result.output

    def test_create_positional(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "positional",
                "--moves",
                "e7e5",
                "--concept",
                "Center control",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0
        assert "Created POSITIONAL exercise" in result.output

    def test_create_opening(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                START_FEN,
                "--type",
                "opening",
                "--moves",
                "e2e4 e7e5 g1f3",
                "--opening-name",
                "Italian",
                "--eco",
                "C50",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0
        assert "Created OPENING exercise" in result.output

    def test_create_invalid_fen(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                "garbage",
                "--type",
                "tactic",
                "--moves",
                "e2e4",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 1
        assert "Invalid FEN" in result.output

    def test_create_illegal_moves(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "tactic",
                "--moves",
                "e2e4",
                "--db",
                db,  # White can't move
            ],
        )
        assert result.exit_code == 1
        assert "Illegal move" in result.output

    def test_create_invalid_type(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                START_FEN,
                "--type",
                "puzzle",
                "--moves",
                "e2e4",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 1
        assert "Invalid exercise type" in result.output

    def test_create_with_notes(self, tmp_path):
        db = str(tmp_path / "test.db")
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "tactic",
                "--moves",
                "e7e5",
                "--notes",
                "Remember this pattern",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 0

        with Repository(tmp_path / "test.db") as repo:
            exercises = list(repo.exercises.iterate_all())
            assert exercises[0].notes == "Remember this pattern"

    def test_duplicate_slug_fails(self, tmp_path):
        db = str(tmp_path / "test.db")
        runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "tactic",
                "--moves",
                "e7e5",
                "--id",
                "dup-test",
                "--db",
                db,
            ],
        )
        result = runner.invoke(
            app,
            [
                "create",
                "--fen",
                AFTER_E4_FEN,
                "--type",
                "tactic",
                "--moves",
                "e7e5",
                "--id",
                "dup-test",
                "--db",
                db,
            ],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output
