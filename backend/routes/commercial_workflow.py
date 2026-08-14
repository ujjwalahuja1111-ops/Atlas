"""Commercial Workflow routes (PX-03 Phase 1). Deliberately thin — all
business logic lives in services/commercial_workflow_service.py.
"""
from fastapi import APIRouter, Depends
from core.auth import get_current_user
from services import commercial_workflow_service as svc

router = APIRouter(prefix="/api", tags=["commercial-workflow"])


@router.get("/projects/{project_id}/commercial/profitability-panel")
async def get_profitability_panel(project_id: str, user: dict = Depends(get_current_user)):
    return await svc.build_profitability_panel(project_id, user=user)


@router.get("/projects/{project_id}/commercial/billing-collections")
async def get_billing_collections(project_id: str, user: dict = Depends(get_current_user)):
    return await svc.build_billing_and_collections(project_id, user=user)


@router.get("/projects/{project_id}/commercial/health")
async def get_commercial_health(project_id: str, user: dict = Depends(get_current_user)):
    return await svc.commercial_health(project_id, user=user)


@router.get("/projects/{project_id}/commercial/cash-flow-timeline")
async def get_cash_flow_timeline(project_id: str, user: dict = Depends(get_current_user)):
    return await svc.cash_flow_timeline(project_id, user=user)
