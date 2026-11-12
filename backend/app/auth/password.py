"""Argon2id password hashing (argon2-cffi). Plaintext passwords are never stored or logged."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)  # argon2id by default
# A real hash used to equalise timing when the account does not exist (no user enumeration by timing).
_DUMMY = _hasher.hash("taskpilot-dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, min_length: int) -> list[str]:
    problems = []
    if len(password) < min_length:
        problems.append(f"at least {min_length} characters")
    if len(password) > 256:
        problems.append("at most 256 characters")
    if password.lower() == password or password.upper() == password:
        problems.append("both upper- and lower-case letters")
    if not any(c.isdigit() for c in password):
        problems.append("at least one digit")
    return problems
