import type { RiskLevel } from "./approval";
import type { CommerceAction } from "./commerce";
import type { IntegrationAction } from "./integration";
import type { IntentType } from "./intent";
import type { Language } from "./telemetry";

export type PlanStatus = "READY" | "NEEDS_CLARIFICATION" | "REJECTED" | "FAILED";

export interface NavigateAction {
  type: "navigate";
  url: string;
  purpose: string;
}

export interface ClickAction {
  type: "click";
  target_description: string;
  role_hint?: string | null;
  accessible_name?: string | null;
  text_hint?: string | null;
}

export interface TypeAction {
  type: "type";
  target_description: string;
  text: string;
  clear_first: boolean;
  sensitive: boolean;
}

export interface ExtractAction {
  type: "extract";
  target_description: string;
  fields: string[];
}

export interface RequestApprovalAction {
  type: "request_approval";
  reason: string;
  risk_level: RiskLevel;
  details: Record<string, string>;
}

export interface StopAction {
  type: "stop";
  reason: string;
}

export type SupportedAction =
  | NavigateAction
  | ClickAction
  | TypeAction
  | ExtractAction
  | RequestApprovalAction
  | StopAction
  | CommerceAction
  // Phase 5: built only by the backend's deterministic integration planner.
  | IntegrationAction;

export type ActionType = SupportedAction["type"];

export interface PlannedAction {
  step_id: string;
  order: number;
  action: SupportedAction;
  description: string;
  expected_outcome: string;
  risk_level: RiskLevel;
  requires_approval: boolean;
  depends_on: string[];
}

export interface ClarificationExchange {
  question: string;
  answer: string;
  answered_at: string;
}

export interface TaskPlan {
  plan_id: string;
  task_id: string;
  session_id: string;
  status: PlanStatus;
  intent: IntentType;
  summary: string;
  user_facing_message: string;
  language: Language;
  target_website: string | null;
  confidence: number;
  assumptions: string[];
  clarification_question: string | null;
  missing_information: string[];
  clarification_history: ClarificationExchange[];
  steps: PlannedAction[];
  requires_human_approval: boolean;
  provider: string;
  model: string;
  is_mock: boolean;
  created_at: string;
  schema_version: string;
}
