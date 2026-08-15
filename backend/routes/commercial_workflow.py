"""Commercial Workflow routes (PX-03 Phase 1, extended PX-03 Phase 2).
Deliberately thin — all business logic lives in
services/commercial_workflow_service.py.

PX-03 Phase 2 — CommercialPermissionError maps to 403, matching this
task's own explicit "a safe client-shaped response, OR a permission
denial" instruction and the exact HTTPException convention every
other commercial route already uses (_require_write_access in
routes/commercial.py).
"""
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from services import commercial_workflow_service as svc

router = APIRouter(prefix="/api", tags=["commercial-workflow"])


def _handle(e: Exception):
    if isinstance(e, svc.CommercialPermissionError):
        raise HTTPException(status_code=403, detail=str(e))
    raise HTTPException(status_code=400, detail=str(e))


@router.get("/projects/{project_id}/commercial/profitability-panel")
async def get_profitability_panel(project_id: str, user: dict = Depends(get_current_user)):
    try:
        return await svc.build_profitability_panel(project_id, user=user)
    except svc.ce.CommercialError as e:
        _handle(e)


@router.get("/projects/{project_id}/commercial/billing-collections")
async def get_billing_collections(project_id: str, user: dict = Depends(get_current_user)):
    try:
        return await svc.build_billing_and_collections(project_id, user=user)
    except svc.ce.CommercialError as e:
        _handle(e)


@router.get("/projects/{project_id}/commercial/health")
async def get_commercial_health(project_id: str, user: dict = Depends(get_current_user)):
    try:
        return await svc.commercial_health(project_id, user=user)
    except svc.ce.CommercialError as e:
        _handle(e)


@router.get("/projects/{project_id}/commercial/cash-flow-timeline")
async def get_cash_flow_timeline(project_id: str, user: dict = Depends(get_current_user)):
    try:
        return await svc.cash_flow_timeline(project_id, user=user)
    except svc.ce.CommercialError as e:
        _handle(e)


@router.get("/projects/{project_id}/commercial/client-safe-bill-summary")
async def get_client_safe_bill_summary(project_id: str, user: dict = Depends(get_current_user)):
    """PX-03 Phase 2 Section 6 — the dedicated client-safe endpoint,
    a genuinely different response shape from profitability-panel,
    not the same data with fields hidden client-side."""
    try:
        return await svc.build_client_safe_bill_summary(project_id, user=user)
    except svc.ce.CommercialError as e:
        _handle(e)
