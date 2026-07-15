"""Operational Items routes (V3)."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, Literal
from core.auth import get_current_user
from engines import operations_engine, memory_engine

router = APIRouter(prefix="/api", tags=["operations"])


def _forbid_client(user: dict, action: str = "perform this action") -> None:
    """Client permission guard. FAC-04 — Final Authorization Model Freeze:
    Client is now a first-class backend role, so this checks `role`
    directly. (Previously — Sprint 6.2 — a client's backend role was the
    same generic `coordinator` a Project Manager had, so `workspace` was
    the only reliable signal; that ambiguity no longer exists.) Clients
    may still transition a client_approval item to fulfilled/cancelled
    (approve/reject) and add comments — see the `transition` and
    `comment` routes below, which do NOT call this guard.
    """
    if user.get("role") == "client":
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
            origin_type=req.origin_type if user["role"] == "site_supervisor" else (
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
    # FAC-04: a client may approve (-> fulfilled) or reject (-> cancelled)
    # a client_approval item — nothing else. Every other transition
    # (assignment lifecycle, closing, reopening, etc.) on any category is
    # an operational action, not a client one.
    if user.get("role") == "client":
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
    # FAC-04 — Final Authorization Model Freeze: "Site Supervisor must not
    # assign work" is now enforced at the backend, not just implicitly
    # absent from the frontend. Only management/project_manager may
    # assign or reassign - the same allowlist already used for project/
    # workflow/proposal management (routes/projects.py, routes/workflow.py,
    # routes/ai_proposals.py).
    if user["role"] not in ("management", "project_manager"):
        raise HTTPException(status_code=403, detail="Only Project Managers/management can assign or reassign work.")
    item_for_scope = await operations_engine.get_item(item_id)
    if not item_for_scope:
        raise HTTPException(status_code=404, detail="Item not found")
    from core.db import db
    assignee = await db.users.find_one({"id": req.assigned_to_user_id}, {"_id": 0})
    if not assignee:
        raise HTTPException(status_code=404, detail="Assignee not found")
    # FAC-OPS-06: enforce the identical eligibility rule the picker used
    # to decide who to display — active, an operational role, a member
    # of this item's project — so assignment can never succeed for
    # someone the picker would have hidden. Same function, not a
    # separately-maintained copy of the same three checks.
    if not memory_engine.is_eligible_assignee(assignee, item_for_scope.get("project_id")):
        raise HTTPException(status_code=400, detail="This user is not eligible to be assigned this item "
                             "(inactive, wrong role, or not a member of this project).")
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


class ClarificationReq(BaseModel):
    note: str


@router.post("/operational-items/{item_id}/request-clarification", status_code=201)
async def request_clarification(item_id: str, req: ClarificationReq, user: dict = Depends(get_current_user)):
    """Client Approval Workflow. Deliberately client-callable — unlike
    every other mutation on this file, this does NOT call
    _forbid_client(): "Request Clarification" is one of the three
    actions (approve, reject, request clarification) the client is
    explicitly allowed to take on a client_approval item. Any other
    role attempting it is rejected below just as clearly, since
    clarification is specifically the client's own question, not an
    internal action."""
    if user.get("role") != "client":
        raise HTTPException(status_code=403, detail="Only the client can request clarification.")
    if not req.note or not req.note.strip():
        raise HTTPException(status_code=400, detail="A note is required to request clarification.")
    try:
        item = await operations_engine.request_clarification(
            item_id=item_id, actor=user, note=req.note.strip())
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
async def list_users(role: Optional[str] = None, project_id: Optional[str] = None,
                     user: dict = Depends(get_current_user)):
    """List users (for assignment pickers). Strips phone for privacy in
    pilot. FAC-OPS-06: only returns ELIGIBLE assignees — active, an
    operational role, and (when project_id is given) a member of that
    project — see memory_engine.is_eligible_assignee for the single
    source of truth this and the assign action below both use.
    """
    docs = await memory_engine.list_assignable_users(role=role, project_id=project_id)
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
                       audio: Optional[UploadFile] = File(None),
                       text: Optional[str] = Form(None),
                       user: dict = Depends(get_current_user)):
    """Add an update to an operational item — voice OR manually-typed
    text, at least one required (mirrors POST /api/events' exact
    audio-or-text pattern). A voice note is persisted as a raw_asset and
    transcribed via Whisper; typed text needs no transcription step at
    all — it already is the text. Both paths converge on the same
    voice_update_item() ledger entry and response shape, so the activity
    feed renders either identically.

    FAC-OPS-06 — reuses the Capture screen's exact recording component
    (src/useVoiceRecorder.ts) on the frontend rather than a second,
    separate recording flow; this is the one backend endpoint both the
    voice and text paths call.
    """
    item = await operations_engine.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Client Approval Workflow: a client may leave voice/text feedback on
    # THEIR OWN client_approval items — the exact same category exception
    # already applied to `transition` above. Every other category/role
    # combination remains forbidden, unchanged.
    if user.get("role") == "client" and item["category"] != "client_approval":
        raise HTTPException(status_code=403, detail="Clients cannot add voice updates.")

    if audio is None and (not text or not text.strip()):
        raise HTTPException(status_code=400, detail="Provide audio or text")

    if text and text.strip():
        transcript = text.strip()
        summary = None
        language = None
        asset_id = None
    else:
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
        asset_id = asset["id"]

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
            transcript=transcript,
            audio_asset_id=asset_id,
            summary=summary,
            language=language,
        )
        return {"item": operations_engine.enrich(updated),
                "audio_asset_id": asset_id,
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
