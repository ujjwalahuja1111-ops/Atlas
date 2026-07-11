"""Operational Items routes (V3)."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, Literal
from core.auth import get_current_user
from engines import operations_engine, memory_engine

router = APIRouter(prefix="/api", tags=["operations"])


def _forbid_client(user: dict, action: str = "perform this action") -> None:
    """Sprint 6.2 Client Permissions. Defense-in-depth: the frontend
    (app/op/[id].tsx) already hides these controls for the client
    workspace, but a client's backend `role` is `coordinator` — the same
    role a Project Manager has — so nothing at the API layer previously
    stopped a client account from calling these endpoints directly.
    `workspace` (Sprint 4.3) is the only reliable signal that
    distinguishes a client from a PM at the backend, so that is what
    this checks, not `role`. Clients may still transition a
    client_approval item to fulfilled/cancelled (approve/reject) and add
    comments — see the `transition` and `comment` routes below, which do
    NOT call this guard.
    """
    if user.get("workspace") == "client":
        raise HTTPException(status_code=403, detail=f"Clients cannot {action}.")


class CreateItem(BaseModel):
    site_id: str
    category: str
    title: str
    description: str = ""
    priority: Literal["low", "normal", "high", "critical"] = "normal"
    origin_type: str = "manual"
    origin_reference_id: Optional[str] = None
    inherited_evidence_event_id: Optional[str] = None
    required_by: Optional[str] = None
    assigned_to_user_id: Optional[str] = None


@router.post("/operational-items", status_code=201)
async def create_item(req: CreateItem, user: dict = Depends(get_current_user)):
    _forbid_client(user, "create operational items")
    assignee = None
    if req.assigned_to_user_id:
        assignee = await memory_engine.db.users.find_one({"id": req.assigned_to_user_id}, {"_id": 0}) \
            if hasattr(memory_engine, "db") else None
    try:
        item = await operations_engine.create_item(
            actor=user,
            site_id=req.site_id,
            category=req.category,
            title=req.title,
            description=req.description,
            priority=req.priority,
            origin_type=req.origin_type if user["role"] == "supervisor" else (
                req.origin_type if req.origin_type in operations_engine.ORIGIN_TYPES else user["role"]
            ),
            origin_reference_id=req.origin_reference_id,
            inherited_evidence_event_id=req.inherited_evidence_event_id,
            required_by=req.required_by,
            assigned_to_user=assignee,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/operational-items")
async def list_items(site_id: Optional[str] = None,
                     project_id: Optional[str] = None,
                     status: Optional[str] = None,
                     priority: Optional[str] = None,
                     category: Optional[str] = None,
                     assigned_to_me: bool = False,
                     user: dict = Depends(get_current_user)):
    items = await operations_engine.list_items(
        site_id=site_id, status=status, priority=priority, category=category,
        assigned_to_user_id=user["id"] if assigned_to_me else None,
    )
    if project_id:
        items = [i for i in items if i.get("project_id") == project_id]
    items = [operations_engine.enrich(i) for i in items]
    await operations_engine.attach_names(items)
    return items


@router.get("/operational-items/{item_id}")
async def get_item(item_id: str, user: dict = Depends(get_current_user)):
    item = await operations_engine.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    events = await operations_engine.list_events_for_item(item_id)
    # Inherited evidence — pull originating Construction Event if any
    inherited = None
    if item.get("inherited_evidence_event_id"):
        from engines import timeline_engine
        inherited = await timeline_engine.single(item["inherited_evidence_event_id"])
    enriched = operations_engine.enrich(item)
    await operations_engine.attach_names_single(enriched)
    return {"item": enriched, "history": events, "evidence": inherited}


class TransitionReq(BaseModel):
    to_status: str
    note: Optional[str] = None


@router.post("/operational-items/{item_id}/transition")
async def transition(item_id: str, req: TransitionReq, user: dict = Depends(get_current_user)):
    # Sprint 6.2 Client Permissions: a client may approve (-> fulfilled) or
    # reject (-> cancelled) a client_approval item — nothing else. Every
    # other transition (assignment lifecycle, closing, reopening, etc.) on
    # any category is an operational action, not a client one.
    if user.get("workspace") == "client":
        item = await operations_engine.get_item(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        if item["category"] != "client_approval" or req.to_status not in ("fulfilled", "cancelled"):
            raise HTTPException(status_code=403, detail="Clients can only approve or reject client approval items.")
    try:
        item = await operations_engine.transition_status(
            item_id=item_id, to_status=req.to_status, actor=user, note=req.note,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class AssignReq(BaseModel):
    assigned_to_user_id: str
    note: Optional[str] = None


@router.post("/operational-items/{item_id}/assign")
async def assign(item_id: str, req: AssignReq, user: dict = Depends(get_current_user)):
    _forbid_client(user, "assign or reassign work")
    from core.db import db
    assignee = await db.users.find_one({"id": req.assigned_to_user_id}, {"_id": 0})
    if not assignee:
        raise HTTPException(status_code=404, detail="Assignee not found")
    try:
        item = await operations_engine.assign_item(
            item_id=item_id, assignee=assignee, actor=user, note=req.note,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CommentReq(BaseModel):
    text: str


@router.post("/operational-items/{item_id}/comments", status_code=201)
async def comment(item_id: str, req: CommentReq, user: dict = Depends(get_current_user)):
    try:
        item = await operations_engine.add_comment(item_id=item_id, actor=user, text=req.text)
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class BlockerReq(BaseModel):
    category: str
    note: Optional[str] = None


@router.post("/operational-items/{item_id}/blocker")
async def set_blocker(item_id: str, req: BlockerReq, user: dict = Depends(get_current_user)):
    _forbid_client(user, "set blockers")
    try:
        item = await operations_engine.set_blocker(
            item_id=item_id, actor=user, category=req.category, note=req.note,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/operational-items/{item_id}/blocker")
async def clear_blocker(item_id: str, user: dict = Depends(get_current_user)):
    _forbid_client(user, "clear blockers")
    try:
        item = await operations_engine.clear_blocker(item_id=item_id, actor=user)
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class DueReq(BaseModel):
    required_by: str


@router.post("/operational-items/{item_id}/due")
async def set_due(item_id: str, req: DueReq, user: dict = Depends(get_current_user)):
    _forbid_client(user, "set due dates")
    try:
        item = await operations_engine.set_due(
            item_id=item_id, actor=user, required_by=req.required_by,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class EscalateReq(BaseModel):
    reason: str


@router.post("/operational-items/{item_id}/escalate")
async def escalate(item_id: str, req: EscalateReq, user: dict = Depends(get_current_user)):
    _forbid_client(user, "escalate items")
    try:
        item = await operations_engine.escalate(
            item_id=item_id, actor=user, reason=req.reason,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users")
async def list_users(role: Optional[str] = None, user: dict = Depends(get_current_user)):
    """List users (for assignment pickers). Strips phone for privacy in pilot."""
    from core.db import db
    q: dict = {}
    if role:
        q["role"] = role
    docs = await db.users.find(q, {"_id": 0}).to_list(500)
    return [{"id": d["id"], "name": d["name"], "role": d["role"]} for d in docs]


# ---------------- V3.3: edit, voice-update, mark-duplicate ----------------
class EditItemReq(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[Literal["low", "normal", "high", "critical"]] = None
    required_by: Optional[str] = None
    quantity: Optional[str] = None
    unit: Optional[str] = None
    assigned_to_user_id: Optional[str] = None


@router.patch("/operational-items/{item_id}")
async def edit_item(item_id: str, req: EditItemReq,
                    user: dict = Depends(get_current_user)):
    _forbid_client(user, "edit operational items")
    from core.db import db
    edits = {k: v for k, v in req.model_dump().items() if v is not None}
    assignee = None
    if "assigned_to_user_id" in edits:
        assignee = await db.users.find_one(
            {"id": edits["assigned_to_user_id"]}, {"_id": 0}
        )
        if not assignee:
            raise HTTPException(status_code=404, detail="Assignee not found")
    try:
        item = await operations_engine.edit_item(
            item_id=item_id, actor=user, edits=edits, assignee=assignee,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/operational-items/{item_id}/voice-update", status_code=201)
async def voice_update(item_id: str,
                       audio: UploadFile = File(...),
                       user: dict = Depends(get_current_user)):
    _forbid_client(user, "add voice updates")
    """Accept an audio note, persist as raw_asset, transcribe via Whisper,
    and append a voice_update activity entry on the item ledger.

    The original asset stays linked via payload.audio_asset_id; transcript
    and AI summary are stored alongside so the activity feed can render them
    without re-running Whisper.
    """
    item = await operations_engine.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    # Persist the raw asset (event_id=None — this asset belongs to an
    # operational item update, not a construction event).
    asset = await memory_engine.put_asset(
        event_id=f"op:{item_id}",
        kind="audio",
        mime=audio.content_type or "audio/m4a",
        raw_bytes=audio_bytes,
    )

    # Transcribe via Whisper. Run async, do not block beyond what Whisper takes.
    from engines import intelligence_engine
    transcript = ""
    summary = None
    language = None
    try:
        transcript = await intelligence_engine.transcribe_audio_bytes(
            audio_bytes, audio.content_type or "audio/m4a"
        )
    except Exception as e:
        # Capture the failure but still append the activity so the audio is not lost.
        transcript = ""
        summary = f"(transcription failed: {type(e).__name__})"

    # Lightweight summary — short, English, no LLM call if transcript empty or
    # already short.
    if transcript:
        try:
            summary, language = await intelligence_engine.summarise_voice_update(
                transcript=transcript, item=item,
            )
        except Exception:
            summary = transcript[:160]

    try:
        updated = await operations_engine.voice_update_item(
            item_id=item_id, actor=user,
            audio_asset_id=asset["id"],
            transcript=transcript,
            summary=summary,
            language=language,
        )
        return {"item": operations_engine.enrich(updated),
                "audio_asset_id": asset["id"],
                "transcript": transcript,
                "summary": summary,
                "language": language}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class MarkDuplicateReq(BaseModel):
    duplicate_of_item_id: str
    note: Optional[str] = None


@router.post("/operational-items/{item_id}/duplicate")
async def mark_duplicate(item_id: str, req: MarkDuplicateReq,
                         user: dict = Depends(get_current_user)):
    _forbid_client(user, "mark items as duplicates")
    try:
        item = await operations_engine.mark_duplicate(
            item_id=item_id, actor=user,
            duplicate_of_item_id=req.duplicate_of_item_id, note=req.note,
        )
        return operations_engine.enrich(item)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
