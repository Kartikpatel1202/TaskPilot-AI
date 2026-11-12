"""Provider-independent LLM boundary.

Nothing outside `app/agent/providers/` touches an SDK object. Providers return an
`LLMResult` whose `parsed_output` has already been validated against the
requested Pydantic schema, or raise a `ProviderError` with a safe message.
"""

from __future__ import annotations

import copy
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError


class LLMUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class LLMResult(BaseModel):
    parsed_output: dict[str, Any]
    provider: str
    model: str
    usage: LLMUsage | None = None
    latency_ms: int
    request_id: str | None = None


# ---------------------------------------------------------------------- errors


class ProviderError(Exception):
    """Base class. `message` is always safe to show to users (no SDK internals)."""

    code = "LLM_PROVIDER_ERROR"
    retryable = False
    default_message = "The AI planner could not complete the request."

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.message = message or self.default_message
        # `detail` is for server logs only; never sent to clients.
        self.detail = detail
        super().__init__(self.message)


class ProviderTimeoutError(ProviderError):
    code = "LLM_PROVIDER_TIMEOUT"
    retryable = True
    default_message = "The AI provider took too long to respond."


class ProviderRateLimitError(ProviderError):
    code = "LLM_RATE_LIMITED"
    retryable = True
    default_message = "The AI provider is rate limiting requests. Please try again shortly."


class ProviderUnavailableError(ProviderError):
    code = "LLM_PROVIDER_UNAVAILABLE"
    retryable = True
    default_message = "The AI provider is temporarily unavailable."


class ProviderAuthError(ProviderError):
    code = "LLM_AUTH_FAILED"
    default_message = "The AI provider rejected the configured credentials."


class ProviderConfigError(ProviderError):
    code = "LLM_CONFIG_ERROR"
    default_message = "The AI provider is not configured correctly."


class ProviderBadRequestError(ProviderError):
    code = "LLM_BAD_REQUEST"
    default_message = "The AI provider rejected the planning request."


class ProviderRefusalError(ProviderError):
    code = "LLM_REFUSED"
    default_message = "The AI provider declined to plan this request."


class InvalidModelOutputError(ProviderError):
    """Output was missing, truncated or failed schema validation. Retried by the orchestrator."""

    code = "LLM_INVALID_OUTPUT"
    retryable = True
    default_message = "The AI provider returned an invalid plan."


# ---------------------------------------------------------------------- protocol


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def generate_structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: type[BaseModel],
        max_tokens: int,
        timeout: float,
    ) -> LLMResult: ...

    async def health_check(self) -> bool: ...

    async def aclose(self) -> None: ...


def validate_output(raw: Any, schema: type[BaseModel]) -> dict[str, Any]:
    """Validate a decoded JSON object against the schema; return its JSON-mode dump."""
    if not isinstance(raw, dict):
        raise InvalidModelOutputError(detail="Structured output was not a JSON object.")
    try:
        return schema.model_validate(raw).model_dump(mode="json")
    except ValidationError as exc:
        raise InvalidModelOutputError(detail=f"Schema validation failed: {exc.error_count()} error(s)") from exc


# ---------------------------------------------------------------------- JSON schema


_DROP_KEYS = {
    "default",
    "title",
    "discriminator",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "format",
    "pattern",
    "examples",
}


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(n) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return {"$ref": node["$ref"]}  # sibling keywords next to $ref are not portable
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROP_KEYS:
            continue
        if key == "const":
            out["enum"] = [value]
            continue
        if key in ("properties", "$defs"):
            out[key] = {k: _strictify(v) for k, v in value.items()}
        else:
            out[key] = _strictify(value)
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"].keys())
        out["additionalProperties"] = False
    if "oneOf" in out:  # discriminated unions -> anyOf (widely supported)
        out["anyOf"] = out.pop("oneOf")
    return out


def strict_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """A portable JSON schema for structured-output APIs.

    Every property is required (optional ones are nullable), no extra properties,
    and value constraints are removed — Pydantic re-validates them on receipt.
    """
    return _strictify(copy.deepcopy(schema.model_json_schema()))
