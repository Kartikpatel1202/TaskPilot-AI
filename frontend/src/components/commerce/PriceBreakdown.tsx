import { formatInr } from "@/lib/commerceApi";
import { cn } from "@/lib/utils";

export interface PriceBreakdownProps {
  subtotal?: string | null;
  deliveryFee?: string | null;
  handlingFee?: string | null;
  discount?: string | null;
  tax?: string | null;
  total?: string | null;
  totalLabel?: string;
  className?: string;
}

/** Observed amounts only. Anything the website did not show is "Not available" — never ₹0. */
export function PriceBreakdown({
  subtotal,
  deliveryFee,
  handlingFee,
  discount,
  tax,
  total,
  totalLabel = "Displayed total",
  className,
}: PriceBreakdownProps) {
  const rows: Array<[string, string | null | undefined]> = [
    ["Subtotal", subtotal],
    ["Delivery", deliveryFee],
    ["Handling", handlingFee],
    ["Discount", discount],
    ["Tax", tax],
  ];
  return (
    <dl className={cn("flex flex-col gap-1 text-xs", className)} data-testid="price-breakdown">
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-3">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className={cn("font-mono tabular-nums", value == null ? "text-muted-foreground/70" : "text-foreground/90")} data-field={label.toLowerCase()}>
            {formatInr(value)}
          </dd>
        </div>
      ))}
      <div className="mt-1 flex justify-between gap-3 border-t border-white/[0.08] pt-1.5 text-sm font-semibold">
        <dt>{totalLabel}</dt>
        <dd className="font-mono tabular-nums" data-field="total">
          {formatInr(total)}
        </dd>
      </div>
    </dl>
  );
}
