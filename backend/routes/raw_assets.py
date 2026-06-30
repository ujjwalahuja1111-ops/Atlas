"""Raw assets endpoint. Returns the asset record (with base64) for clients
that want to render audio/photo from a stored evidence reference.

Kept minimal for the pilot — JSON response so the existing fetch-with-Bearer
pattern works. A streaming /raw-assets/{id}/binary variant can be added later.
"""
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from engines import memory_engine

router = APIRouter(prefix="/api", tags=["assets"])


@router.get("/raw-assets/{asset_id}")
async def get_asset(asset_id: str, user: dict = Depends(get_current_user)):
    doc = await memory_engine.get_asset(asset_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Asset not found")
    return doc
