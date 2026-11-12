import { SESSION, TASK, uuidFor } from "../fixtures";

import type { ApprovalRequest } from "@/types/approval";
import type { CalendarEventReview } from "@/types/calendar";
import type { DownloadedFile } from "@/types/files";
import type { EmailDraftView } from "@/types/gmail";
import type { WorkflowState } from "@/types/workflow";
import type { YouTubeResults } from "@/types/youtube";

export const NOW = "2026-11-09T10:00:00.000000+00:00";

export function calendarApproval(overrides: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    approval_id: uuidFor(700), task_id: TASK, session_id: SESSION,
    action_summary: "Create calendar event “Meeting with Rahul” on Tuesday, November 10, 2026, 3:00 PM – 3:30 PM",
    domain: "Calendar test fixture", reason: "TaskPilot will create exactly this event and nothing else.", risk_level: "HIGH",
    status: "PENDING", estimated_impact: "No overlapping events were seen on that day. No attendees — no invitations are sent.",
    expires_at: "2099-01-01T00:00:00Z", is_demo: false, created_at: NOW,
    calendar: {
      title: "Meeting with Rahul", date_label: "Tuesday, November 10, 2026", time_label: "3:00 PM – 3:30 PM", timezone: "Asia/Kolkata",
      timezone_label: "Asia/Kolkata (IST, UTC+05:30)", start_at: "2026-11-10T09:30:00Z", end_at: "2026-11-10T10:00:00Z",
      location: null, description: null, attendee_emails: [], reminder_minutes: null, recurrence_rule: null,
      conflict_status: "NO_CONFLICT_OBSERVED", conflicts: [], sends_invitations: false, event_hash: "a".repeat(64),
    },
    ...overrides,
  };
}

export function draftView(overrides: Partial<EmailDraftView> = {}): EmailDraftView {
  return {
    draft: {
      status: "NOT_STARTED", recipients_masked: ["h•••@example.com"], recipient_count: 1, cc_count: 0, subject: "Internship opportunities",
      body_preview: "Hi,", saved_at: null, verified: false, sent: false, message: "Planned draft — nothing has been written to Gmail yet.",
      send_blocked: false,
    },
    body: "Hi,\n\nI'm writing regarding internship opportunities.\n\nBest regards,\n[Your name]",
    editable: true,
    recipients: ["hr@example.com"],
    ...overrides,
  };
}

export const VIDEO = {
  option_id: "v1", video_id: "pyBasics001", title: "Python Tutorial for Beginners - Full Course", channel_name: "Code Fixture Academy",
  duration: "4:26:52", views: "41M views", published_label: "5 years ago", video_url: "https://www.youtube.com/watch?v=pyBasics001",
  thumbnail_url: null, relevance: 1, observed_at: NOW,
};

export function youtubeResults(overrides: Partial<YouTubeResults> = {}): YouTubeResults {
  return {
    results: [VIDEO, { ...VIDEO, option_id: "v2", video_id: "pyBasics002", title: "Learn Python in 1 Hour", video_url: "https://www.youtube.com/watch?v=pyBasics002", relevance: 0.5 }],
    selected: VIDEO,
    playback: { state: "PLAYING", video: VIDEO, page_url: null, current_time: 3.2, message: "The video is playing (playback time is advancing).", observed_at: NOW },
    pending_choice: null,
    ...overrides,
  };
}

export function workflowState(overrides: Partial<WorkflowState> = {}): WorkflowState {
  return {
    workflow_id: uuidFor(800), task_id: TASK, session_id: SESSION, domains: ["YOUTUBE", "GMAIL"],
    steps: [
      { step_id: uuidFor(801), order: 1, domain: "YOUTUBE", capability: "YOUTUBE_SEARCH", label: "Search YouTube", status: "COMPLETED",
        depends_on: [], message: "Selected “Python Tutorial for Beginners - Full Course”.", error_code: null, produces: ["youtube.video_reference"], consumes: [] },
      { step_id: uuidFor(802), order: 2, domain: "GMAIL", capability: "GMAIL_CREATE_DRAFT", label: "Save Gmail draft", status: "NOT_STARTED",
        depends_on: [uuidFor(801)], message: null, error_code: null, produces: ["gmail.draft_reference"], consumes: ["youtube.video_reference"] },
    ],
    outputs: [], status: "RUNNING", current_domain: "GMAIL", pending_choice: null, pending_approval_id: null, final_result: null,
    youtube_results: [], youtube_selected: null, youtube_playback: null, gmail_draft: null, calendar: null, downloads: [], updated_at: NOW,
    ...overrides,
  };
}

export function calendarReview(overrides: Partial<CalendarEventReview> = {}): CalendarEventReview {
  return {
    event: { title: "Meeting with Rahul", start_at: "2026-11-10T09:30:00Z", end_at: "2026-11-10T10:00:00Z", timezone: "Asia/Kolkata", attendee_emails: [] },
    date_label: "Tuesday, November 10, 2026", time_label: "3:00 PM – 3:30 PM", timezone_label: "Asia/Kolkata (IST, UTC+05:30)",
    duration_minutes: 30, assumptions: ["Timezone: Asia/Kolkata (your default)."], conflict_status: "NO_CONFLICT_OBSERVED", conflicts: [],
    event_hash: "a".repeat(64), status: "CREATED", approval_id: uuidFor(700), message: "Event created and found on your calendar.",
    verified_reference: "ev1", observed_at: NOW, ...overrides,
  };
}

export function downloadedFile(overrides: Partial<DownloadedFile> = {}): DownloadedFile {
  return {
    file_id: uuidFor(900), session_id: SESSION, task_id: TASK, original_name: "report.pdf", stored_name: `${uuidFor(900)}.pdf`, extension: "pdf",
    mime_type: "application/pdf", size_bytes: 409, sha256: "b".repeat(64), source_domain: "127.0.0.1", status: "COMPLETED", created_at: NOW,
    expires_at: null, validation: ["extension allowed"], ...overrides,
  };
}
