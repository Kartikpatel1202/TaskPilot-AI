"""Prometheus metrics (one registry per app instance). Labels are low-cardinality only: never user
ids, task ids, URLs, email addresses or other personal data."""

from __future__ import annotations

from collections.abc import Callable

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from app.schemas.telemetry import TelemetryEvent

_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)


class Metrics:
    def __init__(self) -> None:
        r = self.registry = CollectorRegistry()
        self.tasks_total = Counter("taskpilot_tasks_total", "Tasks accepted", registry=r)
        self.tasks_failed_total = Counter("taskpilot_tasks_failed_total", "Tasks that ended FAILED", registry=r)
        self.task_duration = Histogram("taskpilot_task_duration_seconds", "Execution duration per task", buckets=_SECONDS, registry=r)
        self.planning_duration = Histogram("taskpilot_planning_duration_seconds", "Planning duration", buckets=_SECONDS, registry=r)
        self.llm_requests = Counter("taskpilot_llm_requests_total", "LLM requests", ["provider", "request_type"], registry=r)
        self.llm_errors = Counter("taskpilot_llm_errors_total", "LLM errors", ["provider", "code"], registry=r)
        self.llm_tokens = Counter("taskpilot_llm_tokens_total", "LLM tokens", ["provider", "direction"], registry=r)
        self.browser_sessions_active = Gauge("taskpilot_browser_sessions_active", "Open browser sessions", registry=r)
        self.browser_launch_failures = Counter("taskpilot_browser_launch_failures_total", "Browser launch failures", registry=r)
        self.browser_action_duration = Histogram("taskpilot_browser_action_duration_seconds", "Plan step duration", ["action_type"],
                                                 buckets=_SECONDS, registry=r)
        self.browser_action_failures = Counter("taskpilot_browser_action_failures_total", "Failed/blocked plan steps",
                                               ["action_type", "status"], registry=r)
        self.selector_recovery = Counter("taskpilot_selector_recovery_total", "Selector recovery attempts", registry=r)
        self.selector_recovery_success = Counter("taskpilot_selector_recovery_success_total", "Successful selector recoveries", registry=r)
        self.approval_pending = Gauge("taskpilot_approval_pending", "Pending approvals", registry=r)
        self.approval_expired = Counter("taskpilot_approval_expired_total", "Expired approvals", registry=r)
        self.workflow_partial = Counter("taskpilot_workflow_partial_success_total", "Partially successful workflows", registry=r)
        self.file_download_bytes = Counter("taskpilot_file_download_bytes", "Validated downloaded bytes", registry=r)
        self.file_download_failures = Counter("taskpilot_file_download_failures_total", "Blocked/failed downloads", ["status"], registry=r)
        self.ws_active = Gauge("taskpilot_websocket_connections_active", "Telemetry WebSocket connections", registry=r)
        self.ws_reconnects = Counter("taskpilot_websocket_reconnect_total", "WebSocket resubscriptions", registry=r)
        self.queue_depth = Gauge("taskpilot_queue_depth", "Queued jobs", ["queue"], registry=r)
        self.queue_wait = Histogram("taskpilot_queue_wait_duration_seconds", "Time from enqueue to start", ["queue"],
                                    buckets=_SECONDS, registry=r)
        self.http_requests = Counter("taskpilot_http_requests_total", "HTTP requests", ["method", "status_class"], registry=r)
        self.http_duration = Histogram("taskpilot_http_request_duration_seconds", "HTTP latency", ["method"], buckets=_SECONDS, registry=r)
        self.errors = Counter("taskpilot_errors_total", "Unhandled errors", ["component"], registry=r)
        self.persistence_failures = Counter("taskpilot_persistence_write_failures_total", "Failed best-effort writes", registry=r)

    def bind_gauge(self, gauge: Gauge, fn: Callable[[], float]) -> None:
        gauge.set_function(fn)

    def render(self) -> bytes:
        return generate_latest(self.registry)

    async def tap(self, event: TelemetryEvent) -> None:
        t = event.type.value
        d = event.data or {}
        if t == "task.accepted":
            self.tasks_total.inc()
        elif t == "task.failed":
            self.tasks_failed_total.inc()
        elif t == "approval.resolved" and d.get("status") == "EXPIRED":
            self.approval_expired.inc()
        elif t == "workflow.partial_success":
            self.workflow_partial.inc()
        elif t == "file.download_completed" and isinstance(d.get("bytes_received"), int):
            self.file_download_bytes.inc(d["bytes_received"])
        elif t in ("file.download_blocked", "file.download_failed"):
            self.file_download_failures.labels(status="BLOCKED" if t.endswith("blocked") else "FAILED").inc()
        elif t in ("task.step_failed", "task.step_blocked"):
            self.browser_action_failures.labels(action_type=_bounded(d.get("action_type")), status=str(d.get("status", ""))[:16]).inc()
        elif t == "task.step_completed" and isinstance(d.get("duration_ms"), int):
            self.browser_action_duration.labels(action_type="step").observe(d["duration_ms"] / 1000)
        elif t == "browser.session_error":
            self.browser_launch_failures.inc()


_KNOWN_ACTIONS = {"navigate", "click", "type", "extract", "request_approval", "stop", "commerce", "youtube_search", "youtube_play",
                  "gmail_create_draft", "calendar_create_event", "file_download"}


def _bounded(value: object) -> str:
    return value if isinstance(value, str) and value in _KNOWN_ACTIONS else "other"
