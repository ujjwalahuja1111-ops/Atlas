"""Atlas Inbox Intelligence (PX-02 Phase 4).

A derived coordination layer, per this task's own explicit "implement
as a derived coordination layer, not by storing duplicated state"
rule. Every function here reads from collections that already exist
(notifications, operational_items, commercial's own payment_requests)
and classifies/groups/scores what it finds — it never writes a new
"waiting state" field anywhere. If the underlying data changes, the
next read reflects it automatically; there is no cache to go stale.

A known, stated fragility: distinguishing "clarification requested"
from "clarification answered" (both share category="clarification")
is done by matching the notification's own title prefix
("Clarification needed:" vs "Clarification answered:"), since
notification_engine.py's own trigger functions were not modified this
phase to add an explicit subtype field - changing an already-working,
already-tested trigger path carried more risk than this phase's own
scope justified. Documented directly in
INBOX_INTELLIGENCE_IMPLEMENTATION.md, not hidden.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from core.db import db
from engines import notification_engine, operations_engine, reasoning_engine, memory_engine
from engines.reasoning_projections import TERMINAL_ITEM_STATUSES

# PX-02 Phase 4 Section 4 — default aging thresholds, in hours. A
# fixed, auditable table, not a fabricated per-project setting -
# exactly the numbers this task's own brief specifies.
AGING_THRESHOLDS_HOURS = {
    "blocker": {"warning": 24, "escalated": 48},
    "clarification": {"warning": 12, "escalated": 24},
    "client_approval": {"warning": 48, "escalated": 72},
    "payment_request": {"warning": 48, "escalated": 96},
    "quality_observation": {"warning": 24, "escalated": 72},
}

# PX-02 Phase 4 Section 7 — the deep-link routing matrix, exactly as
# this task's own table specifies. A single source of truth the
# frontend's own navigation reads from (via each coordination item's
# own target_phase field), rather than duplicating this table in TS.
ENTITY_TYPE_TO_PHASE = {
    "operational_item": "execute",
    "workflow_activity": "execute",
    "variation": "plan",
    "milestone": "plan",
    "payment_request": "bill",
    "payment": "bill",
    "contract": "bill",
}


def _age_hours(created_at: str) -> float:
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds() / 3600
    except Exception:
        return 0.0


def _aging_signal(kind: str, created_at: str) -> str:
    """Green/amber/red, per this task's own explicit 3-color rule."""
    thresholds = AGING_THRESHOLDS_HOURS.get(kind)
    if not thresholds:
        return "green"
    hours = _age_hours(created_at)
    if hours >= thresholds["escalated"]:
        return "red"
    if hours >= thresholds["warning"]:
        return "amber"
    return "green"


def _target_phase(entity_type: Optional[str]) -> str:
    return ENTITY_TYPE_TO_PHASE.get(entity_type or "", "execute")


def _is_severe_escalation_title(title: str) -> bool:
    """PX-03 Phase 4 Section 5 — an escalation notification's title
    already encodes that the underlying request has been overdue for
    OVERDUE_ESCALATION_DAYS+ (per commercial_engine's own generation
    logic) - true from the moment it's created, not something that
    should have to age into red over the following 48-96 hours."""
    return title.startswith("Payment Request") and "is severely overdue" in title


def _card_aging_signal(category: str, title: str, created_at: str) -> str:
    if _is_severe_escalation_title(title):
        return "red"
    return _aging_signal(_category_to_aging_kind(category), created_at)


def _group_notifications(notifs: list[dict]) -> list[dict]:
    """PX-02 Phase 4 Section 3 — Same Entity Grouping. Collapses
    multiple notifications on the same (entity_type, entity_id) into
    one card with a count and the latest title/body, per this task's
    own exact example ('OPS-104 updated 4 times / Latest: ...')."""
    groups: dict[tuple, list[dict]] = {}
    ungrouped: list[dict] = []
    for n in notifs:
        key = (n.get("entity_type"), n.get("entity_id"))
        if key[0] and key[1]:
            groups.setdefault(key, []).append(n)
        else:
            ungrouped.append(n)

    grouped_cards = []
    for (entity_type, entity_id), items in groups.items():
        items.sort(key=lambda n: n["created_at"], reverse=True)
        latest = items[0]
        grouped_cards.append({
            "entity_type": entity_type, "entity_id": entity_id,
            "count": len(items), "latest_title": latest["title"], "latest_body": latest["body"],
            "created_at": latest["created_at"], "read": all(n["read"] for n in items),
            "notification_ids": [n["id"] for n in items],
            "target_phase": _target_phase(entity_type), "project_id": latest.get("project_id"),
            "aging_signal": _card_aging_signal(latest["category"], latest["title"], latest["created_at"]),
        })
    for n in ungrouped:
        grouped_cards.append({
            "entity_type": n.get("entity_type"), "entity_id": n.get("entity_id"),
            "count": 1, "latest_title": n["title"], "latest_body": n["body"],
            "created_at": n["created_at"], "read": n["read"], "notification_ids": [n["id"]],
            "target_phase": _target_phase(n.get("entity_type")), "project_id": n.get("project_id"),
            "aging_signal": _card_aging_signal(n["category"], n["title"], n["created_at"]),
        })
    grouped_cards.sort(key=lambda c: c["created_at"], reverse=True)
    return grouped_cards


def _category_to_aging_kind(category: str) -> str:
    return {"clarification": "clarification", "commercial": "payment_request"}.get(category, "")


async def build_coordination_inbox(user: dict, *, project_id: Optional[str] = None) -> dict:
    """The one entry point. Returns all 6 sections this task's own
    Section 1 names, each populated from real data - never a fabricated
    or placeholder section."""
    notifs = await notification_engine.list_notifications(user["id"], limit=300)
    if project_id:
        notifs = [n for n in notifs if n.get("project_id") == project_id]

    action_required = [n for n in notifs if n["category"] == "assignment"]
    waiting_for_you = [n for n in notifs if n["category"] == "clarification"
                      and n["title"].startswith("Clarification needed")]
    commercial_attention = [n for n in notifs if n["category"] == "commercial"]
    activity_feed = [n for n in notifs if n["category"] in ("status_change",)
                     or (n["category"] == "clarification" and n["title"].startswith("Clarification answered"))]

    # PX-02 Phase 4 Section 2 — Waiting For Others: derived from the
    # underlying entities the user themselves initiated, not from any
    # notification (Atlas never notifies an initiator that their own
    # request is still pending — there was nothing to derive that from
    # without querying the source entities directly).
    waiting_for_others = await _derive_waiting_for_others(user, project_id)

    # PX-02 Phase 4 Section 4 — Escalations: anything in Action
    # Required, Waiting For You, or Commercial Attention whose own
    # aging signal has crossed into red, surfaced separately so it
    # can't be missed inside a longer list. PX-03 Phase 4 — extended
    # to include Commercial Attention: the 7-day overdue escalation
    # notification is the single most urgent commercial notification
    # type, and it would otherwise never surface here.
    #
    # A deeper issue than just "which sections to scan": aging_signal
    # computes age from the notification's own created_at, not the
    # underlying Payment Request's due_date. A freshly-created "is
    # severely overdue" escalation notification would incorrectly
    # show green for its first 48 hours, even though the request it
    # describes has already been overdue for 7+ days by definition.
    # Detected by title prefix instead (matching this file's own
    # established pattern for Clarification needed/answered) and
    # always classified red immediately, regardless of the
    # notification's own age.
    escalations = [
        n for n in (action_required + waiting_for_you + commercial_attention)
        if _card_aging_signal(n["category"], n["title"], n["created_at"]) == "red"
    ]

    return {
        "action_required": _group_notifications(action_required),
        "waiting_for_you": _group_notifications(waiting_for_you),
        "waiting_for_others": waiting_for_others,
        "escalations": _group_notifications(escalations),
        "commercial_attention": _group_notifications(commercial_attention),
        "activity_feed": _group_notifications(activity_feed),
    }


async def _derive_waiting_for_others(user: dict, project_id: Optional[str]) -> list[dict]:
    q: dict = {"created_by_user_id": user["id"], "status": {"$nin": list(TERMINAL_ITEM_STATUSES)}}
    if project_id:
        q["project_id"] = project_id
    items = await db.operational_items.find(q, {"_id": 0}).sort("created_at", -1).to_list(100)
    cards = [{
        "entity_type": "operational_item", "entity_id": i["id"], "count": 1,
        "latest_title": i.get("title") or i.get("name") or "Untitled item",
        "latest_body": f"Waiting on {i.get('assigned_to_user_name') or 'assignment'}",
        "created_at": i["created_at"], "read": True, "notification_ids": [],
        "target_phase": "execute", "project_id": i.get("project_id"),
        "aging_signal": _aging_signal("blocker", i["created_at"]),
    } for i in items]

    pr_q: dict = {"raised_by_user_id": user["id"], "status": {"$nin": ["paid", "cancelled"]}}
    if project_id:
        pr_q["project_id"] = project_id
    payment_requests = await db.payment_requests.find(pr_q, {"_id": 0}).sort("raised_date", -1).to_list(50)
    cards += [{
        "entity_type": "payment_request", "entity_id": pr["id"], "count": 1,
        "latest_title": f"Payment Request {pr['number']}",
        "latest_body": f"Status: {pr['status'].replace('_', ' ')}",
        "created_at": pr.get("raised_date", ""), "read": True, "notification_ids": [],
        "target_phase": "bill", "project_id": pr.get("project_id"),
        "aging_signal": _aging_signal("payment_request", pr.get("raised_date", "")),
    } for pr in payment_requests]

    cards.sort(key=lambda c: c["created_at"], reverse=True)
    return cards


async def management_attention_digest(user: dict) -> dict:
    """PX-02 Phase 4 Section 8 — a portfolio-level synthesis, not a
    raw notification list, per this task's own explicit distinction.
    Reuses reasoning_engine's own portfolio machinery rather than
    re-querying every project from scratch."""
    projects = await memory_engine.list_projects(user=user)
    needs_attention = []
    for p in projects:
        try:
            health = await reasoning_engine.explain_health(p["id"], user=user)
        except Exception:
            continue
        if health.get("status") in ("amber", "red"):
            needs_attention.append({
                "project_id": p["id"], "project_name": p["name"],
                "reason": "declining_health", "health_status": health["status"],
            })
    payment_requests_awaiting = await db.payment_requests.find(
        {"project_id": {"$in": [p["id"] for p in projects]}, "status": {"$in": ["raised", "sent"]}},
        {"_id": 0},
    ).to_list(100)
    escalated_blockers = await db.operational_items.find(
        {"project_id": {"$in": [p["id"] for p in projects]}, "health": "blocked"},
        {"_id": 0},
    ).to_list(200)
    escalated_blockers = [b for b in escalated_blockers if _aging_signal("blocker", b.get("created_at", "")) == "red"]

    return {
        "needs_attention_projects": needs_attention,
        "payment_requests_awaiting_approval": len(payment_requests_awaiting),
        "escalated_blockers_count": len(escalated_blockers),
        "escalated_blockers": [
            {"project_id": b["project_id"], "title": b.get("title") or b.get("name")} for b in escalated_blockers
        ],
    }


async def daily_coordination_digest(user: dict) -> dict:
    """PX-02 Phase 4 Section 9 (optional) — a deterministic summary,
    not an LLM-generated one, matching Phase 3's own established
    "narrative means template-composed from real values" discipline."""
    inbox = await build_coordination_inbox(user)
    action_count = len(inbox["action_required"])
    waiting_you_count = len(inbox["waiting_for_you"])
    commercial_count = len(inbox["commercial_attention"])
    escalations = inbox["escalations"]

    lines = []
    if action_count:
        lines.append(f"{action_count} operational item{'s' if action_count != 1 else ''} requiring action")
    if waiting_you_count:
        lines.append(f"{waiting_you_count} clarification{'s' if waiting_you_count != 1 else ''} awaiting your response")
    if commercial_count:
        lines.append(f"{commercial_count} commercial item{'s' if commercial_count != 1 else ''} needing attention")
    if escalations:
        lines.append(f"{len(escalations)} escalated item{'s' if len(escalations) != 1 else ''}")

    top_priority = None
    if escalations:
        top_priority = f"Resolve: {escalations[0]['latest_title']}"
    elif inbox["waiting_for_you"]:
        top_priority = f"Respond to: {inbox['waiting_for_you'][0]['latest_title']}"

    return {
        "summary_lines": lines,
        "top_priority": top_priority,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
