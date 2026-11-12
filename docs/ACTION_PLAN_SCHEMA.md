# Action plan schema (v1.0)

Python: `backend/app/schemas/{action,plan,intent}.py`. TypeScript: `frontend/src/types/{plan,intent}.ts`. Runtime validation on the frontend: `frontend/src/lib/planValidators.ts` (Zod). Field names are identical on both sides.

## Action primitives
| `type` | Fields | Base risk |
| --- | --- | --- |
| `navigate` | `url` (http/https only, URL policy), `purpose` | LOW |
| `click` | `target_description`, `role_hint?`, `accessible_name?`, `text_hint?` (descriptions only, never CSS selectors) | by rule: LOW, MEDIUM (add to cart / edit), HIGH (send / submit / download / book), CRITICAL (order / pay / checkout / delete) |
| `type` | `target_description`, `text`, `clear_first`, `sensitive` | LOW (credential fields are rejected) |
| `extract` | `target_description`, `fields[1..20]` | LOW |
| `request_approval` | `reason`, `risk_level`, `details{label: value}` | its own risk level |
| `stop` | `reason` | LOW |

```python
class PlannedAction(BaseModel):
    step_id: UUID; order: int (≥1); action: SupportedAction  # discriminated on "type"
    description: str; expected_outcome: str; risk_level: RiskLevel
    requires_approval: bool = False; depends_on: list[UUID] = []

class TaskPlan(BaseModel):
    plan_id, task_id, session_id: UUID
    status: READY | NEEDS_CLARIFICATION | REJECTED | FAILED
    intent: IntentType; summary: str; user_facing_message: str; language: en|hi|hinglish
    target_website: str | None; confidence: float (0..1); assumptions: list[str]
    clarification_question: str | None; missing_information: list[str]
    clarification_history: list[{question, answer, answered_at}]
    steps: list[PlannedAction]; requires_human_approval: bool
    provider: str; model: str; is_mock: bool; created_at: datetime; schema_version: "1.0"
```

```ts
export type SupportedAction = NavigateAction | ClickAction | TypeAction | ExtractAction | RequestApprovalAction | StopAction;
export interface PlannedAction { step_id: string; order: number; action: SupportedAction; description: string;
  expected_outcome: string; risk_level: RiskLevel; requires_approval: boolean; depends_on: string[]; }
export interface TaskPlan { plan_id: string; task_id: string; session_id: string; status: PlanStatus; intent: IntentType; ... }
```

### LLM-facing draft
The model returns a `PlanDraft` rather than a `TaskPlan`:
- Steps carry `depends_on_orders: list[int]` instead of UUIDs, so the model never invents identifiers.
- Approval `details` arrive as a list of `{label, value}` pairs, because strict structured-output modes reject free-form objects.

Trusted code converts the draft into a `TaskPlan`.

## Dependency rules
- A step may depend only on **earlier** steps. Forward references are rejected.
- Self-references, unknown step IDs and cycles are rejected. Cycles are found with a three-colour DFS.
- The mock planner chains each step to the previous one. Approval-gated steps always depend on their gate.

## Validation rules
`PlanValidator` rejects a plan in any of these cases. Each failure triggers a regeneration, up to `AGENT_MAX_RETRIES`.
- **Ownership:** the plan's task or session doesn't match.
- **Unknown intent:** the intent isn't one of the supported values.
- **Empty ready plan:** a READY plan has no steps. GENERAL_CHAT is the only exception.
- **Steps on non-READY plans:** a NEEDS_CLARIFICATION or REJECTED plan contains steps.
- **Clarification without a question:** a NEEDS_CLARIFICATION plan has no `clarification_question`.
- **Too many steps:** more than `AGENT_MAX_PLAN_STEPS` (default 25).
- **Step IDs and order:** step IDs are duplicated, or the order isn't 1..N.
- **Unknown tool or bad parameters:** a step uses an unregistered tool or invalid parameters (checked by the tool registry).
- **Unsafe URL:** a `navigate` URL fails the [URL policy](AGENT_SAFETY.md#url-restrictions).
- **Credentials:** a `type` step targets a password, OTP, PIN, card, CVV, UPI PIN, bank account or ID field, or is marked `sensitive`.
- **Risk too low:** a step's risk is below the deterministic floor.
- **Misplaced stop:** a `stop` step isn't the last step.
- **Dependencies:** any of the dependency rules above is broken.
- **Approval checkpoints:** any of the checkpoint rules below is broken.
- **Approval flag mismatch:** `requires_human_approval` doesn't match the steps.

## Approval checkpoints
Every HIGH or CRITICAL step must meet all of these:
- It is immediately preceded by a `request_approval` step whose risk is at least as high.
- It depends on that approval step.
- It is flagged `requires_approval`.

The approval policy inserts a missing gate automatically, and the validator re-checks it independently. These are **planned** checkpoints only. Phase 2 never creates a runtime approval request. Phase 3 will raise one immediately before the sensitive action.

## Sample plans
**Blinkit (Hinglish).** Command: "Blinkit kholo aur 2 litre Amul milk, ek bread packet aur 12 eggs cart mein add karo." The plan is READY with 14 steps:
1. Navigate to `https://blinkit.com`.
2. Locate the product search.
3. For each item:
   - type the search text ("Amul milk 2 litre", "bread", "eggs");
   - extract and identify the match;
   - add it to the cart (MEDIUM).
4. Open the cart.
5. Extract the cart contents to verify them.
6. `stop` before checkout.

No approval is needed, because adding to a cart doesn't place an order.

**Ambiguous.** Command: "Blinkit par milk order kar do." The plan is NEEDS_CLARIFICATION with `missing_information: ["brand", "quantity"]`, the question "Bhai, milk ka kaunsa brand aur kitni quantity chahiye?", and `steps: []`.

**Payment.** Command: "Amazon par laptop order karo aur payment kar do." The plan is READY: search, identify, add to cart, open the cart and verify. These steps are followed by `request_approval` (CRITICAL) and then `click "Place order / Pay button"` (CRITICAL, `requires_approval`, depends on the gate).

**Gmail draft without a recipient.** The plan is NEEDS_CLARIFICATION asking for the address, which is never guessed. With an address, the plan opens Gmail, checks the signed-in account, composes, fills in To, Subject and Body, verifies the draft and stops while the draft is still unsent.
