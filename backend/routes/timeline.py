"""Timeline routes — chronological projection of construction history."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from core.auth import get_current_user
from engines import timeline_engine, memory_engine

router = APIRouter(prefix="/api", tags=["timeline"])


@router.get("/timeline")
async def timeline(site_id: str, include: Optional[str] = None,
                   user: dict = Depends(get_current_user)):
    site = await memory_engine.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    include_ops = (include == "ops")
    return await timeline_engine.for_site(site_id, include_ops=include_ops)
