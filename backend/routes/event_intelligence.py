"""Event Intelligence routes — the freehand product decision. Deliberately
thin: all composition logic lives in services/event_intelligence_service.py.
"""
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from services import event_intelligence_service as svc
from engines.commercial_engine import CommercialError

router = APIRouter(prefix="/api", tags=["event-intelligence"])


@router.get("/events/{event_id}/understanding")
async def get_event_understanding(event_id: str, user: dict = Depends(get_current_user)):
    try:
        result = await svc.build_event_understanding(event_id, user=user)
    except CommercialError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found.")
    return result
