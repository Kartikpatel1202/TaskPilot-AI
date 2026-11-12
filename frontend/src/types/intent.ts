import type { Language } from "./telemetry";

export type IntentType =
  | "GENERAL_CHAT"
  | "BROWSER_NAVIGATION"
  | "ECOMMERCE_SEARCH"
  | "ECOMMERCE_SHOPPING"
  | "ECOMMERCE_CART_REVIEW"
  | "ECOMMERCE_CHECKOUT_REVIEW"
  | "ECOMMERCE_PURCHASE"
  | "MEDIA_SEARCH"
  | "EMAIL_DRAFT"
  | "EMAIL_SEND"
  | "CALENDAR_MANAGEMENT"
  | "FILE_DOWNLOAD"
  // Phase 5
  | "YOUTUBE_SEARCH"
  | "YOUTUBE_PLAYBACK"
  | "MULTI_DOMAIN_WORKFLOW"
  | "FORM_SUBMISSION"
  | "DATA_EXTRACTION"
  | "UNSUPPORTED";

export const INTENT_TYPES: readonly IntentType[] = [
  "GENERAL_CHAT",
  "BROWSER_NAVIGATION",
  "ECOMMERCE_SEARCH",
  "ECOMMERCE_SHOPPING",
  "ECOMMERCE_CART_REVIEW",
  "ECOMMERCE_CHECKOUT_REVIEW",
  "ECOMMERCE_PURCHASE",
  "MEDIA_SEARCH",
  "EMAIL_DRAFT",
  "EMAIL_SEND",
  "CALENDAR_MANAGEMENT",
  "FILE_DOWNLOAD",
  "YOUTUBE_SEARCH",
  "YOUTUBE_PLAYBACK",
  "MULTI_DOMAIN_WORKFLOW",
  "FORM_SUBMISSION",
  "DATA_EXTRACTION",
  "UNSUPPORTED",
];

/** Payload of `agent.intent_detected` (the full entity set stays server-side). */
export interface IntentClassification {
  intent: IntentType;
  confidence: number;
  target_website: string | null;
  language: Language;
  requires_clarification: boolean;
  is_follow_up: boolean;
}
