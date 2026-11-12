"""What recovery may do. Bounded attempts and time; read-only reinspection only; never relabels a step
into something riskier; never touches approvals; never repeats a step whose effect is uncertain."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.policies.risk_classifier import _text_risk, risk_at_least
from app.agent.self_correction.failure_classifier import RECOVERABLE, FailureType
from app.schemas.approval import RiskLevel


@dataclass(frozen=True)
class RecoveryPolicy:
    enabled: bool = True
    max_attempts: int = 2
    max_replans: int = 2
    max_seconds: float = 60.0

    def may_recover(self, failure: FailureType, attempts_used: int) -> bool:
        return self.enabled and failure in RECOVERABLE and attempts_used < self.max_attempts


def replacement_allowed(step_risk: RiskLevel, new_label: str) -> bool:
    """A replacement target may not be riskier than the planned step (that would bypass its approval policy)."""
    return risk_at_least(step_risk, _text_risk(new_label))
