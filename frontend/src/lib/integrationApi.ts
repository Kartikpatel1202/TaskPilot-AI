/**
 * Phase 5 integrations REST client. Every response is validated with Zod; everything shown comes
 * from what the backend observed (or, before Run Plan, from the validated plan).
 * No call here sends email, creates a calendar event or downloads a file: those happen only
 * inside a run — calendar creation additionally needs the exact-event approval.
 */

import { z } from "zod";

import { API_BASE_URL, API_PREFIX } from "./constants";
import { request } from "./api";
import {
  calendarConflictSchema,
  capabilitySchema,
  conflictStatusSchema,
  domainTypeSchema,
  riskLevelSchema,
} from "./validators";

import type { CalendarEventReview } from "@/types/calendar";
import type { DownloadedFile } from "@/types/files";
import type { EmailDraftView } from "@/types/gmail";
import type { CapabilityDefinition, DomainStatusEntry } from "@/types/integration";
import type { WorkflowState } from "@/types/workflow";
import type { YouTubeResults } from "@/types/youtube";

const uuid = z.string().uuid();
const isoDate = z.string().datetime({ offset: true });
const httpsUrl = z.string().url().refine((u) => /^https?:\/\//.test(u), "http(s) only");

export const capabilityDefinitionSchema = z.object({
  capability: capabilitySchema,
  domain: domainTypeSchema,
  description: z.string().max(500),
  input_schema: z.record(z.unknown()),
  requires_browser: z.boolean(),
  requires_approval: z.boolean(),
  risk_level: riskLevelSchema,
  enabled: z.boolean(),
  action_type: z.string().max(40).nullable().optional(),
});

export const domainStatusSchema = z.object({
  domain: domainTypeSchema,
  label: z.string().max(80),
  status: z.enum(["NOT_CONFIGURED", "AVAILABLE", "AUTHENTICATION_REQUIRED", "CONNECTED", "BLOCKED", "ERROR"]),
  message: z.string().max(500),
  capabilities: z.array(capabilitySchema),
  observed_at: isoDate.nullable().optional(),
});

export const pendingChoiceSchema = z.object({
  choice_id: uuid,
  task_id: uuid,
  step_id: uuid,
  domain: domainTypeSchema,
  question: z.string().max(300),
  options: z.array(z.object({ option_id: z.string().max(40), label: z.string().max(300), detail: z.string().max(300).nullable().optional() })).max(20),
  expires_at: isoDate,
});

export const videoSchema = z.object({
  option_id: z.string().max(10),
  video_id: z.string().max(20).nullable().optional(),
  title: z.string().max(300),
  channel_name: z.string().max(200).nullable().optional(),
  duration: z.string().max(20).nullable().optional(),
  views: z.string().max(60).nullable().optional(),
  published_label: z.string().max(60).nullable().optional(),
  video_url: httpsUrl,
  thumbnail_url: z.string().url().refine((u) => u.startsWith("https://"), "https only").nullable().optional(),
  relevance: z.number().min(0).max(1),
  observed_at: isoDate,
});

export const playbackSchema = z.object({
  state: z.enum(["PLAYING", "PAUSED", "BUFFERING", "LOGIN_REQUIRED", "PLAYBACK_BLOCKED", "UNKNOWN"]),
  video: videoSchema.nullable().optional(),
  page_url: z.string().nullable().optional(),
  current_time: z.number().nullable().optional(),
  message: z.string().max(500),
  observed_at: isoDate,
});

export const draftSummarySchema = z.object({
  status: z.enum(["NOT_STARTED", "DRAFT_COMPOSED", "DRAFT_SAVE_PENDING", "DRAFT_SAVED", "DRAFT_SAVE_FAILED", "SAVE_STATUS_UNKNOWN", "LOGIN_REQUIRED"]),
  recipients_masked: z.array(z.string().max(260)).max(50),
  recipient_count: z.number().int().nonnegative(),
  cc_count: z.number().int().nonnegative(),
  subject: z.string().max(200),
  body_preview: z.string().max(200).nullable().optional(),
  saved_at: isoDate.nullable().optional(),
  verified: z.boolean(),
  sent: z.literal(false),
  message: z.string().max(1000),
  send_blocked: z.boolean(),
});

export const emailDraftViewSchema = z.object({
  draft: draftSummarySchema,
  body: z.string().max(12_000).nullable(),
  editable: z.boolean(),
  recipients: z.array(z.string().max(254)).max(50).optional(),
});

export const calendarReviewSchema = z.object({
  event: z.object({
    title: z.string().max(200),
    description: z.string().max(5000).nullable().optional(),
    location: z.string().max(300).nullable().optional(),
    start_at: isoDate,
    end_at: isoDate,
    timezone: z.string().max(64),
    attendee_emails: z.array(z.string().max(254)).max(200),
    reminder_minutes: z.number().int().nullable().optional(),
    recurrence_rule: z.string().max(120).nullable().optional(),
  }),
  date_label: z.string().max(80),
  time_label: z.string().max(80),
  timezone_label: z.string().max(120),
  duration_minutes: z.number().int(),
  assumptions: z.array(z.string().max(500)).max(10),
  conflict_status: conflictStatusSchema,
  conflicts: z.array(calendarConflictSchema).max(20),
  event_hash: z.string().max(128),
  status: z.enum(["PREPARED", "APPROVAL_PENDING", "REJECTED", "EXPIRED", "CREATING", "CREATED", "ALREADY_EXISTS", "UNKNOWN", "FAILED"]),
  approval_id: uuid.nullable().optional(),
  message: z.string().max(1000).nullable().optional(),
  verified_reference: z.string().max(200).nullable().optional(),
  observed_at: isoDate.nullable().optional(),
});

export const downloadedFileSchema = z.object({
  file_id: uuid,
  session_id: uuid,
  task_id: uuid,
  original_name: z.string().max(120),
  stored_name: z.string().max(80),
  extension: z.string().max(10),
  mime_type: z.string().max(120),
  size_bytes: z.number().int().nonnegative(),
  sha256: z.string().regex(/^[0-9a-f]{64}$/),
  source_domain: z.string().max(253),
  status: z.enum(["QUEUED", "DOWNLOADING", "VALIDATING", "COMPLETED", "BLOCKED", "FAILED"]),
  created_at: isoDate,
  expires_at: isoDate.nullable().optional(),
  validation: z.array(z.string().max(200)).max(20),
});

const attemptSchema = z.object({
  status: z.enum(["QUEUED", "DOWNLOADING", "VALIDATING", "COMPLETED", "BLOCKED", "FAILED"]),
  message: z.string().max(1000),
  code: z.string().max(80).nullable().optional(),
  file: downloadedFileSchema.nullable().optional(),
  source_domain: z.string().max(253).nullable().optional(),
});

export const workflowStateSchema = z.object({
  workflow_id: uuid,
  task_id: uuid,
  session_id: uuid,
  domains: z.array(domainTypeSchema),
  steps: z.array(z.object({
    step_id: uuid,
    order: z.number().int().positive(),
    domain: domainTypeSchema,
    capability: capabilitySchema,
    label: z.string().max(100),
    status: z.enum(["NOT_STARTED", "RUNNING", "WAITING_USER", "COMPLETED", "FAILED", "BLOCKED", "SKIPPED"]),
    depends_on: z.array(uuid),
    message: z.string().max(1000).nullable().optional(),
    error_code: z.string().max(80).nullable().optional(),
    produces: z.array(z.string().max(60)),
    consumes: z.array(z.string().max(60)),
  })).max(60),
  outputs: z.array(z.object({ type: z.string().max(60), step_id: uuid, data: z.record(z.string().max(2048)) })).max(20),
  status: z.enum(["PLANNED", "RUNNING", "WAITING_USER", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]),
  current_domain: domainTypeSchema.nullable().optional(),
  pending_choice: pendingChoiceSchema.nullable().optional(),
  pending_approval_id: uuid.nullable().optional(),
  final_result: z.string().max(1000).nullable().optional(),
  youtube_results: z.array(videoSchema).max(20),
  youtube_selected: videoSchema.nullable().optional(),
  youtube_playback: playbackSchema.nullable().optional(),
  gmail_draft: draftSummarySchema.nullable().optional(),
  calendar: calendarReviewSchema.nullable().optional(),
  downloads: z.array(attemptSchema).max(20),
  updated_at: isoDate,
});

const youtubeResultsSchema = z.object({
  results: z.array(videoSchema).max(20),
  selected: videoSchema.nullable(),
  playback: playbackSchema.nullable(),
  pending_choice: pendingChoiceSchema.nullable(),
});

const q = (sessionId: string) => `session_id=${encodeURIComponent(sessionId)}`;
const t = (id: string) => encodeURIComponent(id);

export const getCapabilities = () =>
  request<CapabilityDefinition[]>("/integrations/capabilities", { schema: z.array(capabilityDefinitionSchema) as z.ZodType<CapabilityDefinition[]> });

export const getIntegrationStatus = (sessionId: string) =>
  request<DomainStatusEntry[]>(`/integrations/status?${q(sessionId)}`, { schema: z.array(domainStatusSchema) as z.ZodType<DomainStatusEntry[]> });

export const getWorkflow = (taskId: string, sessionId: string) =>
  request<WorkflowState>(`/tasks/${t(taskId)}/workflow?${q(sessionId)}`, { schema: workflowStateSchema as z.ZodType<WorkflowState> });

export const answerChoice = (taskId: string, sessionId: string, choiceId: string, optionId: string | null) =>
  request<{ accepted: boolean }>(`/tasks/${t(taskId)}/workflow/choice`, {
    method: "POST",
    body: { session_id: sessionId, choice_id: choiceId, option_id: optionId },
    schema: z.object({ accepted: z.boolean() }).passthrough(),
  });

export const getYouTubeResults = (taskId: string, sessionId: string) =>
  request<YouTubeResults>(`/tasks/${t(taskId)}/youtube/results?${q(sessionId)}`, { schema: youtubeResultsSchema as z.ZodType<YouTubeResults> });

export const getEmailDraft = (taskId: string, sessionId: string) =>
  request<EmailDraftView>(`/tasks/${t(taskId)}/gmail/draft?${q(sessionId)}`, { schema: emailDraftViewSchema as z.ZodType<EmailDraftView> });

export const updateEmailDraft = (taskId: string, sessionId: string, subject: string, body: string) =>
  request<EmailDraftView>(`/tasks/${t(taskId)}/gmail/draft`, {
    method: "PUT",
    body: { session_id: sessionId, subject, body },
    schema: emailDraftViewSchema as z.ZodType<EmailDraftView>,
  });

export const getCalendarReview = (taskId: string, sessionId: string) =>
  request<CalendarEventReview>(`/tasks/${t(taskId)}/calendar/review?${q(sessionId)}`, { schema: calendarReviewSchema as z.ZodType<CalendarEventReview> });

export const listFiles = (sessionId: string) =>
  request<DownloadedFile[]>(`/files?${q(sessionId)}`, { schema: z.array(downloadedFileSchema) as z.ZodType<DownloadedFile[]> });

export const deleteFile = (fileId: string, sessionId: string) =>
  request<{ deleted: boolean }>(`/files/${t(fileId)}`, {
    method: "DELETE",
    body: { session_id: sessionId, confirm: true },
    schema: z.object({ deleted: z.boolean() }).passthrough(),
  });

/** Attachment link for a validated file (served with nosniff; owner session only). */
export const fileDownloadUrl = (fileId: string, sessionId: string) => `${API_BASE_URL}${API_PREFIX}/files/${t(fileId)}/download?${q(sessionId)}`;
