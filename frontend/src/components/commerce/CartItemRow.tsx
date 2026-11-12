"use client";

import { Minus, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatInr } from "@/lib/commerceApi";

import type { CartItem } from "@/types/cart";

interface CartItemRowProps {
  item: CartItem;
  /** When provided, the row offers +/− (each change is verified on the website). */
  onChangeQuantity?: (itemId: string, quantity: number) => void;
  busy?: boolean;
  checkStatus?: string | null;
}

export function CartItemRow({ item, onChangeQuantity, busy = false, checkStatus }: CartItemRowProps) {
  return (
    <li className="flex items-center justify-between gap-3 py-2" data-testid="cart-item" data-check={checkStatus ?? undefined}>
      <div className="min-w-0">
        <p className="truncate text-sm text-foreground">{item.product_name}</p>
        <p className="text-[11px] text-muted-foreground">
          {item.pack_size ?? "size not shown"}
          {item.availability === "UNAVAILABLE" && <span className="ml-2 text-level-error">unavailable</span>}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <div className="flex items-center gap-1" aria-label={`Quantity of ${item.product_name}`}>
          {onChangeQuantity && (
            <Button size="icon-sm" variant="ghost" disabled={busy} aria-label={`Decrease ${item.product_name}`}
              onClick={() => onChangeQuantity(item.item_id, Math.max(0, item.quantity - 1))}>
              <Minus aria-hidden />
            </Button>
          )}
          <span className="min-w-6 text-center font-mono text-sm tabular-nums" data-testid="cart-item-qty">
            {item.quantity}
          </span>
          {onChangeQuantity && (
            <Button size="icon-sm" variant="ghost" disabled={busy} aria-label={`Increase ${item.product_name}`}
              onClick={() => onChangeQuantity(item.item_id, item.quantity + 1)}>
              <Plus aria-hidden />
            </Button>
          )}
        </div>
        <span className="w-24 text-right font-mono text-xs tabular-nums text-foreground/90">{formatInr(item.line_total)}</span>
      </div>
    </li>
  );
}
