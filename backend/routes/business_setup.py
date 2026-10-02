"""AI Business Setup routes (Step 2 of the locked market-ready sequence).

BUSINESS DESCRIPTION -> AI RECOMMENDATION (draft) -> human review -> APPROVE.
Management-only throughout, mirroring routes/admin_system.py's own exact
_require_admin pattern - a business configuration is a system-level
decision, not a per-project one (Atlas is single-tenant per deployment;
see business_setup_engine.py's own module docstring for the trace that
established this).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import get_current_user
from engines import business_setup_engine as bse

router = APIRouter(prefix="/api/business-setup", tags=["business-setup"])


def _require_admin(user: dict) -> None:
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="Business setup is admin-only")


class AnalyzeRequest(BaseModel):
    description: str


@router.post("/analyze")
async def analyze(req: AnalyzeRequest, user: dict = Depends(get_current_user)):
    """Business description -> AI recommendation, saved as a DRAFT only.
    Never activates anything; the draft is not consumed by any other
    part of Atlas until /approve is called."""
    _require_admin(user)
    if not req.description.strip():
        raise HTTPException(status_code=400, detail="Please describe your business.")
    recommendation = await bse.generate_recommendation(req.description.strip())
    if recommendation is None:
        raise HTTPException(status_code=503, detail=(
            "Atlas couldn't analyze that description right now. Please try again, "
            "or describe your business a little differently."))
    try:
        doc = await bse.save_draft_recommendation(
            description=req.description.strip(), recommendation=recommendation, actor=user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return doc


@router.get("")
async def get_current(user: dict = Depends(get_current_user)):
    """Retrieve the current draft or approved configuration, if any."""
    _require_admin(user)
    doc = await bse.get_configuration()
    if not doc:
        return {"status": "none"}
    return doc


class ApproveRequest(BaseModel):
    capability_overrides: Optional[dict[str, str]] = None
    role_overrides: Optional[list[str]] = None
    client_access_override: Optional[bool] = None


@router.post("/approve")
async def approve(req: ApproveRequest, user: dict = Depends(get_current_user)):
    """Human approval - the ONLY way a configuration becomes active.
    Does not provision users, activate engines, or change navigation;
    that is Step 3's own job, consuming this approved document."""
    _require_admin(user)
    try:
        doc = await bse.approve_configuration(
            actor=user, capability_overrides=req.capability_overrides,
            role_overrides=req.role_overrides, client_access_override=req.client_access_override)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return doc
