# Domain capability registry

`app/integrations/capability_registry.py` declares every capability a plan may use. Definitions are
trusted code; the model never adds or edits them.

```json
{
  "capability": "CALENDAR_CREATE_EVENT",
  "domain": "GOOGLE_CALENDAR",
  "description": "Create ONE event after exact-event approval, then verify it.",
  "input_schema": {"title": "string", "start_at": "datetime", "end_at": "datetime", "timezone": "IANA"},
  "requires_browser": true,
  "requires_approval": true,
  "risk_level": "HIGH",
  "enabled": true,
  "action_type": "calendar_create_event"
}
```

| Capability | Domain | Action type | Approval |
| --- | --- | --- | --- |
| YOUTUBE_SEARCH | YOUTUBE | `youtube_search` | no |
| YOUTUBE_PLAY | YOUTUBE | `youtube_play` | no |
| GMAIL_CREATE_DRAFT | GMAIL | `gmail_create_draft` | no (never sends) |
| GMAIL_READ_DRAFT | GMAIL | — (verification inside the draft step) | no |
| CALENDAR_LIST_EVENTS | GOOGLE_CALENDAR | — (conflict check inside the event step) | no |
| CALENDAR_CREATE_EVENT | GOOGLE_CALENDAR | `calendar_create_event` | **yes** |
| FILE_DOWNLOAD | FILES | `file_download` | no (allow-list + validation) |
| FILE_INSPECT | FILES | — (`GET /files/{id}`) | no |
| COMMERCE_SEARCH / COMMERCE_CART | BLINKIT / AMAZON_IN | `commerce` (Phase 4) | purchase approval |

## Enablement

`enabled` is computed from settings: `INTEGRATIONS_ENABLED` plus `YOUTUBE_ENABLED`, `GMAIL_ENABLED`,
`GOOGLE_CALENDAR_ENABLED`, `FILE_DOWNLOAD_ENABLED` (and `COMMERCE_ENABLED`/platforms for commerce).

## Validation points

1. **Planning:** `workflow_validator.validate_workflow()` rejects plans that use a disabled or unknown
   capability, exceed `WORKFLOW_MAX_STEPS` / `WORKFLOW_MAX_DOMAINS`, contain a dependency cycle, or use a
   typed output (`{{youtube.video_url}}`, `insert_outputs`) without depending on the step that produces it.
2. **Runtime:** `IntegrationManager.run_step()` calls `CapabilityRegistry.require(action.type)` before
   every step (settings may have changed after planning). Unknown action types raise
   `CAPABILITY_NOT_SUPPORTED`; disabled ones `CAPABILITY_DISABLED`.

`GET /api/v1/integrations/capabilities` returns the list (read-only).
