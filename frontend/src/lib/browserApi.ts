/**
 * Phase 3 REST client: Run Plan / Stop, execution summaries and browser sessions.
 * Every response is validated with Zod before it reaches the UI.
 */

import { z } from "zod";

import { request } from "./api";
import { API_BASE_URL, API_PREFIX } from "./constants";
import {
  actionExecutionStatusSchema,
  browserSessionStatusSchema,
  executionStatusSchema,
} from "./validators";

import type {
  BrowserSessionCloseResponse,
  BrowserSessionInfo,
  BrowserStatusResponse,
} from "@/types/browser";
import type {
  ActionResult,
  ExecutionAcceptedResponse,
  ExecutionSummary,
  StopTaskResponse,
} from "@/types/execution";

const uuid = z.string().uuid();
const isoDate = z.string().datetime({ offset: true });

export const executionAcceptedSchema: z.ZodType<ExecutionAcceptedResponse> = z.object({
  task_id: uuid,
  session_id: uuid,
  status: z.literal("ACCEPTED"),
  message: z.string(),
});

export const stopTaskResponseSchema: z.ZodType<StopTaskResponse> = z.object({
  task_id: uuid,
  status: z.enum(["STOPPING", "CANCELLED"]),
  message: z.string(),
});

const actionResultSchema: z.ZodType<ActionResult> = z.object({
  step_id: uuid,
  order: z.number().int().nonnegative(),
  action_type: z.string(),
  status: actionExecutionStatusSchema,
  started_at: isoDate,
  completed_at: isoDate.nullable().optional(),
  duration_ms: z.number().int().nonnegative().nullable().optional(),
  message: z.string(),
  error_code: z.string().nullable().optional(),
  extracted_data: z.record(z.unknown()).nullable().optional(),
  retry_count: z.number().int().nonnegative(),
  verified: z.boolean(),
  strategy: z.string().nullable().optional(),
  confidence: z.number().nullable().optional(),
});

export const executionSummarySchema: z.ZodType<ExecutionSummary> = z.object({
  task_id: uuid,
  session_id: uuid,
  plan_id: uuid,
  status: executionStatusSchema,
  total_steps: z.number().int().nonnegative(),
  results: z.array(actionResultSchema),
  started_at: isoDate.nullable().optional(),
  finished_at: isoDate.nullable().optional(),
  message: z.string().nullable().optional(),
  error_code: z.string().nullable().optional(),
});

export const browserStatusSchema: z.ZodType<BrowserStatusResponse> = z.object({
  available: z.boolean(),
  status: z.enum(["ready", "not_started", "unavailable"]),
  engine: z.string(),
  active_sessions: z.number().int().nonnegative(),
  max_sessions: z.number().int().positive(),
  headless: z.boolean(),
  message: z.string().nullable().optional(),
});

export const browserSessionInfoSchema: z.ZodType<BrowserSessionInfo> = z.object({
  session_id: uuid,
  status: browserSessionStatusSchema,
  current_url: z.string().nullable().optional(),
  current_title: z.string().nullable().optional(),
  active_task_id: uuid.nullable().optional(),
  created_at: isoDate,
  last_activity_at: isoDate,
  stream_status: z.enum(["CONNECTED", "DISCONNECTED"]),
  stream_subscribers: z.number().int().nonnegative(),
  has_screenshot: z.boolean(),
  auth_required: z.boolean(),
  headless: z.boolean(),
});

export const browserSessionCloseSchema: z.ZodType<BrowserSessionCloseResponse> = z.object({
  session_id: uuid,
  closed: z.boolean(),
  message: z.string(),
});

const enc = encodeURIComponent;

/**
 * Run Plan. `run_plan_click` = the user pressed Run Plan. `voice_auto` = a spoken request in voice mode; the
 * server accepts it only for low-risk plans (no ordering, paying, sending, creating or deleting) and only when
 * voice auto-run is enabled in Settings.
 */
export async function executeTask(
  taskId: string,
  sessionId: string,
  trigger: "run_plan_click" | "voice_auto" = "run_plan_click",
): Promise<ExecutionAcceptedResponse> {
  return request(`/tasks/${enc(taskId)}/execute`, {
    method: "POST",
    body: { session_id: sessionId, confirm_execution: true, trigger },
    schema: executionAcceptedSchema,
  });
}

export async function stopTask(taskId: string, sessionId: string, reason = "Stopped from the dashboard"): Promise<StopTaskResponse> {
  return request(`/tasks/${enc(taskId)}/stop`, {
    method: "POST",
    body: { session_id: sessionId, reason },
    schema: stopTaskResponseSchema,
  });
}

export async function getExecution(taskId: string, sessionId: string): Promise<ExecutionSummary> {
  return request(`/tasks/${enc(taskId)}/execution?session_id=${enc(sessionId)}`, { schema: executionSummarySchema });
}

export async function getBrowserStatus(): Promise<BrowserStatusResponse> {
  return request("/browser/status", { schema: browserStatusSchema });
}

export async function getBrowserSession(sessionId: string): Promise<BrowserSessionInfo> {
  return request(`/browser/sessions/${enc(sessionId)}`, { schema: browserSessionInfoSchema });
}

export async function closeBrowserSession(sessionId: string): Promise<BrowserSessionCloseResponse> {
  return request(`/browser/sessions/${enc(sessionId)}/close`, {
    method: "POST",
    body: { session_id: sessionId },
    schema: browserSessionCloseSchema,
  });
}

/** Latest real screenshot (JPEG) — used as a fallback after reloads. */
export function latestScreenshotUrl(sessionId: string, bust: number): string {
  return `${API_BASE_URL}${API_PREFIX}/browser/sessions/${enc(sessionId)}/screenshot?t=${bust}`;
}
