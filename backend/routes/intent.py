"""Intent & Orchestration routes — Phase 1. Deliberately thin: all
logic lives in services/intent_service.py.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user
from services import intent_service

router = APIRouter(prefix="/api", tags=["intent"])


class IntentRequest(BaseModel):
    text: str
    active_project_id: Optional[str] = None
    confirmed_project_id: Optional[str] = None


@router.post("/intent")
async def post_intent(req: IntentRequest, user: dict = Depends(get_current_user)):
    return await intent_service.handle_intent(
        req.text, user=user, active_project_id=req.active_project_id,
        confirmed_project_id=req.confirmed_project_id,
    )
