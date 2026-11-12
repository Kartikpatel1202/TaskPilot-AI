"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  SpeechRecognitionConstructor,
  SpeechRecognitionErrorKind,
  SpeechRecognitionLike,
  SpeechRecognitionState,
  SpeechRecognitionStatus,
  VoiceLanguage,
} from "@/types/voice";

export function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}

const ERROR_MESSAGES: Record<SpeechRecognitionErrorKind, string> = {
  unsupported: "Voice input isn't supported in this browser. Try Chrome or Edge.",
  "permission-denied": "Microphone permission was denied. Allow microphone access in your browser settings.",
  "no-microphone": "No microphone was found, or it is being used by another app.",
  "no-speech": "Didn't catch that — no speech was detected. Try again.",
  network: "Speech recognition needs a network connection in this browser.",
  aborted: "Voice input was stopped.",
  unknown: "Voice input failed unexpectedly. Please try again.",
};

export function mapRecognitionError(code: string): SpeechRecognitionErrorKind {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "permission-denied";
    case "audio-capture":
      return "no-microphone";
    case "no-speech":
      return "no-speech";
    case "network":
      return "network";
    case "aborted":
      return "aborted";
    default:
      return "unknown";
  }
}

export interface UseSpeechRecognitionOptions {
  /** Receives each finalised transcript segment. Never submits anything. */
  onFinalTranscript: (text: string) => void;
  initialLanguage?: VoiceLanguage;
}

export interface UseSpeechRecognitionResult extends SpeechRecognitionState {
  start: () => void;
  stop: () => void;
  toggle: () => void;
  setLanguage: (language: VoiceLanguage) => void;
  clearError: () => void;
}

export function useSpeechRecognition({
  onFinalTranscript,
  initialLanguage = "en-IN",
}: UseSpeechRecognitionOptions): UseSpeechRecognitionResult {
  const [isSupported, setIsSupported] = useState(false);
  const [status, setStatus] = useState<SpeechRecognitionStatus>("idle");
  const [interimTranscript, setInterim] = useState("");
  const [error, setError] = useState<SpeechRecognitionState["error"]>(null);
  const [language, setLanguageState] = useState<VoiceLanguage>(initialLanguage);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const onFinalRef = useRef(onFinalTranscript);
  useEffect(() => {
    onFinalRef.current = onFinalTranscript;
  });

  // Feature detection runs on the client only (keeps SSR markup stable).
  useEffect(() => {
    setIsSupported(getSpeechRecognitionConstructor() !== null);
  }, []);

  const detach = (recognition: SpeechRecognitionLike) => {
    recognition.onstart = null;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
  };

  const start = useCallback(() => {
    // Prevent multiple simultaneous recognition instances.
    if (recognitionRef.current) return;
    const Ctor = getSpeechRecognitionConstructor();
    if (!Ctor) {
      setError({ kind: "unsupported", message: ERROR_MESSAGES.unsupported });
      setStatus("error");
      return;
    }

    const recognition = new Ctor();
    recognition.lang = language;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      if (recognitionRef.current === recognition) setStatus("listening");
    };
    recognition.onresult = (event) => {
      if (recognitionRef.current !== recognition) return;
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result?.[0]?.transcript ?? "";
        if (!result) continue;
        if (result.isFinal) {
          const text = transcript.trim();
          if (text) onFinalRef.current(text);
        } else {
          interim += transcript;
        }
      }
      setInterim(interim.trim());
    };
    recognition.onerror = (event) => {
      if (recognitionRef.current !== recognition) return;
      const kind = mapRecognitionError(event.error);
      if (kind !== "aborted") {
        setError({ kind, message: ERROR_MESSAGES[kind] });
        setStatus("error");
      }
    };
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return;
      detach(recognition);
      recognitionRef.current = null;
      setInterim("");
      setStatus((s) => (s === "error" ? "error" : "idle"));
    };

    recognitionRef.current = recognition;
    setError(null);
    setInterim("");
    setStatus("starting");
    try {
      recognition.start();
    } catch {
      detach(recognition);
      recognitionRef.current = null;
      setError({ kind: "unknown", message: ERROR_MESSAGES.unknown });
      setStatus("error");
    }
  }, [language]);

  const stop = useCallback(() => {
    const recognition = recognitionRef.current;
    if (!recognition) return;
    setStatus("stopping");
    try {
      recognition.stop(); // delivers any pending final result, then fires onend
    } catch {
      recognition.abort();
    }
  }, []);

  const toggle = useCallback(() => {
    if (recognitionRef.current) stop();
    else start();
  }, [start, stop]);

  const setLanguage = useCallback((next: VoiceLanguage) => {
    setLanguageState(next);
  }, []);

  const clearError = useCallback(() => {
    setError(null);
    setStatus((s) => (s === "error" ? "idle" : s));
  }, []);

  // Clean up on unmount: abort and release the microphone.
  useEffect(() => {
    return () => {
      const recognition = recognitionRef.current;
      if (recognition) {
        detach(recognition);
        try {
          recognition.abort();
        } catch {
          /* already stopped */
        }
        recognitionRef.current = null;
      }
    };
  }, []);

  return {
    isSupported,
    status,
    isListening: status === "listening" || status === "starting",
    interimTranscript,
    error,
    language,
    start,
    stop,
    toggle,
    setLanguage,
    clearError,
  };
}
