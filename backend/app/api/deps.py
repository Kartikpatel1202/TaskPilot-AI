"""FastAPI dependencies resolving services from the application container."""

from __future__ import annotations

from fastapi import Request

from app.container import Container
from app.services.approval_service import ApprovalService
from app.services.browser_service import BrowserService
from app.services.commerce_service import CommerceService
from app.services.execution_service import ExecutionService
from app.services.planning_service import PlanningService
from app.services.task_service import TaskService


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def get_task_service(request: Request) -> TaskService:
    return get_container(request).tasks


def get_approval_service(request: Request) -> ApprovalService:
    return get_container(request).approvals


def get_planning_service(request: Request) -> PlanningService:
    return get_container(request).planning


def get_execution_service(request: Request) -> ExecutionService:
    return get_container(request).execution_service


def get_browser_service(request: Request) -> BrowserService:
    return get_container(request).browser_service


def get_commerce_service(request: Request) -> CommerceService:
    return get_container(request).commerce_service
