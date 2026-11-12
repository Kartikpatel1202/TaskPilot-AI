import type { z } from "zod";

import { API_BASE_URL, API_PREFIX, REQUEST_TIMEOUT_MS } from "./constants";
import { agentStatusSchema, clarificationAcceptedSchema, taskPlanSchema } from "./planValidators";
import {
  apiErrorSchema,
  approvalRequestSchema,
  approvalResponseSchema,
  demoAcceptedSchema,
  healthResponseSchema,
  taskAcceptedResponseSchema,
} from "./validators";

import type { AgentStatusResponse, ClarificationAcceptedResponse, SubmitClarificationRequest } from "@/types/agent";
import type { ApprovalRequest, ApprovalResponse, SubmitApprovalRequest } from "@/types/approval";
import type { TaskPlan } from "@/types/plan";
import type { CreateTaskRequest, HealthResponse, TaskAcceptedResponse } from "@/types/task";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export interface RequestOptions<T> {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  schema?: z.ZodType<T>;
  timeoutMs?: number;
}

/** Phase 6: the readable CSRF cookie set at login (the access/refresh cookies are HttpOnly). */
export function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith("tp_csrf="));
  return match ? decodeURIComponent(match.slice("tp_csrf=".length)) : null;
}

/** Called when the session can no longer be refreshed (the app shows the sign-in screen). */
let onSessionExpired: (() => void) | null = null;
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

let refreshing: Promise<boolean> | null = null;
async function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${API_BASE_URL}${API_PREFIX}/auth/refresh`, { method: "POST", credentials: "include" })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      setTimeout(() => {
        refreshing = null;
      }, 0);
    });
  return refreshing;
}

const MUTATING = new Set(["POST", "PUT", "DELETE"]);

/** Validated JSON request (shared by every REST client). Sends cookies + CSRF; refreshes an expired session once. */
export async function request<T>(path: string, options: RequestOptions<T>, retried = false): Promise<T> {
  const { method = "GET", body, schema, timeoutMs = REQUEST_TIMEOUT_MS } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const csrf = MUTATING.has(method) ? csrfToken() : null;
  if (csrf) headers["X-CSRF-Token"] = csrf;
  try {
    response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
      method,
      headers,
      credentials: "include",
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    throw new ApiError(
      aborted ? "The server took too long to respond." : "Unable to reach the TaskPilot backend.",
      0,
      aborted ? "TIMEOUT" : "NETWORK_ERROR",
    );
  } finally {
    clearTimeout(timer);
  }

  let json: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = null;
    }
  }

  if (response.status === 401 && !retried && !path.startsWith("/auth/")) {
    const code = (json as { code?: string } | null)?.code;
    if (code === "TOKEN_EXPIRED" && (await refreshSession())) return request(path, options, true);
    if (code && code !== "INVALID_CREDENTIALS") onSessionExpired?.();
  }

  if (!response.ok) {
    const parsed = apiErrorSchema.safeParse(json);
    if (parsed.success) {
      throw new ApiError(parsed.data.message, response.status, parsed.data.code, parsed.data.request_id ?? null);
    }
    throw new ApiError(`Request failed with status ${response.status}.`, response.status, "HTTP_ERROR");
  }

  if (!schema) return undefined as T;
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError("The server returned an unexpected response.", response.status, "INVALID_RESPONSE");
  }
  return parsed.data;
}

export async function getHealth(): Promise<HealthResponse> {
  return request("/health", { schema: healthResponseSchema });
}

export async function createTask(body: CreateTaskRequest): Promise<TaskAcceptedResponse> {
  return request("/tasks", { method: "POST", body, schema: taskAcceptedResponseSchema });
}

export async function submitApprovalDecision(
  approvalId: string,
  body: SubmitApprovalRequest,
): Promise<ApprovalResponse> {
  return request(`/approvals/${encodeURIComponent(approvalId)}/decision`, {
    method: "POST",
    body,
    schema: approvalResponseSchema,
  });
}

/** DEVELOPMENT ONLY — starts a labelled, simulated telemetry stream. */
export async function triggerDemoTelemetry(sessionId: string): Promise<void> {
  await request("/dev/demo/telemetry", { method: "POST", body: { session_id: sessionId }, schema: demoAcceptedSchema });
}

/** DEVELOPMENT ONLY — creates a labelled sample approval request. */
export async function triggerDemoApproval(sessionId: string): Promise<void> {
  await request<ApprovalRequest>("/dev/demo/approval", {
    method: "POST",
    body: { session_id: sessionId },
    schema: approvalRequestSchema,
  });
}

// ------------------------------------------------------------------ Phase 2: agent planning

export async function getTaskPlan(taskId: string, sessionId?: string): Promise<TaskPlan> {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return request(`/tasks/${encodeURIComponent(taskId)}/plan${query}`, { schema: taskPlanSchema });
}

export async function submitClarification(
  taskId: string,
  body: SubmitClarificationRequest,
): Promise<ClarificationAcceptedResponse> {
  return request(`/tasks/${encodeURIComponent(taskId)}/clarification`, {
    method: "POST",
    body,
    schema: clarificationAcceptedSchema,
  });
}

export async function getAgentStatus(): Promise<AgentStatusResponse> {
  return request("/agent/status", { schema: agentStatusSchema });
}
