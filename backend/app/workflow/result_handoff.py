"""Typed result handoff between workflow steps (Phase 5).

Only small, typed, OBSERVED values move between steps (a video's title/URL/channel, a file's
name/size/SHA-256) — never pages, HTML, cookies, file paths or email bodies. A consumer whose
input was not produced fails cleanly instead of sending a half-filled draft.
"""

from __future__ import annotations

import re
from uuid import UUID

from app.integrations.files.downloader import size_label
from app.schemas.files import DownloadedFile
from app.schemas.workflow import WorkflowOutput
from app.schemas.youtube import YouTubeVideo

PLACEHOLDER = re.compile(r"\{\{\s*(youtube|file)\.(title|video_url|channel|name|size|sha256)\s*\}\}")
_PREFIX_TYPE = {"youtube": "youtube.video_reference", "file": "file.reference"}


class MissingOutputError(ValueError):
    def __init__(self, output_type: str) -> None:
        self.output_type = output_type
        super().__init__(f"The required result ({output_type}) is not available.")


def produces(action: object) -> list[str]:
    kind = getattr(action, "type", "")
    if kind == "youtube_search" and getattr(action, "select", False):
        return ["youtube.video_reference"]
    return {
        "youtube_play": ["youtube.video_reference"],
        "file_download": ["file.reference"],
        "gmail_create_draft": ["gmail.draft_reference"],
        "calendar_create_event": ["calendar.event_reference"],
    }.get(kind, [])


def consumes(action: object) -> list[str]:
    if getattr(action, "type", "") == "youtube_play" and getattr(action, "video_reference", "") == "selected_from_search":
        return ["youtube.video_reference"]
    return list(getattr(action, "insert_outputs", []) or [])


def youtube_output(step_id: UUID, video: YouTubeVideo) -> WorkflowOutput:
    return WorkflowOutput(type="youtube.video_reference", step_id=step_id, data={
        "title": video.title[:300], "video_url": video.video_url, "channel": video.channel_name or "",
    })


def file_output(step_id: UUID, file: DownloadedFile) -> WorkflowOutput:
    return WorkflowOutput(type="file.reference", step_id=step_id, data={
        "name": file.original_name, "size": size_label(file.size_bytes), "sha256": file.sha256, "file_id": str(file.file_id),
    })


def resolve(text: str, outputs: dict[str, WorkflowOutput]) -> str:
    def sub(m: re.Match[str]) -> str:
        output = outputs.get(_PREFIX_TYPE[m.group(1)])
        if output is None or m.group(2) not in output.data:
            raise MissingOutputError(_PREFIX_TYPE[m.group(1)])
        return output.data[m.group(2)]

    return PLACEHOLDER.sub(sub, text)


def placeholders_in(text: str) -> set[str]:
    return {_PREFIX_TYPE[m.group(1)] for m in PLACEHOLDER.finditer(text or "")}
