"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  HEARTBEAT_INTERVAL_MS,
  MAX_RECONNECT_ATTEMPTS,
  PONG_TIMEOUT_MS,
} from "@/lib/constants";
import { parseServerMessage } from "@/lib/validators";
import { computeBackoffDelay, serializeClientMessage } from "@/lib/websocket";

import type { ClientMessage, ConnectionStatus, ServerMessage } from "@/types/telemetry";

const CLOSE_POLICY_VIOLATION = 1008;
const CLOSE_HEARTBEAT_TIMEOUT = 4000;

export interface UseWebSocketOptions {
  /** Full WebSocket URL. `null` keeps the hook idle (e.g. before a session id exists). */
  url: string | null;
  onMessage: (message: ServerMessage) => void;
  onProtocolError?: (reason: string) => void;
  /** Called on every (re)connect so the server can replay missed events. */
  getResumeEventId?: () => string | null;
  maxRetries?: number;
  heartbeatIntervalMs?: number;
  pongTimeoutMs?: number;
}

export interface UseWebSocketResult {
  status: ConnectionStatus;
  attempt: number;
  send: (message: ClientMessage) => boolean;
  reconnect: () => void;
  disconnect: () => void;
}

export function useWebSocket({
  url,
  onMessage,
  onProtocolError,
  getResumeEventId,
  maxRetries = MAX_RECONNECT_ATTEMPTS,
  heartbeatIntervalMs = HEARTBEAT_INTERVAL_MS,
  pongTimeoutMs = PONG_TIMEOUT_MS,
}: UseWebSocketOptions): UseWebSocketResult {
  const [status, setStatus] = useState<ConnectionStatus>("CONNECTING");
  const [attempt, setAttempt] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const intentionalCloseRef = useRef(false);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pongTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectRef = useRef<() => void>(() => undefined);

  // "Latest ref" pattern: socket handlers always call the current callbacks,
  // without re-creating the connection when callbacks change (no stale closures).
  const onMessageRef = useRef(onMessage);
  const onProtocolErrorRef = useRef(onProtocolError);
  const getResumeRef = useRef(getResumeEventId);
  useEffect(() => {
    onMessageRef.current = onMessage;
    onProtocolErrorRef.current = onProtocolError;
    getResumeRef.current = getResumeEventId;
  });

  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (heartbeatTimerRef.current) clearInterval(heartbeatTimerRef.current);
    if (pongTimerRef.current) clearTimeout(pongTimerRef.current);
    reconnectTimerRef.current = null;
    heartbeatTimerRef.current = null;
    pongTimerRef.current = null;
  }, []);

  const closeSocket = useCallback((ws: WebSocket | null, code = 1000) => {
    if (!ws) return;
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    if (ws.readyState === WebSocket.CONNECTING) {
      // Closing a CONNECTING socket logs a browser error; close as soon as it opens instead.
      ws.onopen = () => ws.close(1000);
    } else {
      ws.onopen = null;
      if (ws.readyState === WebSocket.OPEN) ws.close(code);
    }
  }, []);

  const sendRaw = useCallback((message: ClientMessage): boolean => {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    try {
      ws.send(serializeClientMessage(message));
      return true;
    } catch {
      return false;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (attemptRef.current >= maxRetries) {
      setStatus("ERROR");
      return;
    }
    const delay = computeBackoffDelay(attemptRef.current);
    attemptRef.current += 1;
    setAttempt(attemptRef.current);
    setStatus("RECONNECTING");
    reconnectTimerRef.current = setTimeout(() => connectRef.current(), delay);
  }, [maxRetries]);

  const connect = useCallback(() => {
    if (!url) return;
    clearTimers();
    closeSocket(socketRef.current);
    intentionalCloseRef.current = false;
    setStatus(attemptRef.current > 0 ? "RECONNECTING" : "CONNECTING");

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      setStatus("ERROR");
      return;
    }
    socketRef.current = ws;

    ws.onopen = () => {
      if (socketRef.current !== ws) return;
      attemptRef.current = 0;
      setAttempt(0);
      setStatus("CONNECTED");
      sendRaw({ type: "subscribe", after_event_id: getResumeRef.current?.() ?? null });
      heartbeatTimerRef.current = setInterval(() => {
        if (!sendRaw({ type: "ping" })) return;
        if (pongTimerRef.current) clearTimeout(pongTimerRef.current);
        pongTimerRef.current = setTimeout(() => {
          // No pong: treat as a dead connection and let onclose reconnect.
          if (socketRef.current === ws) ws.close(CLOSE_HEARTBEAT_TIMEOUT, "Heartbeat timeout");
        }, pongTimeoutMs);
      }, heartbeatIntervalMs);
    };

    ws.onmessage = (event: MessageEvent) => {
      if (socketRef.current !== ws) return;
      const result = parseServerMessage(event.data);
      if (!result.ok) {
        onProtocolErrorRef.current?.(result.reason);
        return;
      }
      if (result.message.kind === "control" && result.message.message.type === "pong" && pongTimerRef.current) {
        clearTimeout(pongTimerRef.current);
        pongTimerRef.current = null;
      }
      try {
        onMessageRef.current(result.message);
      } catch (error) {
        console.error("[TaskPilot] telemetry handler failed", error);
      }
    };

    ws.onerror = () => {
      /* An error is always followed by `close`; reconnection is handled there. */
    };

    ws.onclose = (event: CloseEvent) => {
      if (socketRef.current !== ws) return;
      socketRef.current = null;
      clearTimers();
      if (intentionalCloseRef.current) {
        setStatus("DISCONNECTED");
      } else if (event.code === CLOSE_POLICY_VIOLATION) {
        setStatus("ERROR"); // e.g. invalid session id — retrying cannot help
      } else {
        scheduleReconnect();
      }
    };
  }, [url, clearTimers, closeSocket, sendRaw, scheduleReconnect, heartbeatIntervalMs, pongTimeoutMs]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (!url) return undefined;
    attemptRef.current = 0;
    connect();
    return () => {
      intentionalCloseRef.current = true;
      clearTimers();
      closeSocket(socketRef.current);
      socketRef.current = null;
    };
  }, [url, connect, clearTimers, closeSocket]);

  const reconnect = useCallback(() => {
    attemptRef.current = 0;
    setAttempt(0);
    connect();
  }, [connect]);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    clearTimers();
    closeSocket(socketRef.current);
    socketRef.current = null;
    setStatus("DISCONNECTED");
  }, [clearTimers, closeSocket]);

  // Retry immediately when the browser comes back online after giving up.
  useEffect(() => {
    const handleOnline = () => {
      if (!intentionalCloseRef.current && !socketRef.current) reconnect();
    };
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [reconnect]);

  return { status, attempt, send: sendRaw, reconnect, disconnect };
}
