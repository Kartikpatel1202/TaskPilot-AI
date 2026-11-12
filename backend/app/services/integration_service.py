"""REST-facing integration operations (thin layer over IntegrationManager + FileStore)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from app.integrations.capability_registry import CapabilityRegistry
from app.integrations.files.storage import FileRequestError, FileStore
from app.integrations.integration_manager import IntegrationManager, IntegrationRequestError
from app.schemas.calendar import CalendarEventReview
from app.schemas.files import DownloadedFile
from app.schemas.integration import CapabilityDefinition, DomainStatusEntry
from app.schemas.workflow import WorkflowState


class IntegrationService:
    def __init__(self, manager: IntegrationManager | None, capabilities: CapabilityRegistry, files: FileStore | None) -> None:
        self._manager = manager
        self.capabilities = capabilities
        self._files = files

    @property
    def manager(self) -> IntegrationManager:
        if self._manager is None:
            raise IntegrationRequestError("CAPABILITY_DISABLED", "Multi-domain integrations are disabled on this server.", 503)
        return self._manager

    @property
    def files(self) -> FileStore:
        if self._files is None:
            raise IntegrationRequestError("FILE_DOWNLOAD_DISABLED", "Safe downloads are disabled on this server.", 503)
        return self._files

    # ---------------------------------------------------------------- integrations

    def capability_list(self) -> list[CapabilityDefinition]:
        return self.capabilities.all()

    def statuses(self, session_id: UUID | None) -> list[DomainStatusEntry]:
        return self.manager.statuses(session_id)

    async def workflow(self, task_id: UUID, session_id: UUID | None) -> WorkflowState:
        try:
            return self.manager.workflow(task_id, session_id)
        except IntegrationRequestError as exc:
            if exc.code not in ("PLAN_NOT_FOUND", "WORKFLOW_NOT_FOUND"):
                raise
            stored = await self.manager.stored_workflow(task_id, session_id)
            if stored is None:
                raise
            return stored

    def youtube_results(self, task_id: UUID, session_id: UUID | None) -> dict[str, Any]:
        return self.manager.youtube_results(task_id, session_id)

    def answer_choice(self, task_id: UUID, session_id: UUID, choice_id: UUID, option_id: str | None) -> None:
        self.manager.answer_choice(task_id, session_id, choice_id, option_id)

    def gmail_draft(self, task_id: UUID, session_id: UUID | None) -> dict[str, Any]:
        return self.manager.gmail_draft(task_id, session_id)

    async def update_draft(self, task_id: UUID, session_id: UUID, subject: str, body: str) -> dict[str, Any]:
        return await self.manager.update_draft(task_id, session_id, subject, body)

    def calendar_review(self, task_id: UUID, session_id: UUID | None) -> CalendarEventReview:
        return self.manager.calendar_review(task_id, session_id)

    # ---------------------------------------------------------------- files

    def list_files(self, session_id: UUID) -> list[DownloadedFile]:
        return self.files.list(session_id)

    def get_file(self, file_id: UUID, session_id: UUID) -> DownloadedFile:
        try:
            return self.files.get(file_id, session_id).meta
        except FileRequestError as exc:
            raise IntegrationRequestError(exc.code, exc.message, exc.status_code) from exc

    def file_path(self, file_id: UUID, session_id: UUID) -> tuple[DownloadedFile, Path]:
        try:
            stored = self.files.get(file_id, session_id)
        except FileRequestError as exc:
            raise IntegrationRequestError(exc.code, exc.message, exc.status_code) from exc
        return stored.meta, stored.path

    def delete_file(self, file_id: UUID, session_id: UUID, confirm: bool) -> DownloadedFile:
        if not confirm:
            raise IntegrationRequestError("CONFIRMATION_REQUIRED", "Deleting a file needs explicit confirmation (confirm=true).", 400)
        try:
            meta = self.files.delete(file_id, session_id)
        except FileRequestError as exc:
            raise IntegrationRequestError(exc.code, exc.message, exc.status_code) from exc
        return meta
