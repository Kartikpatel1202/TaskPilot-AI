/** Phase 4 cart types. Mirrors `backend/app/schemas/cart.py`. Unknown fees stay null — never shown as ₹0. */

import type { CommercePlatform, ProductAvailability, ProductRequirement, ProductUnit } from "./product";

export type CartVerificationStatus = "VERIFIED" | "PARTIAL" | "MISMATCH" | "UNVERIFIED";

export interface CartItem {
  item_id: string;
  product_name: string;
  brand?: string | null;
  variant: Record<string, string>;
  pack_size?: string | null;
  quantity: number;
  unit: ProductUnit;
  unit_price?: string | null;
  line_total?: string | null;
  availability: ProductAvailability;
  product_url?: string | null;
  observed_at: string;
  dom_ref?: string | null;
}

export interface CartSnapshot {
  cart_id: string;
  platform: CommercePlatform;
  items: CartItem[];
  item_count: number;
  subtotal?: string | null;
  delivery_fee?: string | null;
  handling_fee?: string | null;
  discount?: string | null;
  tax?: string | null;
  total?: string | null;
  currency: string;
  observed_at: string;
  verification_status: CartVerificationStatus;
  source_page?: string | null;
}

export type CartCheckStatus = "OK" | "MISSING" | "QUANTITY_MISMATCH" | "VARIANT_MISMATCH" | "UNAVAILABLE" | "SKIPPED";

export interface CartItemCheck {
  requirement_id: string;
  label: string;
  status: CartCheckStatus;
  observed_item_id?: string | null;
  requested: string;
  observed?: string | null;
  message: string;
}

export interface CartVerificationReport {
  task_id: string;
  cart_id: string;
  status: CartVerificationStatus;
  requested_items: ProductRequirement[];
  observed_items: CartItem[];
  checks: CartItemCheck[];
  missing_items: string[];
  mismatched_items: string[];
  warnings: string[];
  computed_subtotal?: string | null;
  verified_at: string;
}
