"""Operational Center + Site Requirements (V3)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from core.auth import get_current_user
from engines import operations_engine, memory_engine

router = APIRouter(prefix="/api", tags=["operational-center"])


@router.get("/operational-center")
async def operational_center(site_id: Optional[str] = None,
                             user: dict = Depends(get_current_user)):
    return await operations_engine.operational_center(site_id=site_id)


@router.get("/sites/{site_id}/requirements")
async def site_requirements(site_id: str, user: dict = Depends(get_current_user)):
    site = await memory_engine.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return await operations_engine.site_requirements(site_id)
