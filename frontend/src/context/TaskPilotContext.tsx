"use client";

import { createContext, useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";

import { useAgentPlan } from "@/hooks/useAgentPlan";
import { useBrowserSession } from "@/hooks/useBrowserSession";
import { useCommerce, type CommerceCommandResult } from "@/hooks/useCommerce";
import { useExecution, useExecutionRecovery, type ExecutionCommandResult } from "@/hooks/useExecution";
import { usePreferences } from "@/components/settings/PreferencesProvider";
import { useSpeechSynthesis } from "@/hooks/useSpeechSynthesis";
import { useWebSocket } from "@/hooks/useWebSocket";
import {
  ApiError,
  createTask,
  getAgentStatus,
  submitApprovalDecision,
  submitClarification as submitClarificationRequest,
  triggerDemoApproval,
  triggerDemoTelemetry,
} from "@/lib/api";
import { DEMO_MODE, MAX_COMMAND_LENGTH, VOICE_REPLIES_STORAGE_KEY, WS_BASE_URL } from "@/lib/constants";
import { speechLangFor } from "@/lib/persona";
import { safeStorageGet, safeStorageSet } from "@/lib/utils";
import { EventDeduplicator, buildWebSocketUrl, getOrCreateSessionId } from "@/lib/websocket";

import {
  clientLog,
  initialTaskPilotState,
  mapEventToActions,
  taskPilotReducer,
  type TaskPilotState,
} from "./taskPilotReducer";

import type { ApprovalDecision, ApprovalResponse } from "@/types/approval";
import type { InputMode } from "@/types/task";
import type { ServerMessage } from "@/types/telemetry";

export interface SubmitResult {
  ok: boolean;
  error?: string;
  /** The task the command created or answered (voice mode follows it). */
  taskId?: string;
}

export interface TaskPilotActions {
  submitCommand: (command: string, inputMode: InputMode) => Promise<SubmitResult>;
  decideApproval: (approvalId: string, decision: ApprovalDecision) => Promise<ApprovalResponse>;
  dismissApproval: (approvalId: string) => void;
  runDemoTelemetry: () => Promise<void>;
  runDemoApproval: () => Promise<void>;
  clearLogs: () => void;
  dismissAccepted: () => void;
  clearError: () => void;
  reconnect: () => void;
  setVoiceReplies: (enabled: boolean) => void;
  /** Voice conversation mode: Kamlesh Bhai's replies are spoken (if voice output is on in Settings). */
  setVoiceMode: (active: boolean) => void;
  cancelSpeech: () => void;
  /** Speak a short local message (voice mode), honouring the voice-output setting. */
  say: (text: string, language?: "en" | "hi" | "hinglish") => void;
  /** Answers Kamlesh Bhai's clarification for the active task (never creates a new task). */
  submitClarification: (message: string, inputMode: InputMode) => Promise<SubmitResult>;
  retryPlanFetch: () => void;
  /** The ONLY way a plan starts running in Chromium: Run Plan click, or voice auto-run (server-limited to low-risk plans). */
  runPlan: (taskId: string, trigger?: "run_plan_click" | "voice_auto") => Promise<ExecutionCommandResult>;
  stopExecution: (taskId: string) => Promise<ExecutionCommandResult>;
  closeBrowser: () => Promise<ExecutionCommandResult>;
  dismissBrowserNotice: () => void;
  clearExecutionError: () => void;
  // Phase 4 commerce (no action here can place an order)
  chooseProduct: (selectionId: string, candidateId: string | null) => Promise<CommerceCommandResult>;
  refreshCart: () => Promise<CommerceCommandResult>;
  changeCartQuantity: (itemId: string, quantity: number) => Promise<CommerceCommandResult>;
  reviewCheckout: () => Promise<CommerceCommandResult>;
}

export interface TaskPilotUi {
  /** Demo controls are shown only if the frontend AND backend both allow them. */
  demoAvailable: boolean;
  voiceReplies: boolean;
  speechSupported: boolean;
  /** Kamlesh Bhai is currently speaking (voice mode waits before listening again). */
  isSpeaking: boolean;
  reconnectAttempt: number;
  /** Backend allows real browser execution and Chromium is installed. */
  executionAvailable: boolean;
}

export const TaskPilotStateContext = createContext<TaskPilotState | null>(null);
export const TaskPilotActionsContext = createContext<TaskPilotActions | null>(null);
export const TaskPilotUiContext = createContext<TaskPilotUi | null>(null);

const SPEAK_FRESHNESS_MS = 10_000;

export function TaskPilotProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(taskPilotReducer, initialTaskPilotState);
  const [voiceReplies, setVoiceRepliesState] = useState(false);
  const dedupRef = useRef(new EventDeduplicator());
  const lastEventIdRef = useRef<string | null>(null);
  const lastSequenceRef = useRef(0);
  const voiceRepliesRef = useRef(false);
  const { prefs } = usePreferences();
  const synthesis = useSpeechSynthesis({ rate: prefs.speech_rate });
  const voiceModeRef = useRef(false);
  const voiceOutputRef = useRef(prefs.voice_output_enabled);
  voiceOutputRef.current = prefs.voice_output_enabled;
  const speakRef = useRef(synthesis.speak);
  speakRef.current = synthesis.speak;

  // Session id is created on the client only (avoids SSR hydration mismatch).
  useEffect(() => {
    dispatch({ type: "SET_SESSION_ID", sessionId: getOrCreateSessionId() });
    const stored = safeStorageGet("local", VOICE_REPLIES_STORAGE_KEY) === "true";
    voiceRepliesRef.current = stored;
    setVoiceRepliesState(stored);
  }, []);

  // WebSocket -> validation (in useWebSocket) -> dedupe -> reducer -> UI
  const handleMessage = useCallback((message: ServerMessage) => {
    if (message.kind === "control") {
      if (message.message.type === "error") {
        dispatch({
          type: "ADD_LOG",
          log: clientLog("WARNING", `Server rejected a client message: ${message.message.message}`),
        });
      }
      return;
    }
    const event = message.event;
    if (!dedupRef.current.markIfNew(event.event_id)) return; // duplicate (e.g. replay overlap)

    // connection.ready is per-connection and not part of the replayable history.
    if (event.type !== "connection.ready" && event.sequence > lastSequenceRef.current) {
      lastSequenceRef.current = event.sequence;
      lastEventIdRef.current = event.event_id;
    }
    for (const action of mapEventToActions(event)) dispatch(action);

    const fresh = Date.now() - new Date(event.occurred_at).getTime() < SPEAK_FRESHNESS_MS;
    const speakReplies = voiceRepliesRef.current || (voiceModeRef.current && voiceOutputRef.current);
    if (speakReplies && fresh) {
      if (event.type === "log.created" && event.data.source === "assistant") {
        speakRef.current(event.data.message, speechLangFor(event.data.language));
      } else if (event.type === "agent.response_generated") {
        speakRef.current(event.data.message, speechLangFor(event.data.language));
      }
    }
  }, []);

  const handleProtocolError = useCallback((reason: string) => {
    dispatch({ type: "ADD_LOG", log: clientLog("ERROR", `Protocol error: ignored a message. ${reason}`) });
  }, []);

  const getResumeEventId = useCallback(() => lastEventIdRef.current, []);

  const wsUrl = state.sessionId ? buildWebSocketUrl(WS_BASE_URL, state.sessionId) : null;
  const socket = useWebSocket({
    url: wsUrl,
    onMessage: handleMessage,
    onProtocolError: handleProtocolError,
    getResumeEventId,
  });

  useEffect(() => {
    dispatch({ type: "SET_CONNECTION_STATUS", status: socket.status });
  }, [socket.status]);

  // Kamlesh Bhai's planner status (provider/model/mock) — cheap, no LLM call.
  useEffect(() => {
    if (socket.status !== "CONNECTED") return undefined;
    let cancelled = false;
    getAgentStatus()
      .then((info) => {
        if (!cancelled) dispatch({ type: "SET_AGENT_INFO", info });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [socket.status]);

  const { retryPlanFetch } = useAgentPlan({ planFetch: state.planFetch, sessionId: state.sessionId, dispatch });

  // ---------------------------------------------------------------- actions

  const stateRef = useRef(state);
  stateRef.current = state;

  // ---------------------------------------------------------------- Phase 3: browser + execution
  const connected = socket.status === "CONNECTED";
  const { runPlan, stopExecution } = useExecution({ stateRef, dispatch });
  const { closeSession } = useBrowserSession({
    sessionId: state.sessionId,
    connected,
    sessionStatus: state.browser.sessionStatus,
    dispatch,
  });
  useExecutionRecovery({
    sessionId: state.sessionId,
    taskId: state.activeTask?.task_id ?? null,
    taskState: state.activeTask?.state ?? null,
    hasExecution: state.execution?.taskId === state.activeTask?.task_id && state.execution !== null,
    connected,
    dispatch,
  });
  const closeBrowser = useCallback(async () => {
    const result = await closeSession();
    if (!result.ok && result.error) dispatch({ type: "ADD_LOG", log: clientLog("WARNING", result.error) });
    return result;
  }, [closeSession]);
  const dismissBrowserNotice = useCallback(() => dispatch({ type: "DISMISS_BROWSER_NOTICE" }), []);
  const activeTaskId = state.activeTask?.task_id ?? null;
  const hasCommercePlan =
    state.activePlan?.task_id === activeTaskId && (state.activePlan?.steps.some((s) => s.action.type === "commerce") ?? false);
  const commerce = useCommerce({
    sessionId: state.sessionId,
    taskId: activeTaskId,
    enabled: connected && hasCommercePlan && (state.execution?.taskId === activeTaskId || state.commerce?.taskId === activeTaskId),
    revision: state.commerce?.taskId === activeTaskId ? state.commerce.revision : 0,
    dispatch,
  });
  const clearExecutionError = useCallback(() => dispatch({ type: "CLEAR_EXECUTION_ERROR" }), []);

  const submitCommand = useCallback(async (command: string, inputMode: InputMode): Promise<SubmitResult> => {
    const { sessionId, connectionStatus, isSubmitting } = stateRef.current;
    const trimmed = command.trim();
    if (!trimmed) return { ok: false, error: "Please enter a command." };
    if (trimmed.length > MAX_COMMAND_LENGTH) {
      return { ok: false, error: `Commands are limited to ${MAX_COMMAND_LENGTH.toLocaleString()} characters.` };
    }
    if (!sessionId || connectionStatus !== "CONNECTED") {
      return { ok: false, error: "TaskPilot is offline. Reconnect before sending a command." };
    }
    if (isSubmitting) return { ok: false, error: "A command is already being submitted." };

    dispatch({ type: "SET_SUBMITTING", value: true });
    dispatch({ type: "SET_ERROR", error: null });
    try {
      const response = await createTask({ command: trimmed, session_id: sessionId, input_mode: inputMode });
      dispatch({
        type: "TASK_ACCEPTED",
        message: response.message,
        task: {
          task_id: response.task_id,
          session_id: response.session_id,
          command: trimmed,
          input_mode: inputMode,
          state: response.state,
          created_at: response.created_at,
          updated_at: response.created_at,
          error_message: null,
          is_demo: false,
        },
      });
      return { ok: true, taskId: response.task_id };
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Something went wrong while sending your command.";
      dispatch({ type: "SET_ERROR", error: message });
      dispatch({ type: "ADD_LOG", log: clientLog("ERROR", `Command not submitted: ${message}`) });
      return { ok: false, error: message };
    } finally {
      dispatch({ type: "SET_SUBMITTING", value: false });
    }
  }, []);

  const decideApproval = useCallback(async (approvalId: string, decision: ApprovalDecision) => {
    // Errors propagate to the dialog so it can show them inline.
    return submitApprovalDecision(approvalId, { decision });
  }, []);

  const dismissApproval = useCallback((approvalId: string) => {
    dispatch({ type: "DISMISS_APPROVAL", approvalId });
  }, []);

  const runDemo = useCallback(async (kind: "telemetry" | "approval") => {
    const { sessionId } = stateRef.current;
    if (!sessionId) return;
    try {
      await (kind === "telemetry" ? triggerDemoTelemetry(sessionId) : triggerDemoApproval(sessionId));
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Demo request failed.";
      dispatch({ type: "ADD_LOG", log: clientLog("ERROR", `Demo ${kind} unavailable: ${message}`) });
    }
  }, []);

  const runDemoTelemetry = useCallback(() => runDemo("telemetry"), [runDemo]);
  const runDemoApproval = useCallback(() => runDemo("approval"), [runDemo]);
  const clearLogs = useCallback(() => dispatch({ type: "CLEAR_LOGS" }), []);
  const dismissAccepted = useCallback(() => dispatch({ type: "DISMISS_ACCEPTED" }), []);
  const clearError = useCallback(() => dispatch({ type: "SET_ERROR", error: null }), []);
  const cancelSpeech = synthesis.cancel;

  const setVoiceReplies = useCallback(
    (enabled: boolean) => {
      voiceRepliesRef.current = enabled;
      setVoiceRepliesState(enabled);
      safeStorageSet("local", VOICE_REPLIES_STORAGE_KEY, String(enabled));
      if (!enabled) cancelSpeech();
    },
    [cancelSpeech],
  );

  const say = useCallback((text: string, language: "en" | "hi" | "hinglish" = "en") => {
    if (voiceOutputRef.current) speakRef.current(text, speechLangFor(language));
  }, []);

  const setVoiceMode = useCallback(
    (active: boolean) => {
      voiceModeRef.current = active;
      if (!active && !voiceRepliesRef.current) cancelSpeech();
    },
    [cancelSpeech],
  );

  const submitClarification = useCallback(async (message: string, inputMode: InputMode): Promise<SubmitResult> => {
    const { sessionId, clarification, connectionStatus, isSubmittingClarification } = stateRef.current;
    const trimmed = message.trim();
    if (!trimmed) return { ok: false, error: "Please type your answer first." };
    if (trimmed.length > MAX_COMMAND_LENGTH) return { ok: false, error: "That answer is too long." };
    if (!sessionId || !clarification) return { ok: false, error: "There is no question waiting for an answer." };
    if (connectionStatus !== "CONNECTED") return { ok: false, error: "TaskPilot is offline. Reconnect first." };
    if (isSubmittingClarification) return { ok: false, error: "Your answer is already being sent." };

    dispatch({ type: "SET_CLARIFICATION_SUBMITTING", value: true });
    try {
      await submitClarificationRequest(clarification.taskId, { session_id: sessionId, message: trimmed, input_mode: inputMode });
      dispatch({ type: "CLARIFICATION_SUBMITTED", taskId: clarification.taskId });
      return { ok: true, taskId: clarification.taskId };
    } catch (error) {
      const text = error instanceof ApiError ? error.message : "Your answer could not be sent.";
      dispatch({ type: "SET_CLARIFICATION_SUBMITTING", value: false });
      dispatch({ type: "ADD_LOG", log: clientLog("ERROR", `Clarification not sent: ${text}`) });
      return { ok: false, error: text };
    }
  }, []);

  const { reconnect } = socket;
  const actions = useMemo<TaskPilotActions>(
    () => ({
      submitCommand,
      decideApproval,
      dismissApproval,
      runDemoTelemetry,
      runDemoApproval,
      clearLogs,
      dismissAccepted,
      clearError,
      reconnect,
      setVoiceReplies,
      setVoiceMode,
      cancelSpeech,
      say,
      submitClarification,
      retryPlanFetch,
      runPlan,
      stopExecution,
      closeBrowser,
      dismissBrowserNotice,
      clearExecutionError,
      chooseProduct: commerce.chooseProduct,
      refreshCart: commerce.refreshCart,
      changeCartQuantity: commerce.changeQuantity,
      reviewCheckout: commerce.reviewCheckout,
    }),
    [
      submitCommand,
      decideApproval,
      dismissApproval,
      runDemoTelemetry,
      runDemoApproval,
      clearLogs,
      dismissAccepted,
      clearError,
      reconnect,
      setVoiceReplies,
      setVoiceMode,
      cancelSpeech,
      say,
      submitClarification,
      retryPlanFetch,
      runPlan,
      stopExecution,
      closeBrowser,
      dismissBrowserNotice,
      clearExecutionError,
      commerce.chooseProduct,
      commerce.refreshCart,
      commerce.changeQuantity,
      commerce.reviewCheckout,
    ],
  );

  const ui = useMemo<TaskPilotUi>(
    () => ({
      demoAvailable: DEMO_MODE && state.serverInfo?.demo_endpoints_enabled === true,
      voiceReplies,
      speechSupported: synthesis.isSupported,
      isSpeaking: synthesis.isSpeaking,
      reconnectAttempt: socket.attempt,
      executionAvailable:
        state.agentInfo?.browser_execution_enabled === true && state.browserStatus?.status !== "unavailable",
    }),
    [
      state.serverInfo?.demo_endpoints_enabled,
      voiceReplies,
      synthesis.isSupported,
      synthesis.isSpeaking,
      socket.attempt,
      state.agentInfo?.browser_execution_enabled,
      state.browserStatus?.status,
    ],
  );

  return (
    <TaskPilotStateContext.Provider value={state}>
      <TaskPilotActionsContext.Provider value={actions}>
        <TaskPilotUiContext.Provider value={ui}>{children}</TaskPilotUiContext.Provider>
      </TaskPilotActionsContext.Provider>
    </TaskPilotStateContext.Provider>
  );
}
