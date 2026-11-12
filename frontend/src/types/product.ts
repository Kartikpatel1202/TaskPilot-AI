/** Phase 4 product types. Mirrors `backend/app/schemas/product.py`. Money values are decimal strings. */

export type CommercePlatform = "BLINKIT" | "AMAZON_IN";
export type ProductUnit = "PIECE" | "GRAM" | "KILOGRAM" | "MILLILITER" | "LITER" | "PACK" | "DOZEN" | "UNKNOWN";
export type ProductAvailability = "AVAILABLE" | "UNAVAILABLE" | "UNKNOWN";
export type MatchDecision = "SELECTED" | "NEEDS_CONFIRMATION" | "AMBIGUOUS" | "NOT_FOUND" | "UNAVAILABLE";

export interface ProductRequirement {
  product_id: string;
  query: string;
  product_name: string;
  brand?: string | null;
  model?: string | null;
  quantity: number;
  unit: ProductUnit;
  preferred_variant: Record<string, string>;
  must_match_brand: boolean;
  allow_substitute: boolean;
  category?: string | null;
  max_price?: string | null;
  required_specs: Record<string, string>;
  notes: string[];
}

export interface ProductCandidate {
  candidate_id: string;
  platform: CommercePlatform;
  product_name: string;
  brand?: string | null;
  variant: Record<string, string>;
  pack_size?: string | null;
  displayed_price?: string | null;
  normalized_price?: string | null;
  list_price?: string | null;
  currency: string;
  availability: ProductAvailability;
  seller?: string | null;
  rating?: string | null;
  review_count?: string | null;
  delivery_estimate?: string | null;
  product_url?: string | null;
  image_url?: string | null;
  in_cart_quantity?: number | null;
  observed_at: string;
  source_page: string;
  extraction_confidence: number;
  dom_ref?: string | null;
}

export interface ProductMatch {
  requirement_id: string;
  candidate_id: string;
  brand_score: number;
  name_score: number;
  quantity_score: number;
  variant_score: number;
  overall_score: number;
  exact_match: boolean;
  explanation: string;
  needs_user_confirmation: boolean;
  packs_needed?: number | null;
  disqualified: boolean;
}

export const PLATFORM_LABEL: Record<CommercePlatform, string> = {
  BLINKIT: "Blinkit",
  AMAZON_IN: "Amazon India",
};
