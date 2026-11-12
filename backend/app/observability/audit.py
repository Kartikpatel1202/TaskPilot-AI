"""Audit trail service. Explicit `record()` calls plus a telemetry tap that turns security-relevant
events (task created, execution started, approvals, navigation, blocked actions, purchases, calendar
creation, downloads, sessions) into append-only, hash-chained audit records.

Metadata is redacted and bounded: no secrets, cookies, email bodies, full addresses or file paths.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.auth.context import correlation_id, current_user_id
from app.core.logging import get_logger, redact
from app.database.models import AuditEventRecord
from app.schemas.common import utc_now
from app.schemas.telemetry import TelemetryEvent

logger = get_logger("audit")
_SAFE_KEYS = {"fields", "code", "error_code", "status", "decision", "domain", "action_type", "platform", "capability", "total_steps",
              "step_count", "intent", "final_total", "payment_method", "url_host", "outcome", "reason_code", "filename", "file_id",
              "approval_id", "state", "new_state", "previous_state", "risk_level", "recovery", "size_bytes", "sha256"}

# telemetry type -> (audit event type, outcome or None = derive from data["status"])
_TAP: dict[str, tuple[str, str | None]] = {
    "task.accepted": ("task.created", "SUCCESS"),
    "task.plan_ready": ("plan.created", None),
    "task.execution_started": ("execution.started", "SUCCESS"),
    "task.execution_completed": ("execution.completed", "SUCCESS"),
    "task.execution_failed": ("execution.failed", "FAILURE"),
    "task.execution_cancelled": ("execution.cancelled", "CANCELLED"),
    "task.step_blocked": ("action.blocked", "BLOCKED"),
    "approval.required": ("approval.requested", "PENDING"),
    "approval.resolved": ("approval.resolved", None),
    "browser.session_started": ("browser.session_created", "SUCCESS"),
    "browser.session_closed": ("browser.session_closed", "SUCCESS"),
    "browser.navigation_completed": ("browser.navigation", "SUCCESS"),
    "browser.navigation_blocked": ("browser.navigation", "BLOCKED"),
    "commerce.checkout_review_ready": ("purchase.review", "SUCCESS"),
    "commerce.order_submission_started": ("purchase.submission", "STARTED"),
    "commerce.order_confirmed": ("purchase.submission", "SUCCESS"),
    "commerce.order_status_unknown": ("purchase.submission", "UNKNOWN"),
    "commerce.purchase_rejected": ("purchase.submission", "REJECTED"),
    "calendar.event_created": ("calendar.event_created", "SUCCESS"),
    "calendar.event_creation_failed": ("calendar.event_created", "FAILURE"),
    "gmail.draft_verified": ("gmail.draft_saved", "SUCCESS"),
    "gmail.send_blocked": ("gmail.send_blocked", "BLOCKED"),
    "file.download_completed": ("file.download", "SUCCESS"),
    "file.download_blocked": ("file.download", "BLOCKED"),
}


def _safe_meta(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in _SAFE_KEYS and isinstance(value, (str, int, float, bool)) or (key in _SAFE_KEYS and value is None):
            out[key] = value if not isinstance(value, str) else value[:200]
    if "url" in data and isinstance(data["url"], str):  # host only — never paths or query strings
        from urllib.parse import urlsplit

        out["url_host"] = (urlsplit(data["url"]).hostname or "")[:253]
    return redact(out)


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


class AuditService:
    def __init__(self, persistence: Any, ownership: Any | None = None) -> None:
        self._p = persistence
        self._ownership = ownership
        self.failures = 0

    async def record(self, event_type: str, *, outcome: str, user_id: UUID | None = None, task_id: UUID | None = None,
                     session_id: UUID | None = None, resource_type: str | None = None, resource_id: UUID | None = None,
                     metadata: dict[str, Any] | None = None) -> None:
        if self._p is None:
            return
        uid = user_id or current_user_id()
        if uid is None and session_id is not None and self._ownership is not None:
            uid = self._ownership.owner_cached(session_id)
        cid = _uuid(correlation_id.get()) or uuid4()
        record = AuditEventRecord(event_id=uuid4(), user_id=uid, task_id=task_id, session_id=session_id, event_type=event_type[:64],
                                  outcome=outcome[:24], resource_type=resource_type, resource_id=resource_id, occurred_at=utc_now(),
                                  correlation_id=cid, metadata_json=redact(metadata or {}))
        try:
            await self._p.audit.append(record)
        except Exception:  # noqa: BLE001 - audit failures are surfaced via health/metrics, never crash the action
            self.failures += 1
            logger.exception("audit.append_failed", extra={"event_type": event_type})

    async def tap(self, event: TelemetryEvent) -> None:
        mapped = _TAP.get(event.type.value)
        if mapped is None:
            return
        event_type, outcome = mapped
        data = event.data or {}
        if outcome is None:
            outcome = str(data.get("status") or "UNKNOWN").upper()
        if event.type.value == "task.step_blocked" and data.get("error_code") == "SENSITIVE_ACTION_BLOCKED":
            event_type = "action.sensitive_blocked"
        resource_type, resource_id = None, None
        if event.type.value.startswith("approval."):
            resource_type, resource_id = "approval", _uuid(data.get("approval_id"))
        elif event.type.value.startswith("file."):
            resource_type, resource_id = "file", _uuid(data.get("file_id"))
        await self.record(event_type, outcome=outcome, task_id=event.task_id, session_id=event.session_id,
                          resource_type=resource_type, resource_id=resource_id, metadata=_safe_meta(data))
