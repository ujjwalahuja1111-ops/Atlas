"""Reality Engine — accepts construction reality (voice, photo, text, GPS),
persists it immutably, and enqueues asynchronous AI analysis.

Returns to the caller in <300ms. AI work happens in the background.
The Golden Rule: the event is saved BEFORE the worker is enqueued, and the
worker can never block this path.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import UploadFile
from . import memory_engine
from . import intelligence_engine
from . import operations_engine


async def capture(
    *,
    site_id: str,
    project_id: str,
    user: dict,
    text_input: Optional[str],
    audio_file: Optional[UploadFile],
    photo_files: list[UploadFile],
    gps_json: Optional[str],
    client_created_at: Optional[str],
    app_version: Optional[str],
    activity_id: Optional[str] = None,
) -> dict:
    """Persist a construction event and queue it for AI analysis.

    All raw assets are stored in raw_assets BEFORE the event document is created
    so the event holds final references — preserving immutability.

    Sprint 6.1 — Foundation for AI Client Communication: `project_id` is
    denormalized from the site at capture time (the caller already looks
    the site up to validate it exists, so this costs no extra query) so a
    future reporting engine can query events directly by project without
    an extra site join. `activity_id` is a reserved, optional field — no
    current capture UI sets it, but the column exists so a future capture
    flow (or AI post-processing) can associate an event with a specific
    Construction Workflow activity/stage without a schema change then.
    Neither changes the capture pipeline itself — same inputs, same
    <300ms return, same Golden Rule (event saved before the AI worker is
    enqueued).
    """
    server_created_at = datetime.now(timezone.utc).isoformat()
    event_id = memory_engine._new_id("evt_")

    audio_ref = None
    if audio_file is not None:
        audio_bytes = await audio_file.read()
        if len(audio_bytes) > 0:
            mime = audio_file.content_type or "audio/m4a"
            audio_ref = await memory_engine.put_asset(event_id, "audio", mime, audio_bytes)

    photo_refs: list[dict] = []
    for pf in photo_files:
        if pf is None:
            continue
        b = await pf.read()
        if len(b) > 0:
            mime = pf.content_type or "image/jpeg"
            photo_refs.append(await memory_engine.put_asset(event_id, "photo", mime, b))

    # Decide kind
    has_audio = audio_ref is not None
    has_photos = len(photo_refs) > 0
    has_text = bool(text_input and text_input.strip())
    if has_audio and (has_photos or has_text):
        kind = "mixed"
    elif has_audio:
        kind = "voice"
    elif has_photos and has_text:
        kind = "mixed"
    elif has_photos:
        kind = "photo"
    else:
        kind = "text"

    gps = None
    if gps_json:
        try:
            gps = json.loads(gps_json)
        except Exception:
            gps = None

    event_doc = {
        "id": event_id,
        "site_id": site_id,
        "project_id": project_id,
        "activity_id": activity_id,
        "user_id": user["id"],
        "user_name": user["name"],
        "kind": kind,
        "text_input": text_input.strip() if has_text else None,
        "audio_asset_id": audio_ref["id"] if audio_ref else None,
        "photo_asset_ids": [p["id"] for p in photo_refs],
        "gps": gps,
        "client_created_at": client_created_at,
        "server_created_at": server_created_at,
        "app_version": app_version,
        "ai_status": "pending",
        "ai_analysis_id": None,
        "proposals_status": "pending",
        "proposals_error": None,
    }
    await memory_engine.insert_event(event_doc)

    # Sprint 6.2 — Manual Text Capture Processing. Operational items are
    # normally only created via AI proposal acceptance (a human reviewing
    # a machine GUESS). A manually-typed text observation is not a guess
    # — the human already authored it directly — so when AI is not
    # running at all (and would otherwise never produce a proposal,
    # stranding the observation with ai_status stuck at "pending"
    # forever) this creates a real, actionable operational record
    # straight away. See operations_engine.create_fallback_note_item's
    # docstring for the OTHER half of this fix — the same fallback also
    # fires from intelligence_engine's AI-failure path, covering a
    # configured-but-broken key, not just "no key at all."
    if has_text and not intelligence_engine.is_worker_running():
        await operations_engine.create_fallback_note_item(
            actor=user, site_id=site_id, text=text_input, event_id=event_id,
        )

    # Fire-and-forget enqueue. Never await processing here.
    await intelligence_engine.enqueue(event_id)
    return event_doc
