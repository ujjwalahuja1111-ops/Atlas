"""Construction Reasoning Engine (CRE) — Innovation Sprints 01 / 01A.

Atlas already captures reality (Reality Engine), understands single
utterances (Intelligence Engine), tracks obligations (Operations Engine),
and knows how construction is supposed to flow (Knowledge Core +
Construction Workflow Engine). CRE is the layer that looks at ALL of it
for a project and answers: "what does everything happening here
collectively mean, and what should a human do next?" — engine slot #7 in
memory/ARCHITECTURE.md.

The canonical description of what CRE is, what it may do, and — more
importantly — what it must never become, lives in memory/CRE_ARCHITECTURE.md.
The short form of the boundary:

    CRE IS a deterministic construction reasoning layer that produces
    evidence-backed, explainable recommendations for humans to decide on.

    CRE IS NOT, and must never evolve into, a general LLM agent. AI may
    enhance explanation and summarization of deterministic findings; it
    must never replace deterministic project reasoning, never suggest
    operational actions, and never gain execution ability.

Structural guarantees (each enforced in code and pinned by tests):

1.  READ-ONLY over every other engine's data. CRE writes ONLY to its own
    collections (`reasoning_insights`, `reasoning_runs`). It cannot
    execute work — structurally, not merely by instruction.

2.  REASON FIRST, AI SECOND. The product is a registry of small, PURE
    rule functions (`snapshot -> findings`): no I/O, no Mongo, no
    network. The optional LLM pass is additive, off by default, off
    without a key, failure-isolated, capped — and (Sprint 01A) its
    findings carry NO suggested operational action, role, or due date:
    only deterministic rules may propose operational next steps.

3.  EVERY insight is explainable (Sprint 01A schema v2). It answers
    "why did CRE reach this conclusion?" through:
      * an explicit, always-present EVIDENCE section — typed references
        to the workflow activities, operational items, events, media,
        approvals and knowledge items it reasoned over, plus explicit
        ABSENCES (what was looked for and not found);
      * a structured CONFIDENCE object — level, reason, missing
        evidence, assumptions, contradictory evidence;
      * a full reasoning chain — observation -> risk -> recommendation
        -> suggested operational action -> suggested responsible role
        -> suggested due date. All "suggested_*" fields are inert data
        for a human (or a future one-tap conversion flow) to act on;
        nothing in this engine reads them back or executes them.

4.  IDEMPOTENT RUNS. Findings carry a deterministic `dedupe_key`; an
    open insight with the same key is refreshed (`times_seen`,
    `last_seen_at`), never duplicated. A resolved key is free again —
    recurrence emits a FRESH insight, auto-linked to its predecessor
    with a `previous` relationship (Sprint 01A) so reasoning history
    forms a chain instead of resurrecting closed decisions.

5.  NO HARDCODED CONSTRUCTION SEQUENCES. Construction-logic rules
    generalize over the dependency graph the admin curated in the
    Knowledge Core (denormalized per-project by workflow_engine). CRE
    gets smarter as the Knowledge Core grows, for free.

6.  STABLE KNOWLEDGE INTERFACE (Sprint 01A). Rules never poke raw
    schema keys for knowledge-derived facts; they go through the
    accessor helpers in the "knowledge interface" section below, and
    all Mongo reads happen in exactly one function
    (build_project_snapshot). When the Knowledge Core or upstream
    schemas evolve, those two spots are the only ones that change.

Insight lifecycle — canonical for all future intelligence modules:

    open -> acknowledged -> operational_item_created -> resolved
    open/acknowledged -> dismissed
    (expired: system-set terminal state for insights whose conditions
     age out — reserved)

  Implemented today: open -> acknowledged -> actioned | dismissed, where
  `actioned` is the current implementation of canonical `resolved`.
  `operational_item_created` arrives with the V2 insight->item conversion
  flow; `expired` with scheduled runs. Reopening is deliberately not
  supported — recurrence emits a fresh, `previous`-linked insight.

Human feedback (Sprint 01A — model preparation only, NO learning):
  every insight can record a human verdict — accepted / rejected /
  modified / ignored — with optional reasoning, kept in
  `feedback_history`. A future learning layer consumes this; nothing in
  this sprint reads it back.

Collections owned by CRE:
    reasoning_insights  one doc per distinct open finding (schema v2);
                        status changes append to in-doc `status_history`.
    reasoning_runs      append-only audit of every reasoning pass.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import timedelta
from typing import Callable, Optional

from core.db import db
from core.settings import EMERGENT_LLM_KEY
from engines import memory_engine
from engines import reasoning_projections as projections
from engines.reasoning_projections import (_iso, _now, _parse_iso, snapshot_now)

logger = logging.getLogger(__name__)

INSIGHT_SCHEMA_VERSION = 2
SNAPSHOT_SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Construction domains. Every rule belongs to exactly one (enforced at
# registration + evaluation). `commercial`, `documentation` and
# `resource_planning` are declared metadata-only for now: reserved,
# rule-less, so future rules land in an already-agreed taxonomy.
DOMAINS = {
    "schedule", "construction_logic", "quality", "safety",
    "procurement", "client_communication", "management",
    "commercial", "documentation", "resource_planning",
    "ai_observation",
}
CONFIDENCE_LEVELS = ["low", "medium", "high"]
SEVERITIES = ["info", "advisory", "warning", "critical"]
INSIGHT_STATUSES = {"open", "acknowledged", "actioned", "dismissed"}
# Canonical lifecycle for future intelligence modules (see module
# docstring); states not yet reachable in code are listed reserved.
CANONICAL_LIFECYCLE = [
    "open", "acknowledged", "operational_item_created",
    "resolved", "dismissed", "expired",
]
_ALLOWED_TRANSITIONS = {
    "open": {"acknowledged", "actioned", "dismissed"},
    "acknowledged": {"actioned", "dismissed"},
    "actioned": set(),
    "dismissed": set(),
}

# Evidence: the seven always-present sections of every insight's
# evidence object. `absences` holds negative evidence — what CRE looked
# for and did not find (essential for explaining inference rules).
EVIDENCE_KINDS = [
    "workflow_activities", "operational_items", "events",
    "media", "approvals", "knowledge_items", "absences",
]

# Human feedback verdicts (learning-layer preparation; write-only today).
FEEDBACK_VERDICTS = {"accepted", "rejected", "modified", "ignored"}

# Insight-to-insight relationships (multi-step reasoning preparation).
RELATION_TYPES = {"previous", "duplicate", "supports", "conflicts"}

# Suggestion vocabulary. Suggested actions reuse the Operations Engine's
# existing category vocabulary; suggested roles are exactly the internal
# roles of FAC-04's frozen model (memory_engine.ROLES minus client) — a
# guard test pins this so the two can never drift.
SUGGESTED_ROLES = {"site_supervisor", "project_manager", "management"}
_DUE_DAYS_BY_SEVERITY = {"critical": 1, "warning": 3, "advisory": 7, "info": 14}

# Tunables
STALLED_SUCCESSOR_DAYS = 3
MATERIAL_LEAD_TIME_DAYS = 3
STALE_ITEM_DAYS = 7
SAFETY_UNRESOLVED_HOURS = 24
MILESTONE_WINDOW_DAYS = 7


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


class ReasoningError(ValueError):
    """Subclasses ValueError so routes reuse the `_raise_for()` convention."""


class ReasoningNotFoundError(ReasoningError):
    pass


class InvalidInsightTransitionError(ReasoningError):
    pass


async def _assert_project_visible(project_id: str, user: dict) -> dict:
    """Same convention as workflow_engine._assert_project_visible:
    out-of-scope projects behave as if they do not exist (404, not 403)."""
    project = await memory_engine.get_project(project_id)
    if not project:
        raise ReasoningNotFoundError(f"Project '{project_id}' not found")
    if memory_engine._is_project_scoped(user):
        if project_id not in (user.get("assigned_project_ids") or []):
            raise ReasoningNotFoundError(f"Project '{project_id}' not found")
    return project


# ---------------------------------------------------------------------------
# Knowledge interface (Sprint 01A) — the ONLY way rules read
# knowledge-derived facts off snapshot documents. If the Knowledge Core
# or the workflow denormalization changes shape, these accessors change;
# the rules do not.
# ---------------------------------------------------------------------------

def _act_requires_inspection(activity: dict) -> bool:
    return bool(activity.get("requires_inspection"))


def _act_dependency_ids(activity: dict) -> list[str]:
    return list(activity.get("depends_on_activity_ids") or [])


def _act_knowledge_ref(activity: dict) -> Optional[str]:
    """Traceability link back to the Activity Library item this workflow
    activity was generated from."""
    return activity.get("knowledge_activity_id")


# ---------------------------------------------------------------------------
# Snapshot layer — the ONLY place CRE touches Mongo for reads.
# ---------------------------------------------------------------------------

async def build_project_snapshot(project_id: str) -> dict:
    """One read-only, plain-dict view of everything CRE reasons over.
    Rules never query the database — they see exactly this snapshot,
    which keeps them pure and makes every reasoning pass reproducible.

    The snapshot IS the stable interface between Atlas' data layer and
    the reasoning layer: upstream schema changes are absorbed here (and
    in the knowledge accessors above), never inside rules."""
    project = await memory_engine.get_project(project_id)
    sites = await db.sites.find(
        {"project_id": project_id}, {"_id": 0}).to_list(500)
    site_ids = [s["id"] for s in sites]

    activities = await db.workflow_activities.find(
        {"project_id": project_id}, {"_id": 0}).sort("order", 1).to_list(1000)

    items = await db.operational_items.find(
        {"$or": [{"project_id": project_id}, {"site_id": {"$in": site_ids}}]},
        {"_id": 0},
    ).to_list(2000)

    events = await db.events.find(
        {"site_id": {"$in": site_ids}},
        {"_id": 0, "id": 1, "site_id": 1, "type": 1, "ai_status": 1,
         "server_created_at": 1, "activity_id": 1},
    ).sort("server_created_at", -1).to_list(500)

    # Media corroboration: raw asset refs for events that are linked to a
    # workflow activity (events.activity_id — Sprint 6.1's reserved join).
    linked_event_ids = [e["id"] for e in events if e.get("activity_id")]
    event_assets: dict[str, list[str]] = {}
    if linked_event_ids:
        assets = await db.raw_assets.find(
            {"event_id": {"$in": linked_event_ids}},
            {"_id": 0, "id": 1, "event_id": 1, "kind": 1},
        ).to_list(1000)
        for a in assets:
            event_assets.setdefault(a["event_id"], []).append(a["id"])

    # Human decisions on AI proposals — available to rules as approval
    # evidence (interface wired now; consumed as rules need it).
    proposals = await db.ai_proposals.find(
        {"event_id": {"$in": [e["id"] for e in events]}} if events else {"id": None},
        {"_id": 0, "id": 1, "event_id": 1, "status": 1, "category": 1,
         "decided_by_user_name": 1, "decided_at": 1},
    ).to_list(1000) if events else []

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": _iso(_now()),
        "project": project or {"id": project_id},
        "sites": sites,
        "workflow_activities": activities,
        "operational_items": items,
        "recent_events": events,
        "event_assets": event_assets,
        "recent_proposals": proposals,
        # Sprint 01B: stage awareness — every reasoning pass knows where
        # the project is in its lifecycle (derived deterministically from
        # the workflow itself; see projections.infer_project_stage).
        "stage": projections.infer_project_stage(activities),
    }


# ---------------------------------------------------------------------------
# Finding construction — the schema-v2 insight contract
# ---------------------------------------------------------------------------

def _ref(id_: Optional[str], detail: str) -> dict:
    return {"id": id_, "detail": detail}


def _evidence(*, workflow_activities=(), operational_items=(), events=(),
              media=(), approvals=(), knowledge_items=(), absences=()) -> dict:
    """Build the explicit evidence section. Every kind is ALWAYS present
    (possibly empty) so consumers — human or UI — see exactly what was
    and wasn't considered. `absences` entries are negative evidence:
    what CRE searched for and did not find."""
    ev = {
        "workflow_activities": list(workflow_activities),
        "operational_items": list(operational_items),
        "events": list(events),
        "media": list(media),
        "approvals": list(approvals),
        "knowledge_items": list(knowledge_items),
        "absences": list(absences),
    }
    assert list(ev.keys()) == EVIDENCE_KINDS
    return ev


def _confidence(level: str, reason: str, *, missing_evidence=(),
                assumptions=(), contradictions=()) -> dict:
    """Structured, explainable confidence. `reason` answers "why did CRE
    reach this conclusion at this confidence"; `missing_evidence` names
    what would raise it; `assumptions` names what it takes on faith;
    `contradictions` names evidence that points the other way."""
    assert level in CONFIDENCE_LEVELS, f"unknown confidence level: {level}"
    return {
        "level": level,
        "reason": reason,
        "missing_evidence": list(missing_evidence),
        "assumptions": list(assumptions),
        "contradictions": list(contradictions),
    }


def _suggested_action(category: str, title: str, description: str) -> dict:
    """A suggested operational action — inert data describing the item a
    human COULD create. Reuses the Operations Engine's existing category
    vocabulary; CRE itself never creates the item."""
    return {"category": category, "title": title, "description": description}


def _due_date(snap: dict, severity: str) -> str:
    now = snapshot_now(snap)
    return _iso(now + timedelta(days=_DUE_DAYS_BY_SEVERITY[severity]))


def _corroboration(snap: dict, activity_id: str) -> tuple[list, list]:
    """Site-reality corroboration for an activity: events linked to it
    (via events.activity_id) and their captured media."""
    events, media = [], []
    for e in snap.get("recent_events", []):
        if e.get("activity_id") != activity_id:
            continue
        events.append(_ref(e["id"], f"{e.get('type')} event at "
                                    f"{e.get('server_created_at')}"))
        for asset_id in snap.get("event_assets", {}).get(e["id"], []):
            media.append(_ref(asset_id, f"asset captured on event {e['id']}"))
    return events[:6], media[:6]


def _finding(*, rule_id: str, domain: str, severity: str,
             observation: str, risk: str, recommendation: str,
             confidence: dict, evidence: dict, subject_id: str,
             suggested_operational_action: Optional[dict] = None,
             suggested_responsible_role: Optional[str] = None,
             suggested_due_date: Optional[str] = None,
             affected_activity_id: Optional[str] = None,
             affected_activity_name: Optional[str] = None) -> dict:
    """The full reasoning chain, in order:
    observation -> risk -> recommendation -> suggested operational
    action -> suggested responsible role -> suggested due date.
    CRE never executes the action — only recommends it."""
    assert domain in DOMAINS, f"unknown domain: {domain}"
    assert severity in SEVERITIES, f"unknown severity: {severity}"
    if suggested_responsible_role is not None:
        assert suggested_responsible_role in SUGGESTED_ROLES
    return {
        "schema_version": INSIGHT_SCHEMA_VERSION,
        "rule_id": rule_id,
        "domain": domain,
        "severity": severity,
        "observation": observation,
        "risk": risk,
        "recommendation": recommendation,
        "suggested_operational_action": suggested_operational_action,
        "suggested_responsible_role": suggested_responsible_role,
        "suggested_due_date": suggested_due_date,
        "confidence": confidence,
        "evidence": evidence,
        "affected_activity_id": affected_activity_id,
        "affected_activity_name": affected_activity_name,
        "dedupe_key": f"{rule_id}:{subject_id}",
    }


# ---------------------------------------------------------------------------
# Rule registry — every rule is PURE: (snapshot) -> [finding], and belongs
# to exactly one construction domain (metadata enforced at registration
# and re-checked against every finding it emits).
# ---------------------------------------------------------------------------

_RULES: list[dict] = []


def rule(rule_id: str, domain: str, description: str):
    assert domain in DOMAINS, f"rule '{rule_id}' declares unknown domain"
    def _register(fn: Callable[[dict], list[dict]]):
        _RULES.append({"id": rule_id, "domain": domain,
                       "description": description, "fn": fn})
        return fn
    return _register


@rule("schedule.planned_start_missed", "schedule",
      "An activity's planned start date has passed but work has not begun.")
def _r_planned_start_missed(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    out = []
    for a in snap["workflow_activities"]:
        start = _parse_iso(a.get("planned_start"))
        if not start or a.get("status") not in ("not_started", "ready"):
            continue
        if a.get("actual_start") or start >= now:
            continue
        days_late = (now - start).days
        sev = "critical" if days_late >= 7 else "warning"
        ev_events, ev_media = _corroboration(snap, a["id"])
        kref = _act_knowledge_ref(a)
        out.append(_finding(
            rule_id="schedule.planned_start_missed",
            domain="schedule", severity=sev,
            observation=(f"'{a['name']}' was planned to start "
                         f"{days_late} day(s) ago but has not started."),
            risk=("Every day of slip on this activity pushes each dependent "
                  "activity by at least the same amount; unacknowledged "
                  "slips compound silently into handover delay."),
            recommendation=(f"Confirm whether '{a['name']}' has started on "
                            "site; if it has, record the actual start date — "
                            "if not, resolve whatever is holding it and "
                            "re-plan the downstream schedule."),
            suggested_operational_action=_suggested_action(
                "follow_up", f"Confirm start of '{a['name']}'",
                f"Planned start was {a.get('planned_start')}; verify site "
                "status and record actual start or the blocking reason."),
            suggested_responsible_role="project_manager",
            suggested_due_date=_due_date(snap, sev),
            confidence=_confidence(
                "high",
                "Direct comparison of stored facts: planned_start is in the "
                "past, actual_start is empty, and workflow status is still "
                f"'{a.get('status')}'.",
                missing_evidence=(
                    [] if ev_events else
                    ["site events linked to this activity that could "
                     "confirm whether work has informally begun"]),
                assumptions=["the planned_start date recorded in Atlas is "
                             "the currently agreed plan"],
                contradictions=(
                    ["recent site events are linked to this activity, which "
                     "may indicate unrecorded progress"] if ev_events else []),
            ),
            evidence=_evidence(
                workflow_activities=[_ref(a["id"],
                    f"planned_start={a.get('planned_start')}, "
                    f"status={a.get('status')}, actual_start=None")],
                events=ev_events, media=ev_media,
                knowledge_items=([_ref(kref, "source Activity Library item")]
                                 if kref else []),
            ),
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("schedule.planned_finish_missed", "schedule",
      "An activity is past its planned finish date and not complete.")
def _r_planned_finish_missed(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    out = []
    for a in snap["workflow_activities"]:
        finish = _parse_iso(a.get("planned_finish"))
        if not finish or a.get("status") == "completed" or a.get("actual_finish"):
            continue
        if finish >= now:
            continue
        days_late = (now - finish).days
        sev = "critical" if days_late >= 7 else "warning"
        dependents = [x for x in snap["workflow_activities"]
                      if a["id"] in _act_dependency_ids(x)]
        dep_names = ", ".join(d["name"] for d in dependents[:3])
        ev_events, ev_media = _corroboration(snap, a["id"])
        kref = _act_knowledge_ref(a)
        out.append(_finding(
            rule_id="schedule.planned_finish_missed",
            domain="schedule", severity=sev,
            observation=(f"'{a['name']}' is {days_late} day(s) past its "
                         "planned finish and is not complete."),
            risk=((f"It gates {len(dependents)} downstream "
                   f"activit{'y' if len(dependents) == 1 else 'ies'} "
                   f"({dep_names}{'…' if len(dependents) > 3 else ''}) — "
                   "this is a live critical-path risk.")
                  if dependents else
                  ("No modelled activity depends on it, so the risk is "
                   "contained to this activity's own scope and the overall "
                   "completion date.")),
            recommendation=(f"Get a completion forecast for '{a['name']}' "
                            "from the site team and update planned dates for "
                            "the affected downstream activities."),
            suggested_operational_action=_suggested_action(
                "follow_up", f"Completion forecast for '{a['name']}'",
                f"Planned finish {a.get('planned_finish')} has passed; "
                "obtain a revised forecast and re-plan dependents."),
            suggested_responsible_role="project_manager",
            suggested_due_date=_due_date(snap, sev),
            confidence=_confidence(
                "high",
                "Direct comparison of stored facts: planned_finish has "
                f"passed and workflow status is '{a.get('status')}' with no "
                "actual_finish recorded.",
                assumptions=["the planned_finish date recorded in Atlas is "
                             "the currently agreed plan"],
            ),
            evidence=_evidence(
                workflow_activities=(
                    [_ref(a["id"], f"planned_finish={a.get('planned_finish')}, "
                                   f"status={a.get('status')}")] +
                    [_ref(d["id"], "downstream dependent activity")
                     for d in dependents[:4]]),
                events=ev_events, media=ev_media,
                knowledge_items=([_ref(kref, "source Activity Library item")]
                                 if kref else []),
            ),
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("construction_logic.successor_not_started", "construction_logic",
      "All dependencies of an activity are complete, yet it has not begun "
      "(generalized 'excavation done -> begin PCC', from the project's own "
      "dependency graph).")
def _r_successor_not_started(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    by_id = {a["id"]: a for a in snap["workflow_activities"]}
    out = []
    for a in snap["workflow_activities"]:
        if a.get("status") not in ("ready", "not_started"):
            continue
        deps = [by_id.get(d) for d in _act_dependency_ids(a)]
        deps = [d for d in deps if d]
        if not deps or any(d.get("status") != "completed" for d in deps):
            continue
        unlocked_at = max(
            (_parse_iso(d.get("status_updated_at")) or now for d in deps))
        idle_days = (now - unlocked_at).days
        if idle_days < STALLED_SUCCESSOR_DAYS:
            continue
        dep_names = ", ".join(d["name"] for d in deps)
        sev = "warning" if idle_days < 7 else "critical"
        ev_events, ev_media = _corroboration(snap, a["id"])
        # Readiness-aware recommendation: if execution-readiness gaps
        # exist (materials, inspections, approvals, drawings), the advice
        # is to CLEAR them then begin — never a bare "begin" that would
        # contradict procurement.frontier_material_gap's "hold the start".
        gaps = [c["detail"] for c in
                projections.activity_readiness(snap, a)
                if c["status"] == "not_ready"]
        if gaps:
            recommendation = (
                f"Clear what is holding '{a['name']}' "
                f"({'; '.join(gaps[:3])}), then begin it — or record it "
                "blocked so the delay is visible and attributable.")
            action = _suggested_action(
                "follow_up", f"Prepare and start '{a['name']}'",
                f"Sequence allows '{a['name']}' ({dep_names} completed) but "
                f"readiness gaps remain: {'; '.join(gaps[:3])}. Clear them, "
                "then begin.")
        else:
            recommendation = (
                f"Begin '{a['name']}', or record the reason it cannot start "
                "(mark it blocked) so the delay is visible and attributable.")
            action = _suggested_action(
                "follow_up", f"Start '{a['name']}'",
                f"The construction sequence allows '{a['name']}' to proceed "
                f"({dep_names} completed). Begin it or record the blocker.")
        out.append(_finding(
            rule_id="construction_logic.successor_not_started",
            domain="construction_logic", severity=sev,
            observation=(f"{dep_names} complete for {idle_days} day(s); "
                         f"'{a['name']}' has not begun."),
            risk=(f"{idle_days} idle day(s) since the last dependency "
                  "finished is unrecovered time on this chain of work — "
                  "float is being consumed with nothing to show for it."),
            recommendation=recommendation,
            suggested_operational_action=action,
            suggested_responsible_role="site_supervisor",
            suggested_due_date=_due_date(snap, sev),
            confidence=_confidence(
                "high",
                "Every dependency of this activity is completed in the "
                "project's dependency graph, so the construction sequence "
                "allows it to proceed; its status shows no movement since.",
                missing_evidence=(
                    [] if ev_events else
                    ["site events linked to this activity that could show "
                     "work has informally begun"]),
                assumptions=["the dependency graph generated from the "
                             "Knowledge Core reflects the intended sequence"],
                contradictions=(
                    ["recent site events are linked to this activity, which "
                     "may indicate unrecorded progress"] if ev_events else []),
            ),
            evidence=_evidence(
                workflow_activities=(
                    [_ref(a["id"], f"status={a.get('status')}")] +
                    [_ref(d["id"], "dependency completed at "
                                   f"{d.get('status_updated_at')}")
                     for d in deps]),
                events=ev_events, media=ev_media,
                knowledge_items=[_ref(_act_knowledge_ref(d),
                                      f"Activity Library source of '{d['name']}'")
                                 for d in deps + [a] if _act_knowledge_ref(d)],
            ),
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("construction_logic.activity_blocked", "construction_logic",
      "A workflow activity is marked blocked, halting its dependency chain.")
def _r_activity_blocked(snap: dict) -> list[dict]:
    out = []
    for a in snap["workflow_activities"]:
        if a.get("status") != "blocked":
            continue
        blocked_since = a.get("status_updated_at")
        ev_events, ev_media = _corroboration(snap, a["id"])
        out.append(_finding(
            rule_id="construction_logic.activity_blocked",
            domain="construction_logic", severity="warning",
            observation=f"'{a['name']}' is marked blocked.",
            risk=("A blocked activity halts its entire downstream dependency "
                  "chain until resolved; the cost grows with every day the "
                  "blocker stands."),
            recommendation=("Identify and clear the blocker, or re-sequence "
                            "dependent work around it."),
            suggested_operational_action=_suggested_action(
                "site_issue", f"Resolve blocker on '{a['name']}'",
                f"Marked blocked at {blocked_since} by "
                f"{a.get('status_updated_by_user_name') or 'unknown'}; "
                "identify the cause and clear it or re-sequence."),
            suggested_responsible_role="project_manager",
            suggested_due_date=_due_date(snap, "warning"),
            confidence=_confidence(
                "high",
                "The blocked status was set explicitly by a site user — "
                "this is a recorded human judgment, not an inference.",
                assumptions=["the blocked status is current (it has not "
                             "been resolved on site without being updated)"],
            ),
            evidence=_evidence(
                workflow_activities=[_ref(a["id"],
                    f"blocked since {blocked_since} by "
                    f"{a.get('status_updated_by_user_name') or 'unknown'}")],
                events=ev_events, media=ev_media,
            ),
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("quality.completed_without_inspection", "quality",
      "A requires-inspection activity is complete with no inspection "
      "recorded for its period.")
def _r_completed_without_inspection(snap: dict) -> list[dict]:
    out = []
    for a in snap["workflow_activities"]:
        if not _act_requires_inspection(a) or a.get("status") != "completed":
            continue
        # one shared definition of "covered by an inspection", reused by
        # the readiness checks (projections.activity_readiness)
        if projections.inspection_covered(a, snap["operational_items"]):
            continue
        kref = _act_knowledge_ref(a)
        out.append(_finding(
            rule_id="quality.completed_without_inspection",
            domain="quality", severity="warning",
            observation=(f"'{a['name']}' requires inspection and is marked "
                         "complete, but no inspection is recorded in Atlas "
                         "for this period."),
            risk=("If the inspection genuinely did not happen, defective "
                  "workmanship may be concealed by dependent work — at "
                  "which point rectification cost multiplies."),
            recommendation=(f"Verify an inspection of '{a['name']}' was "
                            "performed; record it in Atlas, or raise an "
                            "inspection item before dependent work conceals "
                            "the workmanship."),
            suggested_operational_action=_suggested_action(
                "inspection", f"Inspect '{a['name']}'",
                "Activity is flagged requires_inspection in the Activity "
                "Library and is complete with no inspection recorded; "
                "verify or perform the inspection."),
            suggested_responsible_role="site_supervisor",
            suggested_due_date=_due_date(snap, "warning"),
            confidence=_confidence(
                "medium",
                "This is an inference from ABSENCE of evidence: the "
                "Activity Library flags the activity requires_inspection, "
                "and Atlas holds no inspection-category item dated after "
                "the activity began.",
                missing_evidence=["an inspection record (operational item "
                                  "or event) covering this activity's "
                                  "execution window"],
                assumptions=["inspections performed on site are normally "
                             "recorded in Atlas as inspection items"],
            ),
            evidence=_evidence(
                workflow_activities=[_ref(a["id"],
                    "requires_inspection=true, status=completed")],
                knowledge_items=([_ref(kref, "Activity Library item "
                                             "declaring requires_inspection")]
                                 if kref else []),
                absences=[_ref(None,
                    "no inspection-category operational item found in the "
                    "project dated after the activity began")],
            ),
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("safety.unresolved_high_priority", "safety",
      "A high/critical safety observation has been open beyond the "
      "resolution window.")
def _r_safety_unresolved(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    out = []
    for i in projections.active_items(snap["operational_items"]):
        if i.get("category") != "safety_observation":
            continue
        if i.get("priority") not in ("high", "critical"):
            continue
        created = _parse_iso(i.get("created_at"))
        hours_open = ((now - created).total_seconds() / 3600) if created else 0
        if hours_open < SAFETY_UNRESOLVED_HOURS:
            continue
        out.append(_finding(
            rule_id="safety.unresolved_high_priority",
            domain="safety", severity="critical",
            observation=(f"{i.get('priority').capitalize()}-priority safety "
                         f"observation '{i.get('title')}' has been open for "
                         f"{int(hours_open)} hours."),
            risk=("This is exposure the company is knowingly carrying: the "
                  "hazard was reported and recorded, and remains unresolved "
                  "— the worst possible position if an incident occurs."),
            recommendation=("Escalate for immediate resolution and record "
                            "the corrective action on the item."),
            suggested_operational_action=_suggested_action(
                "follow_up", f"Escalate: {i.get('title')}",
                f"Safety observation open {int(hours_open)}h past the "
                f"{SAFETY_UNRESOLVED_HOURS}h window; drive to resolution "
                "and record corrective action."),
            suggested_responsible_role="management",
            suggested_due_date=_due_date(snap, "critical"),
            confidence=_confidence(
                "high",
                "Directly recorded facts: a high/critical safety "
                "observation exists, is not in a terminal status, and its "
                "age exceeds the resolution window.",
                assumptions=["the item's open status is current"],
            ),
            evidence=_evidence(
                operational_items=[_ref(i["id"],
                    f"status={i.get('status')}, priority={i.get('priority')}, "
                    f"created_at={i.get('created_at')}")],
            ),
            subject_id=i["id"],
        ))
    return out


@rule("procurement.material_lead_time", "procurement",
      "An open material requirement is inside (or past) the procurement "
      "lead-time window.")
def _r_material_lead_time(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    out = []
    for i in projections.active_items(snap["operational_items"]):
        if i.get("category") != "material_requirement":
            continue
        req = _parse_iso(i.get("required_by"))
        if not req:
            continue
        days_left = (req - now).days
        if days_left > MATERIAL_LEAD_TIME_DAYS:
            continue
        overdue = req < now
        sev = "critical" if overdue else "warning"
        out.append(_finding(
            rule_id="procurement.material_lead_time",
            domain="procurement", severity=sev,
            observation=(f"Material requirement '{i.get('title')}' is "
                         + ("past its required date and still "
                            f"{i.get('status')}." if overdue else
                            f"required in {max(days_left, 0)} day(s) and "
                            f"still {i.get('status')}.")),
            risk=("An unfulfilled material requirement inside the lead-time "
                  "window is the most common precursor to an idle-crew day: "
                  "work stops the morning the material is not on site."),
            recommendation=("Confirm the purchase order and delivery date "
                            "with the vendor now; if delivery will miss the "
                            "required date, re-sequence the dependent work "
                            "today rather than on the morning it fails."),
            suggested_operational_action=_suggested_action(
                "follow_up", f"Confirm delivery: {i.get('title')}",
                f"Required by {i.get('required_by')}; verify PO and delivery "
                "date with the vendor, re-sequence if it will slip."),
            suggested_responsible_role="project_manager",
            suggested_due_date=_due_date(snap, sev),
            confidence=_confidence(
                "high",
                "Directly recorded facts: the material requirement is open "
                "and its required_by date is inside or past the "
                f"{MATERIAL_LEAD_TIME_DAYS}-day lead-time window.",
                missing_evidence=["vendor/PO status (not modelled in Atlas "
                                  "yet) — the material may already be in "
                                  "transit"],
                assumptions=["fulfilment would have been recorded on the "
                             "item if the material had arrived"],
            ),
            evidence=_evidence(
                operational_items=[_ref(i["id"],
                    f"required_by={i.get('required_by')}, "
                    f"status={i.get('status')}")],
            ),
            subject_id=i["id"],
        ))
    return out


@rule("management.stale_open_item", "management",
      "An open operational item has had no activity beyond the staleness "
      "window.")
def _r_stale_open_item(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    out = []
    for i in projections.active_items(snap["operational_items"]):
        last = _parse_iso(i.get("last_updated_at")) or _parse_iso(i.get("created_at"))
        if not last:
            continue
        idle_days = (now - last).days
        if idle_days < STALE_ITEM_DAYS:
            continue
        out.append(_finding(
            rule_id="management.stale_open_item",
            domain="management", severity="advisory",
            observation=(f"'{i.get('title')}' ({i.get('category')}) has had "
                         f"no activity for {idle_days} days and is still "
                         f"{i.get('status')}."),
            risk=("Silently-resolved items pollute every operational metric; "
                  "silently-stuck ones resurface later as bigger problems. "
                  "Either way the ledger is lying to management."),
            recommendation=("Follow up with the owner: close it if it is "
                            "done, or update/escalate it if it is stuck."),
            suggested_operational_action=_suggested_action(
                "follow_up", f"Chase stale item: {i.get('title')}",
                f"No activity for {idle_days} days; confirm real status "
                "with the owner and update or close."),
            suggested_responsible_role="project_manager",
            suggested_due_date=_due_date(snap, "advisory"),
            confidence=_confidence(
                "high",
                "Directly recorded facts: the item is open and its last "
                f"update is more than {STALE_ITEM_DAYS} days old.",
                assumptions=["item activity on site is normally reflected "
                             "as updates in Atlas"],
            ),
            evidence=_evidence(
                operational_items=[_ref(i["id"],
                    f"last_updated_at={i.get('last_updated_at')}, "
                    f"status={i.get('status')}")],
            ),
            subject_id=i["id"],
        ))
    return out


@rule("client_communication.progress_update_due", "client_communication",
      "Meaningful completion momentum with no client-facing item raised "
      "since.")
def _r_client_update_due(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    recent_done = [
        a for a in snap["workflow_activities"]
        if a.get("status") == "completed"
        and (_parse_iso(a.get("status_updated_at")) or now)
        >= now - timedelta(days=MILESTONE_WINDOW_DAYS)
    ]
    if len(recent_done) < 3:
        return []
    oldest = min(_parse_iso(a.get("status_updated_at")) or now
                 for a in recent_done)
    client_items = [i for i in snap["operational_items"]
                    if i.get("category") == "client_approval"]
    if any((_parse_iso(i.get("created_at")) or oldest) >= oldest
           for i in client_items):
        return []
    names = ", ".join(a["name"] for a in recent_done[:4])
    proj = snap["project"]
    return [_finding(
        rule_id="client_communication.progress_update_due",
        domain="client_communication", severity="advisory",
        observation=(f"{len(recent_done)} activities completed in the last "
                     f"{MILESTONE_WINDOW_DAYS} days ({names}"
                     f"{'…' if len(recent_done) > 4 else ''}) with no "
                     "client-facing item raised since."),
        risk=("Progress the client never hears about earns no goodwill — "
              "and goodwill is what later absorbs bad news. Silence during "
              "good weeks makes hard conversations harder."),
        recommendation=("Send the client a progress update covering the "
                        "recently completed work, and record any approvals "
                        "it triggers in Atlas."),
        suggested_operational_action=_suggested_action(
            "general", "Send client progress update",
            f"Cover the {len(recent_done)} recently completed activities "
            f"({names}); record resulting approvals in Atlas."),
        suggested_responsible_role="management",
        suggested_due_date=_due_date(snap, "advisory"),
        confidence=_confidence(
            "medium",
            "Inference from absence: sustained completion momentum is "
            "recorded, and no client-facing item exists after the oldest "
            "recent completion.",
            missing_evidence=["a record of client communication in this "
                              "window (Atlas only models client_approval "
                              "items today)"],
            assumptions=["client updates are normally reflected in Atlas "
                         "as client_approval items"],
            contradictions=(["earlier client_approval items exist in the "
                             "project, so a communication rhythm may exist "
                             "outside this window"] if client_items else []),
        ),
        evidence=_evidence(
            workflow_activities=[_ref(a["id"],
                f"completed {a.get('status_updated_at')}")
                for a in recent_done[:6]],
            absences=[_ref(None, "no client_approval item created after the "
                                 "oldest recent completion")],
        ),
        # subject is the PROJECT: while this insight is open, reruns must
        # refresh it, not mint a weekly sibling (the old key rotated with
        # the ISO week, defeating idempotency for long-open insights).
        subject_id=proj.get("id"),
    )]


@rule("schedule.forecast_finish_slip", "schedule",
      "Deterministic forecast (project's own measured productivity "
      "propagated through the dependency graph) predicts completion will "
      "slip past the plan. Forecast, not detection — no AI estimation.")
def _r_forecast_finish_slip(snap: dict) -> list[dict]:
    fc = projections.delay_forecast(snap)
    slip = fc.get("forecast_slip_days")
    if slip is None or slip < 3:
        return []
    sev = "critical" if slip >= 14 else "warning"
    worst = fc["per_activity"][:4]
    proj = snap["project"]
    return [_finding(
        rule_id="schedule.forecast_finish_slip",
        domain="schedule", severity=sev,
        observation=(f"At the project's own measured pace, completion is "
                     f"forecast {slip:.0f} day(s) past the planned date "
                     f"({fc['planned_completion'][:10]} planned vs "
                     f"{fc['forecast_completion'][:10]} forecast)."),
        risk=("This slip is not yet visible in any single overdue "
              "activity — it is the compounding of measured productivity "
              "through the dependency chain. Left unmanaged it surfaces "
              "later as an unavoidable handover delay."),
        recommendation=("Review the largest forecast slips and decide now: "
                        "recover pace (resources/resequencing) or re-baseline "
                        "the plan and reset expectations with the client."),
        suggested_operational_action=_suggested_action(
            "follow_up", "Review completion forecast slip",
            f"Forecast completion {fc['forecast_completion'][:10]} vs plan "
            f"{fc['planned_completion'][:10]} at measured productivity "
            f"{fc['productivity_ratio']}x. Largest slips: "
            + ", ".join(f"{w['name']} (+{w['forecast_slip_days']:.0f}d)"
                        for w in worst)),
        suggested_responsible_role="management",
        suggested_due_date=_due_date(snap, sev),
        # forecast confidence comes from the forecast itself: sample depth
        # and planned-date coverage, honestly capped (extrapolation is
        # never "high" on thin history)
        confidence=_confidence(
            "medium" if fc["confidence"]["level"] == "high"
            else fc["confidence"]["level"],
            fc["confidence"]["reason"],
            missing_evidence=fc["confidence"]["missing_evidence"],
            assumptions=fc["confidence"]["assumptions"],
        ),
        evidence=_evidence(
            workflow_activities=[
                _ref(w["activity_id"],
                     f"forecast finish {w['forecast_finish'][:10]} vs "
                     f"planned {w['planned_finish'][:10]} "
                     f"(+{w['forecast_slip_days']:.0f}d)")
                for w in worst],
            absences=([_ref(None, m) for m in
                       fc["confidence"]["missing_evidence"]]),
        ),
        subject_id=proj.get("id"),
    )]


@rule("procurement.frontier_material_gap", "procurement",
      "The construction sequence allows the next activity to start, but "
      "the material pipeline has unfulfilled requirements in the window.")
def _r_frontier_material_gap(snap: dict) -> list[dict]:
    now = snapshot_now(snap)
    frontier = projections.frontier(snap["workflow_activities"])
    if not frontier:
        return []
    gaps = [
        i for i in projections.active_items(snap["operational_items"])
        if i.get("category") == "material_requirement"
        and i.get("required_by")
        and (_parse_iso(i.get("required_by")) or now)
        <= now + timedelta(days=MATERIAL_LEAD_TIME_DAYS)
    ]
    if not gaps:
        return []
    names = ", ".join(a["name"] for a in frontier[:3])
    lead = frontier[0]
    proj = snap["project"]
    return [_finding(
        rule_id="procurement.frontier_material_gap",
        domain="procurement", severity="warning",
        observation=(f"The sequence allows {names} to start, but "
                     f"{len(gaps)} material requirement(s) remain "
                     "unfulfilled inside the lead-time window."),
        risk=("The next activity may mobilize into a material gap: crew "
              "on site, sequence clear, nothing to build with — the most "
              "expensive way to discover a procurement problem."),
        recommendation=("Before mobilizing the next activity, confirm the "
                        "listed materials are delivered or firmly scheduled; "
                        "hold the start decision until the pipeline is "
                        "clear."),
        suggested_operational_action=_suggested_action(
            "follow_up", f"Clear material pipeline before '{lead['name']}'",
            "Verify delivery of: "
            + ", ".join(i.get("title", i["id"]) for i in gaps[:5])),
        suggested_responsible_role="project_manager",
        suggested_due_date=_due_date(snap, "warning"),
        confidence=_confidence(
            "medium",
            "The frontier and the material gaps are both directly "
            "recorded; what Atlas cannot yet verify is whether these "
            "specific materials are needed by these specific activities.",
            missing_evidence=["activity-to-material mapping in the "
                              "Knowledge Core"],
            assumptions=["open material requirements in the lead-time "
                         "window relate to imminent work"],
        ),
        evidence=_evidence(
            workflow_activities=[_ref(a["id"],
                "frontier activity - all dependencies complete")
                for a in frontier[:3]],
            operational_items=[_ref(i["id"],
                f"required_by={i.get('required_by')}, "
                f"status={i.get('status')}") for i in gaps[:6]],
        ),
        subject_id=proj.get("id"),
    )]


def evaluate_rules(snapshot: dict) -> list[dict]:
    """Run every registered rule. Pure orchestration of pure functions —
    a misbehaving rule is logged and skipped; the run survives. Every
    finding is re-checked against its rule's declared domain."""
    stage = (snapshot.get("stage")
             or projections.infer_project_stage(
                 snapshot["workflow_activities"]))
    findings: list[dict] = []
    for r in _RULES:
        try:
            for f in r["fn"](snapshot):
                assert f["domain"] == r["domain"], (
                    f"rule '{r['id']}' emitted finding outside its domain")
                # Sprint 01B: every insight knows the project's current
                # lifecycle stage — reasoning is contextual to it.
                f["project_stage"] = stage.get("current")
                findings.append(f)
        except Exception:
            logger.exception(f"CRE rule '{r['id']}' failed; skipping")
    return findings


def list_rules() -> list[dict]:
    """Rule metadata (id, domain, description) — the explicit domain
    organization consumed by /api/reasoning-meta and future UIs."""
    return [{"id": r["id"], "domain": r["domain"],
             "description": r["description"]} for r in _RULES]



# ---------------------------------------------------------------------------
# Project health — five reasoned dimensions, pure over the snapshot.
# Never stored (recomputed on read, like operations_engine.derive_health,
# so it can never go stale) and derived from a FRESH rule evaluation, so
# it is correct even if no reasoning run was ever persisted. Not AI.
# ---------------------------------------------------------------------------

HEALTH_DIMENSIONS = {
    "schedule": {"schedule", "construction_logic"},
    "quality": {"quality"},
    "safety": {"safety"},
    "communication": {"client_communication"},
    "operational": {"procurement", "management"},
}
_HEALTH_SEVERITY_PENALTY = {"critical": 35, "warning": 12, "advisory": 5, "info": 1}
_HEALTH_EXPLANATIONS = {
    "schedule": "Planned dates versus actual movement, and whether the "
                "construction sequence is flowing without dead time.",
    "quality": "Whether required verification is keeping pace with "
               "completed work.",
    "safety": "Unresolved recorded hazards and how long they have stood.",
    "communication": "Whether the client is hearing about the progress "
                     "being made.",
    "operational": "Procurement readiness and the hygiene of the open "
                   "obligation ledger.",
}


def compute_project_health(snapshot: dict,
                           findings: Optional[list[dict]] = None,
                           open_insight_count: int = 0) -> dict:
    """Reason the project's health from the snapshot. `findings` may be
    passed to reuse an evaluation already performed this request;
    otherwise rules are evaluated fresh (pure, cheap)."""
    if findings is None:
        findings = evaluate_rules(snapshot)

    acts = snapshot["workflow_activities"]
    total = len(acts)
    completed = sum(1 for a in acts if a.get("status") == "completed")

    dimensions = {}
    for dim, domains in HEALTH_DIMENSIONS.items():
        hits = [f for f in findings if f["domain"] in domains]
        score = max(0, 100 - sum(
            _HEALTH_SEVERITY_PENALTY[f["severity"]] for f in hits))
        dimensions[dim] = {
            "score": score,
            "explanation": _HEALTH_EXPLANATIONS[dim] + (
                " No reasoned concerns at this time." if not hits else
                f" {len(hits)} reasoned concern(s) currently weigh on this "
                "dimension."),
            "contributing_factors": [
                {"observation": f["observation"], "severity": f["severity"],
                 "rule_id": f["rule_id"]} for f in sorted(
                    hits, key=lambda x: SEVERITIES.index(x["severity"]),
                    reverse=True)[:5]],
        }

    scores = [d["score"] for d in dimensions.values()]
    mean = sum(scores) / len(scores)
    # Overall leans toward the weakest dimension: a project is not "green
    # on average" while safety is on fire.
    overall = round(0.5 * mean + 0.5 * min(scores))
    status = "green" if overall >= 80 else ("amber" if overall >= 55 else "red")

    return {
        "score": overall,
        "status": status,
        "dimensions": dimensions,
        "drivers": [f["observation"] for f in sorted(
            findings, key=lambda x: SEVERITIES.index(x["severity"]),
            reverse=True)[:8]],
        "progress": {
            "activities_total": total,
            "activities_completed": completed,
            "percent_complete": round(100 * completed / total, 1) if total else None,
        },
        "open_insights": open_insight_count,
        "computed_at": snapshot["generated_at"],
    }


# ---------------------------------------------------------------------------
# Optional AI review pass — additive, never required, never blocking, and
# (Sprint 01A boundary) never operational: AI findings carry no suggested
# action, role, or due date. AI's long-term place in CRE is explanation
# and summarization of deterministic findings — never their replacement.
# ---------------------------------------------------------------------------

AI_PROMPT_NAME = "atlas_cre_reviewer"
AI_PROMPT_VERSION = "2.0"
AI_MODEL = "gpt-4o"

AI_SYSTEM_PROMPT = """You are the reasoning reviewer of Project Atlas, a \
Construction Operating System. You receive a compact JSON snapshot of one \
construction project plus the deterministic findings already produced by \
rule-based reasoning.

Your job: identify AT MOST 3 ADDITIONAL cross-cutting observations the \
rules missed — patterns across multiple signals, not restatements of \
individual findings. Never invent facts not present in the snapshot. You \
observe and explain; you never direct site work.

Return ONLY a JSON array (possibly empty). Each element:
{"observation": str, "risk": str, "recommendation": str,
 "confidence": "low"|"medium"|"high", "confidence_reason": str,
 "severity": "info"|"advisory"|"warning"|"critical",
 "evidence_ids": [ids of snapshot documents this is based on]}

Be conservative: an empty array is a perfectly good answer."""


def _snapshot_digest(snapshot: dict, findings: list[dict]) -> str:
    digest = {
        "project": {k: snapshot["project"].get(k) for k in ("id", "name")},
        "workflow_activities": [
            {k: a.get(k) for k in (
                "id", "name", "status", "phase_id", "trade", "order",
                "depends_on_activity_ids", "requires_inspection",
                "planned_start", "planned_finish",
                "actual_start", "actual_finish", "status_updated_at")}
            for a in snapshot["workflow_activities"]
        ],
        "operational_items": [
            {k: i.get(k) for k in (
                "id", "category", "title", "status", "priority", "health",
                "required_by", "created_at", "last_updated_at")}
            for i in snapshot["operational_items"]
        ],
        "recent_event_count": len(snapshot["recent_events"]),
        "deterministic_findings": [
            {k: f.get(k) for k in ("rule_id", "observation", "severity")}
            for f in findings
        ],
    }
    return json.dumps(digest, default=str)


# Atlas id prefixes are deterministic (memory/knowledge/workflow/
# operations engines) — AI-cited references are routed into the correct
# evidence sections by prefix, never guessed.
_ID_PREFIX_TO_EVIDENCE_KIND = {
    "wfa_": "workflow_activities", "op_": "operational_items",
    "evt_": "events", "ast_": "media", "prop_": "approvals",
    "kn_": "knowledge_items",
}


def _ai_cited_evidence(ref_ids: list[str]) -> dict:
    kinds: dict[str, list] = {k: [] for k in EVIDENCE_KINDS}
    for rid in ref_ids:
        kind = next((v for p, v in _ID_PREFIX_TO_EVIDENCE_KIND.items()
                     if rid.startswith(p)), None)
        if kind:
            kinds[kind].append(_ref(rid, "cited by AI reviewer"))
        else:
            kinds["absences"].append(
                _ref(None, f"AI cited unrecognized reference '{rid[:40]}'"))
    return _evidence(**{k: v for k, v in kinds.items()})


async def _ai_review(snapshot: dict, findings: list[dict]) -> list[dict]:
    """Optional LLM pass. Total failure isolation: any exception returns
    [] and the deterministic findings stand alone."""
    if not EMERGENT_LLM_KEY:
        return []
    try:
        from core.llm_compat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=str(uuid.uuid4()),
            system_message=AI_SYSTEM_PROMPT,
        ).with_model("openai", AI_MODEL)
        response = await chat.send_message(UserMessage(
            text=_snapshot_digest(snapshot, findings) + "\n\nReturn JSON only."))
        text = (response if isinstance(response, str) else str(response)).strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip().removesuffix("```").strip()
        raw = json.loads(text)
        out = []
        for idx, obs in enumerate(raw if isinstance(raw, list) else []):
            conf = obs.get("confidence")
            sev = obs.get("severity")
            if conf not in CONFIDENCE_LEVELS or sev not in SEVERITIES:
                continue
            out.append(_finding(
                rule_id="ai.cross_project_review",
                domain="ai_observation", severity=sev,
                observation=str(obs.get("observation", ""))[:500],
                risk=str(obs.get("risk", ""))[:500],
                recommendation=str(obs.get("recommendation", ""))[:500],
                # Boundary: AI never proposes operational actions, owners
                # or deadlines — only deterministic rules may.
                suggested_operational_action=None,
                suggested_responsible_role=None,
                suggested_due_date=None,
                confidence=_confidence(
                    conf,
                    str(obs.get("confidence_reason",
                                "generated by the bounded AI review pass"))[:500],
                    assumptions=["AI review output is advisory context, "
                                 "subordinate to deterministic findings"],
                ),
                evidence=_ai_cited_evidence(
                    [str(r) for r in (obs.get("evidence_ids") or [])[:8]]),
                subject_id=f"{snapshot['project'].get('id')}:ai:{idx}:"
                           f"{snapshot['generated_at'][:10]}",
            ))
        return out[:3]
    except Exception:
        logger.exception("CRE AI review failed; deterministic findings stand")
        return []


# ---------------------------------------------------------------------------
# Run orchestration + persistence (the ONLY writes CRE performs)
# ---------------------------------------------------------------------------

_indexes_ready = False


async def _ensure_indexes_once() -> None:
    """Lazy, idempotent index creation for ALL CRE-owned collections.
    Deliberately NOT in core/db.py: keeping that file byte-identical to
    main reduces the branch's shared-file merge surface to server.py's
    two router lines. Registration moves into ensure_indexes() as part
    of the merge itself."""
    global _indexes_ready
    if _indexes_ready:
        return
    await db.reasoning_insights.create_index(
        [("project_id", 1), ("status", 1), ("created_at", -1)])
    await db.reasoning_insights.create_index(
        [("project_id", 1), ("dedupe_key", 1), ("status", 1)])
    await db.reasoning_runs.create_index(
        [("project_id", 1), ("started_at", -1)])
    await db.construction_memory.create_index(
        [("project_id", 1), ("activity_id", 1)])
    _indexes_ready = True


async def run_reasoning(project_id: str, *, actor: dict,
                        include_ai: bool = False) -> dict:
    """One reasoning pass: snapshot -> rules (-> optional AI) -> dedupe
    against open insights -> persist new insights + run audit doc.
    Idempotent: rerunning on unchanged state refreshes, never duplicates.
    Recurrence after human resolution emits a fresh insight auto-linked
    to its predecessor (`previous` relationship)."""
    project = await _assert_project_visible(project_id, actor)
    await _ensure_indexes_once()
    snapshot = await build_project_snapshot(project_id)

    findings = evaluate_rules(snapshot)
    ai_findings: list[dict] = []
    if include_ai:
        ai_findings = await _ai_review(snapshot, findings)
    all_findings = findings + ai_findings

    open_existing = await db.reasoning_insights.find(
        {"project_id": project_id, "status": "open"},
        {"_id": 0, "id": 1, "dedupe_key": 1},
    ).to_list(2000)
    open_by_key = {x["dedupe_key"]: x["id"] for x in open_existing}

    run_id = _new_id("crun_")
    now = _iso(_now())
    new_ids, refreshed_ids = [], []

    for f in all_findings:
        existing_id = open_by_key.get(f["dedupe_key"])
        if existing_id:
            await db.reasoning_insights.update_one(
                {"id": existing_id},
                {"$set": {"last_seen_at": now, "last_seen_run_id": run_id},
                 "$inc": {"times_seen": 1}},
            )
            refreshed_ids.append(existing_id)
            continue

        # Reasoning chain across time: if this condition was previously
        # raised and humanly resolved/dismissed, link the fresh insight
        # to its predecessor instead of resurrecting it.
        related = []
        predecessor = await db.reasoning_insights.find(
            {"project_id": project_id, "dedupe_key": f["dedupe_key"],
             "status": {"$in": ["actioned", "dismissed"]}},
            {"_id": 0, "id": 1},
        ).sort("created_at", -1).to_list(1)
        if predecessor:
            related.append({
                "insight_id": predecessor[0]["id"], "relation": "previous",
                "added_at": now, "added_by_user_id": None,
                "added_by_user_name": "CRE",
                "note": "same condition recurred after human resolution",
            })

        doc = {
            "id": _new_id("ins_"),
            "project_id": project_id,
            "project_name": project.get("name"),
            "run_id": run_id,
            **f,
            "status": "open",
            "status_history": [
                {"status": "open", "at": now, "by_user_id": actor["id"],
                 "by_user_name": actor["name"], "note": "emitted by reasoning run"}
            ],
            "related_insights": related,
            "feedback": None,
            "feedback_history": [],
            "created_at": now,
            "last_seen_at": now,
            "last_seen_run_id": run_id,
            "times_seen": 1,
            "resolved_at": None,
            "resolved_by_user_id": None,
            "resolved_by_user_name": None,
            "resolution_note": None,
        }
        await db.reasoning_insights.insert_one({**doc})
        new_ids.append(doc["id"])

    run_doc = {
        "id": run_id,
        "project_id": project_id,
        "triggered_by_user_id": actor["id"],
        "triggered_by_user_name": actor["name"],
        "trigger": "manual",
        "started_at": snapshot["generated_at"],
        "finished_at": _iso(_now()),
        "include_ai": include_ai,
        "ai_findings_count": len(ai_findings),
        "ai_prompt": ({"name": AI_PROMPT_NAME, "version": AI_PROMPT_VERSION,
                       "model": AI_MODEL} if include_ai else None),
        "rules_evaluated": [r["id"] for r in _RULES],
        "snapshot_stats": {
            "sites": len(snapshot["sites"]),
            "workflow_activities": len(snapshot["workflow_activities"]),
            "operational_items": len(snapshot["operational_items"]),
            "recent_events": len(snapshot["recent_events"]),
        },
        "insights_new": len(new_ids),
        "insights_refreshed": len(refreshed_ids),
        "new_insight_ids": new_ids,
    }
    run_doc["memory_records_captured"] = \
        await _capture_construction_memory(snapshot)
    await db.reasoning_runs.insert_one({**run_doc})

    open_now = await list_insights(project_id, user=actor,
                                    status="open")
    return {
        "run": run_doc,
        "health": compute_project_health(
            snapshot, findings, open_insight_count=len(open_now)),
        "insights_new": [i for i in open_now if i["id"] in set(new_ids)],
    }


async def list_insights(project_id: str, *, user: dict,
                        status: Optional[str] = None,
                        domain: Optional[str] = None,
                        limit: int = 500) -> list[dict]:
    await _assert_project_visible(project_id, user)
    q: dict = {"project_id": project_id}
    if status:
        if status not in INSIGHT_STATUSES:
            raise ReasoningError(
                f"Invalid status '{status}'. Must be one of {sorted(INSIGHT_STATUSES)}")
        q["status"] = status
    if domain:
        if domain not in DOMAINS:
            raise ReasoningError(
                f"Invalid domain '{domain}'. Must be one of {sorted(DOMAINS)}")
        q["domain"] = domain
    return await db.reasoning_insights.find(q, {"_id": 0}).sort(
        "created_at", -1).to_list(limit)


async def get_insight(insight_id: str) -> Optional[dict]:
    return await db.reasoning_insights.find_one({"id": insight_id}, {"_id": 0})


async def set_insight_status(insight_id: str, new_status: str, *,
                             actor: dict, note: str = "") -> dict:
    """Record the human decision on an insight (see CANONICAL_LIFECYCLE
    in the module docstring; `actioned` implements canonical `resolved`)."""
    if new_status not in INSIGHT_STATUSES:
        raise ReasoningError(
            f"Invalid status '{new_status}'. Must be one of {sorted(INSIGHT_STATUSES)}")
    insight = await get_insight(insight_id)
    if not insight:
        raise ReasoningNotFoundError(f"Insight '{insight_id}' not found")
    await _assert_project_visible(insight["project_id"], actor)
    current = insight.get("status", "open")
    if new_status not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidInsightTransitionError(
            f"Cannot move insight from '{current}' to '{new_status}'.")
    now = _iso(_now())
    upd: dict = {"status": new_status}
    if new_status in ("actioned", "dismissed"):
        upd.update({
            "resolved_at": now,
            "resolved_by_user_id": actor["id"],
            "resolved_by_user_name": actor["name"],
            "resolution_note": note or None,
        })
    await db.reasoning_insights.update_one(
        {"id": insight_id},
        {"$set": upd,
         "$push": {"status_history": {
             "status": new_status, "at": now, "by_user_id": actor["id"],
             "by_user_name": actor["name"], "note": note or None}}},
    )
    return await get_insight(insight_id)


async def record_insight_feedback(insight_id: str, verdict: str, *,
                                  actor: dict, note: str = "") -> dict:
    """Human feedback loop — learning-layer PREPARATION only. The verdict
    (accepted / rejected / modified / ignored) and optional human
    reasoning are stored on the insight; NOTHING in this sprint reads
    them back or adapts behavior. Feedback is independent of lifecycle
    status and may be revised (history preserved)."""
    if verdict not in FEEDBACK_VERDICTS:
        raise ReasoningError(
            f"Invalid feedback verdict '{verdict}'. "
            f"Must be one of {sorted(FEEDBACK_VERDICTS)}")
    insight = await get_insight(insight_id)
    if not insight:
        raise ReasoningNotFoundError(f"Insight '{insight_id}' not found")
    await _assert_project_visible(insight["project_id"], actor)
    entry = {
        "verdict": verdict,
        "note": note or None,
        "by_user_id": actor["id"],
        "by_user_name": actor["name"],
        "at": _iso(_now()),
    }
    await db.reasoning_insights.update_one(
        {"id": insight_id},
        {"$set": {"feedback": entry}, "$push": {"feedback_history": entry}},
    )
    return await get_insight(insight_id)


async def add_insight_relationship(insight_id: str, related_insight_id: str,
                                   relation: str, *, actor: dict,
                                   note: str = "") -> dict:
    """Link two insights (previous / duplicate / supports / conflicts) —
    the substrate for future multi-step reasoning. Idempotent per
    (target, relation) pair."""
    if relation not in RELATION_TYPES:
        raise ReasoningError(
            f"Invalid relation '{relation}'. "
            f"Must be one of {sorted(RELATION_TYPES)}")
    if insight_id == related_insight_id:
        raise ReasoningError("An insight cannot relate to itself.")
    insight = await get_insight(insight_id)
    if not insight:
        raise ReasoningNotFoundError(f"Insight '{insight_id}' not found")
    await _assert_project_visible(insight["project_id"], actor)
    related = await get_insight(related_insight_id)
    if not related:
        raise ReasoningNotFoundError(
            f"Insight '{related_insight_id}' not found")
    if insight["project_id"] != related["project_id"]:
        raise ReasoningError(
            "Insights can only be related within the same project.")
    if any(r["insight_id"] == related_insight_id and r["relation"] == relation
           for r in insight.get("related_insights", [])):
        return insight
    await db.reasoning_insights.update_one(
        {"id": insight_id},
        {"$push": {"related_insights": {
            "insight_id": related_insight_id, "relation": relation,
            "added_at": _iso(_now()), "added_by_user_id": actor["id"],
            "added_by_user_name": actor["name"], "note": note or None}}},
    )
    return await get_insight(insight_id)


async def project_health(project_id: str, *, user: dict) -> dict:
    snapshot = await build_project_snapshot(project_id)
    open_now = await list_insights(project_id, user=user, status="open")
    return compute_project_health(snapshot, open_insight_count=len(open_now))


async def list_runs(project_id: str, *, user: dict, limit: int = 50) -> list[dict]:
    await _assert_project_visible(project_id, user)
    return await db.reasoning_runs.find(
        {"project_id": project_id}, {"_id": 0}).sort(
        "started_at", -1).to_list(limit)


# ---------------------------------------------------------------------------
# Construction memory (Sprint 01B item 11) — capture only, NO learning.
# CRE-owned collection `construction_memory`: one record per completed
# activity. Nothing in this sprint reads these records back; the future
# learning layer consumes them under the CRE_ARCHITECTURE.md boundary.
# ---------------------------------------------------------------------------

async def _capture_construction_memory(snapshot: dict) -> int:
    captured = 0
    for a in snapshot["workflow_activities"]:
        if a.get("status") != "completed":
            continue
        exists = await db.construction_memory.find_one(
            {"activity_id": a["id"]}, {"_id": 0, "activity_id": 1})
        if exists:
            continue
        record = projections.build_memory_record(a, snapshot)
        record["id"] = _new_id("mem_")
        record["captured_at"] = _iso(_now())
        await db.construction_memory.insert_one({**record})
        captured += 1
    return captured


async def list_construction_memory(project_id: str, *, user: dict,
                                   limit: int = 200) -> list[dict]:
    await _assert_project_visible(project_id, user)
    return await db.construction_memory.find(
        {"project_id": project_id}, {"_id": 0}).sort(
        "captured_at", -1).to_list(limit)


# ---------------------------------------------------------------------------
# Projection views (Sprint 01B) — snapshot + pure projection, per request.
# Nothing stored; identical visibility discipline to project_health.
# ---------------------------------------------------------------------------

async def project_lookahead_view(project_id: str, *, user: dict) -> dict:
    await _assert_project_visible(project_id, user)
    snapshot = await build_project_snapshot(project_id)
    return projections.project_lookahead(snapshot)


async def project_forecast_view(project_id: str, *, user: dict) -> dict:
    await _assert_project_visible(project_id, user)
    snapshot = await build_project_snapshot(project_id)
    return projections.delay_forecast(snapshot)


async def project_briefing_view(project_id: str, *, user: dict) -> dict:
    await _assert_project_visible(project_id, user)
    snapshot = await build_project_snapshot(project_id)
    open_now = await list_insights(project_id, user=user, status="open")
    return projections.compose_daily_briefing(snapshot, open_now)


async def client_summary_view(project_id: str, *, user: dict) -> dict:
    """Client communication intelligence: a deterministic plain-English
    DRAFT for the internal team to review and send. Served only to
    internal roles — CRE prepares words; humans decide to send them."""
    await _assert_project_visible(project_id, user)
    snapshot = await build_project_snapshot(project_id)
    return projections.compose_client_summary(snapshot)


async def client_dashboard_view(project_id: str, *, user: dict) -> dict:
    """CRE Integration (client dashboard cards: Progress Summary, Current
    Stage, Upcoming Milestones). The ONLY reasoning view a client account
    may call directly — every other endpoint in this file remains
    internal-only (see routes/reasoning.py's _forbid_client).

    This is presentation, not reasoning: it calls the exact same,
    unmodified projection functions every internal view already uses
    (compose_client_summary, project_lookahead) and returns an explicitly
    reduced projection of their output — stage label, plain-English
    sentences, and milestone NAMES only. It never returns rule ids,
    confidence, evidence, readiness-check detail, or any operational
    item/event id — the fields compose_client_summary already avoids by
    design, plus the additional stripping below for the milestones list,
    which project_lookahead does not itself limit to client-safe fields
    (it is written for internal readiness/preparation use).
    """
    await _assert_project_visible(project_id, user)
    snapshot = await build_project_snapshot(project_id)
    summary = projections.compose_client_summary(snapshot)
    look = projections.project_lookahead(snapshot)
    milestones = [{"name": a["name"]} for a in look.get("upcoming", [])[:5]]
    return {
        "project_id": summary["project_id"],
        "project_name": summary["project_name"],
        # compose_client_summary's own "stage" field is just the plain
        # string stage["current"] (see its final return statement) - NOT
        # the {current, current_label} dict this view needs. look["stage"]
        # (already computed above via project_lookahead) is that full
        # dict; compose_client_summary derives its plain string from the
        # exact same source. Using look["stage"] directly is correct and
        # does not touch compose_client_summary or its existing internal
        # -only consumer (/client-summary) at all.
        "stage": look["stage"],
        "summary_text": summary["summary_text"],
        "upcoming_milestones": milestones,
        "generated_at": summary["generated_at"],
    }


# ---------------------------------------------------------------------------
# Executive reasoning (Sprint 01B item 8) — reusable deterministic
# answers to portfolio-level management questions. No conversational AI:
# a fixed vocabulary of questions, each answered by explicit reasoning
# over per-project snapshots, scoped to the caller's project visibility.
# ---------------------------------------------------------------------------

EXECUTIVE_QUESTIONS = {
    "attention_today":   "What needs my attention today?",
    "greatest_risk":     "Which project is at greatest risk?",
    "top_blocker":       "Which activity is blocking the most work?",
    "overdue_approvals": "Which approvals are overdue?",
    "stalled_projects":  "Which projects have no recent progress?",
    "tomorrow":          "What should happen tomorrow?",
    "supervisor_load":   "Which supervisor is overloaded?",
}
_PORTFOLIO_PROJECT_CAP = 25
STALLED_PROJECT_DAYS = 7


async def _visible_project_ids(user: dict) -> list[str]:
    projects = await memory_engine.list_projects(user=user)
    return [p["id"] for p in projects[:_PORTFOLIO_PROJECT_CAP]]


async def _portfolio(user: dict) -> list[dict]:
    """Per-project context bundles for executive reasoning. Snapshots are
    built once and shared by whichever answer function needs them."""
    out = []
    for pid in await _visible_project_ids(user):
        snapshot = await build_project_snapshot(pid)
        findings = evaluate_rules(snapshot)
        health = compute_project_health(snapshot, findings)
        out.append({
            "snapshot": snapshot,
            "findings": findings,
            "digest": projections.project_digest(snapshot, findings, health),
        })
    return out


async def executive_answer(question: str, *, user: dict) -> dict:
    if question not in EXECUTIVE_QUESTIONS:
        raise ReasoningError(
            f"Unknown executive question '{question}'. "
            f"Must be one of {sorted(EXECUTIVE_QUESTIONS)}")
    portfolio = await _portfolio(user)
    now = _now()

    if question == "attention_today":
        pids = [p["digest"]["project_id"] for p in portfolio]
        urgent = await db.reasoning_insights.find(
            {"project_id": {"$in": pids}, "status": "open",
             "severity": {"$in": ["critical", "warning"]}},
            {"_id": 0, "id": 1, "project_id": 1, "project_name": 1,
             "severity": 1, "observation": 1, "recommendation": 1,
             "suggested_due_date": 1, "domain": 1},
        ).sort("created_at", -1).to_list(200)
        urgent.sort(key=lambda i: (0 if i["severity"] == "critical" else 1,
                                   i.get("suggested_due_date") or "~"))
        answer = {"items": urgent[:10], "total_open_urgent": len(urgent)}
        explanation = ("Open critical and warning insights across your "
                       "visible projects, most severe and soonest-due first.")

    elif question == "greatest_risk":
        ranked = sorted((p["digest"] for p in portfolio),
                        key=lambda d: (d["health_score"],
                                       d["project_id"]))
        answer = {"ranking": ranked,
                  "greatest_risk": ranked[0] if ranked else None}
        explanation = ("Projects ranked by reasoned health score "
                       "(five-dimension model; overall leans toward the "
                       "weakest dimension).")

    elif question == "top_blocker":
        blockers = []
        for p in portfolio:
            for b in projections.blocking_impact(p["snapshot"])[:3]:
                blockers.append({**b,
                                 "project_id": p["digest"]["project_id"],
                                 "project_name": p["digest"]["project_name"]})
        blockers.sort(key=lambda b: (-b["downstream_activities_held"],
                                     b["activity_id"]))
        answer = {"blockers": blockers[:10],
                  "top": blockers[0] if blockers else None}
        explanation = ("Blocked or overdue activities ranked by how many "
                       "incomplete downstream activities their dependency "
                       "chains are holding.")

    elif question == "overdue_approvals":
        overdue = []
        for p in portfolio:
            for i in p["snapshot"]["operational_items"]:
                if i.get("category") not in ("client_approval",
                                             "drawing_request"):
                    continue
                if i.get("status") in projections.TERMINAL_ITEM_STATUSES:
                    continue
                req = _parse_iso(i.get("required_by"))
                created = _parse_iso(i.get("created_at"))
                if (req and req < now) or (not req and created and
                                           (now - created).days >= 7):
                    overdue.append({
                        "item_id": i["id"], "title": i.get("title"),
                        "category": i.get("category"),
                        "required_by": i.get("required_by"),
                        "created_at": i.get("created_at"),
                        "project_id": p["digest"]["project_id"],
                        "project_name": p["digest"]["project_name"]})
        overdue.sort(key=lambda x: x.get("required_by") or x.get("created_at") or "")
        answer = {"approvals": overdue[:15], "total": len(overdue)}
        explanation = ("Open client approvals and drawing requests past "
                       "their required date, or older than 7 days when no "
                       "date was set.")

    elif question == "stalled_projects":
        stalled = [
            p["digest"] for p in portfolio
            if not p["digest"]["last_activity_at"]
            or (now - _parse_iso(p["digest"]["last_activity_at"])).days
            >= STALLED_PROJECT_DAYS]
        answer = {"stalled": stalled,
                  "threshold_days": STALLED_PROJECT_DAYS}
        explanation = (f"Projects with no workflow movement and no site "
                       f"events for {STALLED_PROJECT_DAYS}+ days.")

    elif question == "tomorrow":
        plan = []
        for p in portfolio:
            look = projections.project_lookahead(p["snapshot"])
            if look["next_expected"]:
                plan.append({
                    "project_id": p["digest"]["project_id"],
                    "project_name": p["digest"]["project_name"],
                    "stage": look["stage"]["current"],
                    "next_expected": look["next_expected"]})
        answer = {"projects": plan}
        explanation = ("Per project: the next activity the construction "
                       "sequence expects, with readiness prerequisites and "
                       "recommended preparation.")

    else:  # supervisor_load
        counts: dict[str, dict] = {}
        for p in portfolio:
            for i in p["snapshot"]["operational_items"]:
                uid = i.get("assigned_to_user_id")
                if not uid or i.get("status") in \
                        projections.TERMINAL_ITEM_STATUSES:
                    continue
                c = counts.setdefault(uid, {"open_items": 0, "projects": set()})
                c["open_items"] += 1
                c["projects"].add(p["digest"]["project_id"])
        users = await db.users.find(
            {"id": {"$in": list(counts)}, "role": "site_supervisor"},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(200)
        load = sorted(
            ({"user_id": u["id"], "name": u["name"],
              "open_items": counts[u["id"]]["open_items"],
              "projects": len(counts[u["id"]]["projects"])}
             for u in users),
            key=lambda x: (-x["open_items"], x["user_id"]))
        answer = {"supervisors": load,
                  "most_loaded": load[0] if load else None}
        explanation = ("Supervisors ranked by open operational items "
                       "assigned to them across your visible projects.")

    return {
        "question": question,
        "question_text": EXECUTIVE_QUESTIONS[question],
        "scope": {"projects_considered": len(portfolio)},
        "answer": answer,
        "explanation": explanation,
        "generated_at": _iso(now),
    }


# ---------------------------------------------------------------------------
# Portfolio Control Center (Phase 1 — schedule-based monitoring only).
#
# Deliberately NOT a new engine or a new reasoning mechanism: every number
# below is either read directly off an existing CRE output
# (compute_project_health via project_digest, projections.delay_forecast,
# projections.project_lookahead) or a plain count over
# snapshot["operational_items"] using the exact same TERMINAL_ITEM_STATUSES
# constant executive_answer's own supervisor_load question already uses —
# see _portfolio() above, which this reuses without modification. Health
# status is never set manually here or anywhere upstream of this function;
# it is compute_project_health's own, unmodified "green"/"amber"/"red"
# status, presented under this dashboard's own labels
# (HEALTH_STATUS_LABEL) — a display-layer rename, not a second health
# computation.
#
# Financial fields (budget, forecast_cost, cost_variance, profitability,
# cash_flow) are explicit, typed, always-null placeholders — Phase 1 does
# no financial computation at all, per the brief. Adding Phase 2 later
# means filling these in, not redesigning the row shape or the endpoint.
# ---------------------------------------------------------------------------

HEALTH_STATUS_LABEL = {"green": "Healthy", "amber": "Attention", "red": "Critical"}


def _project_row(p: dict) -> dict:
    """One portfolio row, built entirely from data _portfolio() already
    computed for this project (snapshot, findings, digest) plus two more
    existing, unmodified projections run over that same snapshot."""
    snapshot, digest = p["snapshot"], p["digest"]
    items = snapshot["operational_items"]
    open_items = [i for i in items if i.get("status") not in projections.TERMINAL_ITEM_STATUSES]
    pending_approvals = [i for i in open_items if i.get("category") == "client_approval"]
    critical_open_items = [i for i in open_items if i.get("priority") == "critical"]

    forecast = projections.delay_forecast(snapshot)
    lookahead = projections.project_lookahead(snapshot)
    next_expected = lookahead.get("next_expected")

    return {
        "project_id": digest["project_id"],
        "project_name": digest["project_name"],
        "progress_percent": digest["progress"]["percent_complete"],
        "planned_completion": forecast["planned_completion"],
        "forecast_completion": forecast["forecast_completion"],
        "schedule_variance_days": forecast["forecast_slip_days"],
        "health_status": HEALTH_STATUS_LABEL[digest["health_status"]],
        "health_score": digest["health_score"],
        "critical_issues_count": digest["finding_counts"]["critical"],
        "open_operational_items": len(open_items),
        "pending_client_approvals": len(pending_approvals),
        "critical_operational_items": len(critical_open_items),
        "next_milestone": next_expected["name"] if next_expected else None,
        # Future Ready — Phase 2 placeholders, deliberately null/disabled.
        # See engines/reasoning_engine.py's module note above.
        "financials": {
            "enabled": False,
            "budget": None,
            "forecast_cost": None,
            "cost_variance": None,
            "profitability": None,
            "cash_flow": None,
        },
    }


async def portfolio_control_center(*, user: dict) -> dict:
    """Management/Admin Portfolio Control Center (Phase 1 — schedule-
    based monitoring only, no financial computation). One row per
    visible active project, plus a portfolio-level summary. Role
    enforcement (management-only) is the caller's responsibility, same
    as every other reasoning route in this file."""
    portfolio = await _portfolio(user)
    rows = [_project_row(p) for p in portfolio]

    summary = {
        "active_projects": len(rows),
        "healthy": sum(1 for r in rows if r["health_status"] == "Healthy"),
        "attention": sum(1 for r in rows if r["health_status"] == "Attention"),
        "critical": sum(1 for r in rows if r["health_status"] == "Critical"),
        "projects_behind_schedule": sum(
            1 for r in rows
            if r["schedule_variance_days"] is not None and r["schedule_variance_days"] > 0),
        "pending_client_approvals": sum(r["pending_client_approvals"] for r in rows),
        "critical_operational_items": sum(r["critical_operational_items"] for r in rows),
    }

    return {"summary": summary, "projects": rows, "generated_at": _iso(_now())}
