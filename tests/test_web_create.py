"""Tests for web exercise creation endpoint and page."""

import pytest
from fastapi.testclient import TestClient

from src.config import AppConfig
from src.web import create_app

AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
ENDGAME_FEN = "8/8/8/8/8/4K3/4P3/4k3 w - - 0 1"


@pytest.fixture
def app(tmp_path):
    config = AppConfig()
    config.database.path = str(tmp_path / "test.db")
    return create_app(config)


@pytest.fixture
def client(app):
    return TestClient(app)


class TestCreatePage:
    def test_create_page_renders(self, client):
        resp = client.get("/create")
        assert resp.status_code == 200
        assert "Create Custom Exercise" in resp.text
        assert "create-fen" in resp.text

    def test_create_nav_link_present(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'href="/create"' in resp.text


class TestCreateApi:
    def test_create_tactic(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "tactic",
                "fen": AFTER_E4_FEN,
                "moves": ["e7e5", "d2d4"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["type"] == "tactic"
        assert data["id"].startswith("custom:")
        assert "challenge" in data

    def test_create_endgame(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "endgame",
                "fen": ENDGAME_FEN,
                "moves": ["e3d4"],
                "technique": "King march",
                "target_outcome": "win",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["type"] == "endgame"

    def test_create_positional(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "positional",
                "fen": AFTER_E4_FEN,
                "moves": ["e7e5"],
                "concept": "Center control",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["type"] == "positional"

    def test_create_opening(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "opening",
                "fen": START_FEN,
                "moves": ["e2e4", "e7e5", "g1f3"],
                "opening_name": "Italian",
                "eco": "C50",
                "move_index": 0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["type"] == "opening"

    def test_create_with_slug(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "tactic",
                "fen": AFTER_E4_FEN,
                "moves": ["e7e5"],
                "id": "web-test-01",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "custom:web-test-01"

    def test_create_with_tags_and_notes(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "tactic",
                "fen": AFTER_E4_FEN,
                "moves": ["e7e5"],
                "tags": "pin,middlegame",
                "notes": "Remember this",
                "difficulty": 1500,
            },
        )
        assert resp.status_code == 200

    def test_invalid_fen_returns_400(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "tactic",
                "fen": "garbage",
                "moves": ["e2e4"],
            },
        )
        assert resp.status_code == 400
        assert "Invalid FEN" in resp.json()["error"]

    def test_illegal_move_returns_400(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "tactic",
                "fen": AFTER_E4_FEN,
                "moves": ["e2e4"],  # White can't move
            },
        )
        assert resp.status_code == 400
        assert "Illegal" in resp.json()["error"]

    def test_invalid_type_returns_400(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "puzzle",
                "fen": START_FEN,
                "moves": ["e2e4"],
            },
        )
        assert resp.status_code == 400
        assert "Invalid exercise type" in resp.json()["error"]

    def test_duplicate_id_returns_409(self, client):
        body = {
            "type": "tactic",
            "fen": AFTER_E4_FEN,
            "moves": ["e7e5"],
            "id": "dup-web",
        }
        client.post("/api/exercise/create", json=body)
        resp = client.post("/api/exercise/create", json=body)
        assert resp.status_code == 409
        assert "already exists" in resp.json()["error"]

    def test_notes_too_long_returns_400(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "tactic",
                "fen": AFTER_E4_FEN,
                "moves": ["e7e5"],
                "notes": "x" * 5001,
            },
        )
        assert resp.status_code == 400
        assert "5000" in resp.json()["error"]

    def test_no_moves_returns_400(self, client):
        resp = client.post(
            "/api/exercise/create",
            json={
                "type": "tactic",
                "fen": AFTER_E4_FEN,
            },
        )
        assert resp.status_code == 400
