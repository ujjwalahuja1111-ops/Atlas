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
from engines.reasoning_projections import TERMINAL_ITEM_STATUSES

# ----- vocab -----
CATEGORIES = {
    "material_requirement", "labour_requirement", "equipment_requirement",
    "client_approval", "drawing_request", "site_issue",
    "quality_observation", "safety_observation",
    "commitment", "inspection", "follow_up", "general",
}
ORIGIN_TYPES = {
    "ai_proposal", "manual", "project_manager", "management",
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


async def assert_item_visible(item: dict, user: dict) -> None:
    """Beta-06B security fix. Operational items already carry their own
    project_id field directly (denormalized at creation in create_item)
    - the exact same field my_day/daily_review/site_progress already
    query against. Applies the same _is_project_scoped check every
    other project-visibility boundary in Atlas already uses
    (commercial_engine.assert_project_visible, portfolio_search's own
    _scope()). Raises ValueError (mapped to 404 at the route, matching
    this codebase's "don't leak existence" convention) if the caller
    cannot see this item's project."""
    if not memory_engine._is_project_scoped(user):
        return
    visible = user.get("assigned_project_ids") or []
    if item.get("project_id") not in visible:
        raise ValueError(f"Operational item '{item['id']}' not found")


async def list_items(*, site_id: Optional[str] = None,
                     status: Optional[str] = None,
                     priority: Optional[str] = None,
                     assigned_to_user_id: Optional[str] = None,
                     category: Optional[str] = None,
                     event_id: Optional[str] = None,
                     exclude_terminal: bool = False,
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
    if event_id:
        # Related Operational Items (Canonical Event UX patch) — same
        # field every other event<->item linkage already uses
        # (inherited_evidence_event_id), just not category-restricted
        # here unlike find_open_item_for_event's client_approval-only
        # lookup above.
        q["inherited_evidence_event_id"] = event_id
    if exclude_terminal and not status:
        # Pending Review Synchronization fix — the single backend
        # source of truth for "is this item still awaiting a decision,"
        # the exact same TERMINAL_ITEM_STATUSES set reasoning_engine's
        # own open-item counts already use. Replaces a client-side list
        # (['closed', 'archived', 'cancelled', 'duplicate']) that was
        # missing 'fulfilled' — the status an APPROVED client_approval
        # item actually ends up in — which is why approved items kept
        # appearing as still pending. Only applies when status wasn't
        # explicitly requested, so the two filters can never silently
        # fight each other.
        q["status"] = {"$nin": list(TERMINAL_ITEM_STATUSES)}
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
                      target_start: Optional[str] = None,
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
        # Assignment Timeline (Canonical Event UX patch) — required_by is
        # reused as "Target Finish" (not renamed at the storage layer,
        # to avoid a migration; presented as Target Finish wherever this
        # patch's UI shows it). target_start is the one genuinely new
        # field this patch adds. Neither is duplicated onto a workflow
        # activity — an operational item's target timeline always lives
        # here, since (unlike events) operational items have no
        # activity_id linkage at all today.
        "required_by": required_by,
        "target_start": target_start,
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


async def find_open_item_for_event(event_id: str, *, category: str) -> Optional[dict]:
    """Client Approval Workflow — used to make request_client_approval
    idempotent. Deliberately category-scoped: an event can already have
    an unrelated item linked via inherited_evidence_event_id (e.g. the
    AI-unavailable fallback note, category "general" — see
    create_fallback_note_item below), which must never be mistaken for
    an existing approval request just because it points at the same
    event.
    """
    return await db.operational_items.find_one(
        {"inherited_evidence_event_id": event_id, "category": category},
        {"_id": 0},
    )


async def find_items_for_events(event_ids: list[str], *, category: str) -> dict[str, dict]:
    """Batch form of find_open_item_for_event, for the timeline (avoids
    an N+1 query per event when resolving each event's linked approval
    status)."""
    if not event_ids:
        return {}
    docs = await db.operational_items.find(
        {"inherited_evidence_event_id": {"$in": event_ids}, "category": category},
        {"_id": 0},
    ).to_list(len(event_ids))
    return {d["inherited_evidence_event_id"]: d for d in docs}


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


def resolve_target_timeline(target_start: Optional[str], target_finish: Optional[str],
                            duration_days: Optional[float]) -> tuple[Optional[str], Optional[str]]:
    """Assignment Timeline (Canonical Event UX patch) — 'Users may enter
    Start + Finish OR Start + Duration; Atlas derives the remaining
    value automatically.' A pure function, no DB access: given any two
    of the three inputs, derives the third; with fewer than two, returns
    what was given unchanged (nothing to derive). Both target_start and
    target_finish are ISO 8601 datetime strings.
    """
    ts = _parse_iso(target_start)
    tf = _parse_iso(target_finish)
    if ts and tf:
        return target_start, target_finish
    if ts and duration_days is not None:
        return target_start, _iso(ts + timedelta(days=duration_days))
    if tf and duration_days is not None:
        return _iso(tf - timedelta(days=duration_days)), target_finish
    return target_start, target_finish


async def set_target_timeline(*, item_id: str, actor: dict,
                              target_start: Optional[str] = None,
                              target_finish: Optional[str] = None,
                              duration_days: Optional[float] = None) -> dict:
    """Sets an operational item's target timeline (Target Start +
    required_by/'Target Finish'), deriving whichever of the two was not
    supplied directly from duration_days when possible — see
    resolve_target_timeline. Same ledger pattern as set_due/assign_item
    above (kind + prev/new status unchanged + payload), just generalized
    to cover start as well as finish in one call, matching 'an
    operational item is not fully assigned until both responsibility
    and target timeline are defined.'
    """
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    resolved_start, resolved_finish = resolve_target_timeline(target_start, target_finish, duration_days)
    # resolve_target_timeline only fills in what it can derive from what
    # was actually passed this call; a field neither passed nor
    # derivable must fall back to the item's current value, never be
    # silently cleared by a partial update (e.g. adjusting only the
    # finish date must not wipe an already-set start date).
    if resolved_start is None and target_start is None:
        resolved_start = item.get("target_start")
    if resolved_finish is None and target_finish is None:
        resolved_finish = item.get("required_by")
    ev = await append_event(item_id=item_id, kind="target_timeline_set", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload={"target_start": resolved_start, "required_by": resolved_finish,
                                     "duration_days": duration_days,
                                     "previous_target_start": item.get("target_start"),
                                     "previous_required_by": item.get("required_by")})
    item["target_start"] = resolved_start
    item["required_by"] = resolved_finish
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
EDITABLE_FIELDS = {"title", "description", "priority", "required_by", "target_start",
                   "quantity", "unit", "assigned_to_user_id", "approval_options"}


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
                            transcript: str,
                            audio_asset_id: Optional[str] = None,
                            summary: Optional[str] = None,
                            language: Optional[str] = None) -> dict:
    """Append a voice_update activity entry. The original asset (if any)
    stays linked via payload.audio_asset_id; transcript and AI summary
    are stored alongside so the activity feed can render them without
    re-running Whisper.

    FAC-OPS-06: audio_asset_id is now optional — a manually-typed text
    update (no recording at all) reuses this exact same function and
    ledger-entry shape, with audio_asset_id=None and transcript set
    directly to what was typed. There is no meaningful difference
    between "the text of what was said" and "the text that was typed"
    once it reaches this point, so there is no reason for two separate
    code paths.
    """
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


async def request_clarification(*, item_id: str, actor: dict, note: str) -> dict:
    """Client Approval Workflow — 'Request Clarification' is deliberately
    NOT a status transition: approve (fulfilled) and reject (cancelled)
    are the only two terminal decisions a client_approval item has
    (FAC-04's transition guard already enforces this). Clarification
    keeps the item exactly where it is — open, still awaiting the
    client's real decision — while making it clearly visible to the PM
    that the client has questions before they can decide. Reuses the
    same append-only ledger `voice_update_item` writes to (kind
    "clarification_requested"), not a new mechanism.
    """
    item = await get_item(item_id)
    if not item:
        raise ValueError("item not found")
    if item["category"] != "client_approval":
        raise ValueError("clarification can only be requested on a client approval item")
    ev = await append_event(item_id=item_id, kind="clarification_requested", actor=actor,
                            prev_status=item["status"], new_status=item["status"],
                            payload={"note": note})
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
    # AI Structured Extraction — quantity/unit were already extracted
    # alongside required_date/priority (both of which already flow
    # through above), just never carried onto the item's own fields.
    # Only at high confidence, and only here at creation time — this
    # never runs again later, so it can never clobber a value a human
    # has since entered or edited.
    extra: dict = {
        "suggested_owner_role": prop.get("suggested_owner_role"),
        "ai_details": details,
        "ai_confidence": prop.get("confidence"),
    }
    if prop.get("confidence") == "high":
        if "quantity" in edits:
            extra["quantity"] = edits["quantity"]
        elif details.get("quantity") is not None:
            extra["quantity"] = details["quantity"]
        if "unit" in edits:
            extra["unit"] = edits["unit"]
        elif details.get("unit"):
            extra["unit"] = details["unit"]
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
    if prop.get("decision") not in (None, "pending"):
        raise ValueError(f"proposal already {prop['decision']}")
    await update_ai_proposal_decision(proposal_id, decision="rejected", actor=actor,
                                      reason=reason)
    return {**prop, "decision": "rejected"}


# ---------------------------------------------------------------------------
# Personal Work Queue (Execution Experience Sprint 01, items 1 & 2).
#
# "What is assigned to me, what should I do next, what's urgent" - built
# entirely from data that already exists: operational items' own
# assigned_to_user_id/priority/required_by (unchanged), workflow
# activities' own status="ready" (dependency-resolved, unchanged), and
# memory_engine.list_projects' existing visibility scoping. No new
# entity, no new engine - a read composed from three things that were
# already there, the same way Portfolio Control Center composes CRE
# outputs rather than recomputing them.
#
# Workflow activities have no per-activity assignee field today (only
# operational items do) - "assigned to the supervisor" for an activity
# is expressed here as project-visibility scope (the supervisor can see
# it) combined with status="ready" (its prerequisites are actually
# done), not a fabricated per-activity assignment concept. This is a
# deliberate, documented scoping choice, not an oversight - adding a
# genuine per-activity assignee would be a schema change and a state-
# machine question ("assigned to the supervisor" as a NEW workflow
# state) that deserves its own deliberate pass, not one folded silently
# into a read-only queue endpoint.
# ---------------------------------------------------------------------------

_URGENCY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def _urgency_sort_key(item: dict) -> tuple:
    return (
        _URGENCY_RANK.get(item.get("priority"), 9),
        item.get("required_by") or "9999-99-99",
    )


async def my_day(*, user: dict) -> dict:
    """"My Day" (Execution Experience Sprint 02, item 6) — replaces the
    Sprint 01 work_queue with the full role-based execution dashboard.
    Every section is a read composed from data that already exists:
    operational items' own status/priority/required_by/assignment,
    workflow activities' own status/planned_finish and (new this
    sprint) real assignment via workflow_engine.assign_activity, and
    for Admin, Portfolio Control Center's own summary (reasoning_engine
    .portfolio_control_center) — reused directly, not recomputed a
    second way. No new engine, no duplicated health/urgency logic.
    """
    role = user["role"]
    projects = await memory_engine.list_projects(user=user)
    project_ids = [p["id"] for p in projects]
    now_iso = _iso(_now())
    today = now_iso[:10]

    if role == "site_supervisor":
        return await _my_day_supervisor(user, project_ids, now_iso, today)
    if role == "management":
        return await _my_day_admin(user)
    return await _my_day_pm(user, project_ids, now_iso)


async def _activities_assigned_to(user_id: str, project_ids: list[str]) -> list[dict]:
    return await db.workflow_activities.find(
        {"project_id": {"$in": project_ids}, "assigned_to_user_id": user_id}, {"_id": 0},
    ).sort("order", 1).to_list(300)


_RECENTLY_ASSIGNED_WINDOW_HOURS = 48


async def _my_day_supervisor(user: dict, project_ids: list[str], now_iso: str, today: str) -> dict:
    my_activities = await _activities_assigned_to(user["id"], project_ids)
    my_items = await list_items(assigned_to_user_id=user["id"], exclude_terminal=True, limit=300)
    await attach_names(my_items)

    ready_to_start = (
        [a for a in my_activities if a["status"] == "ready"] +
        [i for i in my_items if i["status"] in ("assigned", "acknowledged")]
    )
    in_progress = (
        [a for a in my_activities if a["status"] == "in_progress"] +
        [i for i in my_items if i["status"] == "in_progress"]
    )
    blocked = (
        [a for a in my_activities if a["status"] == "blocked"] +
        [i for i in my_items if i["status"] == "blocked"]
    )
    due_today = [
        a for a in my_activities
        if a.get("planned_finish") and str(a["planned_finish"])[:10] == today
    ] + [
        i for i in my_items
        if i.get("required_by") and str(i["required_by"])[:10] == today
    ]
    # Overdue — Beta-04: named explicitly alongside "Due today" in this
    # sprint's own "My Work" list but previously missing. Reuses the
    # exact same overdue-detection pattern PM's My Day already uses for
    # delayed_activities — an activity whose planned_finish has already
    # passed and isn't complete, or an item whose required_by has
    # already passed.
    overdue = [
        a for a in my_activities
        if a["status"] != "completed" and a.get("planned_finish") and str(a["planned_finish"]) < now_iso
    ] + [
        i for i in my_items
        if i.get("required_by") and str(i["required_by"]) < now_iso
    ]
    # Waiting for Material — the closest existing signal to a genuine
    # "this activity's dependency isn't in yet" concept: this
    # supervisor's own open material_requirement items. Not a new
    # allocation/inventory model, just what's already tracked.
    waiting_for_material = [i for i in my_items if i["category"] == "material_requirement"]

    cutoff = _iso(_now() - timedelta(hours=_RECENTLY_ASSIGNED_WINDOW_HOURS))
    recently_assigned = (
        [a for a in my_activities if a.get("assigned_at") and a["assigned_at"] >= cutoff] +
        [i for i in my_items if i.get("assigned_at") and i["assigned_at"] >= cutoff]
    )

    def _sorted(lst: list[dict]) -> list[dict]:
        return sorted(lst, key=_urgency_sort_key)

    return {
        "role": "site_supervisor",
        "ready_to_start": _sorted(ready_to_start),
        "in_progress": _sorted(in_progress),
        "due_today": _sorted(due_today),
        "overdue": _sorted(overdue),
        "blocked": _sorted(blocked),
        "waiting_for_material": _sorted(waiting_for_material),
        "recently_assigned": _sorted(recently_assigned),
    }


async def _flag_awaiting_clarification_response(items: list[dict]) -> None:
    """Beta-06G — mutates each item in place, adding
    awaiting_clarification_response: bool. A client_approval item is
    "awaiting response" when its own most recent event
    (last_derived_from_op_event_id, already set by every mutation
    including request_clarification and add_comment) is itself a
    clarification_requested — meaning nothing (no PM comment, no
    status change) has happened since the client asked. Reuses the
    item's own existing field and the existing operational_events
    ledger; adds no new event kind or data model. Batched into one
    query regardless of item count, not one query per item.
    """
    event_ids = [i["last_derived_from_op_event_id"] for i in items if i.get("last_derived_from_op_event_id")]
    if not event_ids:
        for i in items:
            i["awaiting_clarification_response"] = False
        return
    last_events = await db.operational_events.find(
        {"id": {"$in": event_ids}}, {"_id": 0, "id": 1, "kind": 1}).to_list(len(event_ids))
    kind_by_event_id = {e["id"]: e["kind"] for e in last_events}
    for i in items:
        last_id = i.get("last_derived_from_op_event_id")
        i["awaiting_clarification_response"] = kind_by_event_id.get(last_id) == "clarification_requested"


async def _my_day_pm(user: dict, project_ids: list[str], now_iso: str) -> dict:
    everything_open = await db.operational_items.find(
        {"status": {"$nin": list(TERMINAL_ITEM_STATUSES)}}, {"_id": 0},
    ).to_list(2000)
    in_scope = [i for i in everything_open if i.get("project_id") in project_ids]
    await attach_names(in_scope)

    delayed_activities = await db.workflow_activities.find(
        {"project_id": {"$in": project_ids}, "status": {"$nin": ["completed"]},
         "planned_finish": {"$ne": None, "$lt": now_iso}}, {"_id": 0},
    ).to_list(300)

    # Blocked workflow items — the same signal supervisor's own My Day
    # already surfaces, extended to PM (Beta-03): a PM needs to see
    # blocked work across every project they're not personally assigned
    # to just as much as a supervisor needs to see their own.
    blocked_activities = await db.workflow_activities.find(
        {"project_id": {"$in": project_ids}, "status": "blocked"}, {"_id": 0},
    ).to_list(300)

    # Upcoming inspections — activities flagged requires_inspection,
    # already in progress or ready, not yet covered by a real
    # inspection record. Reuses reasoning_projections.inspection_covered
    # directly, the exact function CRE's own quality.completed_without_inspection
    # rule already uses (STAB-01) — never a second, parallel check.
    from engines import reasoning_projections as projections
    candidate_activities = await db.workflow_activities.find(
        {"project_id": {"$in": project_ids}, "requires_inspection": True,
         "status": {"$in": ["ready", "in_progress"]}}, {"_id": 0},
    ).to_list(300)
    upcoming_inspections = []
    if candidate_activities:
        site_ids_by_project: dict[str, list[str]] = {}
        for pid in {a["project_id"] for a in candidate_activities}:
            sites = await memory_engine.list_sites(project_id=pid)
            site_ids_by_project[pid] = [s["id"] for s in sites]
        all_site_ids = [sid for ids in site_ids_by_project.values() for sid in ids]
        items_for_coverage = await db.operational_items.find(
            {"site_id": {"$in": all_site_ids}}, {"_id": 0}).to_list(2000)
        upcoming_inspections = [
            a for a in candidate_activities if not projections.inspection_covered(a, items_for_coverage)]

    # Commercial Awareness (Beta-03) — Commercial Workspace integrated
    # into My Day for the first time. Every project's own pending
    # Variations, unpaid Payment Requests, and next-sequence upcoming
    # Milestone, read directly from commercial_engine's own lists —
    # nothing here recalculates a cost, a status, or a due date.
    from engines import commercial_engine as ce
    pending_variations: list[dict] = []
    pending_payment_requests: list[dict] = []
    upcoming_milestones: list[dict] = []
    for pid in project_ids:
        variations = await ce.list_variations(pid)
        pending_variations.extend(v for v in variations if v["status"] in ("submitted", "client_review"))
        prs = await ce.list_payment_requests(pid)
        pending_payment_requests.extend(pr for pr in prs if pr["status"] not in ("paid", "cancelled"))
        milestones = await ce.list_milestones(pid)
        not_yet_achieved = sorted(
            (m for m in milestones if m["status"] in ("pending", "ready")),
            key=lambda m: m["sequence"])
        if not_yet_achieved:
            upcoming_milestones.append(not_yet_achieved[0])

    pending_approvals = [i for i in in_scope if i["category"] == "client_approval"]
    await _flag_awaiting_clarification_response(pending_approvals)
    high_priority = [i for i in in_scope if i["priority"] in ("critical", "high")]
    # Escalations — the same "genuinely urgent, needs a human now" signal
    # as High Priority Work, surfaced as its own named section per the
    # brief. Not a distinct workflow state (the standalone /escalate
    # endpoint this used to be was removed as redundant with priority
    # editing in the Platform Consolidation Sprint) — critical-priority
    # items are that same signal, reused rather than reinvented.
    escalations = [i for i in in_scope if i["priority"] == "critical"]

    projects_requiring_attention_ids = {i["project_id"] for i in in_scope if i["priority"] == "critical"}
    projects_requiring_attention_ids |= {a["project_id"] for a in delayed_activities}

    return {
        "role": user["role"],
        "projects_requiring_attention": len(projects_requiring_attention_ids),
        "delayed_activities": sorted(delayed_activities, key=lambda a: a.get("planned_finish") or ""),
        "blocked_activities": blocked_activities,
        "open_operational_items_count": len(in_scope),
        "upcoming_inspections": upcoming_inspections,
        "pending_approvals": sorted(pending_approvals, key=_urgency_sort_key),
        "high_priority_work": sorted(high_priority, key=_urgency_sort_key),
        "escalations": sorted(escalations, key=_urgency_sort_key),
        "pending_variations": pending_variations,
        "pending_payment_requests": pending_payment_requests,
        "upcoming_milestones": upcoming_milestones,
    }


# ---------------------------------------------------------------------------
# Daily Review (Beta-03 continuation) — the end-of-day mirror of My Day's
# start-of-day view. Every section here is a read composed from data
# that already exists, matching My Day's own established convention:
# nothing is calculated a new way, nothing is a duplicate of an
# existing engine's own logic. Available to management and project
# manager (the same roles My Day already serves); not available to
# client or supervisor — supervisor's own day is scoped to personal
# assignments (My Day already covers that), and an end-of-day
# portfolio-wide review is a PM/management concern, not a site-level one.
# ---------------------------------------------------------------------------

async def daily_review(*, user: dict) -> dict:
    """Answers exactly the questions this sprint's brief names: what
    finished today, what remains open, what slipped, what became
    blocked, which inspections/approvals/commercial actions remain,
    and which projects need attention tomorrow. Reuses My Day's own
    query patterns directly (the "slipped"/"blocked"/"inspections
    remaining"/"commercial actions remaining" sections are the exact
    same underlying data My Day's own delayed/blocked/inspections/
    commercial sections already compute) rather than inventing a
    second way to ask the same questions.
    """
    if user["role"] not in ("management", "project_manager"):
        raise ValueError("Daily Review is available to management and project manager only.")

    projects = await memory_engine.list_projects(user=user)
    project_ids = [p["id"] for p in projects]
    now = _now()
    today_start = _iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
    now_iso = _iso(now)

    # What finished today — workflow activities completed today, and
    # operational items fulfilled/verified/closed today. "Today" is
    # each entity's own updated_at crossing today_start, not a new
    # timestamp concept.
    completed_activities_today = await db.workflow_activities.find(
        {"project_id": {"$in": project_ids}, "status": "completed",
         "updated_at": {"$gte": today_start}}, {"_id": 0},
    ).to_list(300)
    resolved_items_today = await db.operational_items.find(
        {"project_id": {"$in": project_ids}, "status": {"$in": ["fulfilled", "verified", "closed"]},
         "last_updated_at": {"$gte": today_start}}, {"_id": 0},
    ).to_list(300)
    await attach_names(resolved_items_today)

    # What became blocked today — the same "blocked" signal PM's My Day
    # already surfaces, filtered to today's own updated_at.
    newly_blocked_today = await db.workflow_activities.find(
        {"project_id": {"$in": project_ids}, "status": "blocked",
         "updated_at": {"$gte": today_start}}, {"_id": 0},
    ).to_list(300)

    # What remains open / what slipped — the exact same queries PM's My
    # Day already runs for delayed_activities and open operational
    # items; reused directly, not recomputed a second way.
    everything_open = await db.operational_items.find(
        {"status": {"$nin": list(TERMINAL_ITEM_STATUSES)}}, {"_id": 0},
    ).to_list(2000)
    in_scope_open = [i for i in everything_open if i.get("project_id") in project_ids]
    slipped_activities = await db.workflow_activities.find(
        {"project_id": {"$in": project_ids}, "status": {"$nin": ["completed"]},
         "planned_finish": {"$ne": None, "$lt": now_iso}}, {"_id": 0},
    ).to_list(300)

    # Inspections / approvals / commercial actions remaining — reusing
    # My Day's own PM computation directly rather than a second
    # implementation of the same three sections.
    my_day_pm = await _my_day_pm(user, project_ids, now_iso)

    projects_requiring_attention_ids = {i["project_id"] for i in in_scope_open if i["priority"] == "critical"}
    projects_requiring_attention_ids |= {a["project_id"] for a in slipped_activities}

    return {
        "role": user["role"],
        "finished_today": {
            "activities": sorted(completed_activities_today, key=lambda a: a.get("updated_at") or ""),
            "operational_items": sorted(resolved_items_today, key=lambda i: i.get("last_updated_at") or ""),
        },
        "remains_open_count": len(in_scope_open),
        "slipped_activities": sorted(slipped_activities, key=lambda a: a.get("planned_finish") or ""),
        "newly_blocked_today": newly_blocked_today,
        "inspections_remaining": my_day_pm["upcoming_inspections"],
        "approvals_remaining": my_day_pm["pending_approvals"],
        "commercial_actions_remaining": {
            "pending_variations": my_day_pm["pending_variations"],
            "pending_payment_requests": my_day_pm["pending_payment_requests"],
        },
        "projects_requiring_attention_tomorrow": len(projects_requiring_attention_ids),
    }


# ---------------------------------------------------------------------------
# Site Progress (Beta-04) — "one operational story" for a single
# project: today's work, completed work, current issues, latest
# updates, inspection status. Every section reuses an existing engine
# directly - timeline_engine.for_site for captures (never a second
# Timeline implementation), the same inspection-coverage check My
# Day/Daily Review already use, the same open-items and workflow
# queries used throughout this module. Available to management,
# project_manager, and site_supervisor - a supervisor reviewing their
# own site's story is exactly the intended use; not available to
# client (Client Experience has its own, separate Photos/Timeline
# views built in CX-01).
# ---------------------------------------------------------------------------

async def site_progress(project_id: str, *, user: dict) -> dict:
    """Composes Reality Engine captures, Workflow completions,
    Operations issues, and inspection status into a single chronological
    story for one project. Reuses timeline_engine.for_site directly for
    captures - never a duplicate Timeline read."""
    if user["role"] == "client":
        raise ValueError("Site Progress is not available to the client role - see Client Experience instead.")
    project = await memory_engine.get_project(project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found")
    if memory_engine._is_project_scoped(user) and project_id not in (user.get("assigned_project_ids") or []):
        raise ValueError(f"Project '{project_id}' not found")

    from engines import timeline_engine
    sites = await memory_engine.list_sites(project_id=project_id)
    site_ids = [s["id"] for s in sites]

    latest_updates: list[dict] = []
    for site_id in site_ids:
        latest_updates.extend(await timeline_engine.for_site(site_id, limit=20))
    latest_updates.sort(key=lambda i: i["event"]["server_created_at"], reverse=True)
    latest_updates = latest_updates[:20]

    now = _now()
    today_start = _iso(now.replace(hour=0, minute=0, second=0, microsecond=0))
    now_iso = _iso(now)

    todays_work = await db.workflow_activities.find(
        {"project_id": project_id, "status": {"$in": ["ready", "in_progress"]}}, {"_id": 0},
    ).to_list(300)
    completed_recently = await db.workflow_activities.find(
        {"project_id": project_id, "status": "completed", "updated_at": {"$gte": today_start}}, {"_id": 0},
    ).to_list(300)

    all_open = await db.operational_items.find(
        {"project_id": project_id, "status": {"$nin": list(TERMINAL_ITEM_STATUSES)}}, {"_id": 0},
    ).to_list(500)
    await attach_names(all_open)
    current_issues = [i for i in all_open if i["priority"] in ("critical", "high")]

    # Inspection status — the exact same coverage check My Day and
    # Daily Review already use, scoped to this one project.
    from engines import reasoning_projections as projections
    candidate_activities = await db.workflow_activities.find(
        {"project_id": project_id, "requires_inspection": True,
         "status": {"$in": ["ready", "in_progress"]}}, {"_id": 0},
    ).to_list(300)
    inspections_pending = []
    if candidate_activities:
        items_for_coverage = await db.operational_items.find(
            {"site_id": {"$in": site_ids}}, {"_id": 0}).to_list(2000)
        inspections_pending = [
            a for a in candidate_activities if not projections.inspection_covered(a, items_for_coverage)]

    return {
        "project_id": project_id,
        "project_name": project["name"],
        "todays_work": todays_work,
        "completed_recently": sorted(completed_recently, key=lambda a: a.get("updated_at") or "", reverse=True),
        "current_issues": sorted(current_issues, key=_urgency_sort_key),
        "latest_updates": latest_updates,
        "inspections_pending": inspections_pending,
        "open_items_count": len(all_open),
    }


async def _my_day_admin(user: dict) -> dict:
    # Admin's Portfolio Health / Delayed Projects / Critical Issues /
    # Pending Approvals are Portfolio Control Center's own summary and
    # rows, reused directly — not a second computation of the same
    # numbers. Local import to avoid a module-load-order dependency
    # between operations_engine and reasoning_engine (reasoning_engine
    # never imports operations_engine, so this direction is safe, but
    # importing at call time rather than module scope keeps that
    # asymmetry explicit rather than assumed).
    from engines import reasoning_engine
    portfolio = await reasoning_engine.portfolio_control_center(user=user)
    delayed_projects = [
        r for r in portfolio["projects"]
        if r["schedule_variance_days"] is not None and r["schedule_variance_days"] > 0
    ]

    # Resource Alerts — no equipment/manpower allocation model exists in
    # Atlas today, so this is the closest honest proxy: open material
    # and equipment requirement items across the portfolio. Documented
    # here rather than silently presented as a real resource-planning
    # signal.
    everything_open = await db.operational_items.find(
        {"status": {"$nin": list(TERMINAL_ITEM_STATUSES)},
         "category": {"$in": ["material_requirement", "equipment_requirement"]}},
        {"_id": 0},
    ).to_list(500)

    return {
        "role": "management",
        "portfolio_health": portfolio["summary"],
        "delayed_projects": delayed_projects,
        "critical_issues": portfolio["summary"]["critical_operational_items"],
        "pending_approvals": portfolio["summary"]["pending_client_approvals"],
        "resource_alerts": len(everything_open),
    }


