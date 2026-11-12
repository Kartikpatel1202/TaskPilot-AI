/** Phase 5 Gmail drafts. Mirrors `backend/app/schemas/gmail.py`. TaskPilot never sends email. */

export type DraftStatus =
  | "NOT_STARTED"
  | "DRAFT_COMPOSED"
  | "DRAFT_SAVE_PENDING"
  | "DRAFT_SAVED"
  | "DRAFT_SAVE_FAILED"
  | "SAVE_STATUS_UNKNOWN"
  | "LOGIN_REQUIRED";

export interface EmailDraftSummary {
  status: DraftStatus;
  recipients_masked: string[];
  recipient_count: number;
  cc_count: number;
  subject: string;
  body_preview?: string | null;
  saved_at?: string | null;
  verified: boolean;
  /** Always false: drafts are never sent by TaskPilot. */
  sent: false;
  message: string;
  send_blocked: boolean;
}

export interface EmailDraftView {
  draft: EmailDraftSummary;
  body: string | null;
  /** True only before Run Plan (the planned draft can still be edited). */
  editable: boolean;
  recipients?: string[];
}

export const DRAFT_STATUS_LABEL: Record<DraftStatus, string> = {
  NOT_STARTED: "Planned (not written yet)",
  DRAFT_COMPOSED: "Composed",
  DRAFT_SAVE_PENDING: "Saving…",
  DRAFT_SAVED: "Saved in Drafts",
  DRAFT_SAVE_FAILED: "Save failed",
  SAVE_STATUS_UNKNOWN: "Save status unknown",
  LOGIN_REQUIRED: "Sign-in needed",
};
