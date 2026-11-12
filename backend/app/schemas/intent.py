"""Intent classification schemas. Mirrors `frontend/src/types/intent.ts`."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Language = Literal["en", "hi", "hinglish"]


class IntentType(str, Enum):
    GENERAL_CHAT = "GENERAL_CHAT"
    BROWSER_NAVIGATION = "BROWSER_NAVIGATION"
    ECOMMERCE_SEARCH = "ECOMMERCE_SEARCH"
    ECOMMERCE_SHOPPING = "ECOMMERCE_SHOPPING"
    ECOMMERCE_CART_REVIEW = "ECOMMERCE_CART_REVIEW"
    ECOMMERCE_CHECKOUT_REVIEW = "ECOMMERCE_CHECKOUT_REVIEW"
    ECOMMERCE_PURCHASE = "ECOMMERCE_PURCHASE"
    MEDIA_SEARCH = "MEDIA_SEARCH"
    EMAIL_DRAFT = "EMAIL_DRAFT"
    EMAIL_SEND = "EMAIL_SEND"
    CALENDAR_MANAGEMENT = "CALENDAR_MANAGEMENT"
    FILE_DOWNLOAD = "FILE_DOWNLOAD"
    # Phase 5
    YOUTUBE_SEARCH = "YOUTUBE_SEARCH"
    YOUTUBE_PLAYBACK = "YOUTUBE_PLAYBACK"
    MULTI_DOMAIN_WORKFLOW = "MULTI_DOMAIN_WORKFLOW"
    FORM_SUBMISSION = "FORM_SUBMISSION"
    DATA_EXTRACTION = "DATA_EXTRACTION"
    UNSUPPORTED = "UNSUPPORTED"


# Intents that never produce browser steps.
NON_ACTIONABLE_INTENTS = frozenset({IntentType.GENERAL_CHAT, IntentType.UNSUPPORTED})


class ProductEntity(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=60)
    quantity: float | None = Field(default=None, gt=0, le=1000)
    unit: str | None = Field(default=None, max_length=30)
    # Phase 4 (all optional; never invented): product line/variant ("Taaza", "Gold"), specs ("16GB RAM"),
    # budget in INR and a category ("laptop").
    variant: str | None = Field(default=None, max_length=60)
    specs: list[str] = Field(default_factory=list, max_length=10)
    max_price: float | None = Field(default=None, gt=0, le=10_000_000)
    category: str | None = Field(default=None, max_length=60)


WorkflowStepIntent = Literal["YOUTUBE_SEARCH", "YOUTUBE_PLAYBACK", "EMAIL_DRAFT", "EMAIL_SEND", "CALENDAR_MANAGEMENT", "FILE_DOWNLOAD"]


class WorkflowStepEntity(BaseModel):
    """Phase 5: one domain step of a multi-domain request, in the order the user asked for it."""

    intent: WorkflowStepIntent
    target_website: str | None = Field(default=None, max_length=253)
    search_query: str | None = Field(default=None, max_length=300)
    recipient: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=200)
    message_topic: str | None = Field(default=None, max_length=500)
    datetime_text: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2048)
    text: str | None = Field(default=None, max_length=500)  # the user's own clause for this step
    requested_actions: list[str] = Field(default_factory=list, max_length=10)
    include_previous_output: bool = False


class IntentEntities(BaseModel):
    """Typed entity bag. Every field is optional; missing data is never invented."""

    products: list[ProductEntity] = Field(default_factory=list, max_length=20)
    search_query: str | None = Field(default=None, max_length=300)
    recipient: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=200)
    message_topic: str | None = Field(default=None, max_length=500)
    datetime_text: str | None = Field(default=None, max_length=100)
    url: str | None = Field(default=None, max_length=2048)
    requested_actions: list[str] = Field(default_factory=list, max_length=10)
    # Phase 4: explicit payment choice when the user states one ("COD", "UPI", "CARD"...).
    payment_preference: str | None = Field(default=None, max_length=20)
    # Phase 5: ordered domain steps of a MULTI_DOMAIN_WORKFLOW request (empty otherwise).
    workflow: list[WorkflowStepEntity] = Field(default_factory=list, max_length=8)


class IntentClassification(BaseModel):
    """Structured classifier output (also the LLM response schema)."""

    intent: IntentType
    confidence: float = Field(ge=0, le=1)
    language: Language = "en"
    target_website: str | None = Field(default=None, max_length=253)
    entities: IntentEntities = Field(default_factory=IntentEntities)
    missing_information: list[str] = Field(default_factory=list, max_length=10)
    requires_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=400)
    is_follow_up: bool = False

    @field_validator("missing_information")
    @classmethod
    def _clean_missing(cls, value: list[str]) -> list[str]:
        return [v.strip()[:80] for v in value if v and v.strip()]
