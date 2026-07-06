"""AI Proposal routes (V3) — propose / accept / reject."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user
from engines import operations_engine

router = APIRouter(prefix="/api", tags=["ai-proposals"])


@router.get("/ai-proposals")
async def list_proposals(event_id: Optional[str] = None,
                         site_id: Optional[str] = None,
                         project_id: Optional[str] = None,
                         status: Optional[str] = None,
                         user: dict = Depends(get_current_user)):
    proposals = await operations_engine.list_ai_proposals(
        event_id=event_id, site_id=site_id, status=status,
    )
    await operations_engine.attach_names(proposals)
    if project_id:
        proposals = [p for p in proposals if p.get("project_id") == project_id]
    return proposals


class AcceptReq(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    required_by: Optional[str] = None
    assigned_to_user_id: Optional[str] = None


@router.post("/ai-proposals/{proposal_id}/accept")
async def accept(proposal_id: str, req: AcceptReq, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Only coordinators/management can accept proposals")
    edits = {k: v for k, v in req.model_dump().items() if v is not None and k != "assigned_to_user_id"}
    try:
        item = await operations_engine.accept_ai_proposal(
            proposal_id=proposal_id, actor=user, edits=edits if edits else None,
        )
        # Optional one-tap assign during accept
        if req.assigned_to_user_id:
            from core.db import db
            assignee = await db.users.find_one({"id": req.assigned_to_user_id}, {"_id": 0})
            if assignee:
                item = await operations_engine.assign_item(
                    item_id=item["id"], assignee=assignee, actor=user,
                )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class RejectReq(BaseModel):
    reason: Optional[str] = None


@router.post("/ai-proposals/{proposal_id}/reject")
async def reject(proposal_id: str, req: RejectReq, user: dict = Depends(get_current_user)):
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Only coordinators/management can reject proposals")
    try:
        return await operations_engine.reject_ai_proposal(
            proposal_id=proposal_id, actor=user, reason=req.reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
