"""Phase 5 integration endpoints: capabilities, status, workflows, YouTube results, Gmail drafts,
Calendar review and safe file storage.

Nothing here sends email, creates calendar events or downloads files: those happen only inside
a running plan (calendar creation after the exact-event approval via POST /approvals/{id}/decision).
Every task/file endpoint checks the owning session. File paths are never returned.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.integrations.integration_manager import IntegrationRequestError
from app.schemas.calendar import CalendarEventReview
from app.schemas.common import APIError
from app.schemas.files import DownloadedFile, FileDeleteRequest
from app.schemas.integration import CapabilityDefinition, ChoiceAnswerRequest, DomainStatusEntry
from app.schemas.workflow import WorkflowState
from app.services.integration_service import IntegrationService

router = APIRouter(tags=["integrations"])
ERRORS = {400: {"model": APIError}, 403: {"model": APIError}, 404: {"model": APIError}, 409: {"model": APIError}, 503: {"model": APIError}}


def get_integration_service(request: Request) -> IntegrationService:
    return get_container(request).integration_service  # type: ignore[no-any-return]


class DraftEditRequest(BaseModel):
    session_id: UUID
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12_000)


@router.get("/integrations/capabilities", response_model=list[CapabilityDefinition])
async def capabilities(service: IntegrationService = Depends(get_integration_service)) -> list[CapabilityDefinition]:
    return service.capability_list()


@router.get("/integrations/status", response_model=list[DomainStatusEntry], responses=ERRORS)
async def integration_status(session_id: UUID | None = Query(default=None),
                             service: IntegrationService = Depends(get_integration_service)) -> list[DomainStatusEntry]:
    return service.statuses(session_id)


@router.get("/tasks/{task_id}/workflow", response_model=WorkflowState, responses=ERRORS)
async def workflow(task_id: UUID, session_id: UUID | None = Query(default=None),
                   service: IntegrationService = Depends(get_integration_service)) -> WorkflowState:
    return await service.workflow(task_id, session_id)


@router.post("/tasks/{task_id}/workflow/choice", status_code=status.HTTP_202_ACCEPTED, responses=ERRORS)
async def answer_choice(task_id: UUID, body: ChoiceAnswerRequest, service: IntegrationService = Depends(get_integration_service)) -> dict[str, Any]:
    """Answer a pending choice (which video / which file link). option_id null = skip."""
    service.answer_choice(task_id, body.session_id, body.choice_id, body.option_id)
    return {"accepted": True, "choice_id": str(body.choice_id)}


@router.get("/tasks/{task_id}/youtube/results", responses=ERRORS)
async def youtube_results(task_id: UUID, session_id: UUID | None = Query(default=None),
                          service: IntegrationService = Depends(get_integration_service)) -> dict[str, Any]:
    return service.youtube_results(task_id, session_id)


@router.get("/tasks/{task_id}/gmail/draft", responses=ERRORS)
async def gmail_draft(task_id: UUID, session_id: UUID | None = Query(default=None),
                      service: IntegrationService = Depends(get_integration_service)) -> dict[str, Any]:
    """The draft for this task (planned or saved). Drafts are never sent by TaskPilot."""
    return service.gmail_draft(task_id, session_id)


@router.put("/tasks/{task_id}/gmail/draft", responses=ERRORS)
async def edit_gmail_draft(task_id: UUID, body: DraftEditRequest, service: IntegrationService = Depends(get_integration_service)) -> dict[str, Any]:
    """Edit the planned draft's subject/body before Run Plan (only while the task is PLANNED)."""
    return await service.update_draft(task_id, body.session_id, body.subject, body.body)


@router.get("/tasks/{task_id}/calendar/review", response_model=CalendarEventReview, responses=ERRORS)
async def calendar_review(task_id: UUID, session_id: UUID | None = Query(default=None),
                          service: IntegrationService = Depends(get_integration_service)) -> CalendarEventReview:
    return service.calendar_review(task_id, session_id)


@router.get("/tasks/{task_id}/calendar/status", responses=ERRORS)
async def calendar_status(task_id: UUID, session_id: UUID | None = Query(default=None),
                          service: IntegrationService = Depends(get_integration_service)) -> dict[str, Any]:
    review = service.calendar_review(task_id, session_id)
    return {"status": review.status, "message": review.message, "verified_reference": review.verified_reference,
            "approval_id": review.approval_id, "event_hash": review.event_hash}


@router.get("/files", response_model=list[DownloadedFile], responses=ERRORS)
async def list_files(session_id: UUID = Query(...), service: IntegrationService = Depends(get_integration_service)) -> list[DownloadedFile]:
    return service.list_files(session_id)


@router.get("/files/{file_id}", response_model=DownloadedFile, responses=ERRORS)
async def file_metadata(file_id: UUID, session_id: UUID = Query(...), service: IntegrationService = Depends(get_integration_service)) -> DownloadedFile:
    return service.get_file(file_id, session_id)


@router.get("/files/{file_id}/download", responses=ERRORS)
async def download_file(file_id: UUID, request: Request, session_id: UUID = Query(...),
                        service: IntegrationService = Depends(get_integration_service)) -> FileResponse:
    """Serve a validated file to its owning session as an attachment (never rendered inline)."""
    meta, path = service.file_path(file_id, session_id)
    await request.app.state.container.audit.record("file.download_served", outcome="SUCCESS", session_id=session_id,
                                                   resource_type="file", resource_id=meta.file_id)
    return FileResponse(path, media_type=meta.mime_type, filename=meta.original_name, headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "Content-Security-Policy": "sandbox; default-src 'none'"})


@router.delete("/files/{file_id}", responses=ERRORS)
async def delete_file(file_id: UUID, body: FileDeleteRequest, request: Request,
                      service: IntegrationService = Depends(get_integration_service)) -> dict[str, Any]:
    """Permanently delete one downloaded file (explicit confirm=true required; owner session only)."""
    meta = service.delete_file(file_id, body.session_id, body.confirm)
    container = request.app.state.container
    if container.persistence is not None:
        await container.persistence.best_effort(container.persistence.files.mark_deleted(meta.file_id), "file.delete")
    await container.audit.record("file.delete", outcome="SUCCESS", session_id=body.session_id, resource_type="file", resource_id=meta.file_id)
    return {"deleted": True, "file_id": str(meta.file_id), "name": meta.original_name}


__all__ = ["router", "IntegrationRequestError"]
