"""Phase 6 security tests: an authentication-enforced app (in-memory SQLite, rate limits on) and helpers
to act as different users with their own cookies + CSRF token."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from ..conftest import make_settings

SECRET = "security-test-secret-0123456789-abcdefghijklmnop"
PASSWORD = "Correct-Horse-42-battery"


def auth_settings(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "auth_required": True, "allow_dev_auth_bypass": False, "app_secret_key": SECRET, "registration_enabled": True,
        "rate_limit_enabled": True, "api_rate_limit_per_minute": 10_000, "planning_requests_per_minute": 1_000,
        "auth_login_attempts_per_minute": 5, "cors_origins": "http://localhost:3000",
    }
    base.update(overrides)
    return make_settings(**base)


@dataclass
class Actor:
    email: str
    cookies: dict[str, str] = field(default_factory=dict)
    csrf: str = ""
    user_id: str = ""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}


class Users:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def register(self, email: str, password: str = PASSWORD) -> Any:
        return self.client.post("/api/v1/auth/register", json={"email": email, "password": password})

    def login(self, email: str, password: str = PASSWORD) -> Actor:
        self.client.cookies.clear()
        r = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        actor = Actor(email=email, cookies=dict(self.client.cookies), csrf=r.json()["csrf_token"], user_id=r.json()["user"]["user_id"])
        self.client.cookies.clear()
        return actor

    def new(self, email: str) -> Actor:
        assert self.register(email).status_code == 201
        return self.login(email)

    def as_(self, actor: Actor) -> TestClient:
        self.client.cookies.clear()
        for k, v in actor.cookies.items():
            self.client.cookies.set(k, v, path="/api/v1/auth" if k == "tp_refresh" else "/")
        return self.client

    def get(self, actor: Actor, url: str, **kw: Any) -> Any:
        return self.as_(actor).get(url, **kw)

    def post(self, actor: Actor, url: str, json: Any = None, **kw: Any) -> Any:
        return self.as_(actor).post(url, json=json, headers={**actor.headers(), **kw.pop("headers", {})}, **kw)

    def delete(self, actor: Actor, url: str, json: Any = None) -> Any:
        return self.as_(actor).request("DELETE", url, json=json, headers=actor.headers())


@pytest.fixture
def secure_app() -> Iterator[TestClient]:
    with TestClient(create_app(auth_settings())) as client:
        yield client


@pytest.fixture
def users(secure_app: TestClient) -> Users:
    return Users(secure_app)


@pytest.fixture
def secure_factory() -> Iterator[Callable[..., TestClient]]:
    opened: list[TestClient] = []

    def factory(**overrides: Any) -> TestClient:
        c = TestClient(create_app(auth_settings(**overrides)))
        c.__enter__()
        opened.append(c)
        return c

    yield factory
    for c in opened:
        c.__exit__(None, None, None)
