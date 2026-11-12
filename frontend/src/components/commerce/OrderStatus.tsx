import { Badge } from "@/components/ui/badge";

import type { OrderState, OrderStatus as Status } from "@/types/checkout";

const META: Record<Status, { label: string; variant: "secondary" | "default" | "violet" | "warning" | "success" | "destructive" }> = {
  NOT_STARTED: { label: "Cart prepared", variant: "secondary" },
  REVIEW_REQUIRED: { label: "Checkout reviewed", variant: "default" },
  APPROVAL_PENDING: { label: "Waiting for approval", variant: "warning" },
  REJECTED: { label: "Approval rejected", variant: "secondary" },
  PAYMENT_HANDOFF: { label: "Manual payment required", variant: "warning" },
  SUBMISSION_PENDING: { label: "Submitting once…", variant: "violet" },
  CONFIRMED: { label: "Order confirmed", variant: "success" },
  UNKNOWN: { label: "Order status could not be verified", variant: "destructive" },
  FAILED: { label: "Order failed", variant: "destructive" },
};

/**
 * Final order state as observed on the website. "Order confirmed" appears only when the
 * website itself showed a confirmation — never because a click or HTTP call succeeded.
 */
export function OrderStatus({ order }: { order: OrderState }) {
  const meta = META[order.status];
  return (
    <section className="flex flex-col gap-1 rounded-lg border border-white/[0.08] bg-white/[0.02] p-3" aria-label="Order status" data-testid="order-status" data-status={order.status}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-[0.16em]">Order status</span>
        <Badge variant={meta.variant}>{meta.label}</Badge>
      </div>
      <p className="text-xs text-foreground/90">{order.message}</p>
      {order.order_reference && (
        <p className="font-mono text-xs text-muted-foreground">Reference shown by the website: {order.order_reference}</p>
      )}
      {order.status === "UNKNOWN" && (
        <p role="alert" className="text-xs text-level-error">Please check your orders on the website yourself. TaskPilot will not submit again.</p>
      )}
    </section>
  );
}
