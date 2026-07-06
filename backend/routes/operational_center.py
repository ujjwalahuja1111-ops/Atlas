"""Operational Center + Site Requirements (V3)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from core.auth import get_current_user
from engines import operations_engine, memory_engine

router = APIRouter(prefix="/api", tags=["operational-center"])


@router.get("/operational-center")
async def operational_center(site_id: Optional[str] = None,
                             project_id: Optional[str] = None,
                             user: dict = Depends(get_current_user)):
    center = await operations_engine.operational_center(site_id=site_id)
    # Optional project scope — apply after bucketing (small lists, fine to filter in-memory).
    if project_id:
        for key in ("open", "overdue", "high_priority", "awaiting_verification",
                    "recently_completed", "recently_updated"):
            center[key] = [i for i in center.get(key, []) if i.get("project_id") == project_id]
        center["counts"] = {
            "open": len(center["open"]),
            "overdue": len(center["overdue"]),
            "high_priority": len(center["high_priority"]),
            "awaiting_verification": len(center["awaiting_verification"]),
            "blocked": sum(1 for i in center["open"] if i.get("blocker")),
        }
    # Denormalise names on every list (single bulk lookup — cheap).
    for key in ("open", "overdue", "high_priority", "awaiting_verification",
                "recently_completed", "recently_updated"):
        await operations_engine.attach_names(center.get(key, []))
    return center


@router.get("/sites/{site_id}/requirements")
async def site_requirements(site_id: str, user: dict = Depends(get_current_user)):
    site = await memory_engine.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return await operations_engine.site_requirements(site_id)
