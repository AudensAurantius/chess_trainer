"""Tests for Chess.com data models."""

from src.chesscom.models import ChessComGame, ChessComPlayer, ChessComPuzzle


class TestChessComPlayer:
    def test_from_dict_full(self):
        data = {"username": "hikaru", "rating": 3200, "result": "win"}
        player = ChessComPlayer.from_dict(data)
        assert player.username == "hikaru"
        assert player.rating == 3200
        assert player.result == "win"

    def test_from_dict_missing_fields(self):
        player = ChessComPlayer.from_dict({})
        assert player.username == ""
        assert player.rating == 0
        assert player.result == ""

    def test_from_dict_partial(self):
        player = ChessComPlayer.from_dict({"username": "test"})
        assert player.username == "test"
        assert player.rating == 0


class TestChessComGame:
    SAMPLE_GAME = {
        "url": "https://www.chess.com/game/live/12345678",
        "pgn": '[White "alice"] [Black "bob"]\n1. e4 e5 *',
        "time_control": "600",
        "time_class": "rapid",
        "rated": True,
        "rules": "chess",
        "white": {"username": "alice", "rating": 1500, "result": "win"},
        "black": {"username": "bob", "rating": 1400, "result": "checkmated"},
        "end_time": 1700000000,
    }

    def test_from_dict_full(self):
        game = ChessComGame.from_dict(self.SAMPLE_GAME)
        assert game.url == "https://www.chess.com/game/live/12345678"
        assert game.time_control == "600"
        assert game.time_class == "rapid"
        assert game.rated is True
        assert game.rules == "chess"
        assert game.white.username == "alice"
        assert game.black.username == "bob"
        assert game.end_time == 1700000000

    def test_game_id_from_url(self):
        game = ChessComGame.from_dict(self.SAMPLE_GAME)
        assert game.game_id == "12345678"

    def test_game_id_from_url_trailing_slash(self):
        data = dict(self.SAMPLE_GAME, url="https://www.chess.com/game/live/99999/")
        game = ChessComGame.from_dict(data)
        assert game.game_id == "99999"

    def test_game_id_from_daily_url(self):
        data = dict(self.SAMPLE_GAME, url="https://www.chess.com/game/daily/55555")
        game = ChessComGame.from_dict(data)
        assert game.game_id == "55555"

    def test_from_dict_defaults(self):
        game = ChessComGame.from_dict({})
        assert game.url == ""
        assert game.pgn == ""
        assert game.time_class == ""
        assert game.rated is False
        assert game.rules == "chess"
        assert game.end_time == 0

    def test_pgn_preserved(self):
        game = ChessComGame.from_dict(self.SAMPLE_GAME)
        assert "1. e4 e5" in game.pgn


class TestChessComPuzzle:
    SAMPLE_PUZZLE = {
        "title": "Daily Puzzle: Feb 9",
        "url": "https://www.chess.com/puzzles/problem/12345",
        "publish_time": 1700000000,
        "fen": "r1bqkbnr/pppppppp/2n5/4N3/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 1",
        "pgn": "1... Nxe5",
        "image": "https://images.chess.com/puzzle/12345.png",
    }

    def test_from_dict_full(self):
        puzzle = ChessComPuzzle.from_dict(self.SAMPLE_PUZZLE)
        assert puzzle.title == "Daily Puzzle: Feb 9"
        assert puzzle.url == "https://www.chess.com/puzzles/problem/12345"
        assert puzzle.publish_time == 1700000000
        assert "r1bqkbnr" in puzzle.fen
        assert puzzle.pgn == "1... Nxe5"
        assert "chess.com" in puzzle.image

    def test_from_dict_defaults(self):
        puzzle = ChessComPuzzle.from_dict({})
        assert puzzle.title == ""
        assert puzzle.url == ""
        assert puzzle.publish_time == 0
        assert puzzle.fen == ""
        assert puzzle.pgn == ""
        assert puzzle.image == ""

    def test_from_dict_partial(self):
        puzzle = ChessComPuzzle.from_dict({"fen": "8/8/8/8/8/8/8/8 w - - 0 1"})
        assert puzzle.fen == "8/8/8/8/8/8/8/8 w - - 0 1"
        assert puzzle.title == ""
