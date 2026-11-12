import { SESSION, TASK, uuidFor } from "../fixtures";

import type { ApprovalRequest } from "@/types/approval";
import type { CartSnapshot, CartVerificationReport } from "@/types/cart";
import type { CheckoutSummary } from "@/types/checkout";
import type { ShoppingSummary } from "@/types/commerce";
import type { ProductCandidate, ProductMatch, ProductRequirement } from "@/types/product";

export const NOW = "2026-11-06T10:00:00.000000+00:00";

export function candidate(n: number, overrides: Partial<ProductCandidate> = {}): ProductCandidate {
  return {
    candidate_id: uuidFor(200 + n), platform: "BLINKIT", product_name: "Amul Taaza Toned Fresh Milk", brand: null, variant: {},
    pack_size: "1 ltr", displayed_price: "₹56", normalized_price: "56.00", list_price: "58.00", currency: "INR", availability: "AVAILABLE",
    seller: null, rating: null, review_count: null, delivery_estimate: null, product_url: null, image_url: null, in_cart_quantity: 0,
    observed_at: NOW, source_page: "https://example.test/s", extraction_confidence: 1, dom_ref: null, ...overrides,
  };
}

export function match(c: ProductCandidate, overrides: Partial<ProductMatch> = {}): ProductMatch {
  return {
    requirement_id: uuidFor(300), candidate_id: c.candidate_id, brand_score: 1, name_score: 1, quantity_score: 0.9, variant_score: 1,
    overall_score: 0.975, exact_match: true, explanation: "Exact match — 2 × 1 L = 2 L", needs_user_confirmation: false, packs_needed: 2,
    disqualified: false, ...overrides,
  };
}

export const REQUIREMENT: ProductRequirement = {
  product_id: uuidFor(300), query: "Amul taaza milk", product_name: "milk", brand: "Amul", model: null, quantity: 2, unit: "LITER",
  preferred_variant: { line: "taaza" }, must_match_brand: true, allow_substitute: false, category: null, max_price: null,
  required_specs: {}, notes: [],
};

export const CART: CartSnapshot = {
  cart_id: uuidFor(400), platform: "BLINKIT", item_count: 2, currency: "INR", observed_at: NOW, verification_status: "VERIFIED",
  items: [
    { item_id: uuidFor(401), product_name: "Amul Taaza Toned Fresh Milk", variant: {}, pack_size: "1 ltr", quantity: 2, unit: "PACK",
      unit_price: null, line_total: "112.00", availability: "AVAILABLE", observed_at: NOW },
    { item_id: uuidFor(402), product_name: "Farm Fresh White Eggs", variant: {}, pack_size: "12 pieces", quantity: 1, unit: "PACK",
      unit_price: null, line_total: "96.00", availability: "AVAILABLE", observed_at: NOW },
  ],
  subtotal: "208.00", delivery_fee: "0.00", handling_fee: "4.00", discount: null, tax: null, total: "212.00",
};

export function verification(overrides: Partial<CartVerificationReport> = {}): CartVerificationReport {
  return {
    task_id: TASK, cart_id: CART.cart_id, status: "VERIFIED", requested_items: [REQUIREMENT], observed_items: CART.items, checks: [],
    missing_items: [], mismatched_items: [], warnings: [], computed_subtotal: "208.00", verified_at: NOW, ...overrides,
  };
}

export const CHECKOUT: CheckoutSummary = {
  checkout_id: uuidFor(500), task_id: TASK, platform: "BLINKIT", items: CART.items, subtotal: "208.00", delivery_fee: "0.00",
  handling_fee: "4.00", tax: null, discount: null, final_total: "212.00", currency: "INR", masked_delivery_address: "Home: •••, Gurugram 122•••",
  delivery_slot: "Delivery in 12 minutes", payment_method: "COD", available_payment_methods: ["COD", "UPI", "CARD"], cart_id: CART.cart_id,
  observed_at: NOW, is_verified: true, summary_hash: "a".repeat(64), version: 2, warnings: [],
};

export function summary(overrides: Partial<ShoppingSummary> = {}): ShoppingSummary {
  const c1 = candidate(1);
  return {
    task_id: TASK, session_id: SESSION, platform: "BLINKIT", site_name: "Blinkit test fixture", is_fixture: true, status: "CART_READY",
    message: "Cart verified. No order has been placed.",
    requirements: [{ requirement: REQUIREMENT, status: "ADDED", decision: "SELECTED", message: "cart quantity 0 → 2", candidates: [c1],
      matches: [match(c1)], selected_candidate_id: c1.candidate_id, packs_added: 2 }],
    pending_selection: null, cart: CART, verification: verification(), checkout: null, order: null, price_changes: [], warnings: [],
    updated_at: NOW, ...overrides,
  };
}

export function purchaseApproval(overrides: Partial<ApprovalRequest> = {}): ApprovalRequest {
  return {
    approval_id: uuidFor(600), task_id: TASK, session_id: SESSION, action_summary: "Place this exact COD order", domain: "Blinkit",
    reason: "Confirm this exact order.", risk_level: "CRITICAL", status: "PENDING", estimated_impact: null,
    expires_at: new Date(Date.now() + 120_000).toISOString(), is_demo: false, created_at: NOW,
    purchase: {
      platform: "BLINKIT", checkout_id: CHECKOUT.checkout_id, cart_id: CART.cart_id, summary_hash: "a".repeat(64), summary_version: 2,
      items: [{ name: "Amul Taaza Toned Fresh Milk", quantity: "2 × 1 ltr", line_total: "112.00" }, { name: "Farm Fresh White Eggs", quantity: "1 × 12 pieces", line_total: "96.00" }],
      subtotal: "208.00", delivery_fee: "0.00", handling_fee: "4.00", tax: null, discount: null, final_total: "212.00", currency: "INR",
      masked_delivery_address: "Home: •••, Gurugram 122•••", delivery_slot: "Delivery in 12 minutes", payment_method: "COD",
      places_real_order: true, warnings: [],
    },
    ...overrides,
  };
}
