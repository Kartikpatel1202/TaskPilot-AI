# LLM providers

| `AGENT_PROVIDER` | Implementation | Needs a key | Default model |
| --- | --- | --- | --- |
| `mock` (default) | `MockLLMProvider`: deterministic, offline | No | `taskpilot-mock-v1` |
| `openai` | `OpenAIProvider`: official `openai` SDK, JSON-schema structured outputs (`strict: true`) | `OPENAI_API_KEY` | `OPENAI_MODEL=gpt-4o` |
| `anthropic` | `AnthropicProvider`: official `anthropic` SDK, structured outputs (`output_config.format`) | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL=claude-opus-5-5` |

`AGENT_MODEL` is an optional override. Leave it empty to use the provider-specific model setting. Model names are configuration only, and business logic never depends on them.

## Configuration (backend `.env`)
```env
AGENT_PROVIDER=mock
AGENT_MODEL=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_MODEL=gpt-4o
ANTHROPIC_MODEL=claude-opus-5-5
# ANTHROPIC_EFFORT=medium            # low | medium | high | xhigh | max
# ANTHROPIC_SERVER_FALLBACKS=true    # server-side refusal fallback (Claude API beta)
AGENT_REQUEST_TIMEOUT_SECONDS=40
AGENT_MAX_OUTPUT_TOKENS=16000
AGENT_MAX_RETRIES=2
```
Startup validation (pydantic-settings) fails with a clear message in these cases:
- the selected provider's API key is missing or blank;
- `AGENT_MODEL` names the mock model while a real provider is selected;
- `APP_ENV=production` with the mock provider, unless `AGENT_ALLOW_MOCK_IN_PRODUCTION=true`;
- `AGENT_BROWSER_EXECUTION_ENABLED=true` (not available until Phase 3).

API keys are stored as `SecretStr`, so they never appear in reprs, dumps or logs. They are never sent to the frontend. Do not put them in `NEXT_PUBLIC_*` variables.

## Mock provider
- Reads the same JSON task payload a real model receives and returns schema-valid `IntentClassification` and `PlanDraft` objects.
- Scenario coverage:
  - Blinkit/Zepto groceries, including brands, quantities and "ek dozen".
  - Amazon/Flipkart search and shopping, with payment behind a CRITICAL approval gate.
  - YouTube search and play.
  - Gmail draft and send. A missing recipient address triggers a clarification.
  - Calendar. A missing date or time triggers a clarification.
  - Downloads, forms and data extraction.
  - Follow-ups: "also add…", "one more", "change quantity to…".
  - General chat, unsupported requests, and dangerous or injection attempts.
- Every mock plan is labelled `provider: "mock"` and `is_mock: true`, and carries an explicit assumption line. The UI shows **MOCK PLANNER** / **Mock plan** badges.
- `AGENT_MOCK_LATENCY_MS` (default 350) adds a small per-call delay so planning stages are visible in the UI. Tests set it to 0.
- The mock is **never** a fallback. A failing real provider fails the task with an explicit error.

## OpenAI
- `AsyncOpenAI(max_retries=0)` is built once per app. Retries are owned by `StructuredLLMRunner`.
- Requests use `chat.completions.create(response_format={"type": "json_schema", "json_schema": {"strict": true, ...}}, max_completion_tokens=..., timeout=...)`.
- Refusals, `finish_reason == "length"`, non-JSON content and schema violations are rejected.

## Anthropic
- `AsyncAnthropic(max_retries=0)` is built once.
- Requests use `messages.create(..., output_config={"effort": ..., "format": {"type": "json_schema", "schema": ...}})`.
  - When `ANTHROPIC_SERVER_FALLBACKS=true` (the default), the call goes through `beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", ...)`. A policy decline is then re-run on a fallback model inside the same call. Set it to `false` to turn this off.
- Forced `tool_choice` is deliberately **not** used, because current Claude models reject forced tool use.
- Thinking blocks are ignored, and only the text block holding the JSON is read.
- `stop_reason` of `refusal` or `max_tokens` is treated as an error.

## Error handling
| Provider error | Code | Retried |
| --- | --- | --- |
| Timeout (SDK or `asyncio`) | `LLM_PROVIDER_TIMEOUT` | yes |
| 429 | `LLM_RATE_LIMITED` | yes |
| 5xx, 529, connection errors | `LLM_PROVIDER_UNAVAILABLE` | yes |
| Invalid, truncated or non-schema output | `LLM_INVALID_OUTPUT` | yes |
| 401 / 403 | `LLM_AUTH_FAILED` | no |
| 404 (model) | `LLM_CONFIG_ERROR` | no |
| 400 | `LLM_BAD_REQUEST` | no |
| Refusal | `LLM_REFUSED` | no |

- Retries use exponential backoff (`AGENT_RETRY_BASE_DELAY_SECONDS × 2ⁿ`), up to `AGENT_MAX_RETRIES`.
- A plan that fails validation is regenerated with the validation errors fed back to the model, up to the same limit. It then fails with `PLAN_VALIDATION_FAILED`.
- Only the safe `message` of an error reaches clients. The SDK detail stays in server logs.

## Health
`GET /api/v1/agent/status` reports provider, model, mock flag and enabled flags without calling the LLM. Add `?probe=true` to run a cheap model-metadata lookup (`models.retrieve`) with a 5-second timeout. This makes no generation call and spends no tokens.

## Cost and token usage
- Every planned command costs up to two LLM calls: one classification and one plan. Clarification and unsupported outcomes skip the second call.
- Retries multiply that cost. Keep `AGENT_MAX_RETRIES` low in production.
- Token usage is logged per call (`llm.call_ok` with `input_tokens` and `output_tokens`) and kept server-side on the planning record. It is never part of the user-visible plan.
- Reasoning models spend output tokens on thinking before answering. Values of `AGENT_MAX_OUTPUT_TOKENS` far below about 16,000 risk truncated, invalid plans.

**Verification status:** both real providers are unit-tested against mocked SDK clients, covering request shape, success parsing and error translation. They were **not** exercised against live APIs during Phase 2, because no API key was available.
