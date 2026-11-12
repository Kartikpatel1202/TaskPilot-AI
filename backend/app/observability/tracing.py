"""OpenTelemetry-compatible tracing via the OTel API (a no-op unless an SDK/exporter is configured by
the deployment). Span attributes are low-cardinality and redacted; correlation ids flow through
logs, audit records and spans."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.auth.context import correlation_id

try:  # the API package is tiny and optional; tracing degrades to a no-op without it
    from opentelemetry import trace as _trace

    _tracer = _trace.get_tracer("taskpilot")
except Exception:  # noqa: BLE001
    _tracer = None

_ALLOWED_ATTRS = {"component", "action_type", "domain", "provider", "model", "status", "intent", "step_order", "http.method", "http.route"}


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[None]:
    """Trace a unit of work (planning, LLM call, validation, dispatch, browser step, verification)."""
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as s:
        cid = correlation_id.get()
        if cid:
            s.set_attribute("taskpilot.correlation_id", cid)
        for key, value in attrs.items():
            if key in _ALLOWED_ATTRS and isinstance(value, (str, int, float, bool)):
                s.set_attribute(f"taskpilot.{key}", value)
        yield
