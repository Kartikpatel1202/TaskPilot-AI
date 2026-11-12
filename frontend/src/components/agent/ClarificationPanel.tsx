"use client";

import { Bot, Loader2, MessageCircleQuestion, Send } from "lucide-react";
import { useId, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MAX_COMMAND_LENGTH } from "@/lib/constants";
import { ASSISTANT_NAME } from "@/lib/persona";

import type { SubmitResult } from "@/context/TaskPilotContext";
import type { ClarificationRequest } from "@/types/agent";

interface ClarificationPanelProps {
  clarification: ClarificationRequest;
  onSubmit: (message: string) => Promise<SubmitResult>;
  isSubmitting: boolean;
  disabled?: boolean;
}

/** Answers continue the SAME task — this never creates a new one. */
export function ClarificationPanel({ clarification, onSubmit, isSubmitting, disabled = false }: ClarificationPanelProps) {
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();
  const canSubmit = !disabled && !isSubmitting && answer.trim().length > 0;

  const submit = async () => {
    if (!canSubmit) return;
    setError(null);
    const result = await onSubmit(answer.trim());
    if (result.ok) setAnswer("");
    else setError(result.error ?? "Your answer could not be sent.");
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <div className="flex flex-col gap-3" data-testid="clarification-panel">
      <div className="flex items-start gap-3 rounded-lg border border-level-warning/30 bg-level-warning/[0.06] p-3">
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-violet-brand/40 bg-violet-brand/10">
          <Bot className="h-3.5 w-3.5 text-violet-brand" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-level-warning">
            <MessageCircleQuestion className="h-3.5 w-3.5" aria-hidden /> {ASSISTANT_NAME} needs a detail
          </p>
          <p className="mt-1 text-sm text-foreground" data-testid="clarification-question">
            {clarification.question}
          </p>
          {clarification.missingInformation.length > 0 && (
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Missing information">
              {clarification.missingInformation.map((item) => (
                <li key={item} className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {item.replace(/_/g, " ")}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <label htmlFor={inputId} className="sr-only">
        Your answer to {ASSISTANT_NAME}
      </label>
      <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2 focus-within:border-cyan-brand/40">
        <Textarea
          id={inputId}
          rows={2}
          value={answer}
          maxLength={MAX_COMMAND_LENGTH}
          onChange={(e) => {
            setAnswer(e.target.value.slice(0, MAX_COMMAND_LENGTH));
            if (error) setError(null);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Type your answer… (e.g. Blinkit, 1 litre Amul)"
          disabled={isSubmitting}
          aria-invalid={error ? true : undefined}
        />
      </div>
      {error && (
        <p role="alert" className="text-xs text-level-error">
          {error}
        </p>
      )}
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] text-muted-foreground">Your answer updates this same task&apos;s plan.</p>
        <Button size="sm" onClick={() => void submit()} disabled={!canSubmit}>
          {isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
          {isSubmitting ? "Sending…" : "Send answer"}
        </Button>
      </div>
    </div>
  );
}
