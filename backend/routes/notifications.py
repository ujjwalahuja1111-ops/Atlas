"""Notification Inbox routes (PX-01A P2-09). Deliberately thin — all
business logic lives in engines/notification_engine.py.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from core.auth import get_current_user
from engines import notification_engine as ne

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications")
async def list_notifications(category: Optional[str] = Query(None), unread_only: bool = False,
                             user: dict = Depends(get_current_user)):
    return await ne.list_notifications(user["id"], category=category, unread_only=unread_only)


@router.get("/notifications/unread-count")
async def get_unread_count(user: dict = Depends(get_current_user)):
    return {"unread_count": await ne.unread_count(user["id"])}


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: str, user: dict = Depends(get_current_user)):
    return await ne.mark_read(notification_id, user_id=user["id"])


@router.post("/notifications/read-all")
async def mark_all_read(category: Optional[str] = Query(None), user: dict = Depends(get_current_user)):
    count = await ne.mark_all_read(user["id"], category=category)
    return {"marked_read": count}
