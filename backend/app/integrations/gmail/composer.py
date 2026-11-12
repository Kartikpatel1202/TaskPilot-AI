"""Draft content (Phase 5): deterministic templates that never invent facts.

The body only states what the user asked for plus typed, observed outputs of earlier steps
(e.g. the selected video's title and URL, or a downloaded file's name). Placeholders like
`{{youtube.video_url}}` are resolved by the workflow's result handoff at run time. Names and
details the user did not give are left as a visible [placeholder] for them to fill in.
"""

from __future__ import annotations

from app.schemas.integration import OutputType

_GREETING = {"en": "Hi,", "hinglish": "Hi,", "hi": "नमस्ते,"}
_CLOSING = {"en": "Best regards,\n[Your name]", "hinglish": "Regards,\n[Your name]", "hi": "धन्यवाद,\n[आपका नाम]"}


def subject_for(topic: str | None, outputs: list[OutputType], explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()[:200]
    if topic and topic.strip():
        return topic.strip()[:1].upper() + topic.strip()[1:200]
    if "youtube.video_reference" in outputs:
        return "Video: {{youtube.title}}"
    if "file.reference" in outputs:
        return "File: {{file.name}}"
    return "Quick note"


def body_for(topic: str | None, outputs: list[OutputType], lang: str = "en") -> str:
    lang = lang if lang in _GREETING else "en"
    lines = [_GREETING[lang], ""]
    if topic:
        lines.append({"hi": f"मैं {topic} के बारे में लिख रहा/रही हूँ."}.get(lang, f"I'm writing regarding {topic}."))
    if "youtube.video_reference" in outputs:
        lines.append({"hi": "यह वीडियो देखें:"}.get(lang, "Here is the video:"))
        lines.append("{{youtube.title}}")
        lines.append("{{youtube.video_url}}")
    if "file.reference" in outputs:
        lines.append({"hi": "फ़ाइल: {{file.name}} ({{file.size}})"}.get(lang, "File: {{file.name}} ({{file.size}})"))
    if len(lines) == 2:
        lines.append("[Write your message here]")
    lines += ["", _CLOSING[lang]]
    return "\n".join(lines)
