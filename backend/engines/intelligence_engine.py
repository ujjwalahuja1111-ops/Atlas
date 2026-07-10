"""Construction Intelligence Engine — async worker.

Pops event_ids from an in-process asyncio.Queue, transcribes audio (Whisper),
structures the result (GPT-4o), and persists an ai_analyses doc with
explicit *evidence* references back to the raw assets that justified the output.

Never blocks event capture. Failures only flip event.ai_status to "failed";
factual fields on the event are never touched.

If at startup we find events still stuck in "pending" (worker died mid-run),
we re-queue them.
"""
from __future__ import annotations
import asyncio
import base64
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from openai import OpenAI
from core.llm_compat import LlmChat, UserMessage, ImageContent
from . import memory_engine
from core.settings import EMERGENT_LLM_KEY, EMERGENT_BASE_URL

logger = logging.getLogger(__name__)

# ---------------- prompt config ----------------
PROMPT_NAME = "atlas_event_structurer"
PROMPT_VERSION = "1.1"
LLM_MODEL = "gpt-4o"
STT_MODEL = "whisper-1"

EVENT_SYSTEM_PROMPT = """You are the Intelligence layer of Project Atlas, a Construction Intelligence Platform for an Indian construction company. Site supervisors speak in Hindi, Punjabi, Hinglish or English.

You receive: an optional voice transcript, optional photo(s), and optional typed text from a site supervisor. Recognise CONSTRUCTION INTENT — a single utterance may contain MULTIPLE independent requirements. Extract every distinct intent.

Return ONLY a JSON object with these keys:
- type: one of ["voice_note", "photo", "material_request", "issue", "work_completed", "general"]
- title: short English title (under 10 words)
- summary: 1-2 line English summary
- materials: list of {name, quantity, unit, required_date, priority, trade, area, reason, confidence}
- labour: list of {trade, count, required_date, priority, area, reason, confidence}
- equipment: list of {name, quantity, required_date, priority, reason, confidence}
- client_approvals: list of {what, required_date, priority, reason, confidence}
- drawing_requests: list of {drawing, revision, priority, reason, confidence}
- inspections: list of {what, required_date, priority, reason, confidence}
- safety_observations: list of {observation, priority, area, confidence}
- quality_observations: list of {observation, priority, area, confidence}
- commitments: list of {what, owed_to, by_when, confidence}
- follow_ups: list of {what, when, confidence}
- issues: list of short strings describing problems/blockers — empty if none
- work_done: list of short strings describing completed work — empty if none
- urgency: one of ["low", "normal", "high"]
- language_detected: best guess

CRITICAL RULES:
1. NEVER invent values. If a field is not mentioned, leave it as null or omit it from the object.
2. Each list entry must come from the speaker's actual words.
3. confidence ∈ {"low","medium","high"} based on how clearly the speaker stated this requirement.
4. priority ∈ {"low","normal","high","critical"} — only use "critical" for explicit emergencies (safety, stop-work).
5. A single utterance may produce multiple entries across multiple lists.

Be strict: output ONLY valid JSON, no markdown, no commentary."""


# ---------------- queue + worker state ----------------
_queue: asyncio.Queue = asyncio.Queue()
_worker_task: Optional[asyncio.Task] = None
_openai_client: Optional[OpenAI] = None
_prompt_version: Optional[dict] = None


async def enqueue(event_id: str) -> None:
    await _queue.put(event_id)


# ---------------- worker ----------------
async def _whisper_transcribe(audio_bytes: bytes, mime: str) -> str:
    """Blocking-ish call to Whisper. Run in thread pool to avoid blocking the loop."""
    ext = "m4a"
    if "wav" in mime:
        ext = "wav"
    elif "mp3" in mime or "mpeg" in mime:
        ext = "mp3"
    elif "webm" in mime:
        ext = "webm"
    elif "ogg" in mime:
        ext = "ogg"

    def _run() -> str:
        buf = io.BytesIO(audio_bytes)
        buf.name = f"audio.{ext}"
        resp = _openai_client.audio.transcriptions.create(file=buf, model=STT_MODEL)
        return (resp.text or "").strip()

    return await asyncio.to_thread(_run)


async def _structure(transcript: str, text_input: Optional[str], photo_b64s: list[str]) -> dict:
    session_id = str(uuid.uuid4())
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=EVENT_SYSTEM_PROMPT,
    ).with_model("openai", LLM_MODEL)

    parts = []
    if transcript:
        parts.append(f"Voice transcript:\n{transcript}")
    if text_input:
        parts.append(f"Typed text from supervisor:\n{text_input}")
    if not parts:
        parts.append("(No voice or text — interpret photos only.)")
    parts.append("Return JSON only.")
    user_text = "\n\n".join(parts)

    file_contents = [ImageContent(image_base64=b) for b in photo_b64s[:3]]  # cap to 3 photos
    msg = (
        UserMessage(text=user_text, file_contents=file_contents)
        if file_contents
        else UserMessage(text=user_text)
    )
    response = await chat.send_message(msg)
    text = response if isinstance(response, str) else str(response)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return json.loads(text)


async def _process(event_id: str) -> None:
    event = await memory_engine.get_event(event_id)
    if not event:
        logger.warning(f"worker: event {event_id} not found")
        return

    started_at = datetime.now(timezone.utc).isoformat()
    transcript = ""
    evidence: list[dict] = []
    photo_b64s: list[str] = []
    error: Optional[str] = None

    try:
        # Pull raw assets to feed the models — and to record evidence
        if event.get("audio_asset_id"):
            audio_doc = await memory_engine.get_asset(event["audio_asset_id"])
            if audio_doc:
                evidence.append({"kind": "audio", "asset_id": audio_doc["id"], "sha256": audio_doc["sha256"]})
                audio_bytes = base64.b64decode(audio_doc["data_base64"])
                transcript = await _whisper_transcribe(audio_bytes, audio_doc.get("mime", "audio/m4a"))

        for asset_id in (event.get("photo_asset_ids") or []):
            photo_doc = await memory_engine.get_asset(asset_id)
            if photo_doc:
                evidence.append({"kind": "photo", "asset_id": photo_doc["id"], "sha256": photo_doc["sha256"]})
                photo_b64s.append(photo_doc["data_base64"])

        if event.get("text_input"):
            evidence.append({"kind": "text", "value": event["text_input"]})

        structured = await _structure(transcript, event.get("text_input"), photo_b64s)

        analysis_doc = {
            "id": memory_engine._new_id("ana_"),
            "event_id": event_id,
            "transcript": transcript or None,
            "language_detected": structured.get("language_detected"),
            "structured": structured,
            "evidence": evidence,
            "model_versions": {"stt": STT_MODEL if event.get("audio_asset_id") else None, "llm": LLM_MODEL},
            "prompt_version_id": _prompt_version["id"] if _prompt_version else None,
            "prompt_name": PROMPT_NAME,
            "prompt_version": PROMPT_VERSION,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
        await memory_engine.put_ai_analysis(analysis_doc)
        await memory_engine.set_event_ai_status(event_id, "analyzed", analysis_doc["id"])
        logger.info(f"worker: analyzed {event_id} language={structured.get('language_detected')}")

        # Drive proposal generation off the canonical ai_analyses doc.
        # Same code path for voice / text / mixed input.
        await generate_proposals_for_event(event_id)

    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        logger.error(f"worker: failed {event_id} -> {error}")
        # Still persist an ai_analyses row capturing the failure + evidence
        analysis_doc = {
            "id": memory_engine._new_id("ana_"),
            "event_id": event_id,
            "transcript": transcript or None,
            "language_detected": None,
            "structured": None,
            "evidence": evidence,
            "model_versions": {"stt": STT_MODEL if event.get("audio_asset_id") else None, "llm": LLM_MODEL},
            "prompt_version_id": _prompt_version["id"] if _prompt_version else None,
            "prompt_name": PROMPT_NAME,
            "prompt_version": PROMPT_VERSION,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }
        try:
            await memory_engine.put_ai_analysis(analysis_doc)
            await memory_engine.set_event_ai_status(event_id, "failed", analysis_doc["id"])
        except Exception:
            await memory_engine.set_event_ai_status(event_id, "failed")


async def _worker_loop() -> None:
    logger.info("Intelligence worker started")
    while True:
        event_id = await _queue.get()
        try:
            await _process(event_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker loop error")
        finally:
            _queue.task_done()


async def start_worker() -> None:
    global _worker_task, _openai_client, _prompt_version
    if not EMERGENT_LLM_KEY:
        # Sprint 5.0.2 — Optional AI Worker (Local Development). No AI API
        # key configured: skip starting the worker entirely rather than
        # letting OpenAI(api_key="") raise at construction and crash
        # backend startup. Nothing below this point runs — AI stays fully
        # intact and becomes available automatically on the next startup
        # once a valid key is configured; no code path here was changed.
        logger.info("AI worker disabled - no API key configured.")
        return
    _openai_client = OpenAI(api_key=EMERGENT_LLM_KEY, base_url=EMERGENT_BASE_URL)
    _prompt_version = await memory_engine.get_or_create_prompt_version(
        name=PROMPT_NAME,
        version=PROMPT_VERSION,
        model=LLM_MODEL,
        system_prompt=EVENT_SYSTEM_PROMPT,
        notes="Initial pilot prompt for Hindi/Punjabi/Hinglish/English event structuring.",
    )
    # Recovery 1 — events that never reached analysis (worker died mid-run).
    pending = await memory_engine.list_events_by_status("pending", limit=500)
    for ev in pending:
        await _queue.put(ev["id"])
    if pending:
        logger.info(f"Intelligence worker re-queued {len(pending)} pending events")

    # Recovery 2 — events analyzed but stuck without proposals.
    # Happens when the worker crashed between set_event_ai_status('analyzed')
    # and generate_proposals_for_event, or for legacy events written before
    # proposals_status was introduced. Without this pass, the AI Proposal stage
    # of the pipeline is silently skipped and the upstream voice/photo capture
    # never surfaces as an actionable item — exactly matching the real-world
    # behavioural gap reported in V3.2.2.
    # generate_proposals_for_event is idempotent: it skips events whose proposals
    # already exist, and it operates entirely on the canonical ai_analyses doc
    # (no re-call to Whisper / GPT-4o, no extra spend).
    orphaned = await memory_engine.db.events.find(
        {
            "ai_status": "analyzed",
            "$or": [
                {"proposals_status": {"$exists": False}},
                {"proposals_status": None},
            ],
        },
        {"_id": 0, "id": 1},
    ).to_list(500)
    if orphaned:
        logger.info(
            f"Intelligence worker backfilling proposals for {len(orphaned)} "
            f"analyzed-but-orphaned events"
        )
        for ev in orphaned:
            try:
                await generate_proposals_for_event(ev["id"])
            except Exception:
                logger.exception(f"backfill: proposal generation failed for {ev['id']}")

    _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None


# ---------------- V3 + V3.1: canonical proposal generation ----------------
async def generate_proposals_for_event(event_id: str, *, force: bool = False) -> dict:
    """Generate AI proposals from the canonical ai_analyses doc.

    Single code path for voice / text / mixed input. Operates on the structured
    construction record — never on raw input.

    Returns: {status, generated_count, reason?}.
    Persists `event.proposals_status` ∈ {generated, empty, failed, skipped_existing}.
    """
    event = await memory_engine.get_event(event_id)
    if not event:
        return {"status": "failed", "generated_count": 0, "reason": "event_not_found"}

    analysis = await memory_engine.get_ai_analysis(event_id)
    if not analysis or not analysis.get("structured"):
        await memory_engine.set_event_proposals_status(event_id, "empty",
                                                       error="no_analysis_or_structured")
        return {"status": "empty", "generated_count": 0, "reason": "no_analysis_or_structured"}

    structured = analysis["structured"]

    # Idempotency: if proposals already exist for this event, skip unless forced.
    if not force:
        from engines import operations_engine
        existing = await operations_engine.list_ai_proposals(event_id=event_id)
        if existing:
            await memory_engine.set_event_proposals_status(event_id, "generated")
            return {"status": "skipped_existing", "generated_count": len(existing)}

    try:
        count = await _emit_proposals_from_structured(event, structured)
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        logger.exception(f"proposal generation failed for {event_id}: {reason}")
        await memory_engine.set_event_proposals_status(event_id, "failed", error=reason)
        return {"status": "failed", "generated_count": 0, "reason": reason}

    if count == 0:
        await memory_engine.set_event_proposals_status(event_id, "empty")
        logger.info(f"proposals: empty for {event_id} (no actionable signal)")
        return {"status": "empty", "generated_count": 0}

    await memory_engine.set_event_proposals_status(event_id, "generated")
    logger.info(f"proposals: generated {count} for {event_id}")
    return {"status": "generated", "generated_count": count}


async def _emit_proposals_from_structured(event: dict, structured: dict) -> int:
    """Translate structured construction record into ai_proposals rows.

    Pure function over the canonical record. Input-method-agnostic.
    Recognises 11 construction intents: material, labour, equipment, client_approval,
    drawing_request, inspection, site_issue, safety_observation, quality_observation,
    commitment, follow_up.
    """
    from engines import operations_engine
    site_id = event["site_id"]
    event_id = event["id"]
    base = {
        "site_id": site_id,
        "event_id": event_id,
        "decision": "pending",
        "decided_by_user_id": None,
        "decided_by_user_name": None,
        "decided_at": None,
        "operational_item_id": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    summary = (structured.get("summary") or "")[:300]
    global_urgency = (structured.get("urgency") or "normal") or "normal"
    count = 0

    def _list(key):
        v = structured.get(key)
        return v if isinstance(v, list) else []

    def _str(v, default=""):
        return (str(v) if v is not None else default).strip()

    async def add(category, title, *, suggested_owner_role, priority=None,
                  confidence="high", snippet="", details=None):
        nonlocal count
        if not title:
            return
        prio = priority or global_urgency or "normal"
        if prio not in ("low", "normal", "high", "critical"):
            prio = "normal"
        await operations_engine.insert_ai_proposal({
            **base,
            "id": operations_engine._new_id("prop_"),
            "category": category,
            "title": title[:120],
            "description": summary,
            "suggested_priority": prio,
            "suggested_owner_role": suggested_owner_role,
            "confidence": confidence if confidence in ("low", "medium", "high") else "high",
            "source_snippet": snippet[:240],
            "details": details or {},
        })
        count += 1

    # ---- materials ----
    for m in _list("materials"):
        if not isinstance(m, dict):
            continue
        name = _str(m.get("name")) or "material"
        qty = m.get("quantity")
        unit = _str(m.get("unit"))
        qty_str = "" if qty in (None, "") else str(qty)
        title = " ".join(filter(None, ["Procure", qty_str, unit, name])).strip() or f"Procure {name}"
        await add("material_requirement", title,
                  suggested_owner_role="coordinator",
                  priority=m.get("priority"),
                  confidence=_str(m.get("confidence")) or "high",
                  snippet=f"Material: {name} {qty_str} {unit}".strip(),
                  details={k: m.get(k) for k in ("name", "quantity", "unit", "required_date",
                                                  "priority", "trade", "area", "reason", "confidence")})

    # ---- labour ----
    for lb in _list("labour"):
        if not isinstance(lb, dict):
            continue
        trade = _str(lb.get("trade")) or "labour"
        cnt = lb.get("count")
        cnt_str = "" if cnt in (None, "") else str(cnt)
        title = " ".join(filter(None, [cnt_str, trade, "required"])).strip() or f"{trade} required"
        await add("labour_requirement", title,
                  suggested_owner_role="coordinator",
                  priority=lb.get("priority"),
                  confidence=_str(lb.get("confidence")) or "high",
                  snippet=f"Labour: {cnt_str} {trade}".strip(),
                  details={k: lb.get(k) for k in ("trade", "count", "required_date",
                                                  "priority", "area", "reason", "confidence")})

    # ---- equipment ----
    for e in _list("equipment"):
        if not isinstance(e, dict):
            continue
        name = _str(e.get("name") or e.get("equipment")) or "equipment"
        qty = e.get("quantity")
        qty_str = "" if qty in (None, "") else str(qty)
        title = " ".join(filter(None, [qty_str, name, "required"])).strip() or f"{name} required"
        await add("equipment_requirement", title,
                  suggested_owner_role="coordinator",
                  priority=e.get("priority"),
                  confidence=_str(e.get("confidence")) or "high",
                  snippet=f"Equipment: {qty_str} {name}".strip(),
                  details={k: e.get(k) for k in ("name", "equipment", "quantity",
                                                  "required_date", "priority", "reason", "confidence")})

    # ---- client_approvals ----
    for c in _list("client_approvals"):
        if not isinstance(c, dict):
            continue
        what = _str(c.get("what")) or "Client approval pending"
        await add("client_approval", what,
                  suggested_owner_role="client_coordinator",
                  priority=c.get("priority") or "high",
                  confidence=_str(c.get("confidence")) or "high",
                  snippet=f"Client approval: {what}",
                  details={k: c.get(k) for k in ("what", "required_date", "priority", "reason", "confidence")})

    # ---- drawing_requests ----
    for d in _list("drawing_requests"):
        if not isinstance(d, dict):
            continue
        drawing = _str(d.get("drawing")) or "Drawing request"
        rev = _str(d.get("revision"))
        title = f"{drawing}" + (f" (rev {rev})" if rev else "")
        await add("drawing_request", title,
                  suggested_owner_role="architect",
                  priority=d.get("priority"),
                  confidence=_str(d.get("confidence")) or "high",
                  snippet=f"Drawing: {drawing} {rev}".strip(),
                  details={k: d.get(k) for k in ("drawing", "revision", "priority", "reason", "confidence")})

    # ---- inspections ----
    for ins in _list("inspections"):
        if not isinstance(ins, dict):
            continue
        what = _str(ins.get("what")) or "Inspection"
        await add("inspection", what,
                  suggested_owner_role="qa",
                  priority=ins.get("priority"),
                  confidence=_str(ins.get("confidence")) or "high",
                  snippet=f"Inspection: {what}",
                  details={k: ins.get(k) for k in ("what", "required_date", "priority", "reason", "confidence")})

    # ---- safety_observations ----
    for s in _list("safety_observations"):
        if not isinstance(s, dict):
            continue
        obs = _str(s.get("observation")) or "Safety observation"
        await add("safety_observation", obs,
                  suggested_owner_role="safety_officer",
                  priority=s.get("priority") or "high",
                  confidence=_str(s.get("confidence")) or "high",
                  snippet=f"Safety: {obs}",
                  details={k: s.get(k) for k in ("observation", "priority", "area", "confidence")})

    # ---- quality_observations ----
    for q in _list("quality_observations"):
        if not isinstance(q, dict):
            continue
        obs = _str(q.get("observation")) or "Quality observation"
        await add("quality_observation", obs,
                  suggested_owner_role="qa",
                  priority=q.get("priority"),
                  confidence=_str(q.get("confidence")) or "high",
                  snippet=f"Quality: {obs}",
                  details={k: q.get(k) for k in ("observation", "priority", "area", "confidence")})

    # ---- commitments ----
    for c in _list("commitments"):
        if not isinstance(c, dict):
            continue
        what = _str(c.get("what")) or "Commitment"
        owed_to = _str(c.get("owed_to"))
        title = what + (f" → {owed_to}" if owed_to else "")
        await add("commitment", title,
                  suggested_owner_role="coordinator",
                  priority=c.get("priority"),
                  confidence=_str(c.get("confidence")) or "high",
                  snippet=f"Commitment: {what}",
                  details={k: c.get(k) for k in ("what", "owed_to", "by_when", "confidence")})

    # ---- follow_ups ----
    for f in _list("follow_ups"):
        if not isinstance(f, dict):
            continue
        what = _str(f.get("what")) or "Follow up"
        await add("follow_up", what,
                  suggested_owner_role="coordinator",
                  priority=f.get("priority"),
                  confidence=_str(f.get("confidence")) or "high",
                  snippet=f"Follow up: {what}",
                  details={k: f.get(k) for k in ("what", "when", "confidence")})

    # ---- legacy: free-text "issues" become site_issue proposals ----
    issues = structured.get("issues") or []
    if isinstance(issues, list):
        for it in issues:
            text = _str(it)
            if not text:
                continue
            await add("site_issue", text,
                      suggested_owner_role="site_engineer",
                      priority="high",
                      confidence="high",
                      snippet=f"Issue: {text[:120]}",
                      details={"raw": text})

    return count


# Deprecated alias retained for any in-flight callers; routes through canonical path.
async def _emit_proposals(event: dict, structured: dict) -> None:  # pragma: no cover
    await _emit_proposals_from_structured(event, structured)


# ---------------- V3.3: voice-update helpers ----------------
async def transcribe_audio_bytes(audio_bytes: bytes, mime: str) -> str:
    """Public wrapper around the existing Whisper helper, used by the
    Operational Item voice-update endpoint. Same model/codepath as the
    construction-event worker."""
    return await _whisper_transcribe(audio_bytes, mime)


VOICE_UPDATE_SUMMARY_PROMPT = """You are summarising a short voice update logged
against an existing construction operational item. The supervisor may speak in
Hindi, Punjabi, Hinglish or English.

Return ONLY a JSON object with these keys:
- summary: ≤ 20 English words describing the status update.
- language_detected: best guess language code.

No markdown, no commentary, no extra keys."""


async def summarise_voice_update(*, transcript: str, item: dict) -> tuple[Optional[str], Optional[str]]:
    """Best-effort LLM summary of a voice update transcript. Returns
    (summary, language). On any failure returns (truncated transcript, None).
    Cheap one-shot; reuses the same Emergent LLM key."""
    if not transcript:
        return None, None
    try:
        session_id = str(uuid.uuid4())
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=session_id,
            system_message=VOICE_UPDATE_SUMMARY_PROMPT,
        ).with_model("openai", LLM_MODEL)
        ctx = (
            f"Item title: {item.get('title','')}\n"
            f"Category: {item.get('category','')}\n"
            f"Current status: {item.get('status','')}\n"
            f"Voice update transcript:\n{transcript}\n\nReturn JSON only."
        )
        resp = await chat.send_message(UserMessage(text=ctx))
        text = resp if isinstance(resp, str) else str(resp)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        data = json.loads(text)
        return (data.get("summary") or transcript[:160]), data.get("language_detected")
    except Exception:
        return transcript[:160], None
