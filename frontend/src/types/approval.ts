import type { CalendarApprovalDetails } from "./calendar";
import type { PurchaseApprovalDetails } from "./checkout";

/** WITHDRAWN (Phase 6): the run was stopped or the server restarted — never resumable. */
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "WITHDRAWN";

export type ApprovalDecision = "APPROVE" | "REJECT";

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface ApprovalRequest {
  approval_id: string;
  task_id: string;
  session_id: string;
  action_summary: string;
  domain: string;
  reason: string;
  risk_level: RiskLevel;
  status: ApprovalStatus;
  estimated_impact?: string | null;
  expires_at: string;
  is_demo: boolean;
  created_at?: string;
  resolved_at?: string | null;
  decision?: ApprovalDecision | null;
  /** Phase 4: present only for an exact-order purchase review. */
  purchase?: PurchaseApprovalDetails | null;
  /** Phase 5: present only for an exact calendar-event review. */
  calendar?: CalendarApprovalDetails | null;
}

export interface SubmitApprovalRequest {
  decision: ApprovalDecision;
}

export interface ApprovalResponse {
  approval_id: string;
  decision: ApprovalDecision;
  status: ApprovalStatus;
  resolved_at: string;
}
