import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Compact, non-sensitive display form of an identifier, e.g. `3f2a…9c1d`. */
export function shortId(id: string | null | undefined, head = 4, tail = 4): string {
  if (!id) return "—";
  const compact = id.replace(/-/g, "");
  if (compact.length <= head + tail) return compact;
  return `${compact.slice(0, head)}…${compact.slice(-tail)}`;
}

export function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatRelativeSeconds(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
}

const SENSITIVE_KEY = /(pass(word)?|secret|token|api[_-]?key|authorization|cookie|session[_-]?token|card|cvv|otp|credential)/i;

/** Defence in depth: redact sensitive-looking keys before rendering metadata. */
export function redactSensitive(value: unknown, depth = 0): unknown {
  if (depth > 6) return "[TRUNCATED]";
  if (Array.isArray(value)) return value.slice(0, 100).map((v) => redactSensitive(v, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [
        k,
        SENSITIVE_KEY.test(k) ? "[REDACTED]" : redactSensitive(v, depth + 1),
      ]),
    );
  }
  return value;
}

export function safeStorageGet(storage: "local" | "session", key: string): string | null {
  try {
    return (storage === "local" ? window.localStorage : window.sessionStorage).getItem(key);
  } catch {
    return null;
  }
}

export function safeStorageSet(storage: "local" | "session", key: string, value: string): void {
  try {
    (storage === "local" ? window.localStorage : window.sessionStorage).setItem(key, value);
  } catch {
    /* storage unavailable (private mode, blocked) — non-critical */
  }
}
