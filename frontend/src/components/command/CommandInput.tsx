"use client";

import { CornerDownLeft, Loader2, Play } from "lucide-react";
import { forwardRef, useId, type KeyboardEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MAX_COMMAND_LENGTH } from "@/lib/constants";
import { cn } from "@/lib/utils";

export interface CommandInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  /** Disables submission (e.g. backend offline). Typing stays possible. */
  disabled?: boolean;
  disabledReason?: string;
  isSubmitting?: boolean;
  maxLength?: number;
  placeholder?: string;
  error?: string | null;
  /** Slot rendered beside the Execute button (e.g. the microphone). */
  actions?: ReactNode;
  /** Live, not-yet-final speech text shown under the input. */
  interimText?: string;
}

export const CommandInput = forwardRef<HTMLTextAreaElement, CommandInputProps>(function CommandInput(
  {
    value,
    onChange,
    onSubmit,
    disabled = false,
    disabledReason,
    isSubmitting = false,
    maxLength = MAX_COMMAND_LENGTH,
    placeholder = "Ask TaskPilot to do something...",
    error,
    actions,
    interimText,
  },
  ref,
) {
  const inputId = useId();
  const hintId = useId();
  const errorId = useId();
  const trimmed = value.trim();
  const canSubmit = !disabled && !isSubmitting && trimmed.length > 0 && value.length <= maxLength;
  const nearLimit = value.length >= maxLength * 0.9;

  const submit = () => {
    if (canSubmit) onSubmit(trimmed);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter submits; Shift+Enter inserts a newline; never submit mid-IME-composition.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={inputId} className="sr-only">
        Command for TaskPilot
      </label>
      <Textarea
        ref={ref}
        id={inputId}
        value={value}
        rows={3}
        maxLength={maxLength}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value.slice(0, maxLength))}
        onKeyDown={handleKeyDown}
        aria-describedby={cn(hintId, error && errorId)}
        aria-invalid={error ? true : undefined}
        className="min-h-[88px] px-1 sm:min-h-[96px]"
      />

      {interimText ? (
        <p className="truncate px-1 text-sm italic text-cyan-brand/80" aria-live="polite" data-testid="interim-transcript">
          {interimText}…
        </p>
      ) : null}

      {error ? (
        <p id={errorId} role="alert" className="px-1 text-xs text-level-error">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-3">
        <p id={hintId} className="mr-auto flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <span className="hidden items-center gap-1 sm:inline-flex">
            <kbd className="rounded border border-white/10 bg-white/5 px-1 font-mono">
              <CornerDownLeft className="inline h-2.5 w-2.5" aria-hidden />
            </kbd>
            to run ·
            <kbd className="rounded border border-white/10 bg-white/5 px-1 font-mono">Shift</kbd>+
            <kbd className="rounded border border-white/10 bg-white/5 px-1 font-mono">
              <CornerDownLeft className="inline h-2.5 w-2.5" aria-hidden />
            </kbd>
            new line ·
          </span>
          <span className={cn("tabular-nums", nearLimit && "text-level-warning")} data-testid="char-count">
            {value.length.toLocaleString()}/{maxLength.toLocaleString()}
          </span>
        </p>

        {actions}

        <Button
          onClick={submit}
          disabled={!canSubmit}
          aria-disabled={!canSubmit}
          title={disabled && disabledReason ? disabledReason : undefined}
          className="min-w-[112px]"
        >
          {isSubmitting ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
          {isSubmitting ? "Sending…" : "Execute"}
        </Button>
      </div>
    </div>
  );
});
