# Multi-domain workflows

A single command can chain domains, e.g.:

- "Find a Python tutorial on YouTube and email the link to friend@example.com"
- "Download the report from https://… and draft an email to hr@example.com about it"
- "Schedule a meeting with Rahul tomorrow at 3pm for 30 minutes and email the agenda to a@example.com"

## Classification

The classifier returns `MULTI_DOMAIN_WORKFLOW` only when one command asks for work in **two or more**
integration domains, with `entities.workflow` listing the steps in the user's order
(`WorkflowStepEntity`: intent, target_website, search_query, recipient, subject, message_topic,
datetime_text, url, text, requested_actions, include_previous_output). The offline mock splits clauses on
"and/then/aur/phir/;" and assigns each clause a domain (download > email > calendar > YouTube). Existing
single-domain intents (MEDIA_SEARCH, EMAIL_DRAFT, …) are unchanged. With integrations disabled,
multi-domain requests are rejected politely.

## Typed result hand-off (`workflow/result_handoff.py`)

Only small, observed, typed values move between steps — never pages, HTML, cookies, file paths or bodies:

| Output | Produced by | Data |
| --- | --- | --- |
| `youtube.video_reference` | `youtube_search` with `select`, `youtube_play` | title, video_url, channel |
| `file.reference` | `file_download` | name, size, sha256, file_id |
| `gmail.draft_reference` | `gmail_create_draft` | subject, `sent=false` |
| `calendar.event_reference` | `calendar_create_event` | title, when |

A consumer declares inputs with `insert_outputs` and/or placeholders (`{{youtube.video_url}}`), and must
`depends_on` the producer (validated). A missing input fails the consumer (`WORKFLOW_INPUT_MISSING`)
instead of producing a half-filled draft. Attachments are never added (the email mentions the file).

## Dependencies, partial success and limits

- `dependency_resolver.resolve_order()` rejects unknown dependencies and cycles.
- In multi-domain plans every step has `continue_on_failure`: if a step fails or is blocked, steps that need
  its output are **SKIPPED**, independent steps still run. The workflow ends `COMPLETED`, `PARTIAL`, `FAILED`
  or `CANCELLED`; the run summary starts with "Partial result:" and lists each step — partial results are
  never shown as success.
- Limits: `WORKFLOW_MAX_STEPS` (30), `WORKFLOW_MAX_DOMAINS` (5), `WORKFLOW_MAX_CONCURRENCY` (2 running
  multi-step workflows; must not exceed `EXECUTION_CONCURRENCY`), `WORKFLOW_TIMEOUT_SECONDS` (300, checked
  before each step). Steps of one workflow run sequentially in the session's single browser.

## State and APIs

`GET /tasks/{id}/workflow?session_id=` returns `WorkflowState` (planned view before Run Plan; observed
afterwards): steps with status, outputs, current domain, pending choice/approval, final result and the
domain details (YouTube results/selection/playback, draft summary, calendar review, download attempts).
`POST /tasks/{id}/workflow/choice` answers a pending choice.

## Events

`workflow.step_started`, `workflow.step_completed`, `workflow.step_failed` (multi-step workflows),
`workflow.partial_success`, `workflow.completed`; plus `integration.domain_selected`,
`integration.capability_selected`, `integration.authentication_required`, `integration.session_ready`,
`integration.error` for every step.

## Testing status

Scenarios 5 (YouTube → Gmail), 6 (download → Gmail), partial success/skip and session isolation are
automated with real Chromium on local fixtures; 3, 5 and 6 were also run live through the dashboard on
fixtures. **No real-site workflow was executed.**
