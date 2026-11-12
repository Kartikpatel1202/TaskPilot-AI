from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.schemas.approval import ApprovalRequest, ApprovalResponse, CreateApprovalDecisionRequest
from app.schemas.common import APIError
from app.services.approval_service import ApprovalService

from .deps import get_approval_service

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post(
    "/{approval_id}/decision",
    response_model=ApprovalResponse,
    responses={404: {"model": APIError}, 409: {"model": APIError}, 410: {"model": APIError}},
    summary="Record an immutable human decision (records only — triggers no real action in Phase 1)",
)
async def decide(
    approval_id: UUID,
    body: CreateApprovalDecisionRequest,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    approval = await service.decide(approval_id, body.decision)
    assert approval.decision is not None and approval.resolved_at is not None
    return ApprovalResponse(
        approval_id=approval.approval_id,
        decision=approval.decision,
        status=approval.status,
        resolved_at=approval.resolved_at,
    )


@router.get("/{approval_id}", response_model=ApprovalRequest, responses={404: {"model": APIError}})
async def get_approval(
    approval_id: UUID, service: ApprovalService = Depends(get_approval_service)
) -> ApprovalRequest:
    return service.get(approval_id)
