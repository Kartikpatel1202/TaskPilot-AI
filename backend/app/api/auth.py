"""Phase 6 authentication endpoints. Tokens travel in HttpOnly cookies (plus a readable CSRF cookie);
responses never contain passwords, token hashes or refresh tokens."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from app.auth.authentication import AuthError, IssuedSession
from app.auth.authorization import ACCESS_COOKIE, REFRESH_COOKIE
from app.auth.csrf import CSRF_COOKIE
from app.schemas.common import APIError

router = APIRouter(prefix="/auth", tags=["auth"])
ERRORS = {401: {"model": APIError}, 403: {"model": APIError}, 409: {"model": APIError}, 422: {"model": APIError}, 429: {"model": APIError}}
REFRESH_PATH = "/api/v1/auth"


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserView(BaseModel):
    user_id: str
    email: str
    role: str


class SessionView(BaseModel):
    user: UserView
    access_expires_in: int
    csrf_token: str


class AuthConfigView(BaseModel):
    auth_required: bool
    registration_enabled: bool
    mode: str


def _container(request: Request):  # noqa: ANN202
    return request.app.state.container


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_cookies(request: Request, response: Response, issued: IssuedSession) -> None:
    s = _container(request).settings
    common = {"secure": s.session_cookie_secure, "samesite": s.session_cookie_samesite}
    response.set_cookie(ACCESS_COOKIE, issued.access_token, max_age=issued.access_expires_in, httponly=True, path="/", **common)
    response.set_cookie(REFRESH_COOKIE, issued.refresh_token, max_age=s.refresh_token_ttl_days * 86400, httponly=True,
                        path=REFRESH_PATH, **common)
    response.set_cookie(CSRF_COOKIE, issued.csrf_token, max_age=s.refresh_token_ttl_days * 86400, httponly=False, path="/", **common)


def _clear_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")


def _view(issued: IssuedSession) -> dict[str, object]:
    u = issued.user
    return SessionView(user=UserView(user_id=str(u.id), email=u.email, role=u.role), access_expires_in=issued.access_expires_in,
                       csrf_token=issued.csrf_token).model_dump()


def _error(exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


@router.get("/config", response_model=AuthConfigView)
async def auth_config(request: Request) -> AuthConfigView:
    s = _container(request).settings
    return AuthConfigView(auth_required=s.auth_enforced, registration_enabled=s.registration_enabled, mode=s.auth_mode)


@router.post("/register", status_code=201, response_model=UserView, responses=ERRORS)
async def register(body: Credentials, request: Request) -> Response:
    c = _container(request)
    try:
        user = await c.auth.register(str(body.email), body.password)
    except AuthError as exc:
        return _error(exc)
    await c.audit.record("auth.register", outcome="SUCCESS", user_id=user.id, resource_type="user", resource_id=user.id)
    return JSONResponse(status_code=201, content=UserView(user_id=str(user.id), email=user.email, role=user.role).model_dump())


@router.post("/login", response_model=SessionView, responses=ERRORS)
async def login(body: Credentials, request: Request) -> Response:
    c = _container(request)
    try:
        issued = await c.auth.login(str(body.email), body.password, client_key=_client_key(request))
    except AuthError as exc:
        await c.audit.record("auth.login", outcome="DENIED", metadata={"code": exc.code})
        return _error(exc)
    await c.audit.record("auth.login", outcome="SUCCESS", user_id=issued.user.id)
    response = JSONResponse(content=_view(issued))
    _set_cookies(request, response, issued)
    return response


@router.post("/refresh", response_model=SessionView, responses=ERRORS)
async def refresh(request: Request) -> Response:
    c = _container(request)
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        return _error(AuthError("INVALID_REFRESH_TOKEN", "Please sign in again.", 401))
    try:
        issued = await c.auth.refresh(raw)
    except AuthError as exc:
        await c.audit.record("auth.refresh", outcome="DENIED", metadata={"code": exc.code})
        response = _error(exc)
        _clear_cookies(response)
        return response
    response = JSONResponse(content=_view(issued))
    _set_cookies(request, response, issued)
    return response


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    c = _container(request)
    await c.auth.logout(request.cookies.get(REFRESH_COOKIE))
    await c.audit.record("auth.logout", outcome="SUCCESS")
    response = Response(status_code=204)
    _clear_cookies(response)
    return response


@router.post("/logout-all", status_code=204, responses=ERRORS)
async def logout_all(request: Request) -> Response:
    c = _container(request)
    from app.auth.context import current_user

    user = current_user.get()
    if user is None:
        return _error(AuthError("AUTHENTICATION_REQUIRED", "Please sign in.", 401))
    await c.auth.logout_all(user.id)
    await c.audit.record("auth.logout_all", outcome="SUCCESS", user_id=user.id)
    response = Response(status_code=204)
    _clear_cookies(response)
    return response


@router.get("/me", response_model=UserView, responses=ERRORS)
async def me(request: Request) -> Response:
    from app.auth.context import current_user

    user = current_user.get()
    if user is None:
        if not _container(request).settings.auth_enforced:
            return JSONResponse(content=UserView(user_id="dev", email="developer@localhost", role="OWNER").model_dump())
        return _error(AuthError("AUTHENTICATION_REQUIRED", "Please sign in.", 401))
    return JSONResponse(content=UserView(user_id=str(user.id), email=user.email, role=user.role).model_dump())
