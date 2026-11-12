import { API_PREFIX, DEDUP_WINDOW, RECONNECT_DELAYS_MS, RECONNECT_JITTER_MS, SESSION_STORAGE_KEY } from "./constants";
import { safeStorageGet, safeStorageSet } from "./utils";

import type { ClientMessage } from "@/types/telemetry";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

export function createSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // RFC 4122 v4 fallback using getRandomValues.
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Per-tab session id: survives reloads (so telemetry can be replayed) but not new tabs. */
export function getOrCreateSessionId(): string {
  const existing = safeStorageGet("session", SESSION_STORAGE_KEY);
  if (existing && isUuid(existing)) return existing;
  const id = createSessionId();
  safeStorageSet("session", SESSION_STORAGE_KEY, id);
  return id;
}

export function buildWebSocketUrl(base: string, sessionId: string): string {
  return `${base.replace(/\/+$/, "")}${API_PREFIX}/ws/${encodeURIComponent(sessionId)}`;
}

/**
 * Exponential backoff (1s, 2s, 4s, 8s, 16s by default) plus random jitter.
 * `attempt` is zero-based.
 */
export function computeBackoffDelay(
  attempt: number,
  delays: readonly number[] = RECONNECT_DELAYS_MS,
  jitterMs: number = RECONNECT_JITTER_MS,
  random: () => number = Math.random,
): number {
  const base = delays[Math.min(Math.max(attempt, 0), delays.length - 1)] ?? 1_000;
  return base + Math.floor(random() * jitterMs);
}

export function serializeClientMessage(message: ClientMessage): string {
  return JSON.stringify(message);
}

/** Bounded set of recently processed event ids (FIFO eviction). */
export class EventDeduplicator {
  private readonly ids = new Set<string>();
  private readonly order: string[] = [];

  constructor(private readonly capacity: number = DEDUP_WINDOW) {}

  /** Returns true the first time an id is seen, false for duplicates. */
  markIfNew(id: string): boolean {
    if (this.ids.has(id)) return false;
    this.ids.add(id);
    this.order.push(id);
    if (this.order.length > this.capacity) {
      const evicted = this.order.shift();
      if (evicted !== undefined) this.ids.delete(evicted);
    }
    return true;
  }

  has(id: string): boolean {
    return this.ids.has(id);
  }

  get size(): number {
    return this.ids.size;
  }
}
