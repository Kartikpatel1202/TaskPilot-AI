"""Static definitions of the six action primitives."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.schemas.action import (
    ClickAction,
    ExtractAction,
    NavigateAction,
    RequestApprovalAction,
    StopAction,
    TypeAction,
)
from app.schemas.approval import RiskLevel


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    model: type[BaseModel]
    description: str
    base_risk: RiskLevel
    requires_approval: bool = False


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition("navigate", NavigateAction, "Open a public http(s) URL.", RiskLevel.LOW),
    ToolDefinition(
        "click",
        ClickAction,
        "Click an element described in plain words (role, accessible name or visible text hints). "
        "No CSS selectors.",
        RiskLevel.LOW,
    ),
    ToolDefinition(
        "type",
        TypeAction,
        "Type text into a described field. Never used for passwords, OTPs or payment details.",
        RiskLevel.LOW,
    ),
    ToolDefinition("extract", ExtractAction, "Read named fields from a described part of the page.", RiskLevel.LOW),
    ToolDefinition(
        "request_approval",
        RequestApprovalAction,
        "Pause and ask the human to approve the next sensitive action.",
        RiskLevel.MEDIUM,
        requires_approval=True,
    ),
    ToolDefinition("stop", StopAction, "End the plan intentionally, with a reason.", RiskLevel.LOW),
)
