"""AI Engine / Role Configuration routes (Step 3 of the locked
market-ready sequence). Management-only throughout, matching routes/
business_setup.py's own exact pattern - provisioning who gets access to
Atlas is a system-level decision, not a per-project one.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import get_current_user
from engines import provisioning_engine as pe

router = APIRouter(prefix="/api/provisioning", tags=["provisioning"])


def _require_admin(user: dict) -> None:
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="Provisioning is admin-only")


@router.get("/status")
async def workspace_status(user: dict = Depends(get_current_user)):
    _require_admin(user)
    return await pe.get_workspace_status()


@router.get("/role-slots")
async def role_slots(user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        return await pe.get_required_role_slots()
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


class ProvisionUserRequest(BaseModel):
    phone: str
    name: str
    role: str


@router.post("/users")
async def provision_user(req: ProvisionUserRequest, user: dict = Depends(get_current_user)):
    """Creates ONE real, already-approved account for a role the
    approved configuration actually requires. Never bulk-creates, never
    invents a person - one explicit admin action per real human."""
    _require_admin(user)
    try:
        return await pe.provision_user(actor=user, phone=req.phone, name=req.name, role=req.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
