"""Admin User Management routes (Sprint 4.1, extended Sprint 4.3, frozen FAC-04).

Deliberately a SEPARATE endpoint family from the existing GET /api/users
(routes/operational_items.py), which is a lightweight, unrestricted
assignee-picker used across Sprint 1-4 and left completely untouched here.
These routes are the admin workflow for the Sign Up / Pending Approval /
Identity & Access foundation: list pending/all users, approve/reject,
assign role, assign projects, activate/deactivate.

FAC-04 — Final Authorization Model Freeze: the separate "assign workspace"
endpoint that existed here (Sprint 4.3) is REMOVED. Workspace is now a
pure, deterministic function of role (see memory_engine.WORKSPACE_FOR_ROLE)
— assigning a role is now the only action an admin needs, and it can never
produce an inconsistent role/workspace combination, because there is no
longer a second, independent field to get out of sync.

Admin-only, mirroring the exact `_require_admin` pattern already
established in routes/knowledge.py — reusing that convention rather than
inventing a new one.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
from core.auth import get_current_user
from engines import memory_engine

router = APIRouter(prefix="/api/admin", tags=["admin-users"])

Role = Literal["management", "project_manager", "site_supervisor", "client"]


def _require_admin(user: dict) -> None:
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="User Management is admin-only")


class AssignRoleRequest(BaseModel):
    role: Role


class AssignProjectsRequest(BaseModel):
    project_ids: list[str] = []


class SetActiveRequest(BaseModel):
    is_active: bool


@router.get("/users")
async def list_admin_users(approval_status: Optional[str] = None, user: dict = Depends(get_current_user)):
    _require_admin(user)
    if approval_status and approval_status not in memory_engine.APPROVAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid approval_status. Must be one of {sorted(memory_engine.APPROVAL_STATUSES)}")
    return await memory_engine.list_users_admin(approval_status=approval_status)


@router.post("/users/{user_id}/approve")
async def approve_user(user_id: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    target = await memory_engine.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return await memory_engine.set_user_approval(user_id, "approved")


@router.post("/users/{user_id}/reject")
async def reject_user(user_id: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    target = await memory_engine.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return await memory_engine.set_user_approval(user_id, "rejected")


@router.post("/users/{user_id}/role")
async def assign_role(user_id: str, req: AssignRoleRequest, user: dict = Depends(get_current_user)):
    """Assigns both role AND (automatically, as a consequence — see
    memory_engine.set_user_role) the one correct workspace for that role.
    This is now the ONLY identity-shaping action an admin takes."""
    _require_admin(user)
    target = await memory_engine.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        return await memory_engine.set_user_role(user_id, req.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/users/{user_id}/projects")
async def assign_projects(user_id: str, req: AssignProjectsRequest, user: dict = Depends(get_current_user)):
    _require_admin(user)
    target = await memory_engine.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return await memory_engine.set_user_projects(user_id, req.project_ids)


@router.post("/users/{user_id}/active")
async def set_active(user_id: str, req: SetActiveRequest, user: dict = Depends(get_current_user)):
    _require_admin(user)
    target = await memory_engine.get_user(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user_id == user["id"] and not req.is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    return await memory_engine.set_user_active(user_id, req.is_active)
