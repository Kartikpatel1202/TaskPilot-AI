"use client";

import { AlertCircle, X } from "lucide-react";

import { ASSISTANT_NAME, VOICE_LANGUAGE_OPTIONS } from "@/lib/persona";
import { cn } from "@/lib/utils";

import type { SpeechRecognitionState, VoiceLanguage } from "@/types/voice";

interface VoiceStatusProps {
  state: Pick<SpeechRecognitionState, "isSupported" | "isListening" | "status" | "error" | "language">;
  onLanguageChange: (language: VoiceLanguage) => void;
  onDismissError: () => void;
}

export function VoiceStatus({ state, onLanguageChange, onDismissError }: VoiceStatusProps) {
  const { isSupported, isListening, error, language } = state;

  return (
    <div className="flex min-h-[28px] flex-wrap items-center gap-x-3 gap-y-2 text-xs">
      <div role="radiogroup" aria-label="Voice input language" className="inline-flex rounded-md border border-white/10 p-0.5">
        {VOICE_LANGUAGE_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={language === option.value}
            disabled={isListening || !isSupported}
            onClick={() => onLanguageChange(option.value)}
            title={option.label}
            className={cn(
              "rounded px-2 py-0.5 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
              language === option.value ? "bg-white/10 text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.short}
          </button>
        ))}
      </div>

      {isListening ? (
        <span className="inline-flex items-center gap-2 text-level-error" role="status" aria-live="polite">
          <span className="flex h-3 items-end gap-[2px]" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className="w-[3px] animate-pulse rounded-full bg-level-error"
                style={{ height: `${6 + ((i * 5) % 7)}px`, animationDelay: `${i * 120}ms` }}
              />
            ))}
          </span>
          Listening — {ASSISTANT_NAME} is all ears. Click the mic to stop.
        </span>
      ) : !isSupported ? (
        <span className="text-muted-foreground">Voice input isn&apos;t supported in this browser — try Chrome or Edge.</span>
      ) : (
        <span className="text-muted-foreground">Speak in English, Hindi or Hinglish. Voice never runs a command by itself.</span>
      )}

      {error && error.kind !== "unsupported" && (
        <span role="alert" className="inline-flex items-center gap-1.5 rounded-md border border-level-error/30 bg-level-error/10 px-2 py-1 text-level-error">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          {error.message}
          <button type="button" onClick={onDismissError} aria-label="Dismiss voice error" className="rounded p-0.5 hover:bg-white/10">
            <X className="h-3 w-3" />
          </button>
        </span>
      )}
    </div>
  );
}
