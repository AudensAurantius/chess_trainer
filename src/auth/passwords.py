"""Password hashing with PBKDF2-SHA256."""

from __future__ import annotations

import hashlib
import hmac
import os

_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256.

    Returns:
        Encoded string: ``pbkdf2_sha256$600000${salt_hex}${hash_hex}``
    """
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored hash.

    Returns:
        ``True`` if the password matches.
    """
    try:
        algo, iterations_str, salt_hex, hash_hex = password_hash.split("$")
    except ValueError:
        return False
    if algo != _ALGORITHM:
        return False
    try:
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)
