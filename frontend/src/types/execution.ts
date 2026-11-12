/** Phase 3 execution types. Mirrors `backend/app/schemas/execution.py`. */

export type ActionExecutionStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "BLOCKED" | "SKIPPED";

export type ExecutionStatus = "QUEUED" | "EXECUTING" | "WAITING_APPROVAL" | "COMPLETED" | "FAILED" | "CANCELLED";

export const TERMINAL_EXECUTION_STATUSES: readonly ExecutionStatus[] = ["COMPLETED", "FAILED", "CANCELLED"];

export interface ActionResult {
  step_id: string;
  order: number;
  action_type: string;
  status: ActionExecutionStatus;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  message: string;
  error_code?: string | null;
  extracted_data?: Record<string, unknown> | null;
  retry_count: number;
  verified: boolean;
  strategy?: string | null;
  confidence?: number | null;
}

export interface ExecutionSummary {
  task_id: string;
  session_id: string;
  plan_id: string;
  status: ExecutionStatus;
  total_steps: number;
  results: ActionResult[];
  started_at?: string | null;
  finished_at?: string | null;
  message?: string | null;
  error_code?: string | null;
}

export interface ExecuteTaskRequest {
  session_id: string;
  /** Must be literally true — execution only starts from an explicit click. */
  confirm_execution: true;
}

export interface ExecutionAcceptedResponse {
  task_id: string;
  session_id: string;
  status: "ACCEPTED";
  message: string;
}

export interface StopTaskResponse {
  task_id: string;
  status: "STOPPING" | "CANCELLED";
  message: string;
}

/** One step as observed during execution (from telemetry). */
export interface ExecutionStepView {
  stepId: string;
  order: number;
  actionType: string;
  description: string | null;
  status: ActionExecutionStatus;
  message: string | null;
  errorCode: string | null;
  durationMs: number | null;
  verified: boolean;
  extractedData: Record<string, unknown> | null;
}

export interface ExecutionState {
  taskId: string;
  planId: string | null;
  status: ExecutionStatus;
  totalSteps: number;
  steps: Record<string, ExecutionStepView>;
  currentStepId: string | null;
  pausedApprovalId: string | null;
  message: string | null;
  errorCode: string | null;
  counts: { succeeded: number; failed: number; blocked: number; skipped: number } | null;
  headless: boolean | null;
  startedAt: string | null;
  finishedAt: string | null;
  /** The user clicked Stop and the request was accepted. */
  stopRequested: boolean;
}
