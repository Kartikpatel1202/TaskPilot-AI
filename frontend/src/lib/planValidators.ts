import { z } from "zod";

import {
  intentTypeSchema,
  languageSchema,
  planStatusSchema,
  riskLevelSchema,
  taskStateSchema,
} from "./validators";

import type { AgentStatusResponse, ClarificationAcceptedResponse } from "@/types/agent";
import type { TaskPlan } from "@/types/plan";

const uuid = z.string().uuid();
const isoDate = z.string().datetime({ offset: true });
const text = (max: number) => z.string().min(1).max(max);

export const requirementSchema = z.object({
  product_id: uuid,
  query: text(200),
  product_name: text(120),
  brand: z.string().max(60).nullable().optional(),
  model: z.string().max(80).nullable().optional(),
  quantity: z.number().positive().max(1000),
  unit: z.enum(["PIECE", "GRAM", "KILOGRAM", "MILLILITER", "LITER", "PACK", "DOZEN", "UNKNOWN"]),
  preferred_variant: z.record(z.string().max(80)),
  must_match_brand: z.boolean(),
  allow_substitute: z.boolean(),
  category: z.string().max(60).nullable().optional(),
  max_price: z.string().max(20).nullable().optional(),
  required_specs: z.record(z.string().max(80)),
  notes: z.array(z.string().max(300)).max(10),
});

export const actionSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("navigate"), url: z.string().url().max(2048), purpose: text(300) }),
  z.object({
    type: z.literal("click"),
    target_description: text(300),
    role_hint: z.string().max(40).nullable().optional(),
    accessible_name: z.string().max(200).nullable().optional(),
    text_hint: z.string().max(200).nullable().optional(),
  }),
  z.object({
    type: z.literal("type"),
    target_description: text(300),
    text: text(2000),
    clear_first: z.boolean(),
    sensitive: z.boolean(),
  }),
  z.object({ type: z.literal("extract"), target_description: text(300), fields: z.array(text(80)).min(1).max(20) }),
  z.object({
    type: z.literal("request_approval"),
    reason: text(500),
    risk_level: riskLevelSchema,
    details: z.record(z.string()),
  }),
  z.object({ type: z.literal("stop"), reason: text(500) }),
  // Phase 4: built only by the backend's deterministic commerce planner.
  z.object({
    type: z.literal("commerce"),
    operation: z.enum(["open_store", "search_products", "search_and_add", "verify_cart", "checkout_review", "place_order"]),
    platform: z.enum(["BLINKIT", "AMAZON_IN"]),
    site_key: text(40),
    requirement: requirementSchema.nullable().optional(),
    payment_preference: z.enum(["COD", "PREPAID", "ANY"]).nullable().optional(),
    continue_on_failure: z.boolean(),
  }),
  // Phase 5: built only by the backend's deterministic integration planner.
  z.object({
    type: z.literal("youtube_search"),
    query: text(500),
    max_results: z.number().int().min(1).max(20),
    preferred_channel: z.string().max(100).nullable().optional(),
    select: z.boolean(),
    site_key: text(40),
    continue_on_failure: z.boolean(),
  }),
  z.object({
    type: z.literal("youtube_play"),
    video_reference: z.string().max(200).regex(/^(selected_from_search|https:\/\/(www\.)?youtube\.com\/watch\?v=[\w-]{6,20})$/),
    site_key: text(40),
    continue_on_failure: z.boolean(),
  }),
  z.object({
    type: z.literal("gmail_create_draft"),
    recipient_emails: z.array(z.string().email().max(254)).min(1).max(50),
    cc_emails: z.array(z.string().email().max(254)).max(50),
    subject: text(200),
    body: text(12_000),
    tone: z.string().max(40).nullable().optional(),
    purpose: z.string().max(200).nullable().optional(),
    insert_outputs: z.array(z.enum(["youtube.video_reference", "file.reference"])).max(4),
    send_requested: z.boolean(),
    site_key: text(40),
    continue_on_failure: z.boolean(),
  }),
  z.object({
    type: z.literal("calendar_create_event"),
    title: text(200),
    start_at: isoDate,
    end_at: isoDate,
    timezone: text(64),
    description: z.string().max(5000).nullable().optional(),
    location: z.string().max(300).nullable().optional(),
    attendee_emails: z.array(z.string().email().max(254)).max(200),
    reminder_minutes: z.number().int().nullable().optional(),
    recurrence_rule: z.string().max(120).nullable().optional(),
    check_conflicts: z.boolean(),
    assumptions: z.array(z.string().max(500)).max(5),
    site_key: text(40),
    continue_on_failure: z.boolean(),
  }),
  z.object({
    type: z.literal("file_download"),
    source_url: z.string().url().max(2048).refine((u) => /^https?:\/\//.test(u), "http(s) only"),
    file_description: text(200),
    expected_extension: z.string().max(10).nullable().optional(),
    suggested_filename: z.string().max(120).nullable().optional(),
    site_key: text(40),
    continue_on_failure: z.boolean(),
  }),
]);

export const plannedActionSchema = z.object({
  step_id: uuid,
  order: z.number().int().min(1),
  action: actionSchema,
  description: text(300),
  expected_outcome: text(300),
  risk_level: riskLevelSchema,
  requires_approval: z.boolean(),
  depends_on: z.array(uuid),
});

export const taskPlanSchema: z.ZodType<TaskPlan> = z
  .object({
    plan_id: uuid,
    task_id: uuid,
    session_id: uuid,
    status: planStatusSchema,
    intent: intentTypeSchema,
    summary: z.string(),
    user_facing_message: z.string(),
    language: languageSchema,
    target_website: z.string().nullable(),
    confidence: z.number().min(0).max(1),
    assumptions: z.array(z.string()),
    clarification_question: z.string().nullable(),
    missing_information: z.array(z.string()),
    clarification_history: z.array(z.object({ question: z.string(), answer: z.string(), answered_at: isoDate })),
    steps: z.array(plannedActionSchema).max(100),
    requires_human_approval: z.boolean(),
    provider: z.string(),
    model: z.string(),
    is_mock: z.boolean(),
    created_at: isoDate,
    schema_version: z.string(),
  })
  .superRefine((plan, ctx) => {
    // Defence in depth: the UI never renders a plan whose steps are out of order.
    plan.steps.forEach((step, index) => {
      if (step.order !== index + 1) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "Plan steps must be ordered 1..N", path: ["steps", index] });
      }
    });
  });

export const agentStatusSchema: z.ZodType<AgentStatusResponse> = z.object({
  agent_name: z.string(),
  provider: z.string(),
  model: z.string(),
  status: z.enum(["available", "disabled", "misconfigured", "unavailable"]),
  planning_enabled: z.boolean(),
  browser_execution_enabled: z.boolean(),
  is_mock: z.boolean(),
  provider_reachable: z.boolean().nullable(),
  planner_kind: z.enum(["ai", "offline_rules"]).optional(),
  setup_hint: z.string().max(600).nullable().optional(),
});

export const clarificationAcceptedSchema: z.ZodType<ClarificationAcceptedResponse> = z.object({
  task_id: uuid,
  accepted: z.boolean(),
  state: taskStateSchema,
  message: z.string(),
});

export function parseTaskPlan(raw: unknown): TaskPlan | null {
  const result = taskPlanSchema.safeParse(raw);
  return result.success ? result.data : null;
}
