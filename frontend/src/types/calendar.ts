/** Phase 5 Google Calendar. Mirrors `backend/app/schemas/calendar.py`. */

export interface CalendarEventRequest {
  title: string;
  description?: string | null;
  location?: string | null;
  start_at: string;
  end_at: string;
  timezone: string;
  attendee_emails: string[];
  reminder_minutes?: number | null;
  recurrence_rule?: string | null;
}

export interface CalendarConflict {
  title: string;
  start_label: string;
  end_label: string;
  kind: string;
}

export type ConflictCheckStatus = "NOT_REQUESTED" | "NO_CONFLICT_OBSERVED" | "CONFLICTS_FOUND" | "UNAVAILABLE";

export type CalendarEventStatus =
  | "PREPARED"
  | "APPROVAL_PENDING"
  | "REJECTED"
  | "EXPIRED"
  | "CREATING"
  | "CREATED"
  | "ALREADY_EXISTS"
  | "UNKNOWN"
  | "FAILED";

export interface CalendarEventReview {
  event: CalendarEventRequest;
  date_label: string;
  time_label: string;
  timezone_label: string;
  duration_minutes: number;
  assumptions: string[];
  conflict_status: ConflictCheckStatus;
  conflicts: CalendarConflict[];
  event_hash: string;
  status: CalendarEventStatus;
  approval_id?: string | null;
  message?: string | null;
  verified_reference?: string | null;
  observed_at?: string | null;
}

/** Attached to ApprovalRequest.calendar — exactly the event being approved. */
export interface CalendarApprovalDetails {
  title: string;
  date_label: string;
  time_label: string;
  timezone: string;
  timezone_label: string;
  start_at: string;
  end_at: string;
  location?: string | null;
  description?: string | null;
  attendee_emails: string[];
  reminder_minutes?: number | null;
  recurrence_rule?: string | null;
  conflict_status: ConflictCheckStatus;
  conflicts: CalendarConflict[];
  sends_invitations: boolean;
  event_hash: string;
}

export const CONFLICT_LABEL: Record<ConflictCheckStatus, string> = {
  NOT_REQUESTED: "Conflicts not checked",
  NO_CONFLICT_OBSERVED: "No overlapping events seen",
  CONFLICTS_FOUND: "Overlapping events found",
  UNAVAILABLE: "Calendar unreadable — conflicts unknown",
};

export const EVENT_STATUS_LABEL: Record<CalendarEventStatus, string> = {
  PREPARED: "Prepared",
  APPROVAL_PENDING: "Waiting for your approval",
  REJECTED: "Rejected — not created",
  EXPIRED: "Approval expired — not created",
  CREATING: "Creating…",
  CREATED: "Created (verified)",
  ALREADY_EXISTS: "Already on your calendar",
  UNKNOWN: "Unknown — please check",
  FAILED: "Not created",
};
