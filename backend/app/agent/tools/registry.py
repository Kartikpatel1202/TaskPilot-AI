"""Registry of planning-time tools (browser action contracts).

Only explicitly registered tools are allowed. Tools map to static Pydantic models;
nothing is imported or executed based on model output. Phase 3 binds approved
actions to Playwright implementations elsewhere.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from app.schemas.approval import RiskLevel


class AgentTool(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool = False
    risk_level: RiskLevel
    available: bool = True


class UnknownToolError(KeyError):
    pass


class DuplicateToolError(ValueError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}
        self._models: dict[str, type[BaseModel]] = {}

    def register(self, tool: AgentTool, model: type[BaseModel] | None = None) -> None:
        if tool.name in self._tools:
            raise DuplicateToolError(f"Tool {tool.name!r} is already registered.")
        self._tools[tool.name] = tool
        if model is not None:
            self._models[tool.name] = model

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(name) from exc

    def list_available(self) -> list[AgentTool]:
        return [t for t in self._tools.values() if t.available]

    def names(self) -> list[str]:
        return [t.name for t in self.list_available()]

    def validate(self, name: str, arguments: dict[str, Any]) -> bool:
        """True when `name` is a registered, available tool and `arguments` match its contract."""
        tool = self._tools.get(name)
        if tool is None or not tool.available:
            return False
        model = self._models.get(name)
        if model is None:
            return True
        try:
            model.model_validate({"type": name, **arguments})
        except ValidationError:
            return False
        return True

    def describe_for_prompt(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "risk_level": t.risk_level.value, "requires_approval": t.requires_approval}
            for t in self.list_available()
        ]
