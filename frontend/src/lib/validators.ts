import { z } from "zod";

import type { ApprovalRequest, ApprovalResponse } from "@/types/approval";
import type { HealthResponse, TaskAcceptedResponse } from "@/types/task";
import type { AnyTelemetryEvent, ControlMessage, ServerMessage } from "@/types/telemetry";
import { INTEGRATION_EVENT_TYPES } from "@/types/integration";

const uuid = z.string().uuid();
const isoDate = z.string().datetime({ offset: true });

export const taskStateSchema = z.enum([
  "IDLE",
  "PLANNING",
  "PLANNED",
  "NEEDS_CLARIFICATION",
  "EXECUTING",
  "WAITING_APPROVAL",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);
export const inputModeSchema = z.enum(["TEXT", "VOICE"]);
export const logLevelSchema = z.enum(["DEBUG", "INFO", "WARNING", "ERROR", "SUCCESS"]);
export const riskLevelSchema = z.enum(["LOW", "MEDIUM", "HIGH", "CRITICAL"]);
export const approvalStatusSchema = z.enum(["PENDING", "APPROVED", "REJECTED", "EXPIRED", "WITHDRAWN"]);
export const approvalDecisionSchema = z.enum(["APPROVE", "REJECT"]);
export const languageSchema = z.enum(["en", "hi", "hinglish"]);
export const intentTypeSchema = z.enum([
  "GENERAL_CHAT",
  "BROWSER_NAVIGATION",
  "ECOMMERCE_SEARCH",
  "ECOMMERCE_SHOPPING",
  "ECOMMERCE_CART_REVIEW",
  "ECOMMERCE_CHECKOUT_REVIEW",
  "ECOMMERCE_PURCHASE",
  "MEDIA_SEARCH",
  "EMAIL_DRAFT",
  "EMAIL_SEND",
  "CALENDAR_MANAGEMENT",
  "FILE_DOWNLOAD",
  "YOUTUBE_SEARCH",
  "YOUTUBE_PLAYBACK",
  "MULTI_DOMAIN_WORKFLOW",
  "FORM_SUBMISSION",
  "DATA_EXTRACTION",
  "UNSUPPORTED",
]);
export const planStatusSchema = z.enum(["READY", "NEEDS_CLARIFICATION", "REJECTED", "FAILED"]);
export const browserSessionStatusSchema = z.enum(["INITIALIZING", "READY", "BUSY", "AUTH_REQUIRED", "CLOSED", "ERROR"]);
export const actionExecutionStatusSchema = z.enum(["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED", "SKIPPED"]);
export const executionStatusSchema = z.enum(["QUEUED", "EXECUTING", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"]);
export const planningStageSchema = z.enum([
  "UNDERSTANDING_COMMAND",
  "CLASSIFYING_INTENT",
  "BUILDING_PLAN",
  "VALIDATING_PLAN",
  "FINALIZING",
]);

// ------------------------------------------------------------------ REST

export const healthResponseSchema: z.ZodType<HealthResponse> = z.object({
  status: z.string(),
  service: z.string(),
  version: z.string(),
  timestamp: isoDate,
});

export const taskAcceptedResponseSchema: z.ZodType<TaskAcceptedResponse> = z.object({
  task_id: uuid,
  session_id: uuid,
  state: taskStateSchema,
  accepted: z.boolean(),
  message: z.string(),
  created_at: isoDate,
});

// ------------------------------------------------------------------ Phase 4: commerce

const money = z.string().regex(/^-?\d{1,12}(\.\d{1,3})?$/);
export const commercePlatformSchema = z.enum(["BLINKIT", "AMAZON_IN"]);
export const paymentMethodSchema = z.enum(["COD", "UPI", "CARD", "NET_BANKING", "WALLET", "UNKNOWN"]);

export const purchaseApprovalSchema = z.object({
  platform: commercePlatformSchema,
  checkout_id: z.string().uuid(),
  cart_id: z.string().uuid().nullable().optional(),
  summary_hash: z.string().min(16).max(128),
  summary_version: z.number().int(),
  items: z.array(z.object({ name: z.string().max(300), quantity: z.string().max(60), line_total: money.nullable().optional() })).max(100),
  subtotal: money.nullable().optional(),
  delivery_fee: money.nullable().optional(),
  handling_fee: money.nullable().optional(),
  tax: money.nullable().optional(),
  discount: money.nullable().optional(),
  final_total: money,
  currency: z.string().max(5),
  masked_delivery_address: z.string().max(200).nullable().optional(),
  delivery_slot: z.string().max(200).nullable().optional(),
  payment_method: paymentMethodSchema,
  places_real_order: z.boolean(),
  warnings: z.array(z.string().max(500)).max(20),
});

/** One bounded schema for every commerce.* payload (fields vary by event; unknown keys are dropped). */
export const commerceEventDataSchema = z.object({
  platform: commercePlatformSchema.nullable().optional(),
  message: z.string().max(2000).nullable().optional(),
  status: z.string().max(40).nullable().optional(),
  query: z.string().max(300).nullable().optional(),
  product_name: z.string().max(300).nullable().optional(),
  requirement_id: z.string().uuid().nullable().optional(),
  selection_id: z.string().uuid().nullable().optional(),
  approval_id: z.string().uuid().nullable().optional(),
  checkout_id: z.string().uuid().nullable().optional(),
  code: z.string().max(80).nullable().optional(),
  decision: z.string().max(40).nullable().optional(),
  candidate_count: z.number().int().nonnegative().nullable().optional(),
  exact_match_count: z.number().int().nonnegative().nullable().optional(),
  requested_item_count: z.number().int().nonnegative().nullable().optional(),
  matched_item_count: z.number().int().nonnegative().nullable().optional(),
  missing_items: z.array(z.string().max(300)).max(50).nullable().optional(),
  mismatched_items: z.array(z.string().max(300)).max(50).nullable().optional(),
  warnings: z.array(z.string().max(500)).max(20).nullable().optional(),
  before_quantity: z.number().nullable().optional(),
  after_quantity: z.number().nullable().optional(),
  final_total: money.nullable().optional(),
  previous: money.nullable().optional(),
  current: money.nullable().optional(),
  difference: money.nullable().optional(),
  approval_invalidated: z.boolean().nullable().optional(),
  order_reference: z.string().max(80).nullable().optional(),
  payment_method: z.string().max(20).nullable().optional(),
  is_verified: z.boolean().nullable().optional(),
  item_count: z.number().int().nonnegative().nullable().optional(),
  site_name: z.string().max(80).nullable().optional(),
  is_fixture: z.boolean().nullable().optional(),
});

// ------------------------------------------------------------------ Phase 5: integrations

export const domainTypeSchema = z.enum(["YOUTUBE", "GMAIL", "GOOGLE_CALENDAR", "FILES", "BLINKIT", "AMAZON_IN"]);
export const capabilitySchema = z.enum([
  "YOUTUBE_SEARCH", "YOUTUBE_PLAY", "GMAIL_CREATE_DRAFT", "GMAIL_READ_DRAFT", "CALENDAR_LIST_EVENTS", "CALENDAR_CREATE_EVENT",
  "FILE_DOWNLOAD", "FILE_INSPECT", "COMMERCE_SEARCH", "COMMERCE_CART",
]);
export const conflictStatusSchema = z.enum(["NOT_REQUESTED", "NO_CONFLICT_OBSERVED", "CONFLICTS_FOUND", "UNAVAILABLE"]);
export const calendarConflictSchema = z.object({
  title: z.string().max(300),
  start_label: z.string().max(40),
  end_label: z.string().max(40),
  kind: z.string().max(20),
});

export const calendarApprovalSchema = z.object({
  title: z.string().min(1).max(200),
  date_label: z.string().max(80),
  time_label: z.string().max(80),
  timezone: z.string().max(64),
  timezone_label: z.string().max(120),
  start_at: isoDate,
  end_at: isoDate,
  location: z.string().max(300).nullable().optional(),
  description: z.string().max(5000).nullable().optional(),
  attendee_emails: z.array(z.string().max(254)).max(200),
  reminder_minutes: z.number().int().nullable().optional(),
  recurrence_rule: z.string().max(120).nullable().optional(),
  conflict_status: conflictStatusSchema,
  conflicts: z.array(calendarConflictSchema).max(20),
  sends_invitations: z.boolean(),
  event_hash: z.string().min(16).max(128),
});

/** One bounded schema for every integration/youtube/gmail/calendar/file/workflow payload. */
export const integrationEventDataSchema = z.object({
  domain: domainTypeSchema.nullable().optional(),
  message: z.string().max(2000),
  status: z.string().max(40).nullable().optional(),
  step_id: uuid.nullable().optional(),
  capability: capabilitySchema.nullable().optional(),
  code: z.string().max(80).nullable().optional(),
  result_count: z.number().int().nonnegative().nullable().optional(),
  choice_id: uuid.nullable().optional(),
  approval_id: uuid.nullable().optional(),
  file_id: uuid.nullable().optional(),
  bytes_received: z.number().int().nonnegative().nullable().optional(),
  completed_steps: z.number().int().nonnegative().nullable().optional(),
  total_steps: z.number().int().nonnegative().nullable().optional(),
});

export const approvalRequestSchema: z.ZodType<ApprovalRequest> = z.object({
  approval_id: uuid,
  task_id: uuid,
  session_id: uuid,
  action_summary: z.string().min(1),
  domain: z.string().min(1),
  reason: z.string().min(1),
  risk_level: riskLevelSchema,
  status: approvalStatusSchema,
  estimated_impact: z.string().nullable().optional(),
  expires_at: isoDate,
  is_demo: z.boolean(),
  created_at: isoDate.optional(),
  resolved_at: isoDate.nullable().optional(),
  decision: approvalDecisionSchema.nullable().optional(),
  purchase: purchaseApprovalSchema.nullable().optional(),
  calendar: calendarApprovalSchema.nullable().optional(),
});

export const approvalResponseSchema: z.ZodType<ApprovalResponse> = z.object({
  approval_id: uuid,
  decision: approvalDecisionSchema,
  status: approvalStatusSchema,
  resolved_at: isoDate,
});

export const apiErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  request_id: z.string().nullable().optional(),
  details: z.array(z.record(z.unknown())).nullable().optional(),
});

export const demoAcceptedSchema = z.object({
  accepted: z.boolean(),
  message: z.string(),
  task_id: uuid,
  is_demo: z.literal(true),
});

// ------------------------------------------------------------------ telemetry

const envelope = z.object({
  event_id: uuid,
  session_id: uuid,
  task_id: uuid.nullable(),
  sequence: z.number().int().positive(),
  occurred_at: isoDate,
});

const withType = <T extends string, S extends z.ZodTypeAny>(type: T, data: S) =>
  envelope.extend({ type: z.literal(type), data });

// ---------------------------------------------------------------- Phase 3 payload parts

const shortText = (max: number) => z.string().max(max);

const browserSessionData = z.object({
  status: browserSessionStatusSchema,
  engine: shortText(40),
  headless: z.boolean(),
  message: shortText(1000).nullable().optional(),
});

const browserNavigationData = z.object({
  url: shortText(2048),
  domain: shortText(253).nullable().optional(),
  title: shortText(500).nullable().optional(),
  step_id: uuid.nullable().optional(),
  message: shortText(1000),
});

const browserActionData = z.object({
  step_id: uuid,
  action_type: shortText(40),
  message: shortText(2000),
  strategy: shortText(40).nullable().optional(),
  confidence: z.number().min(0).max(1).nullable().optional(),
  error_code: shortText(80).nullable().optional(),
});

const browserStreamData = z.object({ subscribers: z.number().int().nonnegative() });

const stepFailedData = z.object({
  step_id: uuid,
  order: z.number().int().positive(),
  status: actionExecutionStatusSchema,
  error_code: shortText(80),
  message: shortText(2000),
  duration_ms: z.number().int().nonnegative().nullable().optional(),
});

const executionFinishedData = z.object({
  status: executionStatusSchema,
  total_steps: z.number().int().nonnegative(),
  succeeded_steps: z.number().int().nonnegative(),
  failed_steps: z.number().int().nonnegative(),
  blocked_steps: z.number().int().nonnegative(),
  skipped_steps: z.number().int().nonnegative(),
  message: shortText(2000),
  error_code: shortText(80).nullable().optional(),
});

export const telemetryEventSchema = z.discriminatedUnion("type", [
  withType(
    "connection.ready",
    z.object({
      connection_id: uuid,
      server_version: z.string(),
      assistant_name: z.string(),
      heartbeat_interval_seconds: z.number().positive(),
      history_limit: z.number().int().positive(),
      demo_endpoints_enabled: z.boolean(),
    }),
  ),
  withType(
    "task.accepted",
    z.object({
      task_id: uuid,
      state: taskStateSchema,
      command: z.string(),
      input_mode: inputModeSchema,
      created_at: isoDate,
      is_demo: z.boolean(),
    }),
  ),
  withType(
    "task.state_changed",
    z.object({
      previous_state: taskStateSchema,
      new_state: taskStateSchema,
      reason: z.string().nullable().optional(),
      is_demo: z.boolean(),
    }),
  ),
  withType(
    "log.created",
    z.object({
      level: logLevelSchema,
      message: z.string().max(2000),
      source: z.enum(["system", "assistant", "demo"]),
      language: z.enum(["en", "hi", "hinglish"]).nullable().optional(),
      metadata: z.record(z.unknown()).nullable().optional(),
      is_demo: z.boolean(),
    }),
  ),
  withType(
    "browser.preview",
    z.object({
      mode: z.enum(["DISCONNECTED", "PLACEHOLDER", "FRAME"]),
      message: z.string(),
      url: z.string().nullable().optional(),
      frame_data_url: z
        .string()
        .regex(/^data:image\/(png|jpeg|webp);base64,/)
        .nullable()
        .optional(),
      is_demo: z.boolean(),
    }),
  ),
  withType("approval.required", approvalRequestSchema),
  withType(
    "approval.resolved",
    z.object({
      approval_id: uuid,
      decision: approvalDecisionSchema.nullable(),
      status: approvalStatusSchema,
      resolved_at: isoDate,
      is_demo: z.boolean(),
    }),
  ),
  withType("task.completed", z.object({ summary: z.string(), is_demo: z.boolean() })),
  withType(
    "task.failed",
    z.object({ error_code: z.string(), error_message: z.string(), is_demo: z.boolean() }),
  ),
  withType("system.error", z.object({ code: z.string(), message: z.string() })),
  // ---------------------------------------------------------------- Phase 2: agent planning
  withType(
    "agent.intent_detected",
    z.object({
      intent: intentTypeSchema,
      confidence: z.number().min(0).max(1),
      target_website: z.string().max(253).nullable(),
      language: languageSchema,
      requires_clarification: z.boolean(),
      is_follow_up: z.boolean(),
    }),
  ),
  withType(
    "agent.planning_started",
    z.object({ status: taskStateSchema, message: z.string().max(500), is_clarification: z.boolean() }),
  ),
  withType(
    "agent.planning_progress",
    z.object({ stage: planningStageSchema, progress: z.number().int().min(0).max(100), message: z.string().max(300) }),
  ),
  withType(
    "task.plan_ready",
    z.object({
      plan_id: uuid,
      status: planStatusSchema,
      intent: intentTypeSchema,
      summary: z.string(),
      step_count: z.number().int().nonnegative(),
      requires_human_approval: z.boolean(),
      provider: z.string(),
      model: z.string(),
      is_mock: z.boolean(),
    }),
  ),
  withType(
    "task.clarification_required",
    z.object({ plan_id: uuid, question: z.string().min(1).max(500), missing_information: z.array(z.string()) }),
  ),
  withType("task.planning_failed", z.object({ code: z.string(), message: z.string(), retryable: z.boolean() })),
  withType(
    "agent.response_generated",
    z.object({
      message: z.string().max(2000),
      language: languageSchema,
      kind: z.enum(["acknowledgement", "plan_ready", "clarification", "rejected", "failed", "chat", "execution"]),
    }),
  ),
  // ---------------------------------------------------------------- Phase 3: browser + execution
  withType("browser.session_started", browserSessionData),
  withType("browser.session_ready", browserSessionData),
  withType("browser.navigation_started", browserNavigationData),
  withType("browser.navigation_completed", browserNavigationData),
  withType(
    "browser.navigation_blocked",
    z.object({
      url: shortText(2048),
      domain: shortText(253).nullable().optional(),
      reason_code: shortText(80),
      message: shortText(1000),
      step_id: uuid.nullable().optional(),
    }),
  ),
  withType(
    "browser.page_updated",
    z.object({ url: shortText(2048).nullable(), domain: shortText(253).nullable(), title: shortText(500).nullable() }),
  ),
  withType(
    "browser.frame_available",
    z.object({
      frame_id: uuid,
      sequence: z.number().int().positive(),
      width: z.number().int().positive(),
      height: z.number().int().positive(),
      bytes: z.number().int().nonnegative(),
      captured_at: isoDate,
    }),
  ),
  withType("browser.action_started", browserActionData),
  withType("browser.action_completed", browserActionData),
  withType("browser.action_failed", browserActionData),
  withType(
    "browser.authentication_required",
    z.object({
      domain: shortText(253).nullable(),
      message: shortText(1000),
      headless: z.boolean(),
      step_id: uuid.nullable().optional(),
    }),
  ),
  withType("browser.popup_blocked", z.object({ url: shortText(2048).nullable(), message: shortText(1000) })),
  withType("browser.download_blocked", z.object({ filename: shortText(255).nullable(), message: shortText(1000) })),
  withType("browser.session_closed", z.object({ reason: shortText(500) })),
  withType("browser.session_error", z.object({ code: shortText(80), message: shortText(1000) })),
  withType("browser.stream_connected", browserStreamData),
  withType("browser.stream_disconnected", browserStreamData),
  withType(
    "task.execution_started",
    z.object({ plan_id: uuid, total_steps: z.number().int().nonnegative(), engine: shortText(40), headless: z.boolean() }),
  ),
  withType(
    "task.step_started",
    z.object({ step_id: uuid, order: z.number().int().positive(), action_type: shortText(40), description: shortText(500) }),
  ),
  withType(
    "task.step_completed",
    z.object({
      step_id: uuid,
      order: z.number().int().positive(),
      status: actionExecutionStatusSchema,
      duration_ms: z.number().int().nonnegative().nullable(),
      message: shortText(2000),
      verified: z.boolean(),
      extracted_data: z.record(z.unknown()).nullable().optional(),
    }),
  ),
  withType("task.step_failed", stepFailedData),
  withType("task.step_blocked", stepFailedData),
  withType(
    "task.execution_paused",
    z.object({ step_id: uuid, reason: shortText(1000), approval_id: uuid.nullable().optional() }),
  ),
  withType("task.execution_resumed", z.object({ step_id: uuid, message: shortText(1000) })),
  withType("task.execution_completed", executionFinishedData),
  withType("task.execution_failed", executionFinishedData),
  withType("task.execution_cancelled", executionFinishedData),
  // ---------------------------------------------------------------- Phase 4: commerce
  withType("commerce.session_detected", commerceEventDataSchema),
  withType("commerce.location_required", commerceEventDataSchema),
  withType("commerce.search_started", commerceEventDataSchema),
  withType("commerce.search_completed", commerceEventDataSchema),
  withType("commerce.products_found", commerceEventDataSchema),
  withType("commerce.product_selected", commerceEventDataSchema),
  withType("commerce.product_ambiguous", commerceEventDataSchema),
  withType("commerce.product_unavailable", commerceEventDataSchema),
  withType("commerce.cart_update_started", commerceEventDataSchema),
  withType("commerce.cart_item_added", commerceEventDataSchema),
  withType("commerce.cart_item_updated", commerceEventDataSchema),
  withType("commerce.cart_verification_started", commerceEventDataSchema),
  withType("commerce.cart_verification_completed", commerceEventDataSchema),
  withType("commerce.cart_verification_failed", commerceEventDataSchema),
  withType("commerce.price_changed", commerceEventDataSchema),
  withType("commerce.checkout_review_ready", commerceEventDataSchema),
  withType("commerce.purchase_approval_required", commerceEventDataSchema),
  withType("commerce.purchase_rejected", commerceEventDataSchema),
  withType("commerce.payment_handoff", commerceEventDataSchema),
  withType("commerce.order_submission_started", commerceEventDataSchema),
  withType("commerce.order_confirmed", commerceEventDataSchema),
  withType("commerce.order_status_unknown", commerceEventDataSchema),
  withType("commerce.workflow_failed", commerceEventDataSchema),
  // ---------------------------------------------------------------- Phase 5: integrations
  ...INTEGRATION_EVENT_TYPES.map((type) => withType(type, integrationEventDataSchema)),
]);

export const controlMessageSchema: z.ZodType<ControlMessage> = z.discriminatedUnion("type", [
  z.object({ type: z.literal("pong") }),
  z.object({ type: z.literal("subscribed"), replayed: z.number().int().nonnegative(), complete: z.boolean() }),
  z.object({ type: z.literal("error"), code: z.string(), message: z.string() }),
]);

export type ParseResult = { ok: true; message: ServerMessage } | { ok: false; reason: string };

/** Parse and validate a raw WebSocket frame. Never throws. */
export function parseServerMessage(raw: unknown): ParseResult {
  if (typeof raw !== "string") return { ok: false, reason: "Non-text frame" };
  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch {
    return { ok: false, reason: "Invalid JSON" };
  }
  const control = controlMessageSchema.safeParse(json);
  if (control.success) return { ok: true, message: { kind: "control", message: control.data } };

  const event = telemetryEventSchema.safeParse(json);
  if (event.success) {
    return { ok: true, message: { kind: "event", event: event.data as AnyTelemetryEvent } };
  }
  const type =
    json && typeof json === "object" && "type" in json ? String((json as { type: unknown }).type).slice(0, 40) : "unknown";
  return { ok: false, reason: `Unrecognised or malformed message (type: ${type})` };
}
