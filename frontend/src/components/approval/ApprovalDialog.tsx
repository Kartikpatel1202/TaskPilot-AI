"use client";

import { AlertTriangle, CheckCircle2, FlaskConical, Loader2, ShieldQuestion } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { ASSISTANT_NAME } from "@/lib/persona";

import { ApprovalSummary } from "./ApprovalSummary";

import { CalendarApprovalDialog } from "@/components/calendar/CalendarApprovalDialog";
import { PurchaseApprovalDialog } from "@/components/commerce/PurchaseApprovalDialog";

import type { ApprovalDecision, ApprovalRequest, ApprovalResponse } from "@/types/approval";

export interface ApprovalDialogProps {
  approval: ApprovalRequest;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDecide: (approvalId: string, decision: ApprovalDecision) => Promise<ApprovalResponse>;
}

function secondsUntil(iso: string): number {
  return Math.floor((new Date(iso).getTime() - Date.now()) / 1000);
}

/**
 * Human-in-the-loop approval. Safety properties:
 * - a decision requires an explicit click on Approve or Reject (no shortcuts, no
 *   auto-approval; initial focus lands on the dialog itself, not a decision button);
 * - one decision per approval: buttons lock while submitting and afterwards;
 * - expired requests cannot be approved; backend errors are shown inline.
 */
export function ApprovalDialog(props: ApprovalDialogProps) {
  // Phase 4: an exact-order purchase gets the full order review, not a generic "approve action" dialog.
  if (props.approval.purchase) return <PurchaseApprovalDialog {...props} />;
  // Phase 5: an exact calendar event gets its own exact-event review.
  if (props.approval.calendar) return <CalendarApprovalDialog {...props} />;
  return <GenericApprovalDialog {...props} />;
}

function GenericApprovalDialog({ approval, open, onOpenChange, onDecide }: ApprovalDialogProps) {
  const [submitting, setSubmitting] = useState<ApprovalDecision | null>(null);
  const [result, setResult] = useState<ApprovalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [locallyExpired, setLocallyExpired] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(() => secondsUntil(approval.expires_at));
  const inFlightRef = useRef(false);
  const contentRef = useRef<HTMLDivElement>(null);

  const expired = approval.status === "EXPIRED" || locallyExpired || (remaining !== null && remaining <= 0);
  const decided = result !== null || conflict;
  const locked = submitting !== null || decided || expired || approval.status !== "PENDING";

  useEffect(() => {
    if (!open || approval.status !== "PENDING") return undefined;
    const tick = () => setRemaining(secondsUntil(approval.expires_at));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [open, approval.expires_at, approval.status]);

  const decide = async (decision: ApprovalDecision) => {
    // Synchronous guard against double clicks before React re-renders.
    if (inFlightRef.current || locked) return;
    inFlightRef.current = true;
    setSubmitting(decision);
    setError(null);
    try {
      const response = await onDecide(approval.approval_id, decision);
      setResult(response);
    } catch (err) {
      if (err instanceof ApiError && err.code === "APPROVAL_EXPIRED") {
        setLocallyExpired(true);
        setError("This approval request expired before your decision reached the server.");
      } else if (err instanceof ApiError && err.code === "APPROVAL_ALREADY_RESOLVED") {
        setError("This request was already decided (possibly in another tab). Decisions can't be changed.");
        setConflict(true);
      } else {
        setError(err instanceof Error ? `Your decision could not be recorded: ${err.message}` : "Your decision could not be recorded.");
        inFlightRef.current = false; // allow a deliberate retry
      }
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        tabIndex={-1}
        aria-describedby="approval-description"
        onOpenAutoFocus={(event) => {
          // Never focus a decision button automatically (prevents Enter-to-approve).
          event.preventDefault();
          contentRef.current?.focus();
        }}
      >
        {approval.is_demo && (
          <div
            className="-mx-5 -mt-5 flex items-center justify-center gap-2 border-b border-violet-brand/30 bg-violet-brand/15 px-4 py-2 text-[11px] font-bold uppercase tracking-[0.18em] text-violet-brand sm:-mx-6 sm:-mt-6"
            data-testid="demo-banner"
          >
            <FlaskConical className="h-3.5 w-3.5" aria-hidden />
            DEMO APPROVAL — NO REAL ACTION
          </div>
        )}

        <DialogHeader>
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-level-warning">
            <ShieldQuestion className="h-4 w-4" aria-hidden /> Action approval
          </p>
          <DialogTitle>TaskPilot requires your permission</DialogTitle>
          <DialogDescription id="approval-description">
            {ASSISTANT_NAME} paused before a sensitive step. Review the details and decide explicitly.
          </DialogDescription>
        </DialogHeader>

        <ApprovalSummary approval={approval} secondsRemaining={approval.status === "PENDING" ? remaining : 0} />

        {expired && !decided && (
          <p role="alert" className="flex items-start gap-2 rounded-md border border-level-error/30 bg-level-error/10 px-3 py-2 text-xs text-level-error">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            This request has expired and can no longer be approved. No action was taken.
          </p>
        )}

        {error && !(expired && !decided && error.includes("expired")) && (
          <p role="alert" className="flex items-start gap-2 rounded-md border border-level-error/30 bg-level-error/10 px-3 py-2 text-xs text-level-error">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {error}
          </p>
        )}

        {result && (
          <p role="status" className="flex items-center gap-2 rounded-md border border-level-success/30 bg-level-success/10 px-3 py-2 text-xs text-level-success">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
            Decision recorded: {result.status.toLowerCase()}.{approval.is_demo ? " Demo only — nothing was executed." : ""}
          </p>
        )}

        <p className="text-[11px] text-muted-foreground">
          {approval.is_demo
            ? "Demo request: approving only records your decision — no real-world action runs."
            : "Approving lets TaskPilot perform only the next step shown, in the browser. Payments, checkout, placing orders and sending messages are never automated — even if approved."}{" "}
          TaskPilot never stores payment credentials.
        </p>

        <DialogFooter>
          {expired || decided ? (
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => void decide("REJECT")} disabled={locked} aria-busy={submitting === "REJECT"}>
                {submitting === "REJECT" && <Loader2 className="animate-spin" aria-hidden />}
                Reject
              </Button>
              <Button onClick={() => void decide("APPROVE")} disabled={locked} aria-busy={submitting === "APPROVE"}>
                {submitting === "APPROVE" && <Loader2 className="animate-spin" aria-hidden />}
                {submitting === "APPROVE" ? "Submitting…" : "Approve Action"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
