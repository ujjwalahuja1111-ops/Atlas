"""Inbox Intelligence routes (PX-02 Phase 4). Deliberately thin — all
business logic lives in services/inbox_intelligence_service.py.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from core.auth import get_current_user
from services import inbox_intelligence_service as svc

router = APIRouter(prefix="/api", tags=["inbox-intelligence"])


@router.get("/inbox/coordination")
async def get_coordination_inbox(project_id: Optional[str] = Query(None),
                                 user: dict = Depends(get_current_user)):
    return await svc.build_coordination_inbox(user, project_id=project_id)


@router.get("/inbox/daily-digest")
async def get_daily_digest(user: dict = Depends(get_current_user)):
    return await svc.daily_coordination_digest(user)


@router.get("/inbox/management-digest")
async def get_management_digest(user: dict = Depends(get_current_user)):
    return await svc.management_attention_digest(user)
