/** Activity Logs page: persisted task events, browser steps and audit records (owner-scoped by the server). */

import { z } from "zod";

import { request } from "./api";

export type ActivityKind = "task" | "step" | "approval" | "browser" | "purchase" | "integration" | "security" | "other";

export interface ActivityEvent {
  id: string;
  kind: ActivityKind;
  occurred_at: string;
  title: string;
  status: string;
  task_id: string | null;
  command: string | null;
  detail: string | null;
  error_code: string | null;
  duration_ms: number | null;
}

export interface TaskActivity {
  task_id: string;
  session_id: string;
  command: string;
  input_mode: string;
  state: string;
  error_code: string | null;
  error_message: string | null;
  execution_status: string | null;
  recovery_note: string | null;
  created_at: string;
  updated_at: string;
  intent: string | null;
  plan_status: string | null;
  plan_summary: string | null;
  planner: string | null;
  steps: {
    order: number; action_type: string; lifecycle: string; attempt: number; mutating: boolean; error_code: string | null;
    message: string | null; started_at: string | null; completed_at: string | null; duration_ms: number | null;
  }[];
  events: ActivityEvent[];
  conversation: { role: string; content: string; at: string }[];
}

const eventSchema = z.object({
  id: z.string().max(80),
  kind: z.enum(["task", "step", "approval", "browser", "purchase", "integration", "security", "other"]),
  occurred_at: z.string(),
  title: z.string().max(200),
  status: z.string().max(40),
  task_id: z.string().uuid().nullable(),
  command: z.string().max(300).nullable(),
  detail: z.string().max(1000).nullable(),
  error_code: z.string().max(80).nullable(),
  duration_ms: z.number().int().nullable(),
});

const pageSchema = z.object({ events: z.array(eventSchema).max(200), next_before: z.string().nullable() });

const taskSchema = z.object({
  task_id: z.string().uuid(), session_id: z.string().uuid(), command: z.string(), input_mode: z.string(), state: z.string(),
  error_code: z.string().nullable(), error_message: z.string().nullable(), execution_status: z.string().nullable(),
  recovery_note: z.string().nullable(), created_at: z.string(), updated_at: z.string(), intent: z.string().nullable(),
  plan_status: z.string().nullable(), plan_summary: z.string().nullable(), planner: z.string().nullable(),
  steps: z.array(z.object({
    order: z.number().int(), action_type: z.string(), lifecycle: z.string(), attempt: z.number().int(), mutating: z.boolean(),
    error_code: z.string().nullable(), message: z.string().nullable(), started_at: z.string().nullable(),
    completed_at: z.string().nullable(), duration_ms: z.number().int().nullable(),
  })),
  events: z.array(eventSchema),
  conversation: z.array(z.object({ role: z.string(), content: z.string(), at: z.string() })),
});

export interface ActivityQuery {
  kind?: ActivityKind | "all";
  status?: string;
  q?: string;
  taskId?: string;
  before?: string | null;
  limit?: number;
}

export function getActivity(query: ActivityQuery): Promise<{ events: ActivityEvent[]; next_before: string | null }> {
  const params = new URLSearchParams({ limit: String(query.limit ?? 50) });
  if (query.kind && query.kind !== "all") params.set("kind", query.kind);
  if (query.status) params.set("status", query.status);
  if (query.q) params.set("q", query.q);
  if (query.taskId) params.set("task_id", query.taskId);
  if (query.before) params.set("before", query.before);
  return request(`/activity/events?${params.toString()}`, { schema: pageSchema });
}

export const getTaskActivity = (taskId: string) =>
  request<TaskActivity>(`/activity/tasks/${encodeURIComponent(taskId)}`, { schema: taskSchema as z.ZodType<TaskActivity> });
