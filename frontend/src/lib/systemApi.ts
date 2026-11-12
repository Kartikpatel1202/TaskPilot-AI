/** Phase 6: readiness (everyone), detailed health (OWNER only) and persistent task history. */

import { z } from "zod";

import { request } from "./api";

const checksSchema = z.record(z.string().max(40));

export interface Readiness {
  status: string;
  checks: Record<string, string>;
}

export interface HealthDetails {
  version: string;
  environment: string;
  ready: boolean;
  checks: Record<string, string>;
  auth_enforced: boolean;
  queue_backend: string;
  egress_proxy_configured: boolean;
  llm: { provider: string; model: string; circuit: { state: string } };
  approvals_pending: number;
  persistence_write_failures: number;
  audit_write_failures: number;
  rate_limiter_degraded: boolean;
}

export interface TaskHistoryItem {
  task_id: string;
  session_id: string;
  command: string;
  state: string;
  error_code: string | null;
  error_message: string | null;
  execution_status: string | null;
  recovery_note: string | null;
  created_at: string;
  updated_at: string;
}

const readinessSchema = z.object({ status: z.string().max(20), checks: checksSchema });
const detailsSchema = z.object({
  version: z.string(), environment: z.string(), ready: z.boolean(), checks: checksSchema, auth_enforced: z.boolean(),
  queue_backend: z.string(), egress_proxy_configured: z.boolean(),
  llm: z.object({ provider: z.string(), model: z.string(), circuit: z.object({ state: z.string() }).passthrough() }).passthrough(),
  approvals_pending: z.number().int(), persistence_write_failures: z.number().int(), audit_write_failures: z.number().int(),
  rate_limiter_degraded: z.boolean(),
}).passthrough();
const historySchema = z.object({
  tasks: z.array(z.object({
    task_id: z.string().uuid(), session_id: z.string().uuid(), command: z.string().max(300), state: z.string().max(32),
    error_code: z.string().max(80).nullable(), error_message: z.string().max(1000).nullable(), execution_status: z.string().max(32).nullable(),
    recovery_note: z.string().max(1000).nullable(), created_at: z.string(), updated_at: z.string(),
  })).max(100),
  next_cursor: z.string().max(120).nullable(),
});

/** Readiness answers 503 with the same body when a dependency is down; both are useful to show. */
export async function getReadiness(): Promise<Readiness> {
  try {
    return await request<Readiness>("/health/ready", { schema: readinessSchema as z.ZodType<Readiness> });
  } catch {
    return { status: "not_ready", checks: { api: "unreachable" } };
  }
}

export const getHealthDetails = () => request<HealthDetails>("/health/details", { schema: detailsSchema as unknown as z.ZodType<HealthDetails> });

export function getTaskHistory(params: { sessionId?: string | null; cursor?: string | null; limit?: number }): Promise<{ tasks: TaskHistoryItem[]; next_cursor: string | null }> {
  const q = new URLSearchParams({ limit: String(params.limit ?? 20) });
  if (params.sessionId) q.set("session_id", params.sessionId);
  if (params.cursor) q.set("cursor", params.cursor);
  return request(`/task-history?${q.toString()}`, { schema: historySchema });
}
