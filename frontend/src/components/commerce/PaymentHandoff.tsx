import { HandCoins } from "lucide-react";

import { ASSISTANT_NAME } from "@/lib/persona";

import { formatInr } from "@/lib/commerceApi";

import type { CheckoutSummary, OrderState } from "@/types/checkout";

/** Prepaid payments are always completed by the user on the merchant website. TaskPilot shows no payment fields. */
export function PaymentHandoff({ order, checkout, siteName }: { order: OrderState; checkout?: CheckoutSummary | null; siteName: string }) {
  return (
    <section role="status" className="flex flex-col gap-1.5 rounded-lg border border-level-warning/30 bg-level-warning/[0.07] p-3" data-testid="payment-handoff">
      <p className="flex items-center gap-2 text-sm font-semibold text-level-warning">
        <HandCoins className="h-4 w-4" aria-hidden /> Continue manually on {siteName}
      </p>
      <p className="text-xs text-foreground/90">
        {ASSISTANT_NAME} has prepared your checkout. Please complete the payment manually on the merchant website.
      </p>
      {checkout?.final_total && <p className="text-xs text-muted-foreground">Total shown at checkout: {formatInr(checkout.final_total)}</p>}
      <p className="text-[11px] text-muted-foreground">{order.message}</p>
      <p className="text-[11px] text-muted-foreground">TaskPilot never enters card numbers, UPI PINs or OTPs, and never pays for you.</p>
    </section>
  );
}
