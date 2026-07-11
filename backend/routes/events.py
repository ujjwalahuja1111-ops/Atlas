"""Reality Engine HTTP surface.

Single unified POST /api/events accepts multipart (audio, photos, text, gps).
Returns the persisted event document in <300ms with ai_status="pending".

Corrections: POST /api/events/{id}/corrections — append-only linked record.
"""
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from core.auth import get_current_user
from engines import memory_engine, reality_engine, timeline_engine

router = APIRouter(prefix="/api", tags=["events"])


@router.post("/events", status_code=201)
async def create_event(
    site_id: str = Form(...),
    text: Optional[str] = Form(None),
    gps: Optional[str] = Form(None),
    client_created_at: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    # Sprint 6.1 — reserved, optional. No current capture UI sets this;
    # the field exists so a future capture flow (or AI post-processing)
    # can associate an event with a specific Construction Workflow
    # activity without a schema change then.
    activity_id: Optional[str] = Form(None),
    audio: Optional[UploadFile] = File(None),
    photos: List[UploadFile] = File(default_factory=list),
    user: dict = Depends(get_current_user),
):
    site = await memory_engine.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # At least one of audio/photos/text required
    if (audio is None) and (not photos) and (not text or not text.strip()):
        raise HTTPException(status_code=400, detail="Provide audio, photo(s), or text")

    event = await reality_engine.capture(
        site_id=site_id,
        project_id=site["project_id"],
        user=user,
        text_input=text,
        audio_file=audio,
        photo_files=photos or [],
        gps_json=gps,
        client_created_at=client_created_at,
        app_version=app_version,
        activity_id=activity_id,
    )
    return event


@router.get("/events/{event_id}")
async def get_event(event_id: str, user: dict = Depends(get_current_user)):
    item = await timeline_engine.single(event_id)
    if not item:
        raise HTTPException(status_code=404, detail="Event not found")
    return item


class CorrectionCreate(BaseModel):
    note: str
    corrected_field: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None


@router.post("/events/{event_id}/corrections", status_code=201)
async def add_correction(
    event_id: str,
    req: CorrectionCreate,
    user: dict = Depends(get_current_user),
):
    event = await memory_engine.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return await memory_engine.insert_correction(
        original_event_id=event_id,
        corrected_by=user,
        payload=req.model_dump(),
    )


@router.post("/events/{event_id}/regenerate-proposals")
async def regenerate_proposals(event_id: str, force: bool = False,
                               user: dict = Depends(get_current_user)):
    """Replay proposal generation off the canonical ai_analyses doc.

    Coordinator/management only. Idempotent unless force=true.
    """
    if user["role"] == "supervisor":
        raise HTTPException(status_code=403, detail="Only coordinators/management can regenerate proposals")
    event = await memory_engine.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    from engines import intelligence_engine
    return await intelligence_engine.generate_proposals_for_event(event_id, force=force)
