import type { ApprovalDecision, ApprovalRequest, ApprovalStatus } from "./approval";
import type { BrowserSessionStatus } from "./browser";
import type { CommerceEventData, CommerceEventType } from "./commerce";
import type { IntegrationEventData, IntegrationEventType } from "./integration";
import type { ActionExecutionStatus, ExecutionStatus } from "./execution";
import type { PlanningStage } from "./agent";
import type { IntentType } from "./intent";
import type { PlanStatus } from "./plan";
import type { InputMode, TaskState } from "./task";

export type TelemetryEventType =
  | "connection.ready"
  | "task.accepted"
  | "task.state_changed"
  | "log.created"
  | "browser.preview"
  | "approval.required"
  | "approval.resolved"
  | "task.completed"
  | "task.failed"
  | "system.error"
  | "agent.intent_detected"
  | "agent.planning_started"
  | "agent.planning_progress"
  | "task.plan_ready"
  | "task.clarification_required"
  | "task.planning_failed"
  | "agent.response_generated"
  // Phase 3: browser + execution
  | "browser.session_started"
  | "browser.session_ready"
  | "browser.navigation_started"
  | "browser.navigation_completed"
  | "browser.navigation_blocked"
  | "browser.page_updated"
  | "browser.frame_available"
  | "browser.action_started"
  | "browser.action_completed"
  | "browser.action_failed"
  | "browser.authentication_required"
  | "browser.popup_blocked"
  | "browser.download_blocked"
  | "browser.session_closed"
  | "browser.session_error"
  | "browser.stream_connected"
  | "browser.stream_disconnected"
  | "task.execution_started"
  | "task.step_started"
  | "task.step_completed"
  | "task.step_failed"
  | "task.step_blocked"
  | "task.execution_paused"
  | "task.execution_resumed"
  | "task.execution_completed"
  | "task.execution_failed"
  | "task.execution_cancelled"
  // Phase 4: commerce
  | CommerceEventType
  // Phase 5: integrations (integration.*, youtube.*, gmail.*, calendar.*, file.*, workflow.*)
  | IntegrationEventType;

export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "SUCCESS";

export type LogSource = "system" | "assistant" | "demo" | "client";

export type Language = "en" | "hi" | "hinglish";

export interface TelemetryEvent<T = Record<string, unknown>> {
  event_id: string;
  session_id: string;
  task_id: string | null;
  sequence: number;
  type: TelemetryEventType;
  occurred_at: string;
  data: T;
}

// ------------------------------------------------------------------ payloads

export interface ConnectionReadyData {
  connection_id: string;
  server_version: string;
  assistant_name: string;
  heartbeat_interval_seconds: number;
  history_limit: number;
  demo_endpoints_enabled: boolean;
}

export interface TaskAcceptedData {
  task_id: string;
  state: TaskState;
  command: string;
  input_mode: InputMode;
  created_at: string;
  is_demo: boolean;
}

export interface TaskStateChangedData {
  previous_state: TaskState;
  new_state: TaskState;
  reason?: string | null;
  is_demo: boolean;
}

export interface LogCreatedData {
  level: LogLevel;
  message: string;
  source: Exclude<LogSource, "client">;
  language?: Language | null;
  metadata?: Record<string, unknown> | null;
  is_demo: boolean;
}

export type BrowserPreviewMode = "DISCONNECTED" | "PLACEHOLDER" | "FRAME";

export interface BrowserPreviewData {
  mode: BrowserPreviewMode;
  message: string;
  url?: string | null;
  /** Legacy inline frame field. Phase 3 frames arrive on the binary stream socket instead. */
  frame_data_url?: string | null;
  is_demo: boolean;
}

export interface ApprovalResolvedData {
  approval_id: string;
  decision: ApprovalDecision | null;
  status: ApprovalStatus;
  resolved_at: string;
  is_demo: boolean;
}

export interface TaskCompletedData {
  summary: string;
  is_demo: boolean;
}

export interface TaskFailedData {
  error_code: string;
  error_message: string;
  is_demo: boolean;
}

export interface SystemErrorData {
  code: string;
  message: string;
}

// ------------------------------------------------------------------ Phase 2 payloads

export interface IntentDetectedData {
  intent: IntentType;
  confidence: number;
  target_website: string | null;
  language: Language;
  requires_clarification: boolean;
  is_follow_up: boolean;
}

export interface PlanningStartedData {
  status: TaskState;
  message: string;
  is_clarification: boolean;
}

export interface PlanningProgressData {
  stage: PlanningStage;
  progress: number;
  message: string;
}

export interface PlanReadyData {
  plan_id: string;
  status: PlanStatus;
  intent: IntentType;
  summary: string;
  step_count: number;
  requires_human_approval: boolean;
  provider: string;
  model: string;
  is_mock: boolean;
}

export interface ClarificationRequiredData {
  plan_id: string;
  question: string;
  missing_information: string[];
}

export interface PlanningFailedData {
  code: string;
  message: string;
  retryable: boolean;
}

export type AgentResponseKind =
  | "acknowledgement"
  | "plan_ready"
  | "clarification"
  | "rejected"
  | "failed"
  | "chat"
  | "execution";

export interface AgentResponseData {
  message: string;
  language: Language;
  kind: AgentResponseKind;
}

// ------------------------------------------------------------------ Phase 3 payloads

export interface BrowserSessionData {
  status: BrowserSessionStatus;
  engine: string;
  headless: boolean;
  message?: string | null;
}

export interface BrowserNavigationData {
  url: string;
  domain?: string | null;
  title?: string | null;
  step_id?: string | null;
  message: string;
}

export interface NavigationBlockedData {
  url: string;
  domain?: string | null;
  reason_code: string;
  message: string;
  step_id?: string | null;
}

export interface PageUpdatedData {
  url: string | null;
  domain: string | null;
  title: string | null;
}

export interface FrameAvailableData {
  frame_id: string;
  sequence: number;
  width: number;
  height: number;
  bytes: number;
  captured_at: string;
}

export interface BrowserActionData {
  step_id: string;
  action_type: string;
  message: string;
  strategy?: string | null;
  confidence?: number | null;
  error_code?: string | null;
}

export interface AuthenticationRequiredData {
  domain: string | null;
  message: string;
  headless: boolean;
  step_id?: string | null;
}

export interface PopupBlockedData {
  url: string | null;
  message: string;
}

export interface DownloadBlockedData {
  filename: string | null;
  message: string;
}

export interface BrowserSessionClosedData {
  reason: string;
}

export interface BrowserSessionErrorData {
  code: string;
  message: string;
}

export interface BrowserStreamData {
  subscribers: number;
}

export interface ExecutionStartedData {
  plan_id: string;
  total_steps: number;
  engine: string;
  headless: boolean;
}

export interface StepStartedData {
  step_id: string;
  order: number;
  action_type: string;
  description: string;
}

export interface StepCompletedData {
  step_id: string;
  order: number;
  status: ActionExecutionStatus;
  duration_ms: number | null;
  message: string;
  verified: boolean;
  extracted_data?: Record<string, unknown> | null;
}

export interface StepFailedData {
  step_id: string;
  order: number;
  status: ActionExecutionStatus;
  error_code: string;
  message: string;
  duration_ms?: number | null;
}

export interface ExecutionPausedData {
  step_id: string;
  reason: string;
  approval_id?: string | null;
}

export interface ExecutionResumedData {
  step_id: string;
  message: string;
}

export interface ExecutionFinishedData {
  status: ExecutionStatus;
  total_steps: number;
  succeeded_steps: number;
  failed_steps: number;
  blocked_steps: number;
  skipped_steps: number;
  message: string;
  error_code?: string | null;
}

/** Phase 5: every integration event shares one bounded payload. */
type IntegrationDataMap = { [K in IntegrationEventType]: IntegrationEventData };

export interface TelemetryDataMap extends IntegrationDataMap {
  "connection.ready": ConnectionReadyData;
  "task.accepted": TaskAcceptedData;
  "task.state_changed": TaskStateChangedData;
  "log.created": LogCreatedData;
  "browser.preview": BrowserPreviewData;
  "approval.required": ApprovalRequest;
  "approval.resolved": ApprovalResolvedData;
  "task.completed": TaskCompletedData;
  "task.failed": TaskFailedData;
  "system.error": SystemErrorData;
  "agent.intent_detected": IntentDetectedData;
  "agent.planning_started": PlanningStartedData;
  "agent.planning_progress": PlanningProgressData;
  "task.plan_ready": PlanReadyData;
  "task.clarification_required": ClarificationRequiredData;
  "task.planning_failed": PlanningFailedData;
  "agent.response_generated": AgentResponseData;
  "browser.session_started": BrowserSessionData;
  "browser.session_ready": BrowserSessionData;
  "browser.navigation_started": BrowserNavigationData;
  "browser.navigation_completed": BrowserNavigationData;
  "browser.navigation_blocked": NavigationBlockedData;
  "browser.page_updated": PageUpdatedData;
  "browser.frame_available": FrameAvailableData;
  "browser.action_started": BrowserActionData;
  "browser.action_completed": BrowserActionData;
  "browser.action_failed": BrowserActionData;
  "browser.authentication_required": AuthenticationRequiredData;
  "browser.popup_blocked": PopupBlockedData;
  "browser.download_blocked": DownloadBlockedData;
  "browser.session_closed": BrowserSessionClosedData;
  "browser.session_error": BrowserSessionErrorData;
  "browser.stream_connected": BrowserStreamData;
  "browser.stream_disconnected": BrowserStreamData;
  "task.execution_started": ExecutionStartedData;
  "task.step_started": StepStartedData;
  "task.step_completed": StepCompletedData;
  "task.step_failed": StepFailedData;
  "task.step_blocked": StepFailedData;
  "task.execution_paused": ExecutionPausedData;
  "task.execution_resumed": ExecutionResumedData;
  "task.execution_completed": ExecutionFinishedData;
  "task.execution_failed": ExecutionFinishedData;
  "task.execution_cancelled": ExecutionFinishedData;
  "commerce.session_detected": CommerceEventData;
  "commerce.location_required": CommerceEventData;
  "commerce.search_started": CommerceEventData;
  "commerce.search_completed": CommerceEventData;
  "commerce.products_found": CommerceEventData;
  "commerce.product_selected": CommerceEventData;
  "commerce.product_ambiguous": CommerceEventData;
  "commerce.product_unavailable": CommerceEventData;
  "commerce.cart_update_started": CommerceEventData;
  "commerce.cart_item_added": CommerceEventData;
  "commerce.cart_item_updated": CommerceEventData;
  "commerce.cart_verification_started": CommerceEventData;
  "commerce.cart_verification_completed": CommerceEventData;
  "commerce.cart_verification_failed": CommerceEventData;
  "commerce.price_changed": CommerceEventData;
  "commerce.checkout_review_ready": CommerceEventData;
  "commerce.purchase_approval_required": CommerceEventData;
  "commerce.purchase_rejected": CommerceEventData;
  "commerce.payment_handoff": CommerceEventData;
  "commerce.order_submission_started": CommerceEventData;
  "commerce.order_confirmed": CommerceEventData;
  "commerce.order_status_unknown": CommerceEventData;
  "commerce.workflow_failed": CommerceEventData;
}

/** Discriminated union of every concrete, validated telemetry event. */
export type AnyTelemetryEvent = {
  [K in TelemetryEventType]: Omit<TelemetryEvent<TelemetryDataMap[K]>, "type"> & { type: K };
}[TelemetryEventType];

// ------------------------------------------------------------------ control frames

export type ControlMessage =
  | { type: "pong" }
  | { type: "subscribed"; replayed: number; complete: boolean }
  | { type: "error"; code: string; message: string };

export type ClientMessage = { type: "subscribe"; after_event_id: string | null } | { type: "ping" };

export type ServerMessage =
  | { kind: "event"; event: AnyTelemetryEvent }
  | { kind: "control"; message: ControlMessage };

// ------------------------------------------------------------------ UI state

export type ConnectionStatus = "CONNECTING" | "CONNECTED" | "RECONNECTING" | "DISCONNECTED" | "ERROR";

export interface ExecutionLog {
  id: string;
  timestamp: string;
  level: LogLevel;
  message: string;
  taskId: string | null;
  metadata: Record<string, unknown> | null;
  source: LogSource;
  language: Language | null;
  isDemo: boolean;
  sequence: number | null;
}

export interface BrowserPreviewState {
  mode: BrowserPreviewMode;
  message: string;
  url: string | null;
  frameDataUrl: string | null;
  isDemo: boolean;
  taskId: string | null;
  updatedAt: string | null;
}
