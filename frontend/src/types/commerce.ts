/** Phase 4 commerce workflow types. Mirrors `backend/app/schemas/commerce.py`. */

import type { CartSnapshot, CartVerificationReport } from "./cart";
import type { CheckoutSummary, OrderState } from "./checkout";
import type { CommercePlatform, MatchDecision, ProductCandidate, ProductMatch, ProductRequirement } from "./product";

export type CommerceOperation =
  | "open_store"
  | "search_products"
  | "search_and_add"
  | "verify_cart"
  | "checkout_review"
  | "place_order";

export type PaymentPreference = "COD" | "PREPAID" | "ANY";

/** Plan step built only by the backend's deterministic commerce planner. */
export interface CommerceAction {
  type: "commerce";
  operation: CommerceOperation;
  platform: CommercePlatform;
  site_key: string;
  requirement?: ProductRequirement | null;
  payment_preference?: PaymentPreference | null;
  continue_on_failure: boolean;
}

export type RequirementStatus =
  | "PENDING"
  | "SEARCHING"
  | "AWAITING_SELECTION"
  | "SELECTED"
  | "ADDED"
  | "ALREADY_IN_CART"
  | "FOUND"
  | "NOT_FOUND"
  | "UNAVAILABLE"
  | "SKIPPED"
  | "FAILED";

export interface RequirementProgress {
  requirement: ProductRequirement;
  status: RequirementStatus;
  decision?: MatchDecision | null;
  message?: string | null;
  candidates: ProductCandidate[];
  matches: ProductMatch[];
  selected_candidate_id?: string | null;
  packs_added: number;
}

export interface PendingSelection {
  selection_id: string;
  task_id: string;
  requirement_id: string;
  question: string;
  candidate_ids: string[];
  expires_at: string;
}

export type WorkflowStatus =
  | "PLANNED"
  | "RUNNING"
  | "WAITING_USER"
  | "CART_READY"
  | "PARTIAL"
  | "SEARCH_COMPLETE"
  | "CHECKOUT_READY"
  | "APPROVAL_PENDING"
  | "PAYMENT_HANDOFF"
  | "ORDER_CONFIRMED"
  | "BLOCKED"
  | "FAILED";

export interface ShoppingSummary {
  task_id: string;
  session_id: string;
  platform: CommercePlatform;
  site_name: string;
  is_fixture: boolean;
  status: WorkflowStatus;
  message?: string | null;
  requirements: RequirementProgress[];
  pending_selection?: PendingSelection | null;
  cart?: CartSnapshot | null;
  verification?: CartVerificationReport | null;
  checkout?: CheckoutSummary | null;
  order?: OrderState | null;
  price_changes: string[];
  warnings: string[];
  updated_at: string;
}

/** Commerce telemetry event types (Phase 4). */
export type CommerceEventType =
  | "commerce.session_detected"
  | "commerce.location_required"
  | "commerce.search_started"
  | "commerce.search_completed"
  | "commerce.products_found"
  | "commerce.product_selected"
  | "commerce.product_ambiguous"
  | "commerce.product_unavailable"
  | "commerce.cart_update_started"
  | "commerce.cart_item_added"
  | "commerce.cart_item_updated"
  | "commerce.cart_verification_started"
  | "commerce.cart_verification_completed"
  | "commerce.cart_verification_failed"
  | "commerce.price_changed"
  | "commerce.checkout_review_ready"
  | "commerce.purchase_approval_required"
  | "commerce.purchase_rejected"
  | "commerce.payment_handoff"
  | "commerce.order_submission_started"
  | "commerce.order_confirmed"
  | "commerce.order_status_unknown"
  | "commerce.workflow_failed";

export const COMMERCE_EVENT_TYPES: readonly CommerceEventType[] = [
  "commerce.session_detected",
  "commerce.location_required",
  "commerce.search_started",
  "commerce.search_completed",
  "commerce.products_found",
  "commerce.product_selected",
  "commerce.product_ambiguous",
  "commerce.product_unavailable",
  "commerce.cart_update_started",
  "commerce.cart_item_added",
  "commerce.cart_item_updated",
  "commerce.cart_verification_started",
  "commerce.cart_verification_completed",
  "commerce.cart_verification_failed",
  "commerce.price_changed",
  "commerce.checkout_review_ready",
  "commerce.purchase_approval_required",
  "commerce.purchase_rejected",
  "commerce.payment_handoff",
  "commerce.order_submission_started",
  "commerce.order_confirmed",
  "commerce.order_status_unknown",
  "commerce.workflow_failed",
];

/** Generic commerce event payload as validated on the client (fields vary by type). */
export interface CommerceEventData {
  platform?: CommercePlatform | null;
  message?: string | null;
  status?: string | null;
  query?: string | null;
  product_name?: string | null;
  requirement_id?: string | null;
  selection_id?: string | null;
  approval_id?: string | null;
  code?: string | null;
  candidate_count?: number | null;
  exact_match_count?: number | null;
  final_total?: string | null;
  order_reference?: string | null;
  approval_invalidated?: boolean | null;
  difference?: string | null;
  [key: string]: unknown;
}
