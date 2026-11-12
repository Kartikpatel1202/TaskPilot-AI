"""Product schemas (Phase 4). Mirrors `frontend/src/types/product.ts`.

Every candidate field comes from what was actually observed on a page; unknown
values stay null. Money is `Decimal` (serialised as a string), never float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class CommercePlatform(str, Enum):
    BLINKIT = "BLINKIT"
    AMAZON_IN = "AMAZON_IN"


class ProductUnit(str, Enum):
    PIECE = "PIECE"
    GRAM = "GRAM"
    KILOGRAM = "KILOGRAM"
    MILLILITER = "MILLILITER"
    LITER = "LITER"
    PACK = "PACK"
    DOZEN = "DOZEN"
    UNKNOWN = "UNKNOWN"


class ProductAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ProductRequirement(BaseModel):
    """What the user asked for. Built by trusted code from the classified command."""

    product_id: UUID
    query: str = Field(min_length=1, max_length=200)
    product_name: str = Field(min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=80)
    quantity: float = Field(gt=0, le=1000)
    unit: ProductUnit
    preferred_variant: dict[str, str] = Field(default_factory=dict)
    must_match_brand: bool = False
    allow_substitute: bool = False
    # Phase 4 extensions (Amazon-style searches).
    category: str | None = Field(default=None, max_length=60)
    max_price: Decimal | None = Field(default=None, gt=0)
    required_specs: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list, max_length=10)

    def label(self) -> str:
        qty = int(self.quantity) if float(self.quantity).is_integer() else self.quantity
        unit = {"LITER": "L", "MILLILITER": "ml", "KILOGRAM": "kg", "GRAM": "g", "DOZEN": "dozen", "PACK": "pack",
                "PIECE": "pc"}.get(self.unit.value, "")
        size = f" — {qty} {unit}".rstrip() if self.unit != ProductUnit.UNKNOWN else ""
        brand = f"{self.brand} " if self.brand and self.brand.lower() not in self.product_name.lower() else ""
        line = " ".join(v.title() for v in self.preferred_variant.values() if v and v.lower() not in self.product_name.lower())
        return f"{brand}{line + ' ' if line else ''}{self.product_name}{size}"


class ProductCandidate(BaseModel):
    candidate_id: UUID
    platform: CommercePlatform
    product_name: str = Field(min_length=1, max_length=300)
    brand: str | None = None
    variant: dict[str, str] = Field(default_factory=dict)
    pack_size: str | None = None  # as displayed, e.g. "1 L", "Pack of 6"
    displayed_price: str | None = None
    normalized_price: Decimal | None = None
    list_price: Decimal | None = None  # struck-through MRP when displayed
    currency: str = "INR"
    availability: ProductAvailability
    seller: str | None = None
    rating: str | None = None
    review_count: str | None = None
    delivery_estimate: str | None = None
    product_url: str | None = None
    image_url: str | None = None
    in_cart_quantity: int | None = None  # stepper value shown on the card, when visible
    observed_at: datetime
    source_page: str
    extraction_confidence: float = Field(ge=0, le=1)
    # Trusted, adapter-assigned DOM handle for this card on the page it was read from.
    dom_ref: str | None = Field(default=None, pattern=r"^k-\d{1,7}$")


class MatchDecision(str, Enum):
    SELECTED = "SELECTED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"


class ProductMatch(BaseModel):
    requirement_id: UUID
    candidate_id: UUID
    brand_score: float = Field(ge=0, le=1)
    name_score: float = Field(ge=0, le=1)
    quantity_score: float = Field(ge=0, le=1)
    variant_score: float = Field(ge=0, le=1)
    overall_score: float = Field(ge=0, le=1)
    exact_match: bool
    explanation: str
    needs_user_confirmation: bool
    # How many of this pack make up the requested quantity (None when not computable).
    packs_needed: int | None = None
    disqualified: bool = False


class MatchResult(BaseModel):
    """Deterministic outcome of matching one requirement against observed candidates."""

    requirement_id: UUID
    decision: MatchDecision
    selected: ProductMatch | None = None
    ranked: list[ProductMatch] = Field(default_factory=list)
    message: str
