"use client";

import { AlertTriangle, CalendarCheck2, CheckCircle2, Loader2, Users } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { ASSISTANT_NAME } from "@/lib/persona";
import { formatRelativeSeconds } from "@/lib/utils";

import type { ApprovalDecision, ApprovalRequest, ApprovalResponse } from "@/types/approval";
import { CONFLICT_LABEL } from "@/types/calendar";

export interface CalendarApprovalDialogProps {
  approval: ApprovalRequest;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDecide: (approvalId: string, decision: ApprovalDecision) => Promise<ApprovalResponse>;
}

const secondsUntil = (iso: string) => Math.floor((new Date(iso).getTime() - Date.now()) / 1000);

/**
 * KAMLESH BHAI — EXACT EVENT REVIEW. Shows exactly the event that will be created (title, date,
 * time, timezone, guests, conflicts). Approval needs an explicit click: focus never lands on a
 * decision button and Enter is never a decision. Any change to the event cancels this approval.
 */
export function CalendarApprovalDialog({ approval, open, onOpenChange, onDecide }: CalendarApprovalDialogProps) {
  const event = approval.calendar;
  const [submitting, setSubmitting] = useState<ApprovalDecision | null>(null);
  const [result, setResult] = useState<ApprovalResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(() => secondsUntil(approval.expires_at));
  const inFlight = useRef(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const expired = approval.status === "EXPIRED" || remaining <= 0;
  const locked = submitting !== null || result !== null || expired || approval.status !== "PENDING";

  useEffect(() => {
    if (!open || approval.status !== "PENDING") return undefined;
    const id = setInterval(() => setRemaining(secondsUntil(approval.expires_at)), 1000);
    return () => clearInterval(id);
  }, [open, approval.expires_at, approval.status]);

  if (!event) return null;

  const decide = async (decision: ApprovalDecision) => {
    if (inFlight.current || locked) return;
    inFlight.current = true;
    setSubmitting(decision);
    setError(null);
    try {
      setResult(await onDecide(approval.approval_id, decision));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your decision could not be recorded.");
      if (!(err instanceof ApiError && (err.code === "APPROVAL_EXPIRED" || err.code === "APPROVAL_ALREADY_RESOLVED"))) inFlight.current = false;
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        tabIndex={-1}
        aria-describedby="calendar-approval-description"
        data-testid="calendar-approval-dialog"
        onOpenAutoFocus={(e) => {
          e.preventDefault(); // never focus Confirm/Reject automatically
          contentRef.current?.focus();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.preventDefault(); // Enter is never an approval
        }}
      >
        <DialogHeader>
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-level-warning">
            <CalendarCheck2 className="h-4 w-4" aria-hidden /> {ASSISTANT_NAME} — calendar event review
          </p>
          <DialogTitle>Create exactly this event?</DialogTitle>
          <DialogDescription id="calendar-approval-description">
            {approval.domain}. TaskPilot creates this one event and nothing else — it never deletes or edits your other events.
          </DialogDescription>
        </DialogHeader>

        <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="calendar-approval-details">
          <dt className="text-muted-foreground">Title</dt><dd className="font-medium">{event.title}</dd>
          <dt className="text-muted-foreground">Date</dt><dd>{event.date_label}</dd>
          <dt className="text-muted-foreground">Time</dt><dd>{event.time_label}</dd>
          <dt className="text-muted-foreground">Timezone</dt><dd>{event.timezone_label}</dd>
          {event.location && (<><dt className="text-muted-foreground">Location</dt><dd>{event.location}</dd></>)}
          {event.description && (<><dt className="text-muted-foreground">Details</dt><dd className="whitespace-pre-wrap">{event.description}</dd></>)}
          <dt className="text-muted-foreground">Conflicts</dt><dd data-testid="calendar-conflict-status">{CONFLICT_LABEL[event.conflict_status]}</dd>
          <dt className="text-muted-foreground">Expires in</dt><dd>{expired ? "Expired" : formatRelativeSeconds(remaining)}</dd>
        </dl>

        {event.conflicts.map((c) => (
          <p key={`${c.title}-${c.start_label}`} role="alert" className="flex items-center gap-2 text-xs text-level-warning">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden /> Overlaps “{c.title}” ({c.start_label}–{c.end_label})
          </p>
        ))}
        {event.conflict_status === "UNAVAILABLE" && (
          <p role="alert" className="text-xs text-level-warning">Your calendar could not be read, so conflicts are unknown — not assumed free.</p>
        )}
        <p role="note" className="flex items-start gap-2 rounded-md border border-border px-3 py-2 text-xs" data-testid="calendar-invite-note">
          <Users className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {event.sends_invitations
            ? `Google Calendar will email invitations to: ${event.attendee_emails.join(", ")}.`
            : "No guests — no invitations will be sent."}
        </p>
        {expired && !result && <p role="alert" className="text-xs text-level-error">This review expired. No event was created.</p>}
        {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
        {result && (
          <p role="status" className="flex items-center gap-2 text-xs text-level-success">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Decision recorded: {result.status.toLowerCase()}.
          </p>
        )}

        <DialogFooter>
          {locked && !submitting ? (
            <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => decide("REJECT")} disabled={locked} data-testid="reject-event">
                {submitting === "REJECT" && <Loader2 className="animate-spin" aria-hidden />} Reject Event Creation
              </Button>
              <Button onClick={() => decide("APPROVE")} disabled={locked} data-testid="confirm-event">
                {submitting === "APPROVE" && <Loader2 className="animate-spin" aria-hidden />} Confirm This Exact Event
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
