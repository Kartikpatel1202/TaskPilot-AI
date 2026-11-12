"use client";

import { Sparkles } from "lucide-react";
import { memo } from "react";

import { SUGGESTED_COMMANDS } from "@/lib/constants";

interface CommandSuggestionsProps {
  onSelect: (command: string) => void;
  suggestions?: readonly string[];
}

/** Clicking a suggestion only fills the input — it never executes anything. */
export const CommandSuggestions = memo(function CommandSuggestions({
  onSelect,
  suggestions = SUGGESTED_COMMANDS,
}: CommandSuggestionsProps) {
  return (
    <div className="flex flex-col gap-2">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
        <Sparkles className="h-3 w-3 text-violet-brand" aria-hidden /> Try asking
      </p>
      <ul className="flex flex-wrap gap-2">
        {suggestions.map((suggestion) => (
          <li key={suggestion}>
            <button
              type="button"
              onClick={() => onSelect(suggestion)}
              className="rounded-full border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:border-cyan-brand/40 hover:bg-cyan-brand/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {suggestion}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
});
