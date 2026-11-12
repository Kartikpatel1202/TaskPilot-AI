/**
 * Phase 4 commerce REST client. Every response is validated with Zod; everything shown
 * comes from what the backend observed in the session's real browser.
 * No call here can place an order — purchases need the exact-order approval inside a run.
 */

import { z } from "zod";

import { request } from "./api";
import { requirementSchema } from "./planValidators";
import { commercePlatformSchema, paymentMethodSchema } from "./validators";

import type { CartSnapshot } from "@/types/cart";
import type { CheckoutSummary, OrderState } from "@/types/checkout";
import type { ShoppingSummary } from "@/types/commerce";

const uuid = z.string().uuid();
const isoDate = z.string().datetime({ offset: true });
const money = z.string().regex(/^-?\d{1,12}(\.\d{1,3})?$/);
const optMoney = money.nullable().optional();
const availability = z.enum(["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]);
const unit = z.enum(["PIECE", "GRAM", "KILOGRAM", "MILLILITER", "LITER", "PACK", "DOZEN", "UNKNOWN"]);
const decision = z.enum(["SELECTED", "NEEDS_CONFIRMATION", "AMBIGUOUS", "NOT_FOUND", "UNAVAILABLE"]);
const verification = z.enum(["VERIFIED", "PARTIAL", "MISMATCH", "UNVERIFIED"]);
const safeUrl = z.string().url().refine((u) => /^https?:\/\//.test(u), "http(s) only");

export const candidateSchema = z.object({
  candidate_id: uuid,
  platform: commercePlatformSchema,
  product_name: z.string().min(1).max(300),
  brand: z.string().max(60).nullable().optional(),
  variant: z.record(z.string().max(80)),
  pack_size: z.string().max(60).nullable().optional(),
  displayed_price: z.string().max(40).nullable().optional(),
  normalized_price: optMoney,
  list_price: optMoney,
  currency: z.string().max(5),
  availability,
  seller: z.string().max(120).nullable().optional(),
  rating: z.string().max(40).nullable().optional(),
  review_count: z.string().max(40).nullable().optional(),
  delivery_estimate: z.string().max(120).nullable().optional(),
  product_url: safeUrl.nullable().optional(),
  image_url: z.string().url().refine((u) => u.startsWith("https://"), "https only").nullable().optional(),
  in_cart_quantity: z.number().int().nonnegative().nullable().optional(),
  observed_at: isoDate,
  source_page: z.string().max(2048),
  extraction_confidence: z.number().min(0).max(1),
  dom_ref: z.string().max(20).nullable().optional(),
});

const matchSchema = z.object({
  requirement_id: uuid,
  candidate_id: uuid,
  brand_score: z.number(),
  name_score: z.number(),
  quantity_score: z.number(),
  variant_score: z.number(),
  overall_score: z.number().min(0).max(1),
  exact_match: z.boolean(),
  explanation: z.string().max(300),
  needs_user_confirmation: z.boolean(),
  packs_needed: z.number().int().nullable().optional(),
  disqualified: z.boolean(),
});

export const cartItemSchema = z.object({
  item_id: uuid,
  product_name: z.string().max(300),
  brand: z.string().max(60).nullable().optional(),
  variant: z.record(z.string()),
  pack_size: z.string().max(60).nullable().optional(),
  quantity: z.number().nonnegative(),
  unit,
  unit_price: optMoney,
  line_total: optMoney,
  availability,
  product_url: z.string().max(2048).nullable().optional(),
  observed_at: isoDate,
  dom_ref: z.string().max(20).nullable().optional(),
});

export const cartSnapshotSchema: z.ZodType<CartSnapshot> = z.object({
  cart_id: uuid,
  platform: commercePlatformSchema,
  items: z.array(cartItemSchema).max(200),
  item_count: z.number().int().nonnegative(),
  subtotal: optMoney,
  delivery_fee: optMoney,
  handling_fee: optMoney,
  discount: optMoney,
  tax: optMoney,
  total: optMoney,
  currency: z.string().max(5),
  observed_at: isoDate,
  verification_status: verification,
  source_page: z.string().max(2048).nullable().optional(),
});

const verificationSchema = z.object({
  task_id: uuid,
  cart_id: uuid,
  status: verification,
  requested_items: z.array(requirementSchema),
  observed_items: z.array(cartItemSchema),
  checks: z.array(z.object({
    requirement_id: uuid,
    label: z.string().max(300),
    status: z.enum(["OK", "MISSING", "QUANTITY_MISMATCH", "VARIANT_MISMATCH", "UNAVAILABLE", "SKIPPED"]),
    observed_item_id: uuid.nullable().optional(),
    requested: z.string().max(300),
    observed: z.string().max(400).nullable().optional(),
    message: z.string().max(600),
  })),
  missing_items: z.array(z.string().max(300)),
  mismatched_items: z.array(z.string().max(400)),
  warnings: z.array(z.string().max(600)),
  computed_subtotal: optMoney,
  verified_at: isoDate,
});

export const checkoutSummarySchema: z.ZodType<CheckoutSummary> = z.object({
  checkout_id: uuid,
  task_id: uuid,
  platform: commercePlatformSchema,
  items: z.array(cartItemSchema).max(200),
  subtotal: optMoney,
  delivery_fee: optMoney,
  handling_fee: optMoney,
  tax: optMoney,
  discount: optMoney,
  final_total: optMoney,
  currency: z.string().max(5),
  masked_delivery_address: z.string().max(200).nullable().optional(),
  delivery_slot: z.string().max(200).nullable().optional(),
  payment_method: paymentMethodSchema,
  available_payment_methods: z.array(paymentMethodSchema),
  cart_id: uuid.nullable().optional(),
  observed_at: isoDate,
  is_verified: z.boolean(),
  summary_hash: z.string().max(128),
  version: z.number().int(),
  warnings: z.array(z.string().max(600)),
});

export const orderStateSchema: z.ZodType<OrderState> = z.object({
  task_id: uuid,
  status: z.enum(["NOT_STARTED", "REVIEW_REQUIRED", "APPROVAL_PENDING", "REJECTED", "PAYMENT_HANDOFF", "SUBMISSION_PENDING", "CONFIRMED", "UNKNOWN", "FAILED"]),
  message: z.string().max(1000),
  order_reference: z.string().max(80).nullable().optional(),
  checkout_id: uuid.nullable().optional(),
  approval_id: uuid.nullable().optional(),
  observed_at: isoDate.nullable().optional(),
});

export const shoppingSummarySchema: z.ZodType<ShoppingSummary> = z.object({
  task_id: uuid,
  session_id: uuid,
  platform: commercePlatformSchema,
  site_name: z.string().max(80),
  is_fixture: z.boolean(),
  status: z.enum(["PLANNED", "RUNNING", "WAITING_USER", "CART_READY", "PARTIAL", "SEARCH_COMPLETE", "CHECKOUT_READY", "APPROVAL_PENDING",
    "PAYMENT_HANDOFF", "ORDER_CONFIRMED", "BLOCKED", "FAILED"]),
  message: z.string().max(1000).nullable().optional(),
  requirements: z.array(z.object({
    requirement: requirementSchema,
    status: z.enum(["PENDING", "SEARCHING", "AWAITING_SELECTION", "SELECTED", "ADDED", "ALREADY_IN_CART", "FOUND", "NOT_FOUND",
      "UNAVAILABLE", "SKIPPED", "FAILED"]),
    decision: decision.nullable().optional(),
    message: z.string().max(1000).nullable().optional(),
    candidates: z.array(candidateSchema).max(100),
    matches: z.array(matchSchema).max(100),
    selected_candidate_id: uuid.nullable().optional(),
    packs_added: z.number().int(),
  })).max(50),
  pending_selection: z.object({
    selection_id: uuid,
    task_id: uuid,
    requirement_id: uuid,
    question: z.string().max(600),
    candidate_ids: z.array(uuid).max(20),
    expires_at: isoDate,
  }).nullable().optional(),
  cart: cartSnapshotSchema.nullable().optional(),
  verification: verificationSchema.nullable().optional(),
  checkout: checkoutSummarySchema.nullable().optional(),
  order: orderStateSchema.nullable().optional(),
  price_changes: z.array(z.string().max(600)),
  warnings: z.array(z.string().max(600)),
  updated_at: isoDate,
});

const enc = encodeURIComponent;

export async function getShoppingSummary(taskId: string, sessionId: string): Promise<ShoppingSummary> {
  return request(`/tasks/${enc(taskId)}/commerce/summary?session_id=${enc(sessionId)}`, { schema: shoppingSummarySchema });
}

/** Answer a pending product choice. `candidateId: null` skips the product. */
export async function selectProduct(taskId: string, sessionId: string, selectionId: string, candidateId: string | null): Promise<void> {
  await request(`/tasks/${enc(taskId)}/commerce/selection`, {
    method: "POST",
    body: { session_id: sessionId, selection_id: selectionId, candidate_id: candidateId },
    schema: z.object({ accepted: z.literal(true) }).passthrough(),
  });
}

export async function getCart(sessionId: string): Promise<CartSnapshot> {
  return request(`/browser/sessions/${enc(sessionId)}/commerce/cart`, { schema: cartSnapshotSchema });
}

export async function refreshCart(sessionId: string): Promise<CartSnapshot> {
  return request(`/browser/sessions/${enc(sessionId)}/commerce/cart/refresh`, {
    method: "POST", body: { session_id: sessionId }, schema: cartSnapshotSchema, timeoutMs: 60_000,
  });
}

export async function updateCartQuantity(sessionId: string, itemId: string, quantity: number): Promise<CartSnapshot> {
  return request(`/browser/sessions/${enc(sessionId)}/commerce/cart/items/${enc(itemId)}/quantity`, {
    method: "POST", body: { session_id: sessionId, quantity }, schema: cartSnapshotSchema, timeoutMs: 60_000,
  });
}

export async function reviewCheckout(taskId: string, sessionId: string): Promise<CheckoutSummary> {
  return request(`/tasks/${enc(taskId)}/commerce/checkout/review`, {
    method: "POST", body: { session_id: sessionId }, schema: checkoutSummarySchema, timeoutMs: 60_000,
  });
}

export async function getOrderStatus(taskId: string, sessionId: string): Promise<OrderState> {
  return request(`/tasks/${enc(taskId)}/commerce/order-status?session_id=${enc(sessionId)}`, { schema: orderStateSchema });
}

/** "₹1,23,456.00" from a decimal string; unknown stays "Not available" (never ₹0). */
export function formatInr(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "Not available";
  const n = Number(value);
  if (!Number.isFinite(n)) return "Not available";
  const sign = n < 0 ? "-" : "";
  return `${sign}₹${Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
