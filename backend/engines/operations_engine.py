"""Operations Engine — Engine 5.

The Operational Intelligence Layer of Project Atlas.

Design:
- Two collections:
    * operational_events    — append-only ledger (source of truth for history)
    * operational_items     — derived projection (cheap reads; rebuildable from ledger)
- Construction Events stay immutable; operational items reference them via
  `inherited_evidence_event_id` and never mutate them.
- AI suggests via `ai_proposals`; humans accept/edit/reject.
- "Health" is automatically derived from time + blocker + status and is separate
  from lifecycle "status".
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal, Iterable
from core.db import db
from engines import memory_engine

# ----- vocab -----
CATEGORIES = {
    "material_requirement", "labour_requirement", "equipment_requirement",
    "client_approval", "drawing_request", "site_issue",
    "quality_observation", "safety_observation",
    "commitment", "inspection", "follow_up", "general",
}
ORIGIN_TYPES = {
    "ai_proposal", "manual", "coordinator", "management",
    "client", "architect", "future_integration",
}
STATUSES = ["open", "assigned", "acknowledged", "in_progress",
            "fulfilled", "verified", "closed", "reopened",
            "archived", "cancelled", "duplicate"]
HEALTHS = ["on_track", "due_soon", "overdue", "blocked", "waiting_external", "completed"]
PRIORITIES = ["low", "normal", "high", "critical"]

# Status transition map (from → allowed_to)
# Sprint 6.2: "open" -> "fulfilled" added directly (previously only reachable
# via acknowledged/in_progress) so a client_approval item can be approved
# straight away, without a client ever needing to go through an internal
# assign/acknowledge/start-work pipeline that doesn't apply to their role at
# all. "open" -> "cancelled" already existed and now doubles as "reject".
TRANSITIONS = {
    "open":         {"assigned", "acknowledged", "in_progress", "fulfilled", "closed",
                     "archived", "cancelled", "duplicate"},
    "assigned":     {"acknowledged", "in_progress", "open", "closed",
                     "archived", "cancelled", "duplicate"},
    "acknowledged": {"in_progress", "fulfilled", "closed",
                     "archived", "cancelled", "duplicate"},
    "in_progress":  {"fulfilled", "closed",
                     "archived", "cancelled", "duplicate"},
    "fulfilled":    {"verified", "in_progress", "closed",
                     "archived"},
    "verified":     {"closed", "reopened", "archived"},
    "closed":       {"reopened", "archived"},
    "reopened":     {"assigned", "in_progress", "open", "closed",
                     "archived", "cancelled", "duplicate"},
    "archived":     {"open", "reopened"},
    "cancelled":    {"open", "reopened"},
    "duplicate":    {"open", "reopened"},
}

# When this event kind happens, set this lifecycle field
TIME_FIELD_BY_EVENT_KIND = {
    "assigned":   "assigned_at",
    "started":    "started_at",
    "fulfilled":  "completed_at",
    "verified":   "verified_at",
    "closed":     "closed_at",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_iso(value) -> Optional[datetime]:
    """Centralised ISO/date parser. Always returns tz-aware UTC datetime or None.

    Accepts:
      * full ISO datetime with offset (e.g. '2026-06-30T10:00:00+05:30')
      * ISO datetime with trailing 'Z' (e.g. '2026-06-30T10:00:00Z')
      * naive ISO datetime (assumed UTC)
      * date-only 'YYYY-MM-DD' (assumed UTC midnight)
      * existing datetime objects (normalised to UTC)
      * None / empty / unparseable -> None
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


# ---------------- write helpers ----------------
async def _insert(collection, doc: dict) -> dict:
    await collection.insert_one({**doc})
    return doc


# ---------------- ai_proposals ----------------
async def insert_ai_proposal(doc: dict) -> dict:
    return await _insert(db.ai_proposals, doc)


async def list_ai_proposals(*, event_id: Optional[str] = None,
                            status: Optional[str] = None,
                            site_id: Optional[str] = None) -> list[dict]:
    q: dict = {}
    if event_id:
        q["event_id"] = event_id
    if site_id:
        q["site_id"] = site_id
    if status:
        q["decision"] = status
    return await db.ai_proposals.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


async def get_ai_proposal(proposal_id: str) -> Optional[dict]:
    return await db.ai_proposals.find_one({"id": proposal_id}, {"_id": 0})


async def update_ai_proposal_decision(proposal_id: str, *, decision: str,
                                      actor: dict, operational_item_id: Optional[str] = None,
                                      reason: Optional[str] = None) -> None:
    upd = {
        "decision": decision,
        "decided_by_user_id": actor["id"],
        "decided_by_user_name": actor["name"],
        "decided_at": _iso(_now()),
    }
    if operational_item_id is not None:
        upd["operational_item_id"] = operational_item_id
    if reason is not None:
        upd["decision_reason"] = reason
    await db.ai_proposals.update_one({"id": proposal_id}, {"$set": upd})


# ---------------- operational_events (ledger) ----------------
async def append_event(*, item_id: str, kind: str, actor: dict,
                       prev_status: Optional[str] = None,
                       new_status: Optional[str] = None,
                       payload: Optional[dict] = None) -> dict:
    doc = {
        "id": _new_id("oe_"),
        "operational_item_id": item_id,
        "kind": kind,
        "actor_user_id": actor["id"],
        "actor_user_name": actor["name"],
        "prev_status": prev_status,
        "new_status": new_status,
        "payload": payload or {},
        "created_at": _iso(_now()),
    }
    return await _insert(db.operational_events, doc)


async def list_events_for_item(item_id: str) -> list[dict]:
    return (await db.operational_events
            .find({"operational_item_id": item_id}, {"_id": 0})
            .sort("created_at", 1).to_list(1000))


async def list_events_for_site(site_id: str, limit: int = 500) -> list[dict]:
    # join via items belonging to this site
    items = await db.operational_items.find({"site_id": site_id}, {"_id": 0, "id": 1}).to_list(2000)
    ids = [i["id"] for i in items]
    if not ids:
        return []
    return (await db.operational_events
            .find({"operational_item_id": {"$in": ids}}, {"_id": 0})
            .sort("created_at", -1).to_list(limit))


# ---------------- operational_items (projection) ----------------
async def get_item(item_id: str) -> Optional[dict]:
    return await db.operational_items.find_one({"id": item_id}, {"_id": 0})


async def list_items(*, site_id: Optional[str] = None,
                     status: Optional[str] = None,
                     priority: Optional[str] = None,
                     assigned_to_user_id: Optional[str] = None,
                     category: Optional[str] = None,
                     limit: int = 300) -> list[dict]:
    q: dict = {}
    if site_id:
        q["site_id"] = site_id
    if status:
        q["status"] = status
    if priority:
        q["priority"] = priority
    if assigned_to_user_id:
        q["assigned_to_user_id"] = assigned_to_user_id
    if category:
        q["category"] = category
    return (await db.operational_items.find(q, {"_id": 0})
            .sort("last_updated_at", -1).to_list(limit))


async def _save_item(doc: dict) -> dict:
    """Upsert the projection. Mutating the projection is fine — it is derived."""
    await db.operational_items.update_one({"id": doc["id"]}, {"$set": doc}, upsert=True)
    return doc


# ---------------- core: create + transition ----------------
async def create_item(*, actor: dict, site_id: str,
                      category: str, title: str, description: str = "",
                      priority: str = "normal",
                      origin_type: str = "manual",
                      origin_reference_id: Optional[str] = None,
                      inherited_evidence_event_id: Optional[str] = None,
                      required_by: Optional[str] = None,
                      assigned_to_user: Optional[dict] = None) -> dict:
    assert category in CATEGORIES, f"unknown category: {category}"
    assert origin_type in ORIGIN_TYPES, f"unknown origin: {origin_type}"
    assert priority in PRIORITIES, f"unknown priority: {priority}"

    site = await memory_engine.get_site(site_id)
    if not site:
        raise ValueError("site not found")

    item_id = _new_id("op_")
    created_at = _iso(_now())
    initial_status = "assigned" if assigned_to_user else "open"

    doc = {
        "id": item_id,
        "category": category,
        "title": title,
        "description": description,
        "site_id": site_id,
        "project_id": site.get("project_id"),

        "origin_type": origin_type,
        "origin_reference_id": origin_reference_id,
        "inherited_evidence_event_id": inherited_evidence_event_id,

        "status": initial_status,
        "priority": priority,

        "created_by_user_id": actor["id"],
        "created_by_user_name": actor["name"],
        "assigned_to_user_id": (assigned_to_user or {}).get("id"),
        "assigned_to_user_name": (assigned_to_user or {}).get("name"),
        "assigned_by_user_id": actor["id"] if assigned_to_user else None,
        "assigned_by_user_name": actor["name"] if assigned_to_user else None,
        "completed_by_user_id": None,
        "completed_by_user_name": None,
        "verified_by_user_id": None,
        "verified_by_user_name": None,

        "created_at": created_at,
        "required_by": required_by,
        "assigned_at": created_at if assigned_to_user else None,
        "started_at": None,
        "completed_at": None,
        "verified_at": None,
        "closed_at": None,

        "blocker": None,
        "health": "on_track",
        "last_updated_at": created_at,
        "last_derived_from_op_event_id": None,
    }
    # Initial ledger event
    initial = await append_event(item_id=item_id, kind="created", actor=actor,
                                 prev_status=None, new_status=initial_status,
                                 payload={"category": category, "title": title,
                                          "origin_type": origin_type})
    doc["last_derived_from_op_event_id"] = initial["id"]
    if assigned_to_user:
        await append_event(item_id=item_id, kind="assigned", actor=actor,
                           prev_status="open", new_status="assigned",
                           payload={"assigned_to_user_id": assigned_to_user["id"],
                                    "assigned_to_user_name": assigned_to_user["name"]})

    doc["health"] = derive_health(doc)
    await _save_item(doc)
    return doc


_FALLBACK_TITLE_MAX = 60


async def create_fallback_note_item(*, actor: dict, site_id: str, text: str, event_id: str) -> Optional[dict]:
    """Sprint 6.2 Founder Verification fix — Manual Text Capture Processing.

    Shared by BOTH places a manually-typed observation can end up with no
    AI ever having produced a proposal for it:
      1. reality_engine.capture() — AI was never running at all (no API
         key configured), checked once at capture time.
      2. intelligence_engine._process()'s except block — AI WAS running
         but genuinely failed for this event (bad/expired key, network
         error, rate limit, etc.) — a gap the original Sprint 6.2 patch
         missed entirely: it only ever checked "is the worker task alive"
         at capture time, never "did processing actually succeed."
         "AI unavailable" has to mean both, or a broken-but-configured
         key produces the exact same stranded-observation symptom the
         fix was supposed to eliminate.

    Idempotent: if a fallback (or any) item already traces back to this
    event via inherited_evidence_event_id, does nothing — so an event
    can never end up with two fallback records even if, hypothetically,
    both call sites above were ever reached for the same event.
    """
    existing = await db.operational_items.find_one(
        {"inherited_evidence_event_id": event_id}, {"_id": 0, "id": 1},
    )
    if existing:
        return None

    fallback_text = text.strip()
    if not fallback_text:
        return None
    title = fallback_text if len(fallback_text) <= _FALLBACK_TITLE_MAX else fallback_text[:_FALLBACK_TITLE_MAX - 1] + "…"
    return await create_item(
        actor=actor, site_id=site_id, category="general",
        title=title,
        description=(
            f"{fallback_text}\n\n"
            "(Automatically created from a captured text observation — "
            "AI processing was unavailable at capture time.)"
        ),
        origin_type="manual",
        inherited_evidence_event_id=event_id,
    )


async def transition_status(*, item_id: str, to_status: str, actor: dict,
                            note: Optional[str] = None) -> dict:
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    cur = item["status"]
    if cur == to_status:
        return item
    allowed = TRANSITIONS.get(cur, set())
    if to_status not in allowed:
        raise ValueError(f"transition {cur} → {to_status} not allowed")

    # event kind mapping
    kind_map = {"acknowledged": "acknowledged", "in_progress": "started",
                "fulfilled": "fulfilled", "verified": "verified",
                "closed": "closed", "reopened": "reopened", "assigned": "assigned",
                "open": "reopened"}
    ev_kind = kind_map.get(to_status, to_status)
    ev = await append_event(item_id=item_id, kind=ev_kind, actor=actor,
                            prev_status=cur, new_status=to_status,
                            payload={"note": note} if note else {})

    now_iso = _iso(_now())
    item["status"] = to_status
    field = TIME_FIELD_BY_EVENT_KIND.get(ev_kind)
    if field and not item.get(field):
        item[field] = now_iso

    if to_status == "fulfilled":
        item["completed_by_user_id"] = actor["id"]
        item["completed_by_user_name"] = actor["name"]
    if to_status == "verified":
        item["verified_by_user_id"] = actor["id"]
        item["verified_by_user_name"] = actor["name"]
    if to_status == "closed":
        item["closed_at"] = item.get("closed_at") or now_iso

    item["last_updated_at"] = now_iso
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


async def assign_item(*, item_id: str, assignee: dict, actor: dict,
                      note: Optional[str] = None) -> dict:
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    prev_assignee_id = item.get("assigned_to_user_id")
    ev = await append_event(item_id=item_id, kind="assigned", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload={"assigned_to_user_id": assignee["id"],
                                     "assigned_to_user_name": assignee["name"],
                                     "previous_assignee_id": prev_assignee_id,
                                     "note": note})
    now_iso = _iso(_now())
    item["assigned_to_user_id"] = assignee["id"]
    item["assigned_to_user_name"] = assignee["name"]
    item["assigned_by_user_id"] = actor["id"]
    item["assigned_by_user_name"] = actor["name"]
    if not item.get("assigned_at"):
        item["assigned_at"] = now_iso
    if item["status"] == "open":
        item["status"] = "assigned"
    item["last_updated_at"] = now_iso
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


async def add_comment(*, item_id: str, actor: dict, text: str) -> dict:
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    ev = await append_event(item_id=item_id, kind="comment", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload={"text": text})
    item["last_updated_at"] = _iso(_now())
    item["last_derived_from_op_event_id"] = ev["id"]
    await _save_item(item)
    return item


async def set_blocker(*, item_id: str, actor: dict, category: str,
                      note: Optional[str] = None) -> dict:
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    blocker = {"category": category, "note": note, "set_at": _iso(_now()),
               "set_by_user_id": actor["id"], "set_by_user_name": actor["name"]}
    ev = await append_event(item_id=item_id, kind="blocker_set", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload=blocker)
    item["blocker"] = blocker
    item["last_updated_at"] = _iso(_now())
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


async def clear_blocker(*, item_id: str, actor: dict) -> dict:
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    ev = await append_event(item_id=item_id, kind="blocker_cleared", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload={"previous_blocker": item.get("blocker")})
    item["blocker"] = None
    item["last_updated_at"] = _iso(_now())
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


async def set_due(*, item_id: str, actor: dict, required_by: str) -> dict:
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    ev = await append_event(item_id=item_id, kind="due_set", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload={"required_by": required_by,
                                     "previous_required_by": item.get("required_by")})
    item["required_by"] = required_by
    item["last_updated_at"] = _iso(_now())
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


async def escalate(*, item_id: str, actor: dict, reason: str) -> dict:
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    new_priority = "critical" if item["priority"] != "critical" else item["priority"]
    ev = await append_event(item_id=item_id, kind="escalated", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload={"reason": reason,
                                     "previous_priority": item["priority"],
                                     "new_priority": new_priority})
    item["priority"] = new_priority
    item["escalated"] = True
    item["last_updated_at"] = _iso(_now())
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


# ---------------- V3.3: edit, voice_update, mark_duplicate ----------------
EDITABLE_FIELDS = {"title", "description", "priority", "required_by",
                   "quantity", "unit", "assigned_to_user_id"}


async def edit_item(*, item_id: str, actor: dict, edits: dict,
                    assignee: Optional[dict] = None) -> dict:
    """Patch one or more editable fields. Append a single 'edited' ledger row
    capturing the previous and new values for each changed field. Never
    overwrites history; the projection is updated atomically."""
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")

    # whitelist + diff
    changes: dict = {}
    details_changes: dict = {}
    for k, v in edits.items():
        if k not in EDITABLE_FIELDS:
            continue
        if k == "priority" and v not in PRIORITIES:
            raise ValueError(f"invalid priority: {v}")
        if k in ("quantity", "unit"):
            # quantity/unit live in ai_details (carry from proposal accept)
            current = (item.get("ai_details") or {}).get(k)
            if v != current:
                details_changes[k] = {"from": current, "to": v}
            continue
        if k == "assigned_to_user_id":
            # only reflect ID-only change here; assignment via assignee dict handled below.
            continue
        current = item.get(k)
        if v != current:
            changes[k] = {"from": current, "to": v}

    if assignee is not None:
        cur_id = item.get("assigned_to_user_id")
        if assignee.get("id") != cur_id:
            changes["assigned_to_user_id"] = {
                "from": cur_id, "to": assignee.get("id"),
                "from_name": item.get("assigned_to_user_name"),
                "to_name": assignee.get("name"),
            }

    if not changes and not details_changes:
        return item

    payload = {"changes": changes, "details_changes": details_changes}
    ev = await append_event(item_id=item_id, kind="edited", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload=payload)
    now_iso = _iso(_now())
    for k, diff in changes.items():
        if k == "assigned_to_user_id":
            item["assigned_to_user_id"] = diff["to"]
            item["assigned_to_user_name"] = diff.get("to_name")
            item["assigned_by_user_id"] = actor["id"]
            item["assigned_by_user_name"] = actor["name"]
            if diff["to"] and not item.get("assigned_at"):
                item["assigned_at"] = now_iso
            if item["status"] == "open" and diff["to"]:
                item["status"] = "assigned"
        else:
            item[k] = diff["to"]

    if details_changes:
        details = dict(item.get("ai_details") or {})
        for k, diff in details_changes.items():
            details[k] = diff["to"]
        item["ai_details"] = details

    item["last_updated_at"] = now_iso
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


async def voice_update_item(*, item_id: str, actor: dict,
                            audio_asset_id: str, transcript: str,
                            summary: Optional[str] = None,
                            language: Optional[str] = None) -> dict:
    """Append a voice_update activity entry. The original asset stays linked
    via payload.audio_asset_id; transcript and AI summary are stored alongside
    so the activity feed can render them without re-running Whisper."""
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    payload = {
        "audio_asset_id": audio_asset_id,
        "transcript": transcript,
        "summary": summary,
        "language": language,
    }
    ev = await append_event(item_id=item_id, kind="voice_update", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload=payload)
    item["last_updated_at"] = _iso(_now())
    item["last_derived_from_op_event_id"] = ev["id"]
    await _save_item(item)
    return item


async def mark_duplicate(*, item_id: str, actor: dict,
                         duplicate_of_item_id: str,
                         note: Optional[str] = None) -> dict:
    """Mark item as a duplicate of another. Status moves to 'duplicate'.
    History is preserved; the canonical target is recorded in projection
    and in the ledger payload."""
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    target = await get_item(duplicate_of_item_id)
    if not target:
        raise ValueError("duplicate target not found")
    if item_id == duplicate_of_item_id:
        raise ValueError("cannot mark item as duplicate of itself")
    prev = item["status"]
    if "duplicate" not in TRANSITIONS.get(prev, set()):
        raise ValueError(f"transition {prev} → duplicate not allowed")
    ev = await append_event(item_id=item_id, kind="duplicate_of", actor=actor,
                            prev_status=prev, new_status="duplicate",
                            payload={"duplicate_of_item_id": duplicate_of_item_id,
                                     "duplicate_of_title": target.get("title"),
                                     "note": note})
    now_iso = _iso(_now())
    item["status"] = "duplicate"
    item["duplicate_of_item_id"] = duplicate_of_item_id
    item["last_updated_at"] = now_iso
    item["last_derived_from_op_event_id"] = ev["id"]
    item["health"] = derive_health(item)
    await _save_item(item)
    return item


# ---------------- derived metrics ----------------
EXTERNAL_BLOCKER_CATS = {
    "awaiting_client_approval", "vendor_payment_pending",
    "drawing_revision_pending", "client_response_pending", "external",
}


def derive_health(item: dict) -> str:
    status = item.get("status")
    if status in ("verified", "closed", "fulfilled"):
        return "completed"
    blk = item.get("blocker")
    if blk:
        cat = (blk.get("category") or "").lower()
        if cat in EXTERNAL_BLOCKER_CATS:
            return "waiting_external"
        return "blocked"
    rb = item.get("required_by")
    if not rb:
        return "on_track"
    due = _parse_iso(rb)
    if due is None:
        return "on_track"
    now = _now()
    if due < now:
        return "overdue"
    if due - now < timedelta(hours=24):
        return "due_soon"
    return "on_track"


def compute_metrics(item: dict) -> dict:
    """Computed time-intelligence numbers used by the API/UI."""
    now = _now()

    created = _parse_iso(item.get("created_at"))
    required = _parse_iso(item.get("required_by"))
    assigned = _parse_iso(item.get("assigned_at"))
    completed = _parse_iso(item.get("completed_at"))
    verified = _parse_iso(item.get("verified_at"))

    age_hours = (now - created).total_seconds() / 3600 if created else None
    remaining_hours = (required - now).total_seconds() / 3600 if required else None
    days_overdue = max(0, int((now - required).total_seconds() // 86400)) if (required and required < now) else 0
    ttc_hours = ((completed - assigned).total_seconds() / 3600) if (assigned and completed) else None
    verif_delay = ((verified - completed).total_seconds() / 3600) if (completed and verified) else None
    return {
        "current_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "time_remaining_hours": round(remaining_hours, 2) if remaining_hours is not None else None,
        "days_overdue": days_overdue,
        "time_to_complete_hours": round(ttc_hours, 2) if ttc_hours is not None else None,
        "verification_delay_hours": round(verif_delay, 2) if verif_delay is not None else None,
    }


def enrich(item: dict) -> dict:
    """Attach computed metrics + ensure health is current."""
    item = {**item}
    item["health"] = derive_health(item)
    item["metrics"] = compute_metrics(item)
    return item


# ---------------- Sprint-2: project+site name denormalisation ----------------
async def _name_maps(site_ids: set[str], project_ids: set[str]) -> tuple[dict, dict]:
    """Fetch site+project names in two bulk queries. Cheap and cache-friendly."""
    site_map: dict = {}
    project_map: dict = {}
    if site_ids:
        async for s in db.sites.find({"id": {"$in": list(site_ids)}}, {"_id": 0, "id": 1, "name": 1, "project_id": 1}):
            site_map[s["id"]] = s
    if project_ids:
        async for p in db.projects.find({"id": {"$in": list(project_ids)}}, {"_id": 0, "id": 1, "name": 1}):
            project_map[p["id"]] = p
    return site_map, project_map


async def attach_names(docs: list[dict]) -> list[dict]:
    """Attach site_name + project_name to a list of docs that carry site_id
    (and, optionally, project_id). Never mutates the DB; purely a read-side
    denormalisation. Safe to call on operational_items, ai_proposals, or events.
    """
    if not docs:
        return docs
    site_ids = {d["site_id"] for d in docs if d.get("site_id")}
    project_ids = {d["project_id"] for d in docs if d.get("project_id")}
    # Project ids referenced only via site → resolve after we know the site's project.
    site_map, project_map = await _name_maps(site_ids, project_ids)
    missing_prj = {
        s.get("project_id") for s in site_map.values()
        if s.get("project_id") and s["project_id"] not in project_map
    }
    if missing_prj:
        _, extra = await _name_maps(set(), missing_prj)
        project_map.update(extra)
    for d in docs:
        s = site_map.get(d.get("site_id")) if d.get("site_id") else None
        d["site_name"] = s.get("name") if s else None
        pid = d.get("project_id") or (s.get("project_id") if s else None)
        p = project_map.get(pid) if pid else None
        d["project_id"] = pid
        d["project_name"] = p.get("name") if p else None
    return docs


async def attach_names_single(doc: dict) -> dict:
    """Convenience for single-doc paths."""
    if not doc:
        return doc
    (out,) = await attach_names([doc])
    return out


# ---------------- operational center buckets ----------------
async def operational_center(*, site_id: Optional[str] = None) -> dict:
    items = await list_items(site_id=site_id, limit=1000)
    items = [enrich(i) for i in items]
    open_items = [i for i in items if i["status"] not in ("verified", "closed", "fulfilled")]
    overdue = [i for i in open_items if i["health"] == "overdue"]
    high_priority = [i for i in open_items if i["priority"] in ("high", "critical")]
    awaiting_verification = [i for i in items if i["status"] == "fulfilled"]
    recently_completed = sorted(
        [i for i in items if i["status"] in ("verified", "closed")],
        key=lambda x: x.get("last_updated_at") or "",
        reverse=True,
    )[:20]
    recently_updated = sorted(items, key=lambda x: x.get("last_updated_at") or "", reverse=True)[:20]
    return {
        "open": open_items[:50],
        "overdue": overdue[:50],
        "high_priority": high_priority[:50],
        "awaiting_verification": awaiting_verification[:50],
        "recently_completed": recently_completed,
        "recently_updated": recently_updated,
        "counts": {
            "open": len(open_items),
            "overdue": len(overdue),
            "high_priority": len(high_priority),
            "awaiting_verification": len(awaiting_verification),
            "blocked": len([i for i in open_items if i["health"] in ("blocked", "waiting_external")]),
        },
    }


REQUIREMENT_CATEGORIES = {
    "material_requirement", "labour_requirement", "equipment_requirement",
    "drawing_request", "client_approval", "inspection",
}


async def site_requirements(site_id: str) -> dict:
    """Living checklist for a site — every requirement, fulfilled or not."""
    items = await list_items(site_id=site_id, limit=1000)
    requirements = [enrich(i) for i in items if i["category"] in REQUIREMENT_CATEGORIES]
    pending = [r for r in requirements if r["status"] not in ("verified", "closed", "fulfilled")]
    fulfilled = [r for r in requirements if r["status"] == "fulfilled"]
    verified = [r for r in requirements if r["status"] in ("verified", "closed")]
    return {
        "pending": pending, "fulfilled": fulfilled, "verified": verified,
        "counts": {"pending": len(pending), "fulfilled": len(fulfilled), "verified": len(verified)},
    }


# ---------------- AI proposal accept ----------------
async def accept_ai_proposal(*, proposal_id: str, actor: dict,
                             edits: Optional[dict] = None) -> dict:
    prop = await get_ai_proposal(proposal_id)
    if not prop:
        raise ValueError("proposal not found")
    if prop.get("decision") not in (None, "pending"):
        raise ValueError(f"proposal already {prop['decision']}")
    edits = edits or {}
    details = prop.get("details") or {}
    required_by = edits.get("required_by") or details.get("required_date")
    item = await create_item(
        actor=actor,
        site_id=prop["site_id"],
        category=edits.get("category", prop["category"]),
        title=edits.get("title", prop["title"]),
        description=edits.get("description", prop.get("description", "")),
        priority=edits.get("priority", prop.get("suggested_priority", "normal")),
        origin_type="ai_proposal",
        origin_reference_id=proposal_id,
        inherited_evidence_event_id=prop.get("event_id"),
        required_by=required_by,
    )
    # carry forward suggested_owner_role + AI extracted details on the item (informational)
    extra = {
        "suggested_owner_role": prop.get("suggested_owner_role"),
        "ai_details": details,
        "ai_confidence": prop.get("confidence"),
    }
    await db.operational_items.update_one({"id": item["id"]}, {"$set": extra})
    item.update(extra)
    decision = "edited" if edits else "accepted"
    await update_ai_proposal_decision(proposal_id, decision=decision, actor=actor,
                                      operational_item_id=item["id"])
    return item


async def reject_ai_proposal(*, proposal_id: str, actor: dict,
                             reason: Optional[str] = None) -> dict:
    prop = await get_ai_proposal(proposal_id)
    if not prop:
        raise ValueError("proposal not found")
    await update_ai_proposal_decision(proposal_id, decision="rejected", actor=actor,
                                      reason=reason)
    return {**prop, "decision": "rejected"}
