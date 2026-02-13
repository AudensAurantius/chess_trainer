"""Tests for password hashing."""

from src.auth.passwords import hash_password, verify_password


class TestHashPassword:
    def test_round_trip(self):
        pw = "correcthorsebatterystaple"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)

    def test_wrong_password(self):
        hashed = hash_password("password123")
        assert not verify_password("wrong", hashed)

    def test_different_salts(self):
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salts
        assert verify_password("same", h1)
        assert verify_password("same", h2)

    def test_format(self):
        hashed = hash_password("test")
        parts = hashed.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert parts[1] == "600000"

    def test_unicode(self):
        pw = "p\u00e4ssw\u00f6rd\u2603"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)
        assert not verify_password("password", hashed)

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed)
        assert not verify_password("x", hashed)

    def test_tampered_hash_returns_false(self):
        hashed = hash_password("test")
        tampered = hashed[:-2] + "ff"
        assert not verify_password("test", tampered)

    def test_malformed_hash_returns_false(self):
        assert not verify_password("test", "not-a-hash")
        assert not verify_password("test", "a$b$c")
        assert not verify_password("test", "pbkdf2_sha256$bad$aa$bb")
        assert not verify_password("test", "wrong_algo$600000$aa$bb")
