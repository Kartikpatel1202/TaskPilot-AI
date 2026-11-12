"""Local account authentication: register (when enabled), login, refresh rotation with replay
detection, logout, logout-all, account disablement and throttled logins."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from app.auth.context import AuthUser
from app.auth.password import hash_password, needs_rehash, password_problems, verify_password
from app.auth.tokens import AccessClaims, TokenError, decode_access, hash_refresh, issue_access, new_csrf_token, new_refresh_token
from app.core.logging import get_logger
from app.database.dependencies import Persistence
from app.database.models import UserRole, UserStatus
from app.schemas.common import utc_now

logger = get_logger("auth")


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 401) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class IssuedSession:
    user: AuthUser
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_in: int


class AuthService:
    def __init__(self, persistence: Persistence, *, secret: str, access_ttl_minutes: int, refresh_ttl_days: int,
                 registration_enabled: bool, password_min_length: int, rate_limiter: object | None = None,
                 login_attempts_per_minute: int = 5) -> None:
        self._p = persistence
        self._secret = secret
        self._access_ttl = timedelta(minutes=access_ttl_minutes)
        self._refresh_ttl = timedelta(days=refresh_ttl_days)
        self.registration_enabled = registration_enabled
        self._min_len = password_min_length
        self._limiter = rate_limiter
        self._login_limit = login_attempts_per_minute

    # ---------------------------------------------------------------- accounts

    async def register(self, email: str, password: str) -> AuthUser:
        if not self.registration_enabled:
            raise AuthError("REGISTRATION_DISABLED", "Registration is disabled on this server.", 403)
        problems = password_problems(password, self._min_len)
        if problems:
            raise AuthError("WEAK_PASSWORD", "Password needs " + ", ".join(problems) + ".", 422)
        if await self._p.users.by_email(email):
            raise AuthError("EMAIL_TAKEN", "An account with this email already exists.", 409)
        # The very first account becomes the deployment OWNER; later ones are MEMBERs.
        role = UserRole.OWNER.value if await self._p.users.count() == 0 else UserRole.MEMBER.value
        user = await self._p.users.add(email=email, password_hash=hash_password(password), role=role)
        return AuthUser(user.id, user.email, user.role)

    async def ensure_bootstrap_owner(self, email: str, password: str) -> None:
        if not email or not password or await self._p.users.count() > 0:
            return
        problems = password_problems(password, self._min_len)
        if problems:
            raise AuthError("WEAK_PASSWORD", "BOOTSTRAP_OWNER_PASSWORD needs " + ", ".join(problems) + ".", 500)
        await self._p.users.add(email=email, password_hash=hash_password(password), role=UserRole.OWNER.value)
        logger.info("auth.bootstrap_owner_created")

    async def login(self, email: str, password: str, *, client_key: str) -> IssuedSession:
        key = f"login:{email.strip().lower()}:{client_key}"
        if self._limiter is not None and not await self._limiter.hit(key, self._login_limit, 60):  # type: ignore[attr-defined]
            raise AuthError("TOO_MANY_LOGIN_ATTEMPTS", "Too many login attempts. Try again in a minute.", 429)
        user = await self._p.users.by_email(email)
        ok = verify_password(password, user.password_hash if user else None)
        if not user or not ok:
            raise AuthError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
        if user.status != UserStatus.ACTIVE.value:
            raise AuthError("ACCOUNT_DISABLED", "This account is disabled.", 403)
        if user.password_hash and needs_rehash(user.password_hash):
            logger.info("auth.password_rehash_needed")
        await self._p.users.touch_login(user.id)
        return await self._issue(AuthUser(user.id, user.email, user.role), user.token_version, family=uuid4())

    async def refresh(self, raw_refresh: str) -> IssuedSession:
        row = await self._p.users.refresh_by_hash(hash_refresh(raw_refresh))
        if row is None:
            raise AuthError("INVALID_REFRESH_TOKEN", "Please sign in again.", 401)
        if row.used_at is not None or row.revoked_at is not None:
            # Replay of a rotated (or revoked) token: assume theft and revoke the whole family.
            await self._p.users.revoke_family(row.family_id)
            logger.warning("auth.refresh_replay_detected", extra={"family": str(row.family_id)[:8]})
            raise AuthError("REFRESH_TOKEN_REUSED", "This session was revoked. Please sign in again.", 401)
        if row.expires_at <= utc_now():
            raise AuthError("REFRESH_TOKEN_EXPIRED", "Your session expired. Please sign in again.", 401)
        if not await self._p.users.mark_refresh_used(row.id):
            await self._p.users.revoke_family(row.family_id)
            raise AuthError("REFRESH_TOKEN_REUSED", "This session was revoked. Please sign in again.", 401)
        user = await self._p.users.get(row.user_id)
        if user is None or user.status != UserStatus.ACTIVE.value:
            raise AuthError("ACCOUNT_DISABLED", "This account is disabled.", 403)
        return await self._issue(AuthUser(user.id, user.email, user.role), user.token_version, family=row.family_id)

    async def logout(self, raw_refresh: str | None) -> None:
        if not raw_refresh:
            return
        row = await self._p.users.refresh_by_hash(hash_refresh(raw_refresh))
        if row is not None:
            await self._p.users.revoke_family(row.family_id)

    async def logout_all(self, user_id: UUID) -> None:
        await self._p.users.revoke_all(user_id)
        await self._p.users.bump_token_version(user_id)  # invalidates every outstanding access token

    async def disable(self, user_id: UUID) -> None:
        await self._p.users.set_status(user_id, UserStatus.DISABLED.value)
        await self._p.users.revoke_all(user_id)

    # ---------------------------------------------------------------- tokens

    async def authenticate_access(self, token: str) -> tuple[AuthUser, AccessClaims]:
        try:
            claims = decode_access(self._secret, token)
        except TokenError as exc:
            raise AuthError("TOKEN_EXPIRED" if str(exc) == "expired" else "INVALID_TOKEN", "Please sign in again.", 401) from exc
        user = await self._p.users.get(claims.user_id)
        if user is None or user.status != UserStatus.ACTIVE.value:
            raise AuthError("ACCOUNT_DISABLED", "This account is disabled.", 401)
        if user.token_version != claims.version:
            raise AuthError("TOKEN_REVOKED", "Please sign in again.", 401)
        return AuthUser(user.id, user.email, user.role), claims

    async def _issue(self, user: AuthUser, version: int, *, family: UUID) -> IssuedSession:
        csrf = new_csrf_token()
        access, _ = issue_access(self._secret, user_id=user.id, role=user.role, version=version, csrf_token=csrf, ttl=self._access_ttl)
        raw, digest = new_refresh_token()
        await self._p.users.add_refresh(user_id=user.id, token_hash=digest, family_id=family, expires_at=utc_now() + self._refresh_ttl)
        return IssuedSession(user, access, raw, csrf, int(self._access_ttl.total_seconds()))
