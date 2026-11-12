"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  buildBrowserStreamUrl,
  isNewerFrame,
  parseFramePacket,
  parseStreamControl,
} from "@/lib/browserStream";
import { HEARTBEAT_INTERVAL_MS, MAX_RECONNECT_ATTEMPTS, WS_BASE_URL } from "@/lib/constants";
import { computeBackoffDelay } from "@/lib/websocket";

import type { LiveFrame, StreamStatus } from "@/types/browser";

export interface UseBrowserStreamOptions {
  sessionId: string | null;
  enabled: boolean;
  wsBase?: string;
  maxFrameBytes?: number;
  /** Test seam; defaults to the browser WebSocket. */
  createSocket?: (url: string) => WebSocket;
}

export interface BrowserStreamHandle {
  frame: LiveFrame | null;
  status: StreamStatus;
  error: string | null;
  droppedFrames: number;
  reconnect: () => void;
}

const defaultSocket = (url: string) => new WebSocket(url);

/**
 * Live browser preview over the binary stream socket.
 * Only the newest frame is kept (as one object URL, revoked when replaced);
 * malformed, oversized, foreign-session and stale frames are dropped.
 */
export function useBrowserStream({
  sessionId,
  enabled,
  wsBase = WS_BASE_URL,
  maxFrameBytes,
  createSocket = defaultSocket,
}: UseBrowserStreamOptions): BrowserStreamHandle {
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [droppedFrames, setDroppedFrames] = useState(0);
  const [generation, setGeneration] = useState(0);

  const frameRef = useRef<LiveFrame | null>(null);
  const createRef = useRef(createSocket);
  createRef.current = createSocket;

  const replaceFrame = useCallback((next: LiveFrame | null) => {
    const previous = frameRef.current;
    frameRef.current = next;
    setFrame(next);
    if (previous && previous.url !== next?.url) URL.revokeObjectURL(previous.url);
  }, []);

  useEffect(() => {
    if (!enabled || !sessionId) {
      setStatus("idle");
      return undefined;
    }
    let socket: WebSocket | null = null;
    let disposed = false;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeat: ReturnType<typeof setInterval> | null = null;
    const url = buildBrowserStreamUrl(wsBase, sessionId);

    const clearTimers = () => {
      if (retryTimer) clearTimeout(retryTimer);
      if (heartbeat) clearInterval(heartbeat);
      retryTimer = null;
      heartbeat = null;
    };

    const connect = () => {
      if (disposed) return;
      setStatus(attempt === 0 ? "connecting" : "reconnecting");
      let ws: WebSocket;
      try {
        ws = createRef.current(url);
      } catch {
        setStatus("error");
        setError("The live preview could not connect.");
        return;
      }
      socket = ws;
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        attempt = 0;
        setError(null);
        ws.send(JSON.stringify({ type: "subscribe" }));
        heartbeat = setInterval(() => {
          if (ws.readyState === 1) ws.send(JSON.stringify({ type: "ping" }));
        }, HEARTBEAT_INTERVAL_MS);
      };

      ws.onmessage = (message: MessageEvent) => {
        if (typeof message.data === "string") {
          const parsed = parseStreamControl(message.data);
          if (!parsed.ok) return;
          const control = parsed.message;
          if (control.type === "stream.ready") {
            setStatus(control.status === "live" ? "live" : "waiting");
          } else if (control.type === "stream.ended") {
            setStatus("ended");
          } else if (control.type === "error") {
            setError(control.message);
          }
          return;
        }
        if (!(message.data instanceof ArrayBuffer)) return;
        const parsed = parseFramePacket(message.data, { expectedSessionId: sessionId, maxFrameBytes });
        if (!parsed.ok || !isNewerFrame(frameRef.current?.meta ?? null, parsed.meta)) {
          setDroppedFrames((n) => n + 1);
          return;
        }
        const blob = new Blob([parsed.jpeg], { type: "image/jpeg" });
        replaceFrame({ url: URL.createObjectURL(blob), meta: parsed.meta, receivedAt: Date.now() });
        setStatus("live");
      };

      ws.onerror = () => {
        setError("The live preview connection had a problem.");
      };

      ws.onclose = () => {
        clearTimers();
        if (disposed) return;
        if (attempt >= MAX_RECONNECT_ATTEMPTS) {
          setStatus("error");
          setError("The live preview disconnected. Use Reconnect to try again.");
          return;
        }
        const delay = computeBackoffDelay(attempt);
        attempt += 1;
        setStatus("reconnecting");
        retryTimer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      disposed = true;
      clearTimers();
      if (socket && socket.readyState <= 1) socket.close(1000, "Preview closed");
    };
  }, [enabled, sessionId, wsBase, maxFrameBytes, generation, replaceFrame]);

  // A different session never shows the previous session's frame.
  useEffect(() => {
    if (frameRef.current && frameRef.current.meta.session_id !== sessionId) replaceFrame(null);
  }, [sessionId, replaceFrame]);

  useEffect(() => () => replaceFrame(null), [replaceFrame]);

  const reconnect = useCallback(() => {
    setError(null);
    setGeneration((g) => g + 1);
  }, []);

  return { frame, status, error, droppedFrames, reconnect };
}
