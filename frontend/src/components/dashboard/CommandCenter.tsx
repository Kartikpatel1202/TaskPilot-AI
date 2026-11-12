"use client";

import { CheckCircle2, TerminalSquare, WifiOff, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { CommandInput } from "@/components/command/CommandInput";
import { CommandSuggestions } from "@/components/command/CommandSuggestions";
import { VoiceButton } from "@/components/command/VoiceButton";
import { VoiceConversationBar } from "@/components/command/VoiceConversationBar";
import { VoiceStatus } from "@/components/command/VoiceStatus";
import { usePreferences } from "@/components/settings/PreferencesProvider";
import { Badge } from "@/components/ui/badge";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import { useTaskPilotActions, useTaskPilotState } from "@/hooks/useTaskPilot";
import { useVoiceConversation } from "@/hooks/useVoiceConversation";
import { MAX_COMMAND_LENGTH } from "@/lib/constants";
import { ASSISTANT_NAME } from "@/lib/persona";
import { shortId } from "@/lib/utils";

import type { InputMode } from "@/types/task";

export function CommandCenter() {
  const { connectionStatus, isSubmitting, lastAccepted, error } = useTaskPilotState();
  const { submitCommand, dismissAccepted, clearError } = useTaskPilotActions();
  const [command, setCommand] = useState("");
  const [inputMode, setInputMode] = useState<InputMode>("TEXT");
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const appendTranscript = useCallback((text: string) => {
    setCommand((prev) => {
      const joined = prev.trim() ? `${prev.replace(/\s+$/, "")} ${text}` : text;
      return joined.slice(0, MAX_COMMAND_LENGTH);
    });
    setInputMode("VOICE");
    setLocalError(null);
  }, []);

  // Dictation (fills the box; you press Execute) is used when hands-free voice is off in Settings.
  const speech = useSpeechRecognition({ onFinalTranscript: appendTranscript });
  const voice = useVoiceConversation();
  const { prefs, loaded: prefsLoaded } = usePreferences();
  // Hands-free voice needs the saved Settings (until they load, the mic dictates into the box).
  const handsFree = prefsLoaded && prefs.voice_input_enabled && prefs.voice_auto_submit;
  const toggleMic = () => {
    if (!prefs.voice_input_enabled) return;
    if (handsFree) {
      if (speech.isListening) speech.stop();
      if (voice.active) voice.stop();
      else voice.start();
    } else {
      if (voice.active) voice.stop();
      speech.toggle();
    }
  };
  const offline = connectionStatus !== "CONNECTED";

  const handleChange = (value: string) => {
    setCommand(value);
    if (localError) setLocalError(null);
    if (error) clearError();
    if (!value.trim()) setInputMode("TEXT");
  };

  const handleSubmit = async (value: string) => {
    if (!value.trim()) {
      setLocalError("Please enter a command first.");
      return;
    }
    if (speech.isListening) speech.stop();
    const result = await submitCommand(value, inputMode);
    if (result.ok) {
      setCommand("");
      setInputMode("TEXT");
      setLocalError(null);
    } else {
      setLocalError(result.error ?? "Command could not be submitted.");
    }
  };

  const handleSuggestion = (suggestion: string) => {
    setCommand(suggestion);
    setInputMode("TEXT");
    setLocalError(null);
    inputRef.current?.focus();
  };

  return (
    <section aria-labelledby="command-center-title" className="panel-strong glow-ring relative overflow-hidden rounded-2xl">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-brand/60 to-transparent" />
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="command-center-title" className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
            <TerminalSquare className="h-4 w-4 text-cyan-brand" aria-hidden />
            Command Center
          </h2>
          <Badge variant="secondary">
            {handsFree ? "Text: Execute · Voice: hands-free (sensitive steps always ask)" : "Plan first · runs only when you click Run Plan"}
          </Badge>
        </div>

        {offline && (
          <div role="status" className="flex items-center gap-2 rounded-lg border border-level-warning/25 bg-level-warning/[0.07] px-3 py-2 text-xs text-level-warning">
            <WifiOff className="h-3.5 w-3.5 shrink-0" aria-hidden />
            {connectionStatus === "CONNECTING" || connectionStatus === "RECONNECTING"
              ? "Connecting to the TaskPilot backend… You can type, but commands are sent only once connected."
              : "The TaskPilot backend is offline. Start it or press Retry in the top bar — commands can't be sent until then."}
          </div>
        )}

        <CommandInput
          ref={inputRef}
          value={command}
          onChange={handleChange}
          onSubmit={handleSubmit}
          disabled={offline}
          disabledReason="Backend connection unavailable"
          isSubmitting={isSubmitting}
          error={localError ?? error}
          interimText={voice.active ? undefined : speech.interimTranscript}
          actions={
            <VoiceButton
              isListening={voice.active || speech.isListening}
              isSupported={speech.isSupported && prefs.voice_input_enabled}
              onToggle={toggleMic}
              disabled={offline && !voice.active}
            />
          }
        />

        <VoiceConversationBar voice={voice} />

        <VoiceStatus state={speech} onLanguageChange={speech.setLanguage} onDismissError={speech.clearError} />

        {lastAccepted && (
          <div
            role="status"
            className="flex items-start gap-3 rounded-lg border border-level-success/25 bg-level-success/[0.06] px-3 py-2.5 text-sm"
          >
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-level-success" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="font-medium text-foreground">
                Command accepted — <span className="text-muted-foreground">Kamlesh Bhai is planning. Nothing runs in a browser.</span>
              </p>
              <p className="text-xs text-muted-foreground">
                Task <span className="font-mono">{shortId(lastAccepted.taskId)}</span>: {lastAccepted.message} Follow {ASSISTANT_NAME}
                &apos;s progress in the agent plan panel.
              </p>
            </div>
            <button
              type="button"
              onClick={dismissAccepted}
              aria-label="Dismiss confirmation"
              className="rounded p-1 text-muted-foreground hover:bg-white/10 hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        <CommandSuggestions onSelect={handleSuggestion} />
      </div>
    </section>
  );
}
