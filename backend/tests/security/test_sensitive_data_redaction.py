"""Sensitive data never reaches persistent stores, audit records, metrics labels or logs in clear text."""

from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.observability.audit import _safe_meta

from ..conftest import post_command, wait_for_task_state


def test_commands_are_stored_redacted(client: TestClient) -> None:
    sid = str(uuid4())
    task_id = post_command(client, "Pay with card 4111 1111 1111 1111 cvv 123 and password is hunter2", sid)["task_id"]
    wait_for_task_state(client, task_id)
    row = client.portal.call(client.app.state.container.persistence.tasks.get, UUID(task_id))  # type: ignore[union-attr, attr-defined]
    assert "4111" not in row.command and "hunter2" not in row.command and "123" not in row.command.split("cvv")[-1][:6]
    turns = client.portal.call(client.app.state.container.persistence.conversations.recent, UUID(sid))  # type: ignore[union-attr, attr-defined]
    assert all("4111 1111" not in t.content and "hunter2" not in t.content for t in turns)


def test_audit_metadata_keeps_only_safe_keys_and_url_hosts() -> None:
    meta = _safe_meta({"url": "https://mail.google.com/mail/u/0/#inbox?token=abc", "body": "secret email body", "password": "x",
                       "cookie": "sid=1", "status": "OK", "error_code": "X", "address": "Flat 12, Fixture Lane"})
    blob = json.dumps(meta)
    assert meta.get("url_host") == "mail.google.com"
    for leaked in ("secret email body", "token=abc", "sid=1", "Flat 12", "password"):
        assert leaked not in blob


def test_structured_logs_redact_secret_keys() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    record.authorization = "Bearer abc.def.ghi"
    record.api_key = "sk-live-0123456789abcdef"
    record.nested = {"refresh_token": "raw", "ok": 1}
    out = JsonFormatter().format(record)
    assert "abc.def" not in out and "sk-live" not in out and "raw" not in out and '"ok": 1' in out


def test_metrics_have_no_personal_labels(client: TestClient) -> None:
    sid = str(uuid4())
    post_command(client, "hello", sid)
    text = client.get("/api/v1/metrics").text
    assert "taskpilot_tasks_total" in text and sid not in text and "hello" not in text
