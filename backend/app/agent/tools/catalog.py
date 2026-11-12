"""Builds the default tool registry from the static definitions."""

from __future__ import annotations

from .definitions import TOOL_DEFINITIONS
from .registry import AgentTool, ToolRegistry


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for definition in TOOL_DEFINITIONS:
        registry.register(
            AgentTool(
                name=definition.name,
                description=definition.description,
                input_schema=definition.model.model_json_schema(),
                requires_approval=definition.requires_approval,
                risk_level=definition.base_risk,
            ),
            model=definition.model,
        )
    return registry
