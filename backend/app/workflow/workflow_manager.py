"""Workflow state + workflow.* telemetry (Phase 5).

One WorkflowState per task: steps (with status), typed outputs, current domain, pending choice
and the observed domain details. Steps execute through the existing PlanExecutor in order; this
manager records what really happened and computes the honest final status (COMPLETED / PARTIAL /
FAILED / CANCELLED) — partial results are reported as partial, never as success.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.integrations.capability_registry import ACTION_CAPABILITY
from app.integrations.domain_router import INTENT_DOMAIN
from app.schemas.common import utc_now
from app.schemas.integration import DomainType, IntegrationCapability, IntegrationEventPayload
from app.schemas.plan import TaskPlan
from app.schemas.telemetry import TelemetryEventType as E
from app.schemas.workflow import WorkflowOutput, WorkflowState, WorkflowStatus, WorkflowStep, WorkflowStepStatus
from app.workflow.dependency_resolver import dependents
from app.workflow.result_handoff import consumes, produces

if TYPE_CHECKING:
    from app.core.execution_events import ExecutionEvents

_CAP_DOMAIN = {
    IntegrationCapability.YOUTUBE_SEARCH: DomainType.YOUTUBE, IntegrationCapability.YOUTUBE_PLAY: DomainType.YOUTUBE,
    IntegrationCapability.GMAIL_CREATE_DRAFT: DomainType.GMAIL, IntegrationCapability.CALENDAR_CREATE_EVENT: DomainType.GOOGLE_CALENDAR,
    IntegrationCapability.FILE_DOWNLOAD: DomainType.FILES,
}
_LABELS = {
    "youtube_search": "Search YouTube", "youtube_play": "Play the video", "gmail_create_draft": "Save Gmail draft",
    "calendar_create_event": "Create calendar event", "file_download": "Download file",
}
_ = INTENT_DOMAIN  # domain mapping is shared with the router


class WorkflowManager:
    def __init__(self, telemetry: ExecutionEvents, *, max_records: int = 500) -> None:
        self._telemetry = telemetry
        self._states: OrderedDict[UUID, WorkflowState] = OrderedDict()
        self._max = max_records

    # ---------------------------------------------------------------- lifecycle

    def ensure(self, plan: TaskPlan) -> WorkflowState:
        state = self._states.get(plan.task_id)
        if state is not None:
            return state
        state = self.preview(plan)
        self._states[plan.task_id] = state
        while len(self._states) > self._max:
            self._states.popitem(last=False)
        return state

    def preview(self, plan: TaskPlan) -> WorkflowState:
        """The planned workflow (nothing has run). Not stored."""
        steps = []
        for s in plan.steps:
            cap = ACTION_CAPABILITY.get(s.action.type)
            if cap is None:
                continue
            steps.append(WorkflowStep(
                step_id=s.step_id, order=s.order, domain=_CAP_DOMAIN[cap], capability=cap, label=_LABELS[s.action.type],
                depends_on=list(s.depends_on), produces=produces(s.action), consumes=consumes(s.action),
            ))
        domains = list(dict.fromkeys(st.domain for st in steps))
        return WorkflowState(workflow_id=uuid4(), task_id=plan.task_id, session_id=plan.session_id, domains=domains, steps=steps,
                             updated_at=utc_now())

    def get(self, task_id: UUID) -> WorkflowState | None:
        return self._states.get(task_id)

    def step(self, state: WorkflowState, step_id: UUID) -> WorkflowStep | None:
        return next((s for s in state.steps if s.step_id == step_id), None)

    def outputs(self, state: WorkflowState) -> dict[str, WorkflowOutput]:
        return {o.type: o for o in state.outputs}

    def add_output(self, state: WorkflowState, output: WorkflowOutput) -> None:
        state.outputs = [o for o in state.outputs if o.type != output.type] + [output]
        state.updated_at = utc_now()

    # ---------------------------------------------------------------- step events

    async def started(self, state: WorkflowState, step_id: UUID) -> None:
        step = self.step(state, step_id)
        if step is None:
            return
        step.status = WorkflowStepStatus.RUNNING
        state.status = WorkflowStatus.RUNNING
        state.current_domain = step.domain
        state.updated_at = utc_now()
        await self._emit(state, E.INTEGRATION_DOMAIN_SELECTED, step, f"{step.domain.value.replace('_', ' ').title()} selected.")
        await self._emit(state, E.INTEGRATION_CAPABILITY_SELECTED, step, f"Capability {step.capability.value}.")
        if len(state.steps) > 1:
            await self._emit(state, E.WORKFLOW_STEP_STARTED, step, f"Step {step.order}: {step.label}.")

    async def finished(self, state: WorkflowState, step_id: UUID, status: WorkflowStepStatus, message: str, code: str | None = None) -> None:
        step = self.step(state, step_id)
        if step is None:
            return
        step.status, step.message, step.error_code = status, message[:500], code
        state.updated_at = utc_now()
        if len(state.steps) > 1:
            event = E.WORKFLOW_STEP_COMPLETED if status == WorkflowStepStatus.COMPLETED else E.WORKFLOW_STEP_FAILED
            await self._emit(state, event, step, message, status=status.value, code=code)
        if status in (WorkflowStepStatus.FAILED, WorkflowStepStatus.BLOCKED):
            graph = [(s.step_id, list(s.depends_on)) for s in state.steps]
            for dep_id in dependents(graph, step_id):
                dep = self.step(state, dep_id)
                if dep is not None and dep.status == WorkflowStepStatus.NOT_STARTED:
                    dep.status = WorkflowStepStatus.SKIPPED
                    dep.message = f"Skipped: it needs the result of step {step.order}, which did not succeed."

    async def finalize(self, task_id: UUID, execution_status: str) -> WorkflowState | None:
        state = self._states.get(task_id)
        if state is None:
            return None
        for s in state.steps:
            if s.status in (WorkflowStepStatus.NOT_STARTED, WorkflowStepStatus.RUNNING, WorkflowStepStatus.WAITING_USER):
                s.status = WorkflowStepStatus.SKIPPED
                s.message = s.message or "Not run."
        done = [s for s in state.steps if s.status == WorkflowStepStatus.COMPLETED]
        if len(done) == len(state.steps):
            state.status = WorkflowStatus.COMPLETED
        elif execution_status == "CANCELLED" and not done:
            state.status = WorkflowStatus.CANCELLED
        elif done:
            state.status = WorkflowStatus.PARTIAL
        else:
            state.status = WorkflowStatus.FAILED
        state.final_result = self.result_text(state)
        state.current_domain, state.pending_choice = None, None
        state.updated_at = utc_now()
        payload = IntegrationEventPayload(message=state.final_result[:500], status=state.status.value,
                                          completed_steps=len(done), total_steps=len(state.steps))
        if state.status == WorkflowStatus.PARTIAL:
            await self._telemetry.emit(state.session_id, E.WORKFLOW_PARTIAL_SUCCESS, payload, task_id=task_id)
        await self._telemetry.emit(state.session_id, E.WORKFLOW_COMPLETED, payload, task_id=task_id)
        return state

    def result_text(self, state: WorkflowState) -> str:
        done = [s for s in state.steps if s.status == WorkflowStepStatus.COMPLETED]
        if len(done) == len(state.steps):
            return f"All {len(state.steps)} workflow step(s) finished and were verified."
        parts = [f"{len(done)} of {len(state.steps)} step(s) finished."]
        for s in state.steps:
            if s.status != WorkflowStepStatus.COMPLETED:
                parts.append(f"Step {s.order} ({s.label}): {s.status.value.lower()}" + (f" — {s.message}" if s.message else ""))
        return " ".join(parts)[:1000]

    async def _emit(self, state: WorkflowState, event: Any, step: WorkflowStep, message: str, *, status: str | None = None,
                    code: str | None = None) -> None:
        await self._telemetry.emit(state.session_id, event, IntegrationEventPayload(
            domain=step.domain, message=message[:500], status=status, step_id=step.step_id, capability=step.capability, code=code,
            completed_steps=sum(1 for s in state.steps if s.status == WorkflowStepStatus.COMPLETED), total_steps=len(state.steps),
        ), task_id=state.task_id)
