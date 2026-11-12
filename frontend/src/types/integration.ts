/** Phase 5 multi-domain integrations. Mirrors `backend/app/schemas/integration.py`. */

import type { RiskLevel } from "./approval";

export type DomainType = "YOUTUBE" | "GMAIL" | "GOOGLE_CALENDAR" | "FILES" | "BLINKIT" | "AMAZON_IN";

export type IntegrationCapability =
  | "YOUTUBE_SEARCH"
  | "YOUTUBE_PLAY"
  | "GMAIL_CREATE_DRAFT"
  | "GMAIL_READ_DRAFT"
  | "CALENDAR_LIST_EVENTS"
  | "CALENDAR_CREATE_EVENT"
  | "FILE_DOWNLOAD"
  | "FILE_INSPECT"
  | "COMMERCE_SEARCH"
  | "COMMERCE_CART";

export interface CapabilityDefinition {
  capability: IntegrationCapability;
  domain: DomainType;
  description: string;
  input_schema: Record<string, unknown>;
  requires_browser: boolean;
  requires_approval: boolean;
  risk_level: RiskLevel;
  enabled: boolean;
  action_type?: string | null;
}

export type DomainStatus = "NOT_CONFIGURED" | "AVAILABLE" | "AUTHENTICATION_REQUIRED" | "CONNECTED" | "BLOCKED" | "ERROR";

export interface DomainStatusEntry {
  domain: DomainType;
  label: string;
  status: DomainStatus;
  message: string;
  capabilities: IntegrationCapability[];
  observed_at?: string | null;
}

export const DOMAIN_LABEL: Record<DomainType, string> = {
  YOUTUBE: "YouTube",
  GMAIL: "Gmail",
  GOOGLE_CALENDAR: "Google Calendar",
  FILES: "Safe downloads",
  BLINKIT: "Blinkit",
  AMAZON_IN: "Amazon India",
};

export interface ChoiceOption {
  option_id: string;
  label: string;
  detail?: string | null;
}

export interface PendingChoice {
  choice_id: string;
  task_id: string;
  step_id: string;
  domain: DomainType;
  question: string;
  options: ChoiceOption[];
  expires_at: string;
}

export const INTEGRATION_EVENT_TYPES = [
  "integration.domain_selected",
  "integration.capability_selected",
  "integration.authentication_required",
  "integration.session_ready",
  "integration.error",
  "youtube.search_started",
  "youtube.search_completed",
  "youtube.results_found",
  "youtube.video_selected",
  "youtube.playback_started",
  "youtube.playback_paused",
  "youtube.playback_error",
  "gmail.draft_started",
  "gmail.draft_composed",
  "gmail.draft_saved",
  "gmail.draft_verified",
  "gmail.draft_failed",
  "gmail.send_blocked",
  "calendar.event_prepared",
  "calendar.conflict_detected",
  "calendar.approval_required",
  "calendar.approval_resolved",
  "calendar.event_creation_started",
  "calendar.event_created",
  "calendar.event_creation_failed",
  "file.download_started",
  "file.download_progress",
  "file.download_completed",
  "file.download_blocked",
  "file.download_failed",
  "file.validation_completed",
  "workflow.step_started",
  "workflow.step_completed",
  "workflow.step_failed",
  "workflow.partial_success",
  "workflow.completed",
] as const;

export type IntegrationEventType = (typeof INTEGRATION_EVENT_TYPES)[number];

/** One bounded payload for every integration event (never email bodies, full addresses or paths). */
export interface IntegrationEventData {
  domain?: DomainType | null;
  message: string;
  status?: string | null;
  step_id?: string | null;
  capability?: IntegrationCapability | null;
  code?: string | null;
  result_count?: number | null;
  choice_id?: string | null;
  approval_id?: string | null;
  file_id?: string | null;
  bytes_received?: number | null;
  completed_steps?: number | null;
  total_steps?: number | null;
}

export type IntegrationActionType = "youtube_search" | "youtube_play" | "gmail_create_draft" | "calendar_create_event" | "file_download";

export const INTEGRATION_ACTION_TYPES: readonly IntegrationActionType[] = [
  "youtube_search",
  "youtube_play",
  "gmail_create_draft",
  "calendar_create_event",
  "file_download",
];

export type OutputType = "youtube.video_reference" | "file.reference";

export interface YouTubeSearchAction {
  type: "youtube_search";
  query: string;
  max_results: number;
  preferred_channel?: string | null;
  select: boolean;
  site_key: string;
  continue_on_failure: boolean;
}

export interface YouTubePlayAction {
  type: "youtube_play";
  video_reference: string;
  site_key: string;
  continue_on_failure: boolean;
}

export interface GmailCreateDraftAction {
  type: "gmail_create_draft";
  recipient_emails: string[];
  cc_emails: string[];
  subject: string;
  body: string;
  tone?: string | null;
  purpose?: string | null;
  insert_outputs: OutputType[];
  send_requested: boolean;
  site_key: string;
  continue_on_failure: boolean;
}

export interface CalendarCreateEventAction {
  type: "calendar_create_event";
  title: string;
  start_at: string;
  end_at: string;
  timezone: string;
  description?: string | null;
  location?: string | null;
  attendee_emails: string[];
  reminder_minutes?: number | null;
  recurrence_rule?: string | null;
  check_conflicts: boolean;
  assumptions: string[];
  site_key: string;
  continue_on_failure: boolean;
}

export interface FileDownloadAction {
  type: "file_download";
  source_url: string;
  file_description: string;
  expected_extension?: string | null;
  suggested_filename?: string | null;
  site_key: string;
  continue_on_failure: boolean;
}

export type IntegrationAction =
  | YouTubeSearchAction
  | YouTubePlayAction
  | GmailCreateDraftAction
  | CalendarCreateEventAction
  | FileDownloadAction;
