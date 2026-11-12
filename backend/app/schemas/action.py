"""Browser action primitives (planning contracts only — nothing here executes).

Mirrors `frontend/src/types/plan.ts`. Phase 3 maps approved actions to Playwright.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from app.schemas.approval import RiskLevel

_DESC = Field(min_length=1, max_length=300)


class NavigateAction(BaseModel):
    type: Literal["navigate"]
    url: str = Field(min_length=1, max_length=2048)
    purpose: str = _DESC


class ClickAction(BaseModel):
    type: Literal["click"]
    target_description: str = _DESC
    role_hint: str | None = Field(default=None, max_length=40)
    accessible_name: str | None = Field(default=None, max_length=200)
    text_hint: str | None = Field(default=None, max_length=200)


class TypeAction(BaseModel):
    type: Literal["type"]
    target_description: str = _DESC
    text: str = Field(min_length=1, max_length=2000)
    clear_first: bool = True
    sensitive: bool = False


class ExtractAction(BaseModel):
    type: Literal["extract"]
    target_description: str = _DESC
    fields: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=20)


class RequestApprovalAction(BaseModel):
    type: Literal["request_approval"]
    reason: str = Field(min_length=1, max_length=500)
    risk_level: RiskLevel
    details: dict[str, str] = Field(default_factory=dict)


class StopAction(BaseModel):
    type: Literal["stop"]
    reason: str = Field(min_length=1, max_length=500)


from app.schemas.commerce import CommerceAction  # noqa: E402  (Phase 4; built only by trusted code)
from app.schemas.integration import (  # noqa: E402  (Phase 5; built only by the integration planner)
    CalendarCreateEventAction,
    FileDownloadAction,
    GmailCreateDraftAction,
    YouTubePlayAction,
    YouTubeSearchAction,
)

SupportedAction = Annotated[
    Union[NavigateAction, ClickAction, TypeAction, ExtractAction, RequestApprovalAction, StopAction, CommerceAction,
          YouTubeSearchAction, YouTubePlayAction, GmailCreateDraftAction, CalendarCreateEventAction, FileDownloadAction],
    Field(discriminator="type"),
]

ACTION_TYPES: tuple[str, ...] = ("navigate", "click", "type", "extract", "request_approval", "stop")


# ---------------------------------------------------------------------- LLM-facing variants
# Strict structured-output modes reject free-form objects, so the LLM supplies
# approval details as a list of label/value pairs; the planner converts them.


class ApprovalDetailItem(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    value: str = Field(min_length=1, max_length=300)


class DraftRequestApprovalAction(BaseModel):
    type: Literal["request_approval"]
    reason: str = Field(min_length=1, max_length=500)
    risk_level: RiskLevel
    details: list[ApprovalDetailItem] = Field(default_factory=list, max_length=10)

    def to_action(self) -> RequestApprovalAction:
        return RequestApprovalAction(
            type="request_approval",
            reason=self.reason,
            risk_level=self.risk_level,
            details={d.label: d.value for d in self.details},
        )


DraftAction = Annotated[
    Union[NavigateAction, ClickAction, TypeAction, ExtractAction, DraftRequestApprovalAction, StopAction],
    Field(discriminator="type"),
]
