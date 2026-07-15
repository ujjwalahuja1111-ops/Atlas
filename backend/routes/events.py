"""Reality Engine HTTP surface.

Single unified POST /api/events accepts multipart (audio, photos, text, gps).
Returns the persisted event document in <300ms with ai_status="pending".

Corrections: POST /api/events/{id}/corrections — append-only linked record.
"""
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from core.auth import get_current_user
from engines import memory_engine, reality_engine, timeline_engine, operations_engine

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
    # Client Approval Workflow — purely a marker; never blocks the save.
    requires_client_approval: bool = Form(False),
    audio: Optional[UploadFile] = File(None),
    photos: List[UploadFile] = File(default_factory=list),
    user: dict = Depends(get_current_user),
):
    # FAC-04 — Final Authorization Model Freeze: "Client must never capture
    # events" is now enforced at the backend, not just by the frontend
    # hiding the Capture tab (VIEW_PERMS.client.showCapture=false). A
    # client account calling this endpoint directly was previously
    # unrestricted.
    if user.get("role") == "client":
        raise HTTPException(status_code=403, detail="Clients cannot capture events.")

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
        requires_client_approval=requires_client_approval,
    )
    return event


@router.get("/events/{event_id}")
async def get_event(event_id: str, user: dict = Depends(get_current_user)):
    item = await timeline_engine.single(event_id)
    if not item:
        raise HTTPException(status_code=404, detail="Event not found")
    return item


class RequestApprovalReq(BaseModel):
    message: Optional[str] = None


@router.post("/events/{event_id}/request-approval", status_code=201)
async def request_client_approval(event_id: str, req: RequestApprovalReq,
                                  user: dict = Depends(get_current_user)):
    """Client Approval Workflow — the ONE implementation both the
    'send immediately after capture' and 'send later from Event Details'
    frontend paths call. Creates a Client Approval Request LINKED to the
    original event — never duplicates the event or its media.

    Deliberately reuses, rather than reinvents, three things that
    already exist:
      * the operational_items `client_approval` category — already has
        full approve/reject/comment support (backend-enforced client
        permissions, the client dashboard's Pending Approvals card, and
        the correctly-gated op/[id].tsx screen) and is already read as
        approval evidence by the Construction Reasoning Engine's
        existing rules (e.g. client_communication.progress_update_due) —
        so linking the request this way exposes it to CRE with zero
        engine changes, exactly matching "integrate, do not extend."
      * `inherited_evidence_event_id` — the same event-linkage field the
        AI-unavailable fallback (Sprint 6.2) already uses; the timeline
        can resolve an event's approval status through it without a new
        field on the event itself.
      * an optional text message reuses operations_engine's comment
        mechanism — no new "message" concept to maintain.

    If a client_approval item is already open for this event (either
    send path, called twice, or a double-tap), returns the existing one
    rather than creating a duplicate.
    """
    if user.get("role") == "client":
        raise HTTPException(status_code=403, detail="Clients cannot request approvals.")
    event = await memory_engine.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    existing = await operations_engine.find_open_item_for_event(event_id, category="client_approval")
    if existing:
        return operations_engine.enrich(existing)

    text_preview = (event.get("text_input") or "").strip()
    title = f"Approval requested: {text_preview[:60]}" if text_preview else "Client approval requested"
    item = await operations_engine.create_item(
        actor=user, site_id=event["site_id"], category="client_approval",
        title=title[:120],
        description=req.message.strip() if req.message and req.message.strip() else "",
        origin_type="manual",
        inherited_evidence_event_id=event_id,
    )
    return operations_engine.enrich(item)


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

    Project Manager/management only. Idempotent unless force=true.
    """
    if user["role"] not in ("management", "project_manager"):
        raise HTTPException(status_code=403, detail="Only Project Managers/management can regenerate proposals")
    event = await memory_engine.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    from engines import intelligence_engine
    return await intelligence_engine.generate_proposals_for_event(event_id, force=force)
