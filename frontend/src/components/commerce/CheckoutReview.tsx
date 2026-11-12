import { AlertTriangle, MapPin, ReceiptText, ShieldCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";

import { PriceBreakdown } from "./PriceBreakdown";

import { PAYMENT_LABEL, type CheckoutSummary } from "@/types/checkout";

interface CheckoutReviewProps {
  checkout: CheckoutSummary;
  priceChanges?: string[];
}

/** The checkout page as read from the website. Reviewing never purchases anything. */
export function CheckoutReview({ checkout, priceChanges = [] }: CheckoutReviewProps) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-white/[0.08] bg-white/[0.02] p-3" aria-label="Checkout review" data-testid="checkout-review">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em]">
          <ReceiptText className="h-3.5 w-3.5 text-violet-brand" aria-hidden /> Checkout review
        </h4>
        <Badge variant={checkout.is_verified ? "success" : "destructive"} data-testid="checkout-verified">
          {checkout.is_verified ? "Verified" : "Not verified"}
        </Badge>
      </header>
      <ul className="flex flex-col gap-1 text-xs">
        {checkout.items.map((i) => (
          <li key={i.item_id} className="flex justify-between gap-3">
            <span className="truncate text-foreground/90">{i.product_name} {i.pack_size ? `· ${i.pack_size}` : ""} × {i.quantity}</span>
            <span className="font-mono tabular-nums">{i.line_total ? `₹${Number(i.line_total).toLocaleString("en-IN", { minimumFractionDigits: 2 })}` : "—"}</span>
          </li>
        ))}
      </ul>
      <PriceBreakdown subtotal={checkout.subtotal} deliveryFee={checkout.delivery_fee} handlingFee={checkout.handling_fee}
        discount={checkout.discount} tax={checkout.tax} total={checkout.final_total} totalLabel="Final total (as shown)" />
      <dl className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-3">
        <div><dt className="text-muted-foreground">Deliver to</dt><dd className="flex items-center gap-1"><MapPin className="h-3 w-3" aria-hidden />{checkout.masked_delivery_address ?? "Not shown"}</dd></div>
        <div><dt className="text-muted-foreground">Delivery</dt><dd>{checkout.delivery_slot ?? "Not shown"}</dd></div>
        <div><dt className="text-muted-foreground">Payment</dt><dd data-testid="checkout-payment">{PAYMENT_LABEL[checkout.payment_method]}</dd></div>
      </dl>
      {[...priceChanges, ...checkout.warnings].map((w) => (
        <p key={w} role="alert" className="flex items-start gap-2 text-xs text-level-warning" data-testid="checkout-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> {w}
        </p>
      ))}
      <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Nothing has been purchased. An order needs your separate, exact-order approval.
      </p>
    </section>
  );
}
