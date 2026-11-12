"use client";

import { AudioLines, Hand, Loader2, Mic, PlayCircle, ShieldAlert, Square, Volume2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ASSISTANT_NAME } from "@/lib/persona";
import { cn } from "@/lib/utils";

import type { VoiceConversation, VoicePhase } from "@/hooks/useVoiceConversation";

const PHASES: Record<Exclude<VoicePhase, "off">, { label: string; icon: typeof Mic; tone: string }> = {
  listening: { label: "Listening… speak now", icon: Mic, tone: "text-level-error" },
  processing: { label: `${ASSISTANT_NAME} is thinking…`, icon: Loader2, tone: "text-cyan-brand" },
  executing: { label: "Running in the browser…", icon: PlayCircle, tone: "text-violet-brand" },
  waiting_approval: { label: "Waiting for your approval in the dialog", icon: ShieldAlert, tone: "text-level-warning" },
  speaking: { label: `${ASSISTANT_NAME} is speaking`, icon: Volume2, tone: "text-level-success" },
  paused: { label: "Done — tap the mic to talk again", icon: Hand, tone: "text-muted-foreground" },
};

/** Live state of the hands-free voice conversation, with Stop and Interrupt. */
export function VoiceConversationBar({ voice }: { voice: VoiceConversation }) {
  if (!voice.active && !voice.error) return null;
  const meta = voice.active ? PHASES[voice.phase as Exclude<VoicePhase, "off">] ?? PHASES.processing : null;
  const Icon = meta?.icon ?? AudioLines;

  return (
    <div role="status" aria-live="polite" data-testid="voice-conversation"
      className="flex flex-col gap-1.5 rounded-lg border border-cyan-brand/25 bg-cyan-brand/[0.05] px-3 py-2 text-xs">
      {meta ? (
        <div className="flex flex-wrap items-center gap-2">
          <Icon className={cn("h-3.5 w-3.5", meta.tone, voice.phase === "processing" && "animate-spin")} aria-hidden />
          <span className={cn("font-medium", meta.tone)} data-testid="voice-phase">{meta.label}</span>
          <span className="ml-auto flex gap-1.5">
            {voice.phase === "speaking" && (
              <Button size="sm" variant="ghost" onClick={voice.interrupt}>
                <Hand aria-hidden /> Interrupt
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={voice.stop} data-testid="voice-stop">
              <Square aria-hidden /> Stop voice
            </Button>
          </span>
        </div>
      ) : null}
      {voice.interimTranscript ? <p className="italic text-cyan-brand/80">{voice.interimTranscript}…</p> : null}
      {voice.lastHeard ? (
        <p className="text-muted-foreground">
          You said: <span className="text-foreground">“{voice.lastHeard}”</span>
        </p>
      ) : null}
      {voice.notice ? <p className="text-level-warning">{voice.notice}</p> : null}
      {voice.error ? <p role="alert" className="text-level-error">{voice.error.message}</p> : null}
      {voice.active ? (
        <p className="text-[10px] text-muted-foreground">
          Low-risk steps (open, search, add to cart) can start automatically. Ordering, payment, sending and deleting always
          wait for your explicit approval.
        </p>
      ) : null}
    </div>
  );
}
