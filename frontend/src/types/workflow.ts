/** Phase 5 multi-domain workflow state. Mirrors `backend/app/schemas/workflow.py`. */

import type { CalendarEventReview } from "./calendar";
import type { DownloadAttempt } from "./files";
import type { EmailDraftSummary } from "./gmail";
import type { DomainType, IntegrationCapability, PendingChoice } from "./integration";
import type { YouTubePlayback, YouTubeVideo } from "./youtube";

export type WorkflowStepStatus = "NOT_STARTED" | "RUNNING" | "WAITING_USER" | "COMPLETED" | "FAILED" | "BLOCKED" | "SKIPPED";

export type IntegrationWorkflowStatus = "PLANNED" | "RUNNING" | "WAITING_USER" | "COMPLETED" | "PARTIAL" | "FAILED" | "CANCELLED";

export interface WorkflowStep {
  step_id: string;
  order: number;
  domain: DomainType;
  capability: IntegrationCapability;
  label: string;
  status: WorkflowStepStatus;
  depends_on: string[];
  message?: string | null;
  error_code?: string | null;
  produces: string[];
  consumes: string[];
}

export interface WorkflowOutput {
  type: string;
  step_id: string;
  data: Record<string, string>;
}

export interface WorkflowState {
  workflow_id: string;
  task_id: string;
  session_id: string;
  domains: DomainType[];
  steps: WorkflowStep[];
  outputs: WorkflowOutput[];
  status: IntegrationWorkflowStatus;
  current_domain?: DomainType | null;
  pending_choice?: PendingChoice | null;
  pending_approval_id?: string | null;
  final_result?: string | null;
  youtube_results: YouTubeVideo[];
  youtube_selected?: YouTubeVideo | null;
  youtube_playback?: YouTubePlayback | null;
  gmail_draft?: EmailDraftSummary | null;
  calendar?: CalendarEventReview | null;
  downloads: DownloadAttempt[];
  updated_at: string;
}

export const WORKFLOW_STATUS_LABEL: Record<IntegrationWorkflowStatus, string> = {
  PLANNED: "Planned",
  RUNNING: "Running…",
  WAITING_USER: "Needs you",
  COMPLETED: "Completed",
  PARTIAL: "Partly done",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

export const STEP_STATUS_LABEL: Record<WorkflowStepStatus, string> = {
  NOT_STARTED: "Not started",
  RUNNING: "Running",
  WAITING_USER: "Waiting for you",
  COMPLETED: "Done",
  FAILED: "Failed",
  BLOCKED: "Blocked",
  SKIPPED: "Skipped",
};
