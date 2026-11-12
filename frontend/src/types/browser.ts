/** Phase 3 browser types. Mirrors `backend/app/schemas/browser.py`. */

export type BrowserSessionStatus = "INITIALIZING" | "READY" | "BUSY" | "AUTH_REQUIRED" | "CLOSED" | "ERROR";

export interface BrowserStatusResponse {
  available: boolean;
  status: "ready" | "not_started" | "unavailable";
  engine: string;
  active_sessions: number;
  max_sessions: number;
  headless: boolean;
  message?: string | null;
}

export interface BrowserSessionInfo {
  session_id: string;
  status: BrowserSessionStatus;
  current_url?: string | null;
  current_title?: string | null;
  active_task_id?: string | null;
  created_at: string;
  last_activity_at: string;
  stream_status: "CONNECTED" | "DISCONNECTED";
  stream_subscribers: number;
  has_screenshot: boolean;
  auth_required: boolean;
  headless: boolean;
}

export interface BrowserSessionCloseResponse {
  session_id: string;
  closed: boolean;
  message: string;
}

/** Metadata that precedes every JPEG in a binary stream packet. */
export interface FrameMetadata {
  frame_id: string;
  session_id: string;
  task_id: string | null;
  sequence: number;
  captured_at: string;
  mime_type: "image/jpeg";
  width: number;
  height: number;
}

/** Text control messages on the stream socket. */
export type StreamControlMessage =
  | {
      type: "stream.ready";
      session_id: string;
      format: "jpeg";
      width: number;
      height: number;
      status: "live" | "waiting";
      max_fps: number;
    }
  | { type: "pong" }
  | { type: "stream.ended"; reason: string }
  | { type: "error"; code: string; message: string };

/** idle: not connected · connecting · waiting: connected, no browser yet · live: frames arriving. */
export type StreamStatus = "idle" | "connecting" | "waiting" | "live" | "reconnecting" | "ended" | "error";

export interface LiveFrame {
  /** Object URL of the latest JPEG (revoked when replaced). */
  url: string;
  meta: FrameMetadata;
  receivedAt: number;
}

export interface BrowserNotice {
  kind: "navigation_blocked" | "authentication_required" | "popup_blocked" | "download_blocked" | "session_error";
  message: string;
  url?: string | null;
  code?: string | null;
  at: string;
}

/** Browser state derived from telemetry (session-level, survives task changes). */
export interface BrowserLiveState {
  sessionStatus: BrowserSessionStatus | null;
  headless: boolean | null;
  engine: string | null;
  url: string | null;
  title: string | null;
  domain: string | null;
  lastFrameSequence: number | null;
  notice: BrowserNotice | null;
  updatedAt: string | null;
}
