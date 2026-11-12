import type { InputMode, TaskState } from "./task";

/** What the dashboard shows about Kamlesh Bhai for the active task. */
export type AgentStatus = "IDLE" | "PLANNING" | "NEEDS_CLARIFICATION" | "PLAN_READY" | "REJECTED" | "ERROR";

export type PlanningStage =
  | "UNDERSTANDING_COMMAND"
  | "CLASSIFYING_INTENT"
  | "BUILDING_PLAN"
  | "VALIDATING_PLAN"
  | "FINALIZING";

export interface PlanningProgress {
  stage: PlanningStage;
  progress: number;
  message: string;
}

export interface ClarificationRequest {
  taskId: string;
  planId: string;
  question: string;
  missingInformation: string[];
}

export interface SubmitClarificationRequest {
  session_id: string;
  message: string;
  input_mode: InputMode;
}

export interface ClarificationAcceptedResponse {
  task_id: string;
  accepted: boolean;
  state: TaskState;
  message: string;
}

export type AgentAvailability = "available" | "disabled" | "misconfigured" | "unavailable";

export interface AgentStatusResponse {
  agent_name: string;
  provider: string;
  model: string;
  status: AgentAvailability;
  planning_enabled: boolean;
  browser_execution_enabled: boolean;
  is_mock: boolean;
  provider_reachable: boolean | null;
  /** "ai" when a real LLM plans; "offline_rules" for the offline rule-based planner. */
  planner_kind?: "ai" | "offline_rules";
  /** Shown when no AI planner is configured (what to set up). */
  setup_hint?: string | null;
}

export interface PlanningFailure {
  taskId: string;
  code: string;
  message: string;
}

/** Tracks the REST fetch of a plan announced over WebSocket. */
export interface PlanFetchState {
  taskId: string;
  planId: string;
  status: "pending" | "loading" | "error";
  error: string | null;
}
