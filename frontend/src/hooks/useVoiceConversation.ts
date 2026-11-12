"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { usePreferences } from "@/components/settings/PreferencesProvider";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { useTaskPilotActions, useTaskPilotState, useTaskPilotUi } from "@/hooks/useTaskPilot";

import type { VoiceLanguage } from "@/types/voice";

/**
 * Hands-free voice conversation with Kamlesh Bhai.
 *
 *   mic click → listen → (pause) → final transcript is submitted automatically — as the answer when Kamlesh Bhai
 *   asked a question, otherwise as a new command → planning → low-risk browser plans start automatically
 *   (server-checked `voice_auto` trigger; anything sensitive waits for Run Plan and approvals) → the reply is
 *   spoken → listening resumes (when "keep listening" is on).
 *
 * One recognition instance only; the microphone is off while Kamlesh Bhai speaks or a plan is running, so
 * his own voice is never transcribed. Duplicate transcripts within a few seconds are ignored.
 */
export type VoicePhase = "off" | "listening" | "processing" | "executing" | "waiting_approval" | "speaking" | "paused";

const SUBMIT_AFTER_SILENCE_MS = 1200;
const DUPLICATE_WINDOW_MS = 5000;
const RESUME_DELAY_MS = 700;
const BUSY_STATES = new Set(["IDLE", "PLANNING", "EXECUTING", "WAITING_APPROVAL"]);

export interface VoiceConversation {
  active: boolean;
  phase: VoicePhase;
  interimTranscript: string;
  lastHeard: string | null;
  notice: string | null;
  isSupported: boolean;
  language: VoiceLanguage;
  setLanguage: (language: VoiceLanguage) => void;
  error: ReturnType<typeof useSpeechRecognition>["error"];
  clearError: () => void;
  start: () => void;
  stop: () => void;
  /** Stop Kamlesh Bhai speaking and listen right away (barge-in by click). */
  interrupt: () => void;
}

export function useVoiceConversation(): VoiceConversation {
  const state = useTaskPilotState();
  const { submitCommand, submitClarification, runPlan, setVoiceMode, cancelSpeech, say } = useTaskPilotActions();
  const { isSpeaking } = useTaskPilotUi();
  const { prefs } = usePreferences();

  const [active, setActive] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [lastHeard, setLastHeard] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const activeRef = useRef(false);
  const bufferRef = useRef("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSubmitRef = useRef<{ text: string; at: number } | null>(null);
  const voiceTasksRef = useRef(new Set<string>());
  const autoRunRef = useRef(new Set<string>());
  const stateRef = useRef(state);
  stateRef.current = state;

  const flush = useCallback(async () => {
    timerRef.current = null;
    const text = bufferRef.current.trim();
    bufferRef.current = "";
    if (!text || !activeRef.current) return;
    const now = Date.now();
    const last = lastSubmitRef.current;
    if (last && last.text.toLowerCase() === text.toLowerCase() && now - last.at < DUPLICATE_WINDOW_MS) return; // repeated phrase
    lastSubmitRef.current = { text, at: now };
    setLastHeard(text);
    setNotice(null);
    setProcessing(true);
    speechRef.current?.stop(); // the microphone stays off until the reply has been handled
    const { clarification, activeTask } = stateRef.current;
    const answering = clarification !== null && activeTask?.task_id === clarification.taskId;
    const result = answering ? await submitClarification(text, "VOICE") : await submitCommand(text, "VOICE");
    setProcessing(false);
    if (result.ok && result.taskId) voiceTasksRef.current.add(result.taskId);
    else if (!result.ok) setNotice(result.error ?? "That could not be sent.");
  }, [submitClarification, submitCommand]);

  const onFinalTranscript = useCallback(
    (text: string) => {
      if (!activeRef.current) return;
      bufferRef.current = `${bufferRef.current} ${text}`.trim();
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => void flush(), SUBMIT_AFTER_SILENCE_MS);
    },
    [flush],
  );

  const speech = useSpeechRecognition({
    onFinalTranscript,
    initialLanguage: prefs.language === "hi" ? "hi-IN" : "en-IN",
  });
  const speechRef = useRef(speech);
  speechRef.current = speech;

  // Settings: a fixed reply language also picks the recognition language.
  const { setLanguage } = speech;
  useEffect(() => {
    if (prefs.language === "hi") setLanguage("hi-IN");
    else if (prefs.language === "en" || prefs.language === "hinglish") setLanguage("en-IN");
  }, [prefs.language, setLanguage]);

  const task = state.activeTask;
  const taskState = task?.state ?? null;
  const isVoiceTask = task !== null && voiceTasksRef.current.has(task.task_id);
  const busy = processing || state.isSubmitting || state.isSubmittingClarification || (isVoiceTask && taskState !== null && BUSY_STATES.has(taskState));

  // Auto-run: a READY browser plan for a task spoken in this conversation (server re-checks risk and Settings).
  const plan = state.activePlan;
  useEffect(() => {
    if (!activeRef.current || !prefs.voice_auto_execute || !task || !plan) return;
    if (!voiceTasksRef.current.has(task.task_id) || plan.task_id !== task.task_id || autoRunRef.current.has(task.task_id)) return;
    if (task.state !== "PLANNED" || plan.status !== "READY" || plan.intent === "GENERAL_CHAT" || plan.steps.length === 0) return;
    autoRunRef.current.add(task.task_id);
    void runPlan(task.task_id, "voice_auto").then((result) => {
      if (!result.ok && result.error) {
        setNotice(result.error);
        say(result.error, plan.language ?? "en");
      }
    });
  }, [task, plan, prefs.voice_auto_execute, runPlan, say]);

  // Resume listening once nothing is pending and Kamlesh Bhai has finished speaking.
  useEffect(() => {
    if (!active || busy || isSpeaking || speech.isListening || speech.status === "error") return undefined;
    if (lastHeard !== null && !prefs.voice_continuous) {
      return undefined; // one exchange per mic click
    }
    const id = setTimeout(() => {
      if (activeRef.current && !speechRef.current.isListening) speechRef.current.start();
    }, RESUME_DELAY_MS);
    return () => clearTimeout(id);
  }, [active, busy, isSpeaking, speech.isListening, speech.status, lastHeard, prefs.voice_continuous]);

  // While Kamlesh Bhai speaks or a plan runs, keep the microphone closed (no self-transcription, no conflicts).
  useEffect(() => {
    if (active && (isSpeaking || busy) && speech.isListening && !timerRef.current) speech.stop();
  }, [active, isSpeaking, busy, speech]);

  // Microphone permission problems end the conversation (with the error shown).
  useEffect(() => {
    if (active && speech.error && speech.error.kind !== "no-speech" && speech.error.kind !== "aborted") {
      activeRef.current = false;
      setActive(false);
      setVoiceMode(false);
    }
  }, [active, speech.error, setVoiceMode]);

  const start = useCallback(() => {
    if (activeRef.current) return;
    activeRef.current = true;
    bufferRef.current = "";
    setActive(true);
    setNotice(null);
    setLastHeard(null);
    setVoiceMode(true);
    speechRef.current.clearError();
    speechRef.current.start();
  }, [setVoiceMode]);

  const stop = useCallback(() => {
    activeRef.current = false;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    bufferRef.current = "";
    setActive(false);
    setProcessing(false);
    speechRef.current.stop();
    cancelSpeech();
    setVoiceMode(false);
  }, [cancelSpeech, setVoiceMode]);

  const interrupt = useCallback(() => {
    cancelSpeech();
    if (activeRef.current && !speechRef.current.isListening) speechRef.current.start();
  }, [cancelSpeech]);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  let phase: VoicePhase = "off";
  if (active) {
    if (speech.isListening) phase = "listening";
    else if (isSpeaking) phase = "speaking";
    else if (isVoiceTask && taskState === "WAITING_APPROVAL") phase = "waiting_approval";
    else if (isVoiceTask && taskState === "EXECUTING") phase = "executing";
    else if (busy) phase = "processing";
    else phase = prefs.voice_continuous || lastHeard === null ? "processing" : "paused";
  }

  return {
    active,
    phase,
    interimTranscript: speech.interimTranscript,
    lastHeard,
    notice,
    isSupported: speech.isSupported,
    language: speech.language,
    setLanguage: speech.setLanguage,
    error: speech.error,
    clearError: speech.clearError,
    start,
    stop,
    interrupt,
  };
}
