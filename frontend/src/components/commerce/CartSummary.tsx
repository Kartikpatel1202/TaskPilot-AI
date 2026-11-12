"use client";

import { AlertTriangle, CheckCircle2, RefreshCw, ShoppingCart } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatTime } from "@/lib/utils";

import { CartItemRow } from "./CartItemRow";
import { PriceBreakdown } from "./PriceBreakdown";

import type { CartSnapshot, CartVerificationReport } from "@/types/cart";

const STATUS = {
  VERIFIED: { label: "Cart verified", variant: "success" as const },
  PARTIAL: { label: "Partly prepared", variant: "warning" as const },
  MISMATCH: { label: "Does not match", variant: "destructive" as const },
  UNVERIFIED: { label: "Not verified", variant: "secondary" as const },
};

interface CartSummaryProps {
  cart: CartSnapshot;
  verification?: CartVerificationReport | null;
  siteName: string;
  busy?: boolean;
  onRefresh?: () => void;
  onChangeQuantity?: (itemId: string, quantity: number) => void;
}

/** The cart exactly as last read from the website. */
export function CartSummary({ cart, verification, siteName, busy = false, onRefresh, onChangeQuantity }: CartSummaryProps) {
  const status = STATUS[verification?.status ?? cart.verification_status];
  const checkFor = (itemId: string) => verification?.checks.find((c) => c.observed_item_id === itemId)?.status ?? null;
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-white/[0.08] bg-white/[0.02] p-3" aria-label="Shopping cart" data-testid="cart-summary">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em]">
          <ShoppingCart className="h-3.5 w-3.5 text-cyan-brand" aria-hidden /> Shopping cart · {siteName}
        </h4>
        <div className="flex items-center gap-2">
          <Badge variant={status.variant} data-testid="cart-verification">{status.label}</Badge>
          {onRefresh && (
            <Button size="sm" variant="ghost" onClick={onRefresh} disabled={busy}>
              <RefreshCw aria-hidden /> Refresh
            </Button>
          )}
        </div>
      </header>

      {cart.items.length === 0 ? (
        <p className="text-xs text-muted-foreground">The cart is empty on the website.</p>
      ) : (
        <ul className="divide-y divide-white/[0.05]">
          {cart.items.map((item) => (
            <CartItemRow key={item.item_id} item={item} onChangeQuantity={onChangeQuantity} busy={busy} checkStatus={checkFor(item.item_id)} />
          ))}
        </ul>
      )}

      <PriceBreakdown subtotal={cart.subtotal} deliveryFee={cart.delivery_fee} handlingFee={cart.handling_fee} discount={cart.discount}
        tax={cart.tax} total={cart.total} />

      {verification && verification.missing_items.length > 0 && (
        <p role="alert" className="flex items-start gap-2 text-xs text-level-warning" data-testid="missing-items">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Missing: {verification.missing_items.join(", ")}
        </p>
      )}
      {verification && verification.mismatched_items.length > 0 && (
        <p role="alert" className="flex items-start gap-2 text-xs text-level-error" data-testid="mismatched-items">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Mismatch: {verification.mismatched_items.join("; ")}
        </p>
      )}
      {verification?.status === "VERIFIED" && (
        <p className="flex items-center gap-1.5 text-xs text-level-success">
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Every requested item and quantity was found in the cart. No order has been placed.
        </p>
      )}
      {verification?.warnings.map((w) => (
        <p key={w} className="text-[11px] text-muted-foreground">{w}</p>
      ))}
      <p className="text-[10px] text-muted-foreground/70">Read from the website at {formatTime(cart.observed_at)}.</p>
    </section>
  );
}
