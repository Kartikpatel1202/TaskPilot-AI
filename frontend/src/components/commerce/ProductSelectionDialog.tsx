"use client";

import { Loader2, PackageSearch } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

import { ProductCandidateCard } from "./ProductCandidateCard";

import type { CommerceCommandResult } from "@/hooks/useCommerce";
import type { PendingSelection, RequirementProgress } from "@/types/commerce";

interface ProductSelectionDialogProps {
  open: boolean;
  selection: PendingSelection;
  requirement: RequirementProgress;
  onChoose: (selectionId: string, candidateId: string | null) => Promise<CommerceCommandResult>;
  onOpenChange: (open: boolean) => void;
}

/**
 * Several real products match equally well (or the closest one needs confirmation).
 * Nothing is added until the user picks one explicitly; weak matches are never auto-selected.
 */
export function ProductSelectionDialog({ open, selection, requirement, onChoose, onOpenChange }: ProductSelectionDialogProps) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const matches = new Map(requirement.matches.map((m) => [m.candidate_id, m]));
  const options = selection.candidate_ids
    .map((id) => requirement.candidates.find((c) => c.candidate_id === id))
    .filter((c): c is NonNullable<typeof c> => Boolean(c));

  const submit = async (candidateId: string | null) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const result = await onChoose(selection.selection_id, candidateId);
    setBusy(false);
    if (!result.ok) setError(result.error ?? "Your choice could not be sent.");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby="selection-description" data-testid="product-selection-dialog">
        <DialogHeader>
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-level-warning">
            <PackageSearch className="h-4 w-4" aria-hidden /> Choose the product
          </p>
          <DialogTitle>Which one did you mean?</DialogTitle>
          <DialogDescription id="selection-description">{selection.question}</DialogDescription>
        </DialogHeader>
        <div role="radiogroup" aria-label="Matching products" className="flex max-h-[50vh] flex-col gap-2 overflow-y-auto">
          {options.map((c) => (
            <ProductCandidateCard key={c.candidate_id} candidate={c} match={matches.get(c.candidate_id)} selectable
              selected={chosen === c.candidate_id} onSelect={setChosen} />
          ))}
        </div>
        {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={() => submit(null)} disabled={busy}>Skip this product</Button>
          <Button onClick={() => chosen && submit(chosen)} disabled={!chosen || busy} data-testid="confirm-selection">
            {busy && <Loader2 className="animate-spin" aria-hidden />} Add the selected product
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
