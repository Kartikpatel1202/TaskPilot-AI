"use client";

import { AlertTriangle, CheckCircle2, Loader2, ShieldAlert, ShoppingBag } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { formatInr } from "@/lib/commerceApi";
import { ASSISTANT_NAME } from "@/lib/persona";
import { formatRelativeSeconds } from "@/lib/utils";

import { PriceBreakdown } from "./PriceBreakdown";

import type { ApprovalDecision, ApprovalRequest, ApprovalResponse } from "@/types/approval";
import { PAYMENT_LABEL } from "@/types/checkout";
import { PLATFORM_LABEL } from "@/types/product";

export interface PurchaseApprovalDialogProps {
  approval: ApprovalRequest;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDecide: (approvalId: string, decision: ApprovalDecision) => Promise<ApprovalResponse>;
}

const secondsUntil = (iso: string) => Math.floor((new Date(iso).getTime() - Date.now()) / 1000);

/**
 * KAMLESH BHAI — FINAL PURCHASE REVIEW. Shows exactly what is being approved (observed items,
 * totals, masked address, payment method). Approval requires an explicit button click: focus
 * never lands on a decision button, so pressing Enter cannot approve a purchase.
 */
export function PurchaseApprovalDialog({ approval, open, onOpenChange, onDecide }: PurchaseApprovalDialogProps) {
  const purchase = approval.purchase;
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

  if (!purchase) return null;

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

  const isCod = purchase.payment_method === "COD";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        tabIndex={-1}
        aria-describedby="purchase-description"
        data-testid="purchase-approval-dialog"
        onOpenAutoFocus={(event) => {
          event.preventDefault(); // never focus Confirm/Reject automatically
          contentRef.current?.focus();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.preventDefault(); // Enter is never a purchase decision
        }}
      >
        <DialogHeader>
          <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-level-error">
            <ShieldAlert className="h-4 w-4" aria-hidden /> {ASSISTANT_NAME} — final purchase review
          </p>
          <DialogTitle>Confirm this exact order?</DialogTitle>
          <DialogDescription id="purchase-description">
            Website: {PLATFORM_LABEL[purchase.platform]}. Everything below was read from the checkout page just now.
          </DialogDescription>
        </DialogHeader>

        <section aria-label="Items" className="flex flex-col gap-1 text-sm">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            <ShoppingBag className="h-3.5 w-3.5" aria-hidden /> Items
          </p>
          <ol className="flex flex-col gap-1" data-testid="purchase-items">
            {purchase.items.map((item, i) => (
              <li key={`${item.name}-${i}`} className="flex justify-between gap-3">
                <span>{i + 1}. {item.name} — {item.quantity}</span>
                <span className="font-mono tabular-nums">{formatInr(item.line_total)}</span>
              </li>
            ))}
          </ol>
        </section>

        <PriceBreakdown subtotal={purchase.subtotal} deliveryFee={purchase.delivery_fee} handlingFee={purchase.handling_fee}
          discount={purchase.discount} tax={purchase.tax} total={purchase.final_total} totalLabel="FINAL TOTAL" />

        <dl className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
          <div><dt className="text-muted-foreground">Delivery address</dt><dd data-testid="purchase-address">{purchase.masked_delivery_address ?? "Not shown"}</dd></div>
          <div><dt className="text-muted-foreground">Payment method</dt><dd data-testid="purchase-payment">{PAYMENT_LABEL[purchase.payment_method]}</dd></div>
          {purchase.delivery_slot && <div><dt className="text-muted-foreground">Delivery</dt><dd>{purchase.delivery_slot}</dd></div>}
          <div><dt className="text-muted-foreground">Expires in</dt><dd>{expired ? "Expired" : formatRelativeSeconds(remaining)}</dd></div>
        </dl>

        {purchase.warnings.map((w) => (
          <p key={w} role="alert" className="flex items-start gap-2 text-xs text-level-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />{w}</p>
        ))}
        <p role="note" className="rounded-md border border-level-error/30 bg-level-error/[0.08] px-3 py-2 text-xs text-level-error" data-testid="purchase-warning">
          {isCod
            ? "Approving may place a real cash-on-delivery order on the website. TaskPilot re-checks the checkout first; if anything changed, it asks you again."
            : "This payment method must be completed by you on the website. TaskPilot never enters payment details."}
        </p>
        {expired && !result && <p role="alert" className="text-xs text-level-error">This review expired. No order was placed.</p>}
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
              <Button variant="outline" onClick={() => decide("REJECT")} disabled={locked} data-testid="reject-purchase">
                {submitting === "REJECT" && <Loader2 className="animate-spin" aria-hidden />} Reject Purchase
              </Button>
              <Button variant="destructive" onClick={() => decide("APPROVE")} disabled={locked} data-testid="confirm-purchase">
                {submitting === "APPROVE" && <Loader2 className="animate-spin" aria-hidden />} Confirm This Exact Order
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
