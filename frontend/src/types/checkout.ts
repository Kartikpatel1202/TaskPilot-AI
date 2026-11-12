/** Phase 4 checkout/purchase types. Mirrors `backend/app/schemas/checkout.py` and `purchase.py`. */

import type { CartItem } from "./cart";
import type { CommercePlatform } from "./product";

export type PaymentMethod = "COD" | "UPI" | "CARD" | "NET_BANKING" | "WALLET" | "UNKNOWN";

export type OrderStatus =
  | "NOT_STARTED"
  | "REVIEW_REQUIRED"
  | "APPROVAL_PENDING"
  | "REJECTED"
  | "PAYMENT_HANDOFF"
  | "SUBMISSION_PENDING"
  | "CONFIRMED"
  | "UNKNOWN"
  | "FAILED";

export interface CheckoutSummary {
  checkout_id: string;
  task_id: string;
  platform: CommercePlatform;
  items: CartItem[];
  subtotal?: string | null;
  delivery_fee?: string | null;
  handling_fee?: string | null;
  tax?: string | null;
  discount?: string | null;
  final_total?: string | null;
  currency: string;
  masked_delivery_address?: string | null;
  delivery_slot?: string | null;
  payment_method: PaymentMethod;
  available_payment_methods: PaymentMethod[];
  cart_id?: string | null;
  observed_at: string;
  is_verified: boolean;
  summary_hash: string;
  version: number;
  warnings: string[];
}

export interface OrderState {
  task_id: string;
  status: OrderStatus;
  message: string;
  order_reference?: string | null;
  checkout_id?: string | null;
  approval_id?: string | null;
  observed_at?: string | null;
}

export interface PurchaseApprovalItem {
  name: string;
  quantity: string;
  line_total?: string | null;
}

/** Attached to an ApprovalRequest when it is an exact-order purchase review. */
export interface PurchaseApprovalDetails {
  platform: CommercePlatform;
  checkout_id: string;
  cart_id?: string | null;
  summary_hash: string;
  summary_version: number;
  items: PurchaseApprovalItem[];
  subtotal?: string | null;
  delivery_fee?: string | null;
  handling_fee?: string | null;
  tax?: string | null;
  discount?: string | null;
  final_total: string;
  currency: string;
  masked_delivery_address?: string | null;
  delivery_slot?: string | null;
  payment_method: PaymentMethod;
  places_real_order: boolean;
  warnings: string[];
}

export const PAYMENT_LABEL: Record<PaymentMethod, string> = {
  COD: "Cash on Delivery",
  UPI: "UPI",
  CARD: "Card",
  NET_BANKING: "Net banking",
  WALLET: "Wallet",
  UNKNOWN: "Not selected",
};
