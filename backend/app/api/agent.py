from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.schemas.agent import AgentStatusResponse
from app.services.planning_service import PlanningService

from .deps import get_planning_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/status", response_model=AgentStatusResponse, summary="Kamlesh Bhai's planner status (no secrets)")
async def agent_status(
    probe: bool = Query(
        default=False,
        description="Also run a cheap provider reachability check (model metadata lookup, no generation).",
    ),
    planning: PlanningService = Depends(get_planning_service),
) -> AgentStatusResponse:
    return await planning.agent_status(probe=probe)
