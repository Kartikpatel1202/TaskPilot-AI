/**
 * Centralised runtime configuration. Components never read env vars directly.
 * NEXT_PUBLIC_* values are inlined at build time and visible to the browser —
 * they must never contain secrets.
 */

const trimSlash = (value: string) => value.replace(/\/+$/, "");

function parsePositiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

// Local development defaults only; deployments must set the env vars.
export const API_BASE_URL = trimSlash(process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000");
export const WS_BASE_URL = trimSlash(process.env.NEXT_PUBLIC_WS_BASE_URL || "ws://localhost:8000");
export const DEMO_MODE = (process.env.NEXT_PUBLIC_DEMO_MODE ?? "false").toLowerCase() === "true";

export const API_PREFIX = "/api/v1";
export const MAX_COMMAND_LENGTH = 4000;
export const MAX_LOGS = parsePositiveInt(process.env.NEXT_PUBLIC_MAX_LOGS, 500);
export const MAX_RECENT_TASKS = 25;

export const REQUEST_TIMEOUT_MS = 10_000;
export const RECONNECT_DELAYS_MS: readonly number[] = [1_000, 2_000, 4_000, 8_000, 16_000];
export const RECONNECT_JITTER_MS = 400;
export const MAX_RECONNECT_ATTEMPTS = RECONNECT_DELAYS_MS.length;
export const HEARTBEAT_INTERVAL_MS = 25_000;
export const PONG_TIMEOUT_MS = 10_000;
export const DEDUP_WINDOW = 2_000;

export const SESSION_STORAGE_KEY = "taskpilot.session_id";
export const VOICE_REPLIES_STORAGE_KEY = "taskpilot.voice_replies";
export const SIDEBAR_STORAGE_KEY = "taskpilot.sidebar_collapsed";

export const SUGGESTED_COMMANDS: readonly string[] = [
  "Open YouTube and search for Python tutorials.",
  "Find a laptop under ₹60,000 on Amazon.",
  "Open Blinkit and prepare my grocery cart.",
  "Draft an email in Gmail.",
];
