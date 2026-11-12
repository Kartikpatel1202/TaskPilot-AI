"use client";

import { Mic, MicOff, Square } from "lucide-react";

import { cn } from "@/lib/utils";

interface VoiceButtonProps {
  isListening: boolean;
  isSupported: boolean;
  onToggle: () => void;
  disabled?: boolean;
}

export function VoiceButton({ isListening, isSupported, onToggle, disabled = false }: VoiceButtonProps) {
  const label = !isSupported
    ? "Voice input is not supported in this browser"
    : isListening
      ? "Stop voice input"
      : "Start voice input";

  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled || !isSupported}
      aria-pressed={isListening}
      aria-label={label}
      title={label}
      className={cn(
        "relative inline-flex h-10 w-10 items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-40",
        isListening
          ? "border-level-error/50 bg-level-error/15 text-level-error"
          : "border-white/10 bg-white/[0.04] text-muted-foreground hover:border-cyan-brand/40 hover:text-cyan-brand",
      )}
    >
      {isListening && (
        <span aria-hidden className="absolute inset-0 rounded-full border border-level-error/60 animate-pulse-ring" />
      )}
      {!isSupported ? (
        <MicOff className="h-4 w-4" aria-hidden />
      ) : isListening ? (
        <Square className="h-3.5 w-3.5 fill-current" aria-hidden />
      ) : (
        <Mic className="h-4 w-4" aria-hidden />
      )}
    </button>
  );
}
