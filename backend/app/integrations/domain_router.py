"""Domain router (Phase 5): classified intent -> integration domain(s).

Pure, deterministic mapping. It never trusts a model-supplied domain name: the target
website is resolved through the IntegrationRegistry (canonical hosts / exact fixtures).
"""

from __future__ import annotations

from app.schemas.intent import IntentClassification, IntentType, WorkflowStepEntity
from app.schemas.integration import DomainType

INTENT_DOMAIN: dict[str, DomainType] = {
    "YOUTUBE_SEARCH": DomainType.YOUTUBE,
    "YOUTUBE_PLAYBACK": DomainType.YOUTUBE,
    "MEDIA_SEARCH": DomainType.YOUTUBE,
    "EMAIL_DRAFT": DomainType.GMAIL,
    "EMAIL_SEND": DomainType.GMAIL,
    "CALENDAR_MANAGEMENT": DomainType.GOOGLE_CALENDAR,
    "FILE_DOWNLOAD": DomainType.FILES,
}
INTEGRATION_INTENTS = frozenset({
    IntentType.YOUTUBE_SEARCH, IntentType.YOUTUBE_PLAYBACK, IntentType.MEDIA_SEARCH, IntentType.EMAIL_DRAFT,
    IntentType.EMAIL_SEND, IntentType.CALENDAR_MANAGEMENT, IntentType.FILE_DOWNLOAD, IntentType.MULTI_DOMAIN_WORKFLOW,
})
_NON_YOUTUBE_MEDIA = ("spotify",)


def single_step(classification: IntentClassification) -> WorkflowStepEntity | None:
    """The one domain step of a single-domain request (None when it is not an integration request)."""
    intent = classification.intent.value
    if intent not in INTENT_DOMAIN:
        return None
    e = classification.entities
    actions = [a.lower() for a in e.requested_actions]
    if intent == "MEDIA_SEARCH":
        site = (classification.target_website or "").lower()
        if any(s in site for s in _NON_YOUTUBE_MEDIA):
            return None  # other media sites stay on the generic planner
        intent = "YOUTUBE_PLAYBACK" if "play" in actions else "YOUTUBE_SEARCH"
    return WorkflowStepEntity(
        intent=intent,  # type: ignore[arg-type]
        target_website=classification.target_website, search_query=e.search_query, recipient=e.recipient, subject=e.subject,
        message_topic=e.message_topic, datetime_text=e.datetime_text, url=e.url, requested_actions=e.requested_actions,
    )


def route(classification: IntentClassification) -> list[WorkflowStepEntity]:
    """Ordered domain steps for a classified request ([] = not an integration request)."""
    if classification.intent == IntentType.MULTI_DOMAIN_WORKFLOW:
        steps = []
        for s in classification.entities.workflow:
            if s.intent == "YOUTUBE_SEARCH" and "play" in [a.lower() for a in s.requested_actions]:
                s = s.model_copy(update={"intent": "YOUTUBE_PLAYBACK"})
            steps.append(s)
        return steps
    step = single_step(classification)
    return [step] if step else []


def domain_of(step: WorkflowStepEntity) -> DomainType:
    return INTENT_DOMAIN[step.intent]
