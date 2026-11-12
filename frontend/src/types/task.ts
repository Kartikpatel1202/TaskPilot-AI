export type TaskState =
  | "IDLE"
  | "PLANNING"
  | "PLANNED"
  | "NEEDS_CLARIFICATION"
  | "EXECUTING"
  | "WAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type InputMode = "TEXT" | "VOICE";

export interface Task {
  task_id: string;
  session_id: string;
  command: string;
  input_mode: InputMode;
  state: TaskState;
  created_at: string;
  updated_at: string;
  error_message?: string | null;
  is_demo?: boolean;
}

export interface CreateTaskRequest {
  command: string;
  session_id: string;
  input_mode: InputMode;
}

export interface TaskAcceptedResponse {
  task_id: string;
  session_id: string;
  state: TaskState;
  accepted: boolean;
  message: string;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  timestamp: string;
}

export const TERMINAL_TASK_STATES: readonly TaskState[] = ["COMPLETED", "FAILED", "CANCELLED"];
