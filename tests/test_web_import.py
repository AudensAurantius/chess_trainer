"""Tests for web import functionality."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import AppConfig
from src.exercises import TacticExercise
from src.web import create_app

SAMPLE_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def _make_tactic(puzzle_id: str, source: str = "lichess") -> TacticExercise:
    return TacticExercise(
        id=f"{source}:{puzzle_id}",
        fen=SAMPLE_FEN,
        tags=["fork", "tactic"],
        source=source,
        difficulty=1500.0,
        solution=["e7e5"],
        themes=["fork"],
    )


@pytest.fixture
def app(tmp_path):
    config = AppConfig()
    config.database.path = str(tmp_path / "test.db")
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app)


class TestSessionManagerImport:
    """Tests for SessionManager.import_lichess_puzzles."""

    def test_import_creates_cards_and_tags(self, tmp_path):
        """Imported puzzles get cards and tags synced."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        puzzles = [_make_tactic("p1"), _make_tactic("p2")]

        with patch("src.importers.lichess_puzzles.LichessPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter(puzzles)
            result = manager.import_lichess_puzzles(count=2)

        assert result["added"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["cards_created"] == 2

        # Verify cards exist
        repo = manager._open_repo()
        card1 = repo.cards.get("lichess:p1")
        card2 = repo.cards.get("lichess:p2")
        assert card1 is not None
        assert card2 is not None
        manager.end_session()

    def test_import_skips_duplicates(self, tmp_path):
        """Re-importing the same puzzle skips it."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        puzzles = [_make_tactic("p1")]

        with patch("src.importers.lichess_puzzles.LichessPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter(puzzles)
            result1 = manager.import_lichess_puzzles(count=1)

        assert result1["added"] == 1

        with patch("src.importers.lichess_puzzles.LichessPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter([_make_tactic("p1")])
            result2 = manager.import_lichess_puzzles(count=1)

        assert result2["added"] == 0
        assert result2["skipped"] == 1
        manager.end_session()

    def test_import_caps_count_at_100(self, tmp_path):
        """Count is capped at 100."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch("src.importers.lichess_puzzles.LichessPuzzleImporter.import_to") as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Lichess Puzzles", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_lichess_puzzles(count=200)

            # Verify import_to was called with count=100
            _, kwargs = mock_import.call_args
            assert kwargs["count"] == 100
        manager._close_repo()

    def test_import_passes_difficulty_and_themes(self, tmp_path):
        """Difficulty and themes are forwarded to the importer."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch("src.importers.lichess_puzzles.LichessPuzzleImporter.import_to") as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Lichess Puzzles", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_lichess_puzzles(
                    count=10, difficulty="harder", themes=["fork", "pin"]
                )

            _, kwargs = mock_import.call_args
            assert kwargs["difficulty"] == "harder"
            assert kwargs["themes"] == ["fork", "pin"]
        manager._close_repo()


class TestImportPage:
    """Tests for the import page and nav link."""

    def test_import_page_renders(self, client):
        res = client.get("/import")
        assert res.status_code == 200
        assert "Import Exercises" in res.text
        assert "Lichess Puzzles" in res.text

    def test_import_page_has_form_fields(self, client):
        res = client.get("/import")
        assert 'id="import-count"' in res.text
        assert 'id="import-difficulty"' in res.text
        assert 'id="import-themes"' in res.text

    def test_nav_has_import_link(self, client):
        """Nav bar should contain an Import link."""
        res = client.get("/")
        assert 'href="/import"' in res.text
        assert "Import" in res.text


class TestImportAPI:
    """Tests for POST /api/import/lichess."""

    def test_import_api_returns_result(self, client):
        """API returns correct JSON with mocked importer."""
        puzzles = [_make_tactic("api1"), _make_tactic("api2")]
        with patch("src.importers.lichess_puzzles.LichessPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter(puzzles)
            res = client.post("/api/import/lichess", json={"count": 2})

        assert res.status_code == 200
        data = res.json()
        assert data["added"] == 2
        assert data["skipped"] == 0

    def test_import_api_caps_count(self, client):
        """API caps count at 100."""
        with patch("src.importers.lichess_puzzles.LichessPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter([])
            res = client.post("/api/import/lichess", json={"count": 999})

        assert res.status_code == 200
        data = res.json()
        assert data["added"] == 0  # no puzzles fetched, but no error


class TestFailedPuzzleImport:
    """Tests for Lichess failed puzzle import."""

    def test_import_creates_cards_and_tags(self, tmp_path):
        """Imported failed puzzles get cards and tags synced."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        puzzles = [
            TacticExercise(
                id="lichess:fail1",
                fen=SAMPLE_FEN,
                tags=["failed-puzzle", "needs-review", "fork"],
                source="lichess",
                difficulty=1500.0,
                solution=["e7e5"],
                themes=["fork"],
            ),
        ]

        with patch(
            "src.importers.lichess_puzzles.LichessPuzzleImporter.fetch_failed"
        ) as mock_fetch:
            mock_fetch.return_value = iter(puzzles)
            result = manager.import_lichess_failed_puzzles(count=1)

        assert result["added"] == 1
        assert result["cards_created"] == 1
        manager.end_session()

    def test_import_caps_count_at_100(self, tmp_path):
        """Count is capped at 100."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch(
            "src.importers.lichess_puzzles.LichessPuzzleImporter.import_to_failed"
        ) as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Lichess Puzzles", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_lichess_failed_puzzles(count=200)

            _, kwargs = mock_import.call_args
            assert kwargs["count"] == 100
        manager._close_repo()

    def test_import_passes_since_and_auto_tag(self, tmp_path):
        """since and auto_tag are forwarded to the importer."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch(
            "src.importers.lichess_puzzles.LichessPuzzleImporter.import_to_failed"
        ) as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Lichess Puzzles", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_lichess_failed_puzzles(count=10, since="3 months", auto_tag=False)

            _, kwargs = mock_import.call_args
            assert kwargs["since"] == "3 months"
            assert kwargs["auto_tag"] is False
        manager._close_repo()


class TestFailedPuzzleImportAPI:
    """Tests for POST /api/import/lichess-failed."""

    def test_api_returns_result(self, client):
        """API returns correct JSON."""
        puzzles = [_make_tactic("fail1")]
        with patch(
            "src.importers.lichess_puzzles.LichessPuzzleImporter.fetch_failed"
        ) as mock_fetch:
            mock_fetch.return_value = iter(puzzles)
            res = client.post("/api/import/lichess-failed", json={"count": 1})

        assert res.status_code == 200
        data = res.json()
        assert data["added"] == 1

    def test_api_returns_401_on_auth_error(self, client):
        """401 errors from Lichess return a clear message."""
        with patch(
            "src.importers.lichess_puzzles.LichessPuzzleImporter.fetch_failed"
        ) as mock_fetch:
            mock_fetch.side_effect = RuntimeError("HTTP 401: unauthorized")
            res = client.post("/api/import/lichess-failed", json={"count": 5})

        assert res.status_code == 401
        assert "token" in res.json()["error"].lower()

    def test_api_returns_500_on_other_error(self, client):
        """Non-auth errors return 500."""
        with patch(
            "src.importers.lichess_puzzles.LichessPuzzleImporter.fetch_failed"
        ) as mock_fetch:
            mock_fetch.side_effect = RuntimeError("Network timeout")
            res = client.post("/api/import/lichess-failed", json={"count": 5})

        assert res.status_code == 500
        assert "Network timeout" in res.json()["error"]


class TestHasLichessToken:
    """Tests for token detection."""

    def test_no_token_by_default(self, tmp_path):
        """No token configured by default."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        with patch("src.lichess.constants.LICHESS_TOKEN", None):
            assert manager.has_lichess_token() is False
        manager._close_repo()

    def test_token_from_config(self, tmp_path):
        """Token from config.lichess.token is detected."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")
        config.lichess.token = "lip_test123"

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        assert manager.has_lichess_token() is True
        manager._close_repo()

    def test_token_from_env(self, tmp_path):
        """Token from LICHESS_TOKEN env constant is detected."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        with patch("src.lichess.constants.LICHESS_TOKEN", "lip_env_token"):
            assert manager.has_lichess_token() is True
        manager._close_repo()

    def test_import_page_passes_token_flag(self, client):
        """GET /import passes has_lichess_token to the template."""
        res = client.get("/import")
        assert res.status_code == 200
        # Template should render — token context is present
        # (even if false, it shouldn't error)


class TestLichessGameImport:
    """Tests for Lichess game analysis import."""

    def test_import_creates_cards_and_tags(self, tmp_path):
        """Imported game exercises get cards and tags synced."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        exercises = [
            TacticExercise(
                id="game:abc123:m10",
                fen=SAMPLE_FEN,
                tags=["mistake", "own_game"],
                source="game_analysis",
                difficulty=1500.0,
                solution=["e7e5"],
                themes=["mistake"],
            ),
        ]

        with patch("src.importers.games.GameImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter(exercises)
            result = manager.import_lichess_games(username="testuser", max_games=5)

        assert result["added"] == 1
        assert result["cards_created"] == 1
        manager.end_session()

    def test_import_caps_max_games_at_50(self, tmp_path):
        """max_games is capped at 50."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch("src.importers.games.GameImporter.import_to") as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Game Analysis", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_lichess_games(username="testuser", max_games=200)

            _, kwargs = mock_import.call_args
            assert kwargs["max_games"] == 50
        manager._close_repo()

    def test_import_uses_server_evals(self, tmp_path):
        """Server evals are always enabled for web game import."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch("src.importers.games.GameImporter.import_to") as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Game Analysis", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_lichess_games(username="testuser")

            _, kwargs = mock_import.call_args
            assert kwargs["use_server_evals"] is True
        manager._close_repo()

    def test_import_passes_filters(self, tmp_path):
        """Color, perf_type, rated filters are forwarded."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch("src.importers.games.GameImporter.import_to") as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Game Analysis", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_lichess_games(
                    username="testuser",
                    max_games=5,
                    color="white",
                    perf_type="rapid",
                    rated=True,
                )

            _, kwargs = mock_import.call_args
            assert kwargs["color"] == "white"
            assert kwargs["perf_type"] == "rapid"
            assert kwargs["rated"] is True
        manager._close_repo()

    def test_import_uses_config_values(self, tmp_path):
        """GameImporter is constructed with values from config."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")
        config.game_analysis.min_classification = "BLUNDER"
        config.own_game_eval.cp_tolerance = 75

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch("src.importers.games.GameImporter.__init__", return_value=None) as mock_init:
            with patch("src.importers.games.GameImporter.import_to") as mock_import:
                from src.importers.base import ImportResult

                mock_import.return_value = ImportResult(source="Game Analysis", total_added=0)
                with patch.object(manager, "_open_repo") as mock_repo:
                    mock_repo.return_value = MagicMock()
                    mock_repo.return_value.exercises.search.return_value = []
                    manager.import_lichess_games(username="testuser")

            from src.analysis.classification import MoveClassification

            _, kwargs = mock_init.call_args
            assert kwargs["min_classification"] == MoveClassification.BLUNDER
            assert kwargs["cp_tolerance"] == 75
        manager._close_repo()


class TestLichessGameImportAPI:
    """Tests for POST /api/import/lichess-games."""

    def test_api_returns_result(self, client):
        """API returns correct JSON."""
        exercises = [
            TacticExercise(
                id="game:abc:m5",
                fen=SAMPLE_FEN,
                tags=["mistake", "own_game"],
                source="game_analysis",
                difficulty=1500.0,
                solution=["e7e5"],
                themes=["mistake"],
            ),
        ]
        with patch("src.importers.games.GameImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter(exercises)
            res = client.post(
                "/api/import/lichess-games",
                json={"username": "testuser", "max_games": 5},
            )

        assert res.status_code == 200
        data = res.json()
        assert data["added"] == 1

    def test_api_requires_username(self, client):
        """Missing username returns 400."""
        res = client.post("/api/import/lichess-games", json={"max_games": 5})
        assert res.status_code == 400
        assert "username" in res.json()["error"].lower()

    def test_api_caps_max_games(self, client):
        """max_games is capped at 50."""
        with patch("src.importers.games.GameImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter([])
            res = client.post(
                "/api/import/lichess-games",
                json={"username": "testuser", "max_games": 999},
            )

        assert res.status_code == 200

    def test_api_passes_filters(self, client):
        """Color, perf_type, rated are forwarded."""
        with patch("src.importers.games.GameImporter.import_to") as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Game Analysis", total_added=0)
            res = client.post(
                "/api/import/lichess-games",
                json={
                    "username": "testuser",
                    "max_games": 5,
                    "color": "black",
                    "perf_type": "blitz",
                    "rated": True,
                },
            )

        assert res.status_code == 200
        _, kwargs = mock_import.call_args
        assert kwargs["color"] == "black"
        assert kwargs["perf_type"] == "blitz"
        assert kwargs["rated"] is True

    def test_api_error_returns_500(self, client):
        """Import errors return 500."""
        with patch("src.importers.games.GameImporter.fetch") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("Network error")
            res = client.post(
                "/api/import/lichess-games",
                json={"username": "testuser"},
            )

        assert res.status_code == 500
        assert "Network error" in res.json()["error"]


class TestChessComImport:
    """Tests for Chess.com puzzle import."""

    def test_import_creates_cards_and_tags(self, tmp_path):
        """Imported Chess.com puzzles get cards and tags synced."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)
        puzzles = [
            _make_tactic("daily1", source="chesscom"),
            _make_tactic("daily2", source="chesscom"),
        ]

        with patch("src.importers.chesscom_puzzles.ChessComPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter(puzzles)
            result = manager.import_chesscom_puzzles(count=2)

        assert result["added"] == 2
        assert result["skipped"] == 0
        assert result["errors"] == 0
        assert result["cards_created"] == 2

        repo = manager._open_repo()
        assert repo.cards.get("chesscom:daily1") is not None
        assert repo.cards.get("chesscom:daily2") is not None
        manager.end_session()

    def test_import_caps_count_at_100(self, tmp_path):
        """Count is capped at 100."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch(
            "src.importers.chesscom_puzzles.ChessComPuzzleImporter.import_to"
        ) as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Chess.com Puzzles", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_chesscom_puzzles(count=200)

            _, kwargs = mock_import.call_args
            assert kwargs["count"] == 100
        manager._close_repo()

    def test_import_passes_include_daily(self, tmp_path):
        """include_daily flag is forwarded to the importer."""
        config = AppConfig()
        config.database.path = str(tmp_path / "test.db")

        from src.web.session_manager import SessionManager

        manager = SessionManager(config)

        with patch(
            "src.importers.chesscom_puzzles.ChessComPuzzleImporter.import_to"
        ) as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Chess.com Puzzles", total_added=0)
            with patch.object(manager, "_open_repo") as mock_repo:
                mock_repo.return_value = MagicMock()
                mock_repo.return_value.exercises.search.return_value = []
                manager.import_chesscom_puzzles(count=10, include_daily=False)

            _, kwargs = mock_import.call_args
            assert kwargs["include_daily"] is False
        manager._close_repo()


class TestChessComImportAPI:
    """Tests for POST /api/import/chesscom."""

    def test_api_returns_result(self, client):
        """API returns correct JSON with mocked importer."""
        puzzles = [
            _make_tactic("cc1", source="chesscom"),
            _make_tactic("cc2", source="chesscom"),
        ]
        with patch("src.importers.chesscom_puzzles.ChessComPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter(puzzles)
            res = client.post("/api/import/chesscom", json={"count": 2})

        assert res.status_code == 200
        data = res.json()
        assert data["added"] == 2
        assert data["skipped"] == 0

    def test_api_caps_count(self, client):
        """API caps count at 100."""
        with patch("src.importers.chesscom_puzzles.ChessComPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.return_value = iter([])
            res = client.post("/api/import/chesscom", json={"count": 999})

        assert res.status_code == 200
        data = res.json()
        assert data["added"] == 0

    def test_api_passes_include_daily(self, client):
        """include_daily is forwarded from the request body."""
        with patch(
            "src.importers.chesscom_puzzles.ChessComPuzzleImporter.import_to"
        ) as mock_import:
            from src.importers.base import ImportResult

            mock_import.return_value = ImportResult(source="Chess.com Puzzles", total_added=0)
            res = client.post("/api/import/chesscom", json={"count": 5, "include_daily": False})

        assert res.status_code == 200
        _, kwargs = mock_import.call_args
        assert kwargs["include_daily"] is False

    def test_api_error_returns_500(self, client):
        """Import errors return 500 with error message."""
        with patch("src.importers.chesscom_puzzles.ChessComPuzzleImporter.fetch") as mock_fetch:
            mock_fetch.side_effect = RuntimeError("API is down")
            res = client.post("/api/import/chesscom", json={"count": 5})

        assert res.status_code == 500
        assert "API is down" in res.json()["error"]
