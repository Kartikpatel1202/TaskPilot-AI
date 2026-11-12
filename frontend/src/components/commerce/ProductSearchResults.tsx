"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";

import { ProductCandidateCard } from "./ProductCandidateCard";

import type { RequirementProgress, RequirementStatus } from "@/types/commerce";

const STATUS: Record<RequirementStatus, { label: string; variant: "secondary" | "default" | "violet" | "warning" | "success" | "destructive" }> = {
  PENDING: { label: "Pending", variant: "secondary" },
  SEARCHING: { label: "Searching", variant: "violet" },
  AWAITING_SELECTION: { label: "Needs your choice", variant: "warning" },
  SELECTED: { label: "Matched", variant: "default" },
  ADDED: { label: "Added", variant: "success" },
  ALREADY_IN_CART: { label: "Already in cart", variant: "success" },
  FOUND: { label: "Options found", variant: "success" },
  NOT_FOUND: { label: "Not found", variant: "destructive" },
  UNAVAILABLE: { label: "Unavailable", variant: "destructive" },
  SKIPPED: { label: "Skipped", variant: "secondary" },
  FAILED: { label: "Failed", variant: "destructive" },
};

function label(entry: RequirementProgress): string {
  const r = entry.requirement;
  const size = r.unit !== "UNKNOWN" ? ` · ${r.quantity} ${r.unit.toLowerCase()}` : "";
  const budget = r.max_price ? ` · under ₹${Number(r.max_price).toLocaleString("en-IN")}` : "";
  const specs = Object.entries(r.required_specs).map(([k, v]) => `${v} ${k}`).join(", ");
  return `${r.query}${size}${budget}${specs ? ` · ${specs}` : ""}`;
}

/** Requested products with the real search results the matcher compared. */
export function ProductSearchResults({ requirements }: { requirements: RequirementProgress[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ol className="flex flex-col gap-2" aria-label="Requested products" data-testid="product-search-results">
      {requirements.map((entry) => {
        const id = entry.requirement.product_id;
        const meta = STATUS[entry.status];
        const matches = new Map(entry.matches.map((m) => [m.candidate_id, m]));
        const ranked = [...entry.candidates].sort((a, b) => (matches.get(b.candidate_id)?.overall_score ?? 0) - (matches.get(a.candidate_id)?.overall_score ?? 0));
        return (
          <li key={id} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3" data-testid="requirement" data-status={entry.status}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-foreground">{label(entry)}</p>
              <Badge variant={meta.variant}>{meta.label}</Badge>
            </div>
            {entry.message && <p className="mt-1 text-xs text-muted-foreground">{entry.message}</p>}
            {ranked.length > 0 && (
              <>
                <button type="button" className="mt-2 inline-flex items-center gap-1 text-[11px] text-cyan-brand" aria-expanded={open === id}
                  onClick={() => setOpen(open === id ? null : id)}>
                  <ChevronDown className={open === id ? "h-3 w-3 rotate-180" : "h-3 w-3"} aria-hidden /> {ranked.length} product(s) read from the website
                </button>
                {open === id && (
                  <div className="mt-2 flex flex-col gap-2">
                    {ranked.slice(0, 8).map((c) => (
                      <ProductCandidateCard key={c.candidate_id} candidate={c} match={matches.get(c.candidate_id)}
                        selected={c.candidate_id === entry.selected_candidate_id} />
                    ))}
                  </div>
                )}
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}
