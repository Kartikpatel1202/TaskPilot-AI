import { MAX_LOGS, MAX_RECENT_TASKS } from "@/lib/constants";

import type {
  AgentStatus,
  AgentStatusResponse,
  ClarificationRequest,
  PlanFetchState,
  PlanningFailure,
  PlanningProgress,
} from "@/types/agent";
import type { ApprovalDecision, ApprovalRequest, ApprovalStatus } from "@/types/approval";
import type {
  BrowserLiveState,
  BrowserNotice,
  BrowserSessionInfo,
  BrowserSessionStatus,
  BrowserStatusResponse,
} from "@/types/browser";
import type { CommerceEventType, ShoppingSummary } from "@/types/commerce";
import { INTEGRATION_EVENT_TYPES, type IntegrationEventType } from "@/types/integration";
import type { ActionExecutionStatus, ExecutionState, ExecutionStatus, ExecutionSummary } from "@/types/execution";
import type { IntentClassification } from "@/types/intent";
import type { TaskPlan } from "@/types/plan";
import type { Task, TaskState } from "@/types/task";
import type {
  AnyTelemetryEvent,
  BrowserPreviewState,
  ConnectionReadyData,
  ConnectionStatus,
  ExecutionLog,
  LogLevel,
} from "@/types/telemetry";

export interface AcceptedNotice {
  taskId: string;
  message: string;
  at: string;
}

export interface TaskPilotState {
  sessionId: string | null;
  connectionStatus: ConnectionStatus;
  activeTask: Task | null;
  tasks: Task[];
  logs: ExecutionLog[];
  activeApproval: ApprovalRequest | null;
  browserPreview: BrowserPreviewState;
  isSubmitting: boolean;
  error: string | null;
  serverInfo: ConnectionReadyData | null;
  lastAccepted: AcceptedNotice | null;
  /** Highest telemetry sequence applied per task, used to drop stale/out-of-order updates. */
  taskSequences: Record<string, number>;
  /** States each task actually visited (drives an honest lifecycle display). */
  taskHistory: Record<string, TaskState[]>;

  // ---------------------------------------------------------------- Phase 2: agent
  activePlan: TaskPlan | null;
  intentClassification: IntentClassification | null;
  agentStatus: AgentStatus;
  isPlanning: boolean;
  clarification: ClarificationRequest | null;
  isSubmittingClarification: boolean;
  planningProgress: PlanningProgress | null;
  planFetch: PlanFetchState | null;
  planningFailure: PlanningFailure | null;
  agentInfo: AgentStatusResponse | null;

  // ---------------------------------------------------------------- Phase 3: browser + execution
  /** Execution of the ACTIVE task's plan (from telemetry; null until Run Plan is clicked). */
  execution: ExecutionState | null;
  /** A Run Plan request is in flight. */
  isStartingExecution: boolean;
  executionError: string | null;
  browser: BrowserLiveState;
  browserStatus: BrowserStatusResponse | null;

  // ---------------------------------------------------------------- Phase 4: commerce
  /** Shopping workflow of the ACTIVE task (observed data from the backend). */
  commerce: CommerceState | null;

  // ---------------------------------------------------------------- Phase 5: integrations
  /** Integration workflow activity of the ACTIVE task (details are re-fetched from the backend). */
  integrations: IntegrationsState | null;
}

export interface IntegrationsState {
  taskId: string;
  /** Bumped on every integration.* / youtube.* / gmail.* / calendar.* / file.* / workflow.* event. */
  revision: number;
  lastEvent: { type: IntegrationEventType; message: string; at: string } | null;
  /** The most recent integration events (newest last, bounded). */
  activity: { type: IntegrationEventType; message: string; at: string }[];
}

export interface CommerceState {
  taskId: string;
  summary: ShoppingSummary | null;
  /** Bumped on every commerce.* event so the summary is re-fetched from the backend. */
  revision: number;
  lastEvent: { type: CommerceEventType; message: string | null; at: string } | null;
}

export const INITIAL_BROWSER_PREVIEW: BrowserPreviewState = {
  mode: "DISCONNECTED",
  message: "Browser not connected.",
  url: null,
  frameDataUrl: null,
  isDemo: false,
  taskId: null,
  updatedAt: null,
};

export const INITIAL_BROWSER_STATE: BrowserLiveState = {
  sessionStatus: null,
  headless: null,
  engine: null,
  url: null,
  title: null,
  domain: null,
  lastFrameSequence: null,
  notice: null,
  updatedAt: null,
};

export const initialTaskPilotState: TaskPilotState = {
  sessionId: null,
  connectionStatus: "CONNECTING",
  activeTask: null,
  tasks: [],
  logs: [],
  activeApproval: null,
  browserPreview: INITIAL_BROWSER_PREVIEW,
  isSubmitting: false,
  error: null,
  serverInfo: null,
  lastAccepted: null,
  taskSequences: {},
  taskHistory: {},
  activePlan: null,
  intentClassification: null,
  agentStatus: "IDLE",
  isPlanning: false,
  clarification: null,
  isSubmittingClarification: false,
  planningProgress: null,
  planFetch: null,
  planningFailure: null,
  agentInfo: null,
  execution: null,
  isStartingExecution: false,
  executionError: null,
  browser: INITIAL_BROWSER_STATE,
  browserStatus: null,
  commerce: null,
  integrations: null,
};

const AGENT_RESET = {
  activePlan: null,
  intentClassification: null,
  agentStatus: "IDLE",
  isPlanning: false,
  clarification: null,
  isSubmittingClarification: false,
  planningProgress: null,
  planFetch: null,
  planningFailure: null,
  execution: null,
  isStartingExecution: false,
  executionError: null,
  commerce: null,
  integrations: null,
} as const satisfies Partial<TaskPilotState>;

export type TaskPilotAction =
  | { type: "SET_SESSION_ID"; sessionId: string }
  | { type: "SET_CONNECTION_STATUS"; status: ConnectionStatus }
  | { type: "SERVER_READY"; info: ConnectionReadyData }
  | { type: "SET_SUBMITTING"; value: boolean }
  | { type: "TASK_ACCEPTED"; task: Task; sequence?: number; message?: string }
  | {
      type: "TASK_STATE_CHANGED";
      taskId: string;
      previous: TaskState;
      next: TaskState;
      at: string;
      sequence: number;
      reason?: string | null;
    }
  | { type: "ADD_LOG"; log: ExecutionLog }
  | { type: "SET_BROWSER_PREVIEW"; preview: BrowserPreviewState }
  | { type: "APPROVAL_REQUIRED"; approval: ApprovalRequest }
  | {
      type: "APPROVAL_RESOLVED";
      approvalId: string;
      status: ApprovalStatus;
      decision: ApprovalDecision | null;
      resolvedAt: string;
    }
  | { type: "DISMISS_APPROVAL"; approvalId: string }
  | { type: "TASK_COMPLETED"; taskId: string; summary: string; at: string }
  | { type: "TASK_FAILED"; taskId: string; errorCode: string; errorMessage: string; at: string }
  | { type: "SET_ERROR"; error: string | null }
  | { type: "DISMISS_ACCEPTED" }
  | { type: "CLEAR_LOGS" }
  // ---------------------------------------------------------------- Phase 2: agent
  | { type: "AGENT_INTENT_DETECTED"; taskId: string; intent: IntentClassification }
  | { type: "AGENT_PLANNING_STARTED"; taskId: string; isClarification: boolean }
  | { type: "AGENT_PLANNING_PROGRESS"; taskId: string; progress: PlanningProgress }
  | { type: "PLAN_ANNOUNCED"; taskId: string; planId: string }
  | { type: "PLAN_FETCH_STARTED"; planId: string }
  | { type: "PLAN_READY"; plan: TaskPlan }
  | { type: "PLAN_FETCH_FAILED"; planId: string; error: string }
  | { type: "CLARIFICATION_REQUIRED"; taskId: string; planId: string; question: string; missingInformation: string[] }
  | { type: "SET_CLARIFICATION_SUBMITTING"; value: boolean }
  | { type: "CLARIFICATION_SUBMITTED"; taskId: string }
  | { type: "PLANNING_FAILED"; taskId: string; code: string; message: string }
  | { type: "AGENT_RESPONSE_RECEIVED"; taskId: string; kind: string }
  | { type: "SET_AGENT_INFO"; info: AgentStatusResponse }
  // ---------------------------------------------------------------- Phase 3: execution
  | { type: "EXECUTION_REQUESTED"; taskId: string }
  | { type: "EXECUTION_REQUEST_FAILED"; taskId: string; error: string }
  | { type: "EXECUTION_STARTED"; taskId: string; planId: string; totalSteps: number; headless: boolean; at: string }
  | { type: "EXECUTION_STEP_STARTED"; taskId: string; stepId: string; order: number; actionType: string; description: string }
  | {
      type: "EXECUTION_STEP_FINISHED";
      taskId: string;
      stepId: string;
      order: number;
      status: ActionExecutionStatus;
      message: string;
      errorCode: string | null;
      durationMs: number | null;
      verified: boolean;
      extractedData: Record<string, unknown> | null;
    }
  | { type: "EXECUTION_PAUSED"; taskId: string; stepId: string; approvalId: string | null }
  | { type: "EXECUTION_RESUMED"; taskId: string; stepId: string }
  | {
      type: "EXECUTION_FINISHED";
      taskId: string;
      status: ExecutionStatus;
      message: string;
      errorCode: string | null;
      totalSteps: number;
      counts: { succeeded: number; failed: number; blocked: number; skipped: number };
      at: string;
    }
  | { type: "EXECUTION_STOP_REQUESTED"; taskId: string }
  | { type: "EXECUTION_SUMMARY_LOADED"; summary: ExecutionSummary }
  | { type: "CLEAR_EXECUTION_ERROR" }
  // ---------------------------------------------------------------- Phase 3: browser
  | { type: "BROWSER_SESSION_UPDATED"; status: BrowserSessionStatus; engine: string; headless: boolean; at: string }
  | { type: "BROWSER_PAGE_UPDATED"; url: string | null; title: string | null; domain: string | null; at: string }
  | { type: "BROWSER_FRAME_ANNOUNCED"; sequence: number; at: string }
  | { type: "BROWSER_NOTICE"; notice: BrowserNotice }
  | { type: "DISMISS_BROWSER_NOTICE" }
  | { type: "BROWSER_SESSION_CLOSED"; at: string }
  | { type: "BROWSER_STATUS_LOADED"; status: BrowserStatusResponse }
  | { type: "BROWSER_SESSION_LOADED"; info: BrowserSessionInfo }
  // ---------------------------------------------------------------- Phase 4: commerce
  | { type: "COMMERCE_EVENT"; taskId: string; eventType: CommerceEventType; message: string | null; at: string }
  | { type: "COMMERCE_SUMMARY_LOADED"; summary: ShoppingSummary }
  // ---------------------------------------------------------------- Phase 5: integrations
  | { type: "INTEGRATION_EVENT"; taskId: string; eventType: IntegrationEventType; message: string; at: string };

// ------------------------------------------------------------------ helpers

function upsertTask(state: TaskPilotState, task: Task, makeActive: boolean): TaskPilotState {
  const exists = state.tasks.some((t) => t.task_id === task.task_id);
  const tasks = exists
    ? state.tasks.map((t) => (t.task_id === task.task_id ? task : t))
    : [task, ...state.tasks].slice(0, MAX_RECENT_TASKS);
  const activeTask =
    state.activeTask?.task_id === task.task_id || makeActive || !state.activeTask ? task : state.activeTask;
  return { ...state, tasks, activeTask };
}

function patchTask(state: TaskPilotState, taskId: string, patch: Partial<Task>): TaskPilotState {
  const current = state.tasks.find((t) => t.task_id === taskId);
  if (!current) return state;
  return upsertTask(state, { ...current, ...patch }, false);
}

function isActive(state: TaskPilotState, taskId: string | null | undefined): boolean {
  return !!taskId && state.activeTask?.task_id === taskId;
}

function insertLog(logs: ExecutionLog[], log: ExecutionLog): ExecutionLog[] {
  let next: ExecutionLog[];
  const last = logs[logs.length - 1];
  if (log.sequence === null || !last || last.sequence === null || last.sequence <= log.sequence) {
    next = [...logs, log];
  } else {
    // Out-of-order arrival: insert at the position that keeps sequence order.
    const index = logs.findIndex((l) => l.sequence !== null && l.sequence > (log.sequence as number));
    next = [...logs.slice(0, index), log, ...logs.slice(index)];
  }
  return next.length > MAX_LOGS ? next.slice(next.length - MAX_LOGS) : next;
}

function newExecution(taskId: string, patch: Partial<ExecutionState> = {}): ExecutionState {
  return {
    taskId,
    planId: null,
    status: "QUEUED",
    totalSteps: 0,
    steps: {},
    currentStepId: null,
    pausedApprovalId: null,
    message: null,
    errorCode: null,
    counts: null,
    headless: null,
    startedAt: null,
    finishedAt: null,
    stopRequested: false,
    ...patch,
  };
}

const EXECUTION_TERMINAL: readonly ExecutionStatus[] = ["COMPLETED", "FAILED", "CANCELLED"];

/** Applies `fn` only to the execution of `taskId` (events of other tasks are ignored). */
function withExecution(
  state: TaskPilotState,
  taskId: string,
  fn: (execution: ExecutionState) => ExecutionState,
): TaskPilotState {
  if (!state.execution || state.execution.taskId !== taskId) return state;
  const next = fn(state.execution);
  return next === state.execution ? state : { ...state, execution: next };
}

function safeHost(url: string): string | null {
  try {
    return new URL(url).hostname || null;
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------ reducer

export function taskPilotReducer(state: TaskPilotState, action: TaskPilotAction): TaskPilotState {
  switch (action.type) {
    case "SET_SESSION_ID":
      return { ...state, sessionId: action.sessionId };

    case "SET_CONNECTION_STATUS":
      return state.connectionStatus === action.status ? state : { ...state, connectionStatus: action.status };

    case "SERVER_READY":
      return { ...state, serverInfo: action.info };

    case "SET_SUBMITTING":
      return { ...state, isSubmitting: action.value };

    case "TASK_ACCEPTED": {
      const existing = state.tasks.find((t) => t.task_id === action.task.task_id);
      // If newer state already arrived (out of order), keep it.
      const task = existing ? { ...action.task, state: existing.state, updated_at: existing.updated_at } : action.task;
      const next = upsertTask(state, task, true);
      // A brand-new active task starts with a clean agent view. Re-deliveries of a known
      // task (REST response + WebSocket event, replays) must not wipe newer agent state.
      const agentReset = existing ? {} : AGENT_RESET;
      const taskHistory = existing ? state.taskHistory : { ...state.taskHistory, [task.task_id]: [task.state] };
      const lastAccepted = action.message
        ? { taskId: task.task_id, message: action.message, at: task.created_at }
        : state.lastAccepted;
      const taskSequences =
        action.sequence !== undefined && !(task.task_id in state.taskSequences)
          ? { ...state.taskSequences, [task.task_id]: action.sequence }
          : state.taskSequences;
      return { ...next, ...agentReset, taskHistory, lastAccepted, taskSequences };
    }

    case "TASK_STATE_CHANGED": {
      const lastSeq = state.taskSequences[action.taskId] ?? 0;
      if (action.sequence <= lastSeq) return state; // stale or duplicate
      const patched = patchTask(state, action.taskId, { state: action.next, updated_at: action.at });
      if (patched === state) return state;
      const visited = state.taskHistory[action.taskId] ?? [action.previous];
      const taskHistory = {
        ...state.taskHistory,
        [action.taskId]: visited.includes(action.next) ? visited : [...visited, action.next],
      };
      // The planning indicator is driven only by agent events (planning_started etc.).
      // A task that leaves planning without them (e.g. the Phase 1 demo simulation,
      // or a failure) must never leave the indicator spinning.
      const leftPlanning =
        isActive(state, action.taskId) &&
        state.isPlanning &&
        (action.next === "FAILED" ||
          action.next === "EXECUTING" ||
          action.next === "COMPLETED" ||
          action.next === "CANCELLED");
      const planning = leftPlanning ? { isPlanning: false, planningProgress: null } : {};
      return {
        ...patched,
        ...planning,
        taskHistory,
        taskSequences: { ...state.taskSequences, [action.taskId]: action.sequence },
      };
    }

    case "TASK_COMPLETED":
      return patchTask(state, action.taskId, { state: "COMPLETED", updated_at: action.at, error_message: null });

    case "TASK_FAILED":
      return patchTask(state, action.taskId, {
        state: "FAILED",
        updated_at: action.at,
        error_message: action.errorMessage,
      });

    case "ADD_LOG":
      return { ...state, logs: insertLog(state.logs, action.log) };

    case "CLEAR_LOGS":
      return { ...state, logs: [] };

    case "SET_BROWSER_PREVIEW":
      return { ...state, browserPreview: action.preview };

    case "APPROVAL_REQUIRED":
      return { ...state, activeApproval: action.approval };

    case "APPROVAL_RESOLVED": {
      if (state.activeApproval?.approval_id !== action.approvalId) return state;
      if (action.status === "EXPIRED") {
        return {
          ...state,
          activeApproval: { ...state.activeApproval, status: "EXPIRED", resolved_at: action.resolvedAt },
        };
      }
      return { ...state, activeApproval: null };
    }

    case "DISMISS_APPROVAL":
      if (state.activeApproval?.approval_id !== action.approvalId) return state;
      return state.activeApproval.status === "PENDING" ? state : { ...state, activeApproval: null };

    case "SET_ERROR":
      return { ...state, error: action.error };

    case "DISMISS_ACCEPTED":
      return { ...state, lastAccepted: null };

    // ---------------------------------------------------------------- Phase 2: agent

    case "AGENT_INTENT_DETECTED":
      return isActive(state, action.taskId) ? { ...state, intentClassification: action.intent } : state;

    case "AGENT_PLANNING_STARTED":
      if (!isActive(state, action.taskId)) return state;
      return {
        ...state,
        isPlanning: true,
        agentStatus: "PLANNING",
        planningProgress: null,
        planningFailure: null,
        clarification: null,
        activePlan: action.isClarification ? state.activePlan : null,
      };

    case "AGENT_PLANNING_PROGRESS":
      if (!isActive(state, action.taskId) || !state.isPlanning) return state;
      // Stages only move forward; a replayed earlier stage never rewinds the indicator.
      if (state.planningProgress && state.planningProgress.progress > action.progress.progress) return state;
      return { ...state, planningProgress: action.progress };

    case "PLAN_ANNOUNCED":
      if (!isActive(state, action.taskId)) return state;
      if (state.activePlan?.plan_id === action.planId) return state;
      return { ...state, planFetch: { taskId: action.taskId, planId: action.planId, status: "pending", error: null } };

    case "PLAN_FETCH_STARTED":
      if (state.planFetch?.planId !== action.planId) return state;
      return { ...state, planFetch: { ...state.planFetch, status: "loading", error: null } };

    case "PLAN_FETCH_FAILED":
      if (state.planFetch?.planId !== action.planId) return state;
      return { ...state, planFetch: { ...state.planFetch, status: "error", error: action.error }, isPlanning: false };

    case "PLAN_READY": {
      const { plan } = action;
      if (!isActive(state, plan.task_id)) return state;
      const agentStatus: AgentStatus =
        plan.status === "READY"
          ? "PLAN_READY"
          : plan.status === "NEEDS_CLARIFICATION"
            ? "NEEDS_CLARIFICATION"
            : plan.status === "REJECTED"
              ? "REJECTED"
              : "ERROR";
      return {
        ...state,
        activePlan: plan,
        agentStatus,
        isPlanning: false,
        planningProgress: null,
        planFetch: state.planFetch?.planId === plan.plan_id ? null : state.planFetch,
      };
    }

    case "CLARIFICATION_REQUIRED":
      if (!isActive(state, action.taskId)) return state;
      return {
        ...state,
        isPlanning: false,
        planningProgress: null,
        agentStatus: "NEEDS_CLARIFICATION",
        clarification: {
          taskId: action.taskId,
          planId: action.planId,
          question: action.question,
          missingInformation: action.missingInformation,
        },
      };

    case "SET_CLARIFICATION_SUBMITTING":
      return { ...state, isSubmittingClarification: action.value };

    case "CLARIFICATION_SUBMITTED":
      if (!isActive(state, action.taskId)) return state;
      return { ...state, clarification: null, isPlanning: true, agentStatus: "PLANNING", isSubmittingClarification: false };

    case "PLANNING_FAILED":
      if (!isActive(state, action.taskId)) return state;
      return {
        ...state,
        isPlanning: false,
        planningProgress: null,
        agentStatus: "ERROR",
        planningFailure: { taskId: action.taskId, code: action.code, message: action.message },
      };

    case "AGENT_RESPONSE_RECEIVED":
      return state;

    case "SET_AGENT_INFO":
      return { ...state, agentInfo: action.info };

    // ---------------------------------------------------------------- Phase 3: execution

    case "EXECUTION_REQUESTED":
      if (!isActive(state, action.taskId)) return state;
      return { ...state, isStartingExecution: true, executionError: null };

    case "EXECUTION_REQUEST_FAILED":
      if (!isActive(state, action.taskId)) return state;
      return { ...state, isStartingExecution: false, executionError: action.error };

    case "CLEAR_EXECUTION_ERROR":
      return state.executionError === null ? state : { ...state, executionError: null };

    case "EXECUTION_STARTED": {
      if (!isActive(state, action.taskId)) return state;
      const same = state.execution?.taskId === action.taskId ? state.execution : null;
      // A replayed start never wipes step progress that already arrived.
      if (same?.startedAt) return { ...state, isStartingExecution: false };
      return {
        ...state,
        isStartingExecution: false,
        executionError: null,
        browser: { ...state.browser, sessionStatus: "BUSY" },
        execution: newExecution(action.taskId, {
          planId: action.planId,
          status: "EXECUTING",
          totalSteps: action.totalSteps,
          headless: action.headless,
          startedAt: action.at,
          steps: same?.steps ?? {},
        }),
      };
    }

    case "EXECUTION_STEP_STARTED": {
      const base =
        !state.execution && isActive(state, action.taskId)
          ? { ...state, execution: newExecution(action.taskId, { status: "EXECUTING" }) }
          : state;
      return withExecution(base, action.taskId, (ex) => {
        const existing = ex.steps[action.stepId];
        if (existing && existing.status !== "PENDING" && existing.status !== "RUNNING") return ex; // stale replay
        return {
          ...ex,
          status: EXECUTION_TERMINAL.includes(ex.status) ? ex.status : "EXECUTING",
          currentStepId: action.stepId,
          steps: {
            ...ex.steps,
            [action.stepId]: {
              stepId: action.stepId,
              order: action.order,
              actionType: action.actionType,
              description: action.description,
              status: "RUNNING",
              message: null,
              errorCode: null,
              durationMs: null,
              verified: false,
              extractedData: null,
            },
          },
        };
      });
    }

    case "EXECUTION_STEP_FINISHED":
      return withExecution(state, action.taskId, (ex) => ({
        ...ex,
        currentStepId: ex.currentStepId === action.stepId ? null : ex.currentStepId,
        steps: {
          ...ex.steps,
          [action.stepId]: {
            stepId: action.stepId,
            order: action.order,
            actionType: ex.steps[action.stepId]?.actionType ?? "",
            description: ex.steps[action.stepId]?.description ?? null,
            status: action.status,
            message: action.message,
            errorCode: action.errorCode,
            durationMs: action.durationMs,
            verified: action.verified,
            extractedData: action.extractedData,
          },
        },
      }));

    case "EXECUTION_PAUSED":
      return withExecution(state, action.taskId, (ex) =>
        EXECUTION_TERMINAL.includes(ex.status) ? ex : { ...ex, status: "WAITING_APPROVAL", pausedApprovalId: action.approvalId },
      );

    case "EXECUTION_RESUMED":
      return withExecution(state, action.taskId, (ex) =>
        EXECUTION_TERMINAL.includes(ex.status) ? ex : { ...ex, status: "EXECUTING", pausedApprovalId: null },
      );

    case "EXECUTION_FINISHED": {
      const base =
        !state.execution && isActive(state, action.taskId) ? { ...state, execution: newExecution(action.taskId) } : state;
      const next = withExecution(base, action.taskId, (ex) => ({
        ...ex,
        status: action.status,
        message: action.message,
        errorCode: action.errorCode,
        totalSteps: action.totalSteps || ex.totalSteps,
        counts: action.counts,
        currentStepId: null,
        pausedApprovalId: null,
        finishedAt: action.at,
      }));
      if (next === base) return state;
      // The run is over: a browser that was busy with it is idle again (unless it needs sign-in or failed).
      const sessionStatus = next.browser.sessionStatus === "BUSY" ? "READY" : next.browser.sessionStatus;
      return { ...next, isStartingExecution: false, browser: { ...next.browser, sessionStatus } };
    }

    case "EXECUTION_STOP_REQUESTED":
      return withExecution(state, action.taskId, (ex) => ({ ...ex, stopRequested: true }));

    case "EXECUTION_SUMMARY_LOADED": {
      const { summary } = action;
      if (!isActive(state, summary.task_id)) return state;
      const live = state.execution?.taskId === summary.task_id ? state.execution : null;
      // Telemetry is the live source; the REST summary only fills gaps (e.g. after a reload).
      if (live?.finishedAt) return state;
      const steps: ExecutionState["steps"] = { ...(live?.steps ?? {}) };
      for (const r of summary.results) {
        steps[r.step_id] = {
          stepId: r.step_id,
          order: r.order,
          actionType: r.action_type,
          description: steps[r.step_id]?.description ?? null,
          status: r.status,
          message: r.message,
          errorCode: r.error_code ?? null,
          durationMs: r.duration_ms ?? null,
          verified: r.verified,
          extractedData: r.extracted_data ?? null,
        };
      }
      const count = (st: ActionExecutionStatus) => summary.results.filter((r) => r.status === st).length;
      const terminal = EXECUTION_TERMINAL.includes(summary.status);
      return {
        ...state,
        execution: newExecution(summary.task_id, {
          ...(live ?? {}),
          planId: summary.plan_id,
          status: summary.status,
          totalSteps: summary.total_steps,
          steps,
          message: summary.message ?? null,
          errorCode: summary.error_code ?? null,
          startedAt: summary.started_at ?? live?.startedAt ?? null,
          finishedAt: terminal ? (summary.finished_at ?? null) : null,
          counts: terminal
            ? { succeeded: count("SUCCEEDED"), failed: count("FAILED"), blocked: count("BLOCKED"), skipped: count("SKIPPED") }
            : null,
        }),
      };
    }

    // ---------------------------------------------------------------- Phase 3: browser

    case "BROWSER_SESSION_UPDATED":
      return {
        ...state,
        browser: {
          ...state.browser,
          sessionStatus: action.status,
          engine: action.engine,
          headless: action.headless,
          updatedAt: action.at,
        },
      };

    case "BROWSER_PAGE_UPDATED":
      return {
        ...state,
        browser: {
          ...state.browser,
          url: action.url,
          title: action.title,
          domain: action.domain,
          updatedAt: action.at,
          // a new page clears an old "blocked" notice, never an auth-required one
          notice: state.browser.notice?.kind === "navigation_blocked" ? null : state.browser.notice,
        },
      };

    case "BROWSER_FRAME_ANNOUNCED":
      if (state.browser.lastFrameSequence !== null && action.sequence <= state.browser.lastFrameSequence) return state;
      return { ...state, browser: { ...state.browser, lastFrameSequence: action.sequence, updatedAt: action.at } };

    case "BROWSER_NOTICE":
      return {
        ...state,
        browser: {
          ...state.browser,
          notice: action.notice,
          sessionStatus: action.notice.kind === "authentication_required" ? "AUTH_REQUIRED" : state.browser.sessionStatus,
        },
      };

    case "DISMISS_BROWSER_NOTICE":
      return state.browser.notice ? { ...state, browser: { ...state.browser, notice: null } } : state;

    case "BROWSER_SESSION_CLOSED":
      return {
        ...state,
        browser: { ...INITIAL_BROWSER_STATE, sessionStatus: "CLOSED", headless: state.browser.headless, updatedAt: action.at },
      };

    case "BROWSER_STATUS_LOADED":
      return { ...state, browserStatus: action.status };

    // ---------------------------------------------------------------- Phase 4: commerce

    case "COMMERCE_EVENT": {
      if (!isActive(state, action.taskId)) return state;
      const current = state.commerce?.taskId === action.taskId ? state.commerce : null;
      return {
        ...state,
        commerce: {
          taskId: action.taskId,
          summary: current?.summary ?? null,
          revision: (current?.revision ?? 0) + 1,
          lastEvent: { type: action.eventType, message: action.message, at: action.at },
        },
      };
    }

    case "COMMERCE_SUMMARY_LOADED": {
      const { summary } = action;
      if (!isActive(state, summary.task_id)) return state;
      const current = state.commerce?.taskId === summary.task_id ? state.commerce : null;
      // Never replace a newer summary with an older response.
      if (current?.summary && current.summary.updated_at > summary.updated_at) return state;
      return {
        ...state,
        commerce: { taskId: summary.task_id, summary, revision: current?.revision ?? 0, lastEvent: current?.lastEvent ?? null },
      };
    }

    // ---------------------------------------------------------------- Phase 5: integrations

    case "INTEGRATION_EVENT": {
      if (!isActive(state, action.taskId)) return state;
      const current = state.integrations?.taskId === action.taskId ? state.integrations : null;
      const entry = { type: action.eventType, message: action.message, at: action.at };
      return {
        ...state,
        integrations: {
          taskId: action.taskId,
          revision: (current?.revision ?? 0) + 1,
          lastEvent: entry,
          activity: [...(current?.activity ?? []), entry].slice(-MAX_INTEGRATION_ACTIVITY),
        },
      };
    }

    case "BROWSER_SESSION_LOADED": {
      const { info } = action;
      return {
        ...state,
        browser: {
          ...state.browser,
          sessionStatus: info.status,
          headless: info.headless,
          url: info.current_url ?? state.browser.url,
          title: info.current_title ?? state.browser.title,
          domain: info.current_url ? safeHost(info.current_url) : state.browser.domain,
          updatedAt: info.last_activity_at,
        },
      };
    }

    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

// ------------------------------------------------------------------ event mapping

function systemLog(
  event: AnyTelemetryEvent,
  level: LogLevel,
  message: string,
  isDemo: boolean,
  metadata: Record<string, unknown> | null = null,
): TaskPilotAction {
  return {
    type: "ADD_LOG",
    log: {
      id: event.event_id,
      timestamp: event.occurred_at,
      level,
      message,
      taskId: event.task_id,
      metadata,
      source: isDemo ? "demo" : "system",
      language: null,
      isDemo,
      sequence: event.sequence,
    },
  };
}

const STATE_LABEL: Record<TaskState, string> = {
  IDLE: "Idle",
  PLANNING: "Planning",
  PLANNED: "Plan ready",
  NEEDS_CLARIFICATION: "Needs clarification",
  EXECUTING: "Executing",
  WAITING_APPROVAL: "Waiting for approval",
  COMPLETED: "Completed",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

/** Translate a validated telemetry event into reducer actions (pure, testable). */
export function mapEventToActions(event: AnyTelemetryEvent): TaskPilotAction[] {
  switch (event.type) {
    case "connection.ready":
      return [{ type: "SERVER_READY", info: event.data }];

    case "task.accepted": {
      const d = event.data;
      return [
        {
          type: "TASK_ACCEPTED",
          sequence: event.sequence,
          task: {
            task_id: d.task_id,
            session_id: event.session_id,
            command: d.command,
            input_mode: d.input_mode,
            state: d.state,
            created_at: d.created_at,
            updated_at: event.occurred_at,
            error_message: null,
            is_demo: d.is_demo,
          },
        },
        systemLog(event, "INFO", `Task accepted (state: ${STATE_LABEL[d.state]}).`, d.is_demo),
      ];
    }

    case "task.state_changed": {
      if (!event.task_id) return [];
      const d = event.data;
      return [
        {
          type: "TASK_STATE_CHANGED",
          taskId: event.task_id,
          previous: d.previous_state,
          next: d.new_state,
          at: event.occurred_at,
          sequence: event.sequence,
          reason: d.reason ?? null,
        },
        systemLog(
          event,
          "DEBUG",
          `State ${STATE_LABEL[d.previous_state]} → ${STATE_LABEL[d.new_state]}${d.reason ? ` · ${d.reason}` : ""}`,
          d.is_demo,
        ),
      ];
    }

    case "log.created": {
      const d = event.data;
      return [
        {
          type: "ADD_LOG",
          log: {
            id: event.event_id,
            timestamp: event.occurred_at,
            level: d.level,
            message: d.message,
            taskId: event.task_id,
            metadata: d.metadata ?? null,
            source: d.source,
            language: d.language ?? null,
            isDemo: d.is_demo,
            sequence: event.sequence,
          },
        },
      ];
    }

    case "browser.preview": {
      const d = event.data;
      return [
        {
          type: "SET_BROWSER_PREVIEW",
          preview: {
            mode: d.mode,
            message: d.message,
            url: d.url ?? null,
            frameDataUrl: d.frame_data_url ?? null,
            isDemo: d.is_demo,
            taskId: event.task_id,
            updatedAt: event.occurred_at,
          },
        },
      ];
    }

    case "approval.required":
      return [
        { type: "APPROVAL_REQUIRED", approval: event.data },
        systemLog(
          event,
          "WARNING",
          `Approval required: ${event.data.action_summary} (${event.data.domain}, risk ${event.data.risk_level}).`,
          event.data.is_demo,
        ),
      ];

    case "approval.resolved": {
      const d = event.data;
      return [
        {
          type: "APPROVAL_RESOLVED",
          approvalId: d.approval_id,
          status: d.status,
          decision: d.decision,
          resolvedAt: d.resolved_at,
        },
        systemLog(
          event,
          d.status === "APPROVED" ? "SUCCESS" : "WARNING",
          `Approval ${d.status.toLowerCase()}.${d.is_demo ? " (demo — no real action)" : ""}`,
          d.is_demo,
        ),
      ];
    }

    case "task.completed":
      if (!event.task_id) return [];
      return [
        { type: "TASK_COMPLETED", taskId: event.task_id, summary: event.data.summary, at: event.occurred_at },
        systemLog(event, "SUCCESS", event.data.summary, event.data.is_demo),
      ];

    case "task.failed":
      if (!event.task_id) return [];
      return [
        {
          type: "TASK_FAILED",
          taskId: event.task_id,
          errorCode: event.data.error_code,
          errorMessage: event.data.error_message,
          at: event.occurred_at,
        },
        systemLog(event, "ERROR", `${event.data.error_message} [${event.data.error_code}]`, event.data.is_demo),
      ];

    case "system.error":
      return [systemLog(event, "ERROR", `${event.data.message} [${event.data.code}]`, false)];

    // ---------------------------------------------------------------- Phase 2: agent

    case "agent.intent_detected": {
      if (!event.task_id) return [];
      const d = event.data;
      const site = d.target_website ? ` · ${d.target_website}` : "";
      return [
        { type: "AGENT_INTENT_DETECTED", taskId: event.task_id, intent: d },
        systemLog(event, "INFO", `Intent: ${d.intent} (${Math.round(d.confidence * 100)}% confidence)${site}`, false),
      ];
    }

    case "agent.planning_started":
      if (!event.task_id) return [];
      return [
        { type: "AGENT_PLANNING_STARTED", taskId: event.task_id, isClarification: event.data.is_clarification },
        systemLog(event, "INFO", event.data.message, false),
      ];

    case "agent.planning_progress":
      if (!event.task_id) return [];
      return [
        { type: "AGENT_PLANNING_PROGRESS", taskId: event.task_id, progress: event.data },
        systemLog(event, "DEBUG", event.data.message, false),
      ];

    case "task.plan_ready": {
      if (!event.task_id) return [];
      const d = event.data;
      const mock = d.is_mock ? " (offline mock planner)" : "";
      const steps = `${d.step_count} step${d.step_count === 1 ? "" : "s"}`;
      const message =
        d.status === "READY" ? `Plan ready: ${d.summary} (${steps})${mock}. Not executed.` : `Request not planned: ${d.summary}`;
      return [
        { type: "PLAN_ANNOUNCED", taskId: event.task_id, planId: d.plan_id },
        systemLog(event, d.status === "READY" ? "SUCCESS" : "WARNING", message, false),
      ];
    }

    case "task.clarification_required":
      if (!event.task_id) return [];
      return [
        {
          type: "CLARIFICATION_REQUIRED",
          taskId: event.task_id,
          planId: event.data.plan_id,
          question: event.data.question,
          missingInformation: event.data.missing_information,
        },
        systemLog(event, "WARNING", `Clarification needed: ${event.data.question}`, false),
      ];

    case "task.planning_failed":
      if (!event.task_id) return [];
      return [
        { type: "PLANNING_FAILED", taskId: event.task_id, code: event.data.code, message: event.data.message },
        systemLog(event, "ERROR", `Planning failed: ${event.data.message} [${event.data.code}]`, false),
      ];

    case "agent.response_generated":
      return [
        ...(event.task_id
          ? [{ type: "AGENT_RESPONSE_RECEIVED" as const, taskId: event.task_id, kind: event.data.kind }]
          : []),
        {
          type: "ADD_LOG",
          log: {
            id: event.event_id,
            timestamp: event.occurred_at,
            level: event.data.kind === "failed" ? "ERROR" : "INFO",
            message: event.data.message,
            taskId: event.task_id,
            metadata: null,
            source: "assistant",
            language: event.data.language,
            isDemo: false,
            sequence: event.sequence,
          },
        },
      ];

    // ---------------------------------------------------------------- Phase 3: browser

    case "browser.session_started":
    case "browser.session_ready": {
      const d = event.data;
      const fallback =
        event.type === "browser.session_ready"
          ? `Chromium ready (${d.headless ? "headless" : "visible window"}).`
          : "Starting Chromium…";
      return [
        { type: "BROWSER_SESSION_UPDATED", status: d.status, engine: d.engine, headless: d.headless, at: event.occurred_at },
        systemLog(event, "INFO", d.message ?? fallback, false),
      ];
    }

    case "browser.navigation_started":
      return [systemLog(event, "DEBUG", event.data.message, false)];

    case "browser.navigation_completed": {
      const d = event.data;
      return [
        { type: "BROWSER_PAGE_UPDATED", url: d.url, title: d.title ?? null, domain: d.domain ?? null, at: event.occurred_at },
        systemLog(event, "INFO", d.message, false),
      ];
    }

    case "browser.navigation_blocked": {
      const d = event.data;
      return [
        {
          type: "BROWSER_NOTICE",
          notice: { kind: "navigation_blocked", message: d.message, url: d.url, code: d.reason_code, at: event.occurred_at },
        },
        systemLog(event, "WARNING", `Navigation blocked: ${d.message}`, false),
      ];
    }

    case "browser.page_updated": {
      const d = event.data;
      return [{ type: "BROWSER_PAGE_UPDATED", url: d.url, title: d.title, domain: d.domain, at: event.occurred_at }];
    }

    case "browser.frame_available":
      return [{ type: "BROWSER_FRAME_ANNOUNCED", sequence: event.data.sequence, at: event.occurred_at }];

    case "browser.action_started":
      return [systemLog(event, "DEBUG", event.data.message, false)];

    case "browser.action_completed": {
      const d = event.data;
      const confidence = d.confidence != null ? ` ${Math.round(d.confidence * 100)}%` : "";
      const how = d.strategy ? ` · ${d.strategy}${confidence}` : "";
      return [systemLog(event, "INFO", `${d.message}${how}`, false)];
    }

    case "browser.action_failed": {
      const d = event.data;
      return [systemLog(event, "ERROR", `${d.message}${d.error_code ? ` [${d.error_code}]` : ""}`, false)];
    }

    case "browser.authentication_required": {
      const d = event.data;
      return [
        {
          type: "BROWSER_NOTICE",
          notice: {
            kind: "authentication_required",
            message: d.message,
            url: d.domain,
            code: "AUTHENTICATION_REQUIRED",
            at: event.occurred_at,
          },
        },
        systemLog(event, "WARNING", d.message, false),
      ];
    }

    case "browser.popup_blocked":
      return [
        {
          type: "BROWSER_NOTICE",
          notice: { kind: "popup_blocked", message: event.data.message, url: event.data.url, at: event.occurred_at },
        },
        systemLog(event, "WARNING", event.data.message, false),
      ];

    case "browser.download_blocked":
      return [
        {
          type: "BROWSER_NOTICE",
          notice: { kind: "download_blocked", message: event.data.message, url: event.data.filename, at: event.occurred_at },
        },
        systemLog(event, "WARNING", event.data.message, false),
      ];

    case "browser.session_closed":
      return [
        { type: "BROWSER_SESSION_CLOSED", at: event.occurred_at },
        systemLog(event, "INFO", `Browser closed: ${event.data.reason}`, false),
      ];

    case "browser.session_error":
      return [
        {
          type: "BROWSER_NOTICE",
          notice: { kind: "session_error", message: event.data.message, code: event.data.code, at: event.occurred_at },
        },
        systemLog(event, "ERROR", `${event.data.message} [${event.data.code}]`, false),
      ];

    case "browser.stream_connected":
    case "browser.stream_disconnected":
      return [];

    // ---------------------------------------------------------------- Phase 3: execution

    case "task.execution_started": {
      if (!event.task_id) return [];
      const d = event.data;
      return [
        {
          type: "EXECUTION_STARTED",
          taskId: event.task_id,
          planId: d.plan_id,
          totalSteps: d.total_steps,
          headless: d.headless,
          at: event.occurred_at,
        },
        systemLog(
          event,
          "INFO",
          `Execution started in ${d.engine} (${d.headless ? "headless" : "visible"}) · ${d.total_steps} steps.`,
          false,
        ),
      ];
    }

    case "task.step_started": {
      if (!event.task_id) return [];
      const d = event.data;
      return [
        {
          type: "EXECUTION_STEP_STARTED",
          taskId: event.task_id,
          stepId: d.step_id,
          order: d.order,
          actionType: d.action_type,
          description: d.description,
        },
        systemLog(event, "INFO", `Step ${d.order} started: ${d.description}`, false),
      ];
    }

    case "task.step_completed": {
      if (!event.task_id) return [];
      const d = event.data;
      return [
        {
          type: "EXECUTION_STEP_FINISHED",
          taskId: event.task_id,
          stepId: d.step_id,
          order: d.order,
          status: d.status,
          message: d.message,
          errorCode: null,
          durationMs: d.duration_ms,
          verified: d.verified,
          extractedData: d.extracted_data ?? null,
        },
        systemLog(event, "SUCCESS", `Step ${d.order}: ${d.message}`, false),
      ];
    }

    case "task.step_failed":
    case "task.step_blocked": {
      if (!event.task_id) return [];
      const d = event.data;
      return [
        {
          type: "EXECUTION_STEP_FINISHED",
          taskId: event.task_id,
          stepId: d.step_id,
          order: d.order,
          status: d.status,
          message: d.message,
          errorCode: d.error_code,
          durationMs: d.duration_ms ?? null,
          verified: false,
          extractedData: null,
        },
        systemLog(
          event,
          event.type === "task.step_blocked" ? "WARNING" : "ERROR",
          `Step ${d.order}: ${d.message} [${d.error_code}]`,
          false,
        ),
      ];
    }

    case "task.execution_paused":
      if (!event.task_id) return [];
      return [
        {
          type: "EXECUTION_PAUSED",
          taskId: event.task_id,
          stepId: event.data.step_id,
          approvalId: event.data.approval_id ?? null,
        },
        systemLog(event, "WARNING", `Paused for your approval: ${event.data.reason}`, false),
      ];

    case "task.execution_resumed":
      if (!event.task_id) return [];
      return [
        { type: "EXECUTION_RESUMED", taskId: event.task_id, stepId: event.data.step_id },
        systemLog(event, "INFO", event.data.message, false),
      ];

    case "task.execution_completed":
    case "task.execution_failed":
    case "task.execution_cancelled": {
      if (!event.task_id) return [];
      const d = event.data;
      const level: LogLevel = d.status === "COMPLETED" ? "SUCCESS" : d.status === "CANCELLED" ? "WARNING" : "ERROR";
      return [
        {
          type: "EXECUTION_FINISHED",
          taskId: event.task_id,
          status: d.status,
          message: d.message,
          errorCode: d.error_code ?? null,
          totalSteps: d.total_steps,
          counts: {
            succeeded: d.succeeded_steps,
            failed: d.failed_steps,
            blocked: d.blocked_steps,
            skipped: d.skipped_steps,
          },
          at: event.occurred_at,
        },
        systemLog(
          event,
          level,
          `Execution ${d.status.toLowerCase()}: ${d.message}${d.error_code ? ` [${d.error_code}]` : ""}`,
          false,
        ),
      ];
    }

    // ---------------------------------------------------------------- Phase 4: commerce

    case "commerce.session_detected":
    case "commerce.location_required":
    case "commerce.search_started":
    case "commerce.search_completed":
    case "commerce.products_found":
    case "commerce.product_selected":
    case "commerce.product_ambiguous":
    case "commerce.product_unavailable":
    case "commerce.cart_update_started":
    case "commerce.cart_item_added":
    case "commerce.cart_item_updated":
    case "commerce.cart_verification_started":
    case "commerce.cart_verification_completed":
    case "commerce.cart_verification_failed":
    case "commerce.price_changed":
    case "commerce.checkout_review_ready":
    case "commerce.purchase_approval_required":
    case "commerce.purchase_rejected":
    case "commerce.payment_handoff":
    case "commerce.order_submission_started":
    case "commerce.order_confirmed":
    case "commerce.order_status_unknown":
    case "commerce.workflow_failed": {
      if (!event.task_id) return [];
      const d = event.data;
      const message = commerceMessage(event.type, d);
      return [
        { type: "COMMERCE_EVENT", taskId: event.task_id, eventType: event.type, message, at: event.occurred_at },
        systemLog(event, COMMERCE_LEVEL[event.type] ?? "INFO", message, false),
      ];
    }

    default: {
      if (isIntegrationEvent(event.type)) {
        // Phase 5: one bounded payload for every integration event (no email bodies, addresses or paths).
        if (!event.task_id) return [];
        const d = event.data as { message: string; code?: string | null };
        const message = d.code ? `${d.message} [${d.code}]` : d.message;
        return [
          { type: "INTEGRATION_EVENT", taskId: event.task_id, eventType: event.type, message: d.message, at: event.occurred_at },
          systemLog(event, INTEGRATION_LEVEL[event.type] ?? "INFO", message, false),
        ];
      }
      const exhaustive: never = event as never;
      return exhaustive;
    }
  }
}

const MAX_INTEGRATION_ACTIVITY = 40;
const INTEGRATION_SET: ReadonlySet<string> = new Set(INTEGRATION_EVENT_TYPES);

function isIntegrationEvent(type: string): type is IntegrationEventType {
  return INTEGRATION_SET.has(type);
}

const INTEGRATION_LEVEL: Partial<Record<IntegrationEventType, LogLevel>> = {
  "integration.domain_selected": "DEBUG",
  "integration.capability_selected": "DEBUG",
  "file.download_progress": "DEBUG",
  "youtube.search_started": "DEBUG",
  "integration.session_ready": "SUCCESS",
  "youtube.playback_started": "SUCCESS",
  "gmail.draft_verified": "SUCCESS",
  "calendar.event_created": "SUCCESS",
  "file.download_completed": "SUCCESS",
  "workflow.completed": "SUCCESS",
  "integration.authentication_required": "WARNING",
  "youtube.playback_paused": "WARNING",
  "gmail.send_blocked": "WARNING",
  "calendar.conflict_detected": "WARNING",
  "calendar.approval_required": "WARNING",
  "file.download_blocked": "WARNING",
  "workflow.partial_success": "WARNING",
  "workflow.step_failed": "WARNING",
  "integration.error": "ERROR",
  "youtube.playback_error": "ERROR",
  "gmail.draft_failed": "ERROR",
  "calendar.event_creation_failed": "ERROR",
  "file.download_failed": "ERROR",
};

const COMMERCE_LEVEL: Partial<Record<CommerceEventType, LogLevel>> = {
  "commerce.search_started": "DEBUG",
  "commerce.cart_update_started": "DEBUG",
  "commerce.cart_verification_started": "DEBUG",
  "commerce.cart_item_added": "SUCCESS",
  "commerce.cart_verification_completed": "SUCCESS",
  "commerce.order_confirmed": "SUCCESS",
  "commerce.location_required": "WARNING",
  "commerce.product_ambiguous": "WARNING",
  "commerce.product_unavailable": "WARNING",
  "commerce.cart_verification_failed": "WARNING",
  "commerce.price_changed": "WARNING",
  "commerce.purchase_approval_required": "WARNING",
  "commerce.purchase_rejected": "WARNING",
  "commerce.payment_handoff": "WARNING",
  "commerce.order_status_unknown": "ERROR",
  "commerce.workflow_failed": "ERROR",
};

function commerceMessage(type: CommerceEventType, d: { [key: string]: unknown }): string {
  const msg = typeof d.message === "string" && d.message ? d.message : null;
  switch (type) {
    case "commerce.products_found":
      return `Read ${d.candidate_count ?? 0} product(s) for "${d.query ?? ""}" · ${d.exact_match_count ?? 0} exact match(es).`;
    case "commerce.cart_verification_completed":
      return `Cart verified: ${d.matched_item_count ?? 0}/${d.requested_item_count ?? 0} item(s) match. No order placed.`;
    case "commerce.cart_verification_failed":
      return `Cart ${String(d.status ?? "unverified").toLowerCase()}: ${[...((d.missing_items as string[]) ?? []), ...((d.mismatched_items as string[]) ?? [])].join("; ") || "differences found"}.`;
    case "commerce.checkout_review_ready":
      return `Checkout reviewed (${d.item_count ?? 0} item(s), total ${d.final_total ? "₹" + d.final_total : "not shown"}). Nothing purchased.`;
    default:
      return msg ?? type.replace("commerce.", "").replace(/_/g, " ");
  }
}

export function clientLog(level: LogLevel, message: string, metadata: Record<string, unknown> | null = null): ExecutionLog {
  return {
    id: `client-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    timestamp: new Date().toISOString(),
    level,
    message,
    taskId: null,
    metadata,
    source: "client",
    language: null,
    isDemo: false,
    sequence: null,
  };
}
