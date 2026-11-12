"""Role policies. Resource ownership is enforced separately for every role (OWNER is not a super-user
for other people's tasks, files or approvals — only for operational endpoints such as audit export)."""

from __future__ import annotations

from app.database.models import UserRole

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Paths a READ_ONLY user may still call with a mutating method.
READ_ONLY_ALLOWED = ("/api/v1/auth/logout", "/api/v1/auth/logout-all", "/api/v1/auth/refresh")


def may_mutate(role: str, path: str) -> bool:
    return role != UserRole.READ_ONLY.value or path.startswith(READ_ONLY_ALLOWED)


def is_admin(role: str) -> bool:
    return role == UserRole.OWNER.value
