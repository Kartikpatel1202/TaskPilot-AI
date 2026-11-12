"use client";

import { FlaskConical, ScanSearch, ShoppingBasket } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { CartSummary } from "./CartSummary";
import { CheckoutReview } from "./CheckoutReview";
import { OrderStatus } from "./OrderStatus";
import { PaymentHandoff } from "./PaymentHandoff";
import { ProductSearchResults } from "./ProductSearchResults";
import { ProductSelectionDialog } from "./ProductSelectionDialog";

import type { CommerceCommandResult } from "@/hooks/useCommerce";
import type { ShoppingSummary, WorkflowStatus } from "@/types/commerce";

const STATUS: Record<WorkflowStatus, { label: string; variant: "secondary" | "default" | "violet" | "warning" | "success" | "destructive" }> = {
  PLANNED: { label: "Planned", variant: "secondary" },
  RUNNING: { label: "Shopping…", variant: "violet" },
  WAITING_USER: { label: "Needs your choice", variant: "warning" },
  CART_READY: { label: "Cart verified", variant: "success" },
  PARTIAL: { label: "Partly prepared", variant: "warning" },
  SEARCH_COMPLETE: { label: "Search complete", variant: "success" },
  CHECKOUT_READY: { label: "Checkout reviewed", variant: "default" },
  APPROVAL_PENDING: { label: "Waiting for approval", variant: "warning" },
  PAYMENT_HANDOFF: { label: "Manual payment", variant: "warning" },
  ORDER_CONFIRMED: { label: "Order confirmed", variant: "success" },
  BLOCKED: { label: "Needs you", variant: "warning" },
  FAILED: { label: "Failed", variant: "destructive" },
};

export interface ShoppingPanelProps {
  summary: ShoppingSummary;
  busy?: boolean;
  allowCartEdits?: boolean;
  onChooseProduct: (selectionId: string, candidateId: string | null) => Promise<CommerceCommandResult>;
  onRefreshCart?: () => void;
  onChangeQuantity?: (itemId: string, quantity: number) => void;
  className?: string;
}

/** Shopping workflow of the active task — every value comes from the real (or fixture) website. */
export function ShoppingPanel({ summary, busy = false, allowCartEdits = false, onChooseProduct, onRefreshCart, onChangeQuantity, className }: ShoppingPanelProps) {
  const status = STATUS[summary.status];
  const pending = summary.pending_selection ?? null;
  const pendingReq = pending ? summary.requirements.find((r) => r.requirement.product_id === pending.requirement_id) : undefined;
  const [hiddenSelection, setHiddenSelection] = useState<string | null>(null);
  const order = summary.order;
  return (
    <Card className={cn("flex flex-col", className)} aria-labelledby="shopping-panel-title" data-testid="shopping-panel">
      <CardHeader className="flex-wrap gap-2">
        <CardTitle id="shopping-panel-title">
          <ShoppingBasket className="h-3.5 w-3.5" aria-hidden /> Shopping · {summary.site_name}
        </CardTitle>
        <div className="flex items-center gap-2">
          {summary.is_fixture && (
            <Badge variant="violet" title="Local test fixture — not the real website">
              <FlaskConical className="h-3 w-3" aria-hidden /> Test fixture
            </Badge>
          )}
          <Badge variant={status.variant} data-testid="shopping-status">{status.label}</Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {summary.message && <p className="text-xs text-muted-foreground">{summary.message}</p>}
        {summary.requirements.length > 0 && (
          <div className="flex flex-col gap-2">
            <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              <ScanSearch className="h-3 w-3" aria-hidden /> Requested products
            </p>
            <ProductSearchResults requirements={summary.requirements} />
          </div>
        )}
        {summary.cart && (
          <CartSummary cart={summary.cart} verification={summary.verification} siteName={summary.site_name} busy={busy}
            onRefresh={allowCartEdits ? onRefreshCart : undefined} onChangeQuantity={allowCartEdits ? onChangeQuantity : undefined} />
        )}
        {summary.checkout && <CheckoutReview checkout={summary.checkout} priceChanges={summary.price_changes} />}
        {order?.status === "PAYMENT_HANDOFF" && <PaymentHandoff order={order} checkout={summary.checkout} siteName={summary.site_name} />}
        {order && <OrderStatus order={order} />}
        {!order && summary.cart && (
          <p className="text-[11px] text-muted-foreground" data-testid="no-order-note">No order has been placed. Checkout needs your instruction and a final exact-order approval.</p>
        )}
      </CardContent>
      {pending && pendingReq && (
        <ProductSelectionDialog
          key={pending.selection_id}
          open={hiddenSelection !== pending.selection_id}
          selection={pending}
          requirement={pendingReq}
          onChoose={onChooseProduct}
          onOpenChange={(open) => setHiddenSelection(open ? null : pending.selection_id)}
        />
      )}
    </Card>
  );
}
