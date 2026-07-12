"""Construction Reasoning Engine (CRE) — Innovation Sprint 01.

Atlas already captures reality (Reality Engine), understands single
utterances (Intelligence Engine), tracks obligations (Operations Engine),
and knows how construction is supposed to flow (Knowledge Core +
Construction Workflow Engine). What no engine does yet is look at ALL of
it for a project and answer: "what does everything happening here
collectively mean, and what should a human do next?"

That is this engine's single responsibility. It is Atlas' reasoning
layer — engine slot #7 in memory/ARCHITECTURE.md's engine map, previously
reserved.

Design principles (each one deliberate):

1.  READ-ONLY over every other engine's data. CRE never mutates
    events, operational_items, workflow_activities, knowledge_items or
    anything else it reasons about. It writes ONLY to its own two
    collections: `reasoning_insights` and `reasoning_runs`. This is the
    hard guarantee behind "CRE must never execute work automatically" —
    it is structurally incapable of doing so, not just instructed not to.

2.  REASON FIRST, AI SECOND. The core of CRE is a registry of small,
    deterministic, PURE rule functions (`snapshot -> findings`). They
    take a plain dict and return plain dicts — no I/O, no Mongo, no
    network — which makes every construction-logic rule unit-testable
    without a database (see tests/test_cre_rules.py). An optional LLM
    review pass can ADD observations on top (mirroring the Intelligence
    Engine's optional-worker pattern: no key configured -> silently
    skipped; AI failure -> deterministic findings still returned intact).
    The LLM is never in the critical path and never required.

3.  EVERY insight is a structured recommendation carrying exactly the
    contract the sprint mandates: observation, evidence (typed refs back
    to the concrete documents that justify it — same philosophy as
    ai_analyses' `evidence` array), reasoning, confidence, affected
    project, affected activity, recommended_action. The human decides;
    CRE only advises.

4.  IDEMPOTENT RUNS. Re-running reasoning on an unchanged project must
    not spam duplicates. Every finding carries a deterministic
    `dedupe_key` (rule + subject); if an OPEN insight with that key
    already exists, the run refreshes `last_seen_at` / `times_seen`
    instead of inserting a new document. Once a human resolves
    (acknowledges / dismisses / actions) an insight, the key is free
    again — if the condition later recurs, that is genuinely new
    information and a new insight is emitted.

5.  NO HARDCODED CONSTRUCTION SEQUENCES. The "excavation complete, no
    PCC started -> begin PCC" class of reasoning is derived from the
    dependency graph the admin already curated in the Knowledge Core and
    that workflow_engine already denormalized per-project
    (`depends_on_activity_ids`). CRE generalizes over that graph rather
    than shipping its own opinion of how buildings are built — which is
    exactly why it gets smarter as the Knowledge Core grows, for free.

6.  BRANCH DISCIPLINE. Nothing here touches authentication,
    authorization, user management or role logic. Project visibility
    reuses the exact `_assert_project_visible` convention
    workflow_engine.py established (memory_engine.get_project +
    memory_engine._is_project_scoped), treating those as stable
    dependencies.

Collections owned by CRE:

    reasoning_insights   one document per distinct open finding.
                         `status` lifecycle: open -> acknowledged ->
                         actioned | dismissed  (acknowledge optional —
                         open -> actioned/dismissed directly is allowed).
                         Status changes append to the document's own
                         `status_history` so the decision trail is never
                         lost (append-only in spirit, mirroring how
                         ai_proposals record their decision once).

    reasoning_runs       append-only audit trail: one document per
                         reasoning run — who triggered it, when, snapshot
                         stats, which rules fired, counts of new vs
                         refreshed insights, whether the AI pass ran.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from core.db import db
from core.settings import EMERGENT_LLM_KEY
from engines import memory_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

DOMAINS = {
    "schedule", "construction_logic", "quality", "safety",
    "procurement", "client_communication", "management", "ai_observation",
}
CONFIDENCES = ["low", "medium", "high"]
SEVERITIES = ["info", "advisory", "warning", "critical"]
INSIGHT_STATUSES = {"open", "acknowledged", "actioned", "dismissed"}
# Terminal-ish transitions: acknowledge is an intermediate "a human has
# seen this"; actioned/dismissed close the insight. Reopening is
# deliberately NOT supported — if the condition still holds on the next
# run, a fresh insight is emitted instead (cleaner audit trail than
# resurrecting a dismissed one).
_ALLOWED_TRANSITIONS = {
    "open": {"acknowledged", "actioned", "dismissed"},
    "acknowledged": {"actioned", "dismissed"},
    "actioned": set(),
    "dismissed": set(),
}

# Tunables — module-level constants like operations_engine's vocab sets.
STALLED_SUCCESSOR_DAYS = 3      # deps done N+ days ago, successor untouched
MATERIAL_LEAD_TIME_DAYS = 3     # flag material needs due within N days
STALE_ITEM_DAYS = 7             # open op item silent for N+ days
SAFETY_UNRESOLVED_HOURS = 24    # high/critical safety item open N+ hours
MILESTONE_WINDOW_DAYS = 7       # completions within N days => client update


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value) -> Optional[datetime]:
    """Same tolerant ISO parsing convention as operations_engine._parse_iso:
    naive timestamps are assumed UTC; garbage returns None instead of
    raising (a bad date in one document must never sink a whole run)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4()}"


class ReasoningError(ValueError):
    """Base validation error — subclasses ValueError so routes reuse the
    established broad `except ValueError` + `_raise_for()` convention."""


class ReasoningNotFoundError(ReasoningError):
    pass


class InvalidInsightTransitionError(ReasoningError):
    pass


async def _assert_project_visible(project_id: str, user: dict) -> dict:
    """Identical convention to workflow_engine._assert_project_visible —
    reused pattern, not modified auth: out-of-scope projects behave as if
    they do not exist (404, not 403)."""
    project = await memory_engine.get_project(project_id)
    if not project:
        raise ReasoningNotFoundError(f"Project '{project_id}' not found")
    if memory_engine._is_project_scoped(user):
        if project_id not in (user.get("assigned_project_ids") or []):
            raise ReasoningNotFoundError(f"Project '{project_id}' not found")
    return project


# ---------------------------------------------------------------------------
# Snapshot layer — the ONLY place CRE touches Mongo for reads.
# ---------------------------------------------------------------------------

async def build_project_snapshot(project_id: str) -> dict:
    """Assemble one read-only, plain-dict view of everything CRE reasons
    over for a project. Rules never query the database themselves — they
    see exactly this snapshot, which is what makes them pure and the
    whole reasoning pass reproducible (the run audit records snapshot
    stats, and a snapshot could later be persisted wholesale for replay).
    """
    project = await memory_engine.get_project(project_id)
    sites = await db.sites.find(
        {"project_id": project_id}, {"_id": 0}).to_list(500)
    site_ids = [s["id"] for s in sites]

    activities = await db.workflow_activities.find(
        {"project_id": project_id}, {"_id": 0}).sort("order", 1).to_list(1000)

    # operational_items carry project_id denormalized since Sprint 2 —
    # but pre-Sprint-2 items may only have site_id, so query by both.
    items = await db.operational_items.find(
        {"$or": [{"project_id": project_id}, {"site_id": {"$in": site_ids}}]},
        {"_id": 0},
    ).to_list(2000)

    # Recent construction events: lightweight projection only (CRE does
    # not need raw assets or full analyses to reason at project level yet).
    events = await db.events.find(
        {"site_id": {"$in": site_ids}},
        {"_id": 0, "id": 1, "site_id": 1, "type": 1, "ai_status": 1,
         "server_created_at": 1, "activity_id": 1},
    ).sort("server_created_at", -1).to_list(500)

    return {
        "generated_at": _iso(_now()),
        "project": project or {"id": project_id},
        "sites": sites,
        "workflow_activities": activities,
        "operational_items": items,
        "recent_events": events,
    }


# ---------------------------------------------------------------------------
# Finding construction helper
# ---------------------------------------------------------------------------

def _finding(*, rule_id: str, domain: str, severity: str, confidence: str,
             observation: str, reasoning: str, recommended_action: str,
             evidence: list[dict], subject_id: str,
             affected_activity_id: Optional[str] = None,
             affected_activity_name: Optional[str] = None) -> dict:
    assert domain in DOMAINS, f"unknown domain: {domain}"
    assert severity in SEVERITIES, f"unknown severity: {severity}"
    assert confidence in CONFIDENCES, f"unknown confidence: {confidence}"
    return {
        "rule_id": rule_id,
        "domain": domain,
        "severity": severity,
        "confidence": confidence,
        "observation": observation,
        "reasoning": reasoning,
        "recommended_action": recommended_action,
        "evidence": evidence,
        "affected_activity_id": affected_activity_id,
        "affected_activity_name": affected_activity_name,
        # rule + subject uniquely identify "this finding about this thing"
        "dedupe_key": f"{rule_id}:{subject_id}",
    }


def _ev(kind: str, ref_id: Optional[str], detail: str) -> dict:
    """Typed evidence reference — same spirit as ai_analyses.evidence."""
    return {"kind": kind, "ref_id": ref_id, "detail": detail}


# ---------------------------------------------------------------------------
# Rule registry — every rule is PURE: (snapshot: dict) -> list[finding dict]
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, Callable[[dict], list[dict]]]] = []


def rule(rule_id: str):
    def _register(fn):
        _RULES.append((rule_id, fn))
        return fn
    return _register


def _active(items: list[dict]) -> list[dict]:
    """Operational items still demanding attention (not terminal)."""
    terminal = {"fulfilled", "verified", "closed", "archived",
                "cancelled", "duplicate"}
    return [i for i in items if i.get("status") not in terminal]


@rule("schedule.planned_start_missed")
def _r_planned_start_missed(snap: dict) -> list[dict]:
    """Delay risk: an activity's planned start date has passed but work
    has not begun. Direct comparison of stored facts -> high confidence."""
    now = _parse_iso(snap["generated_at"])
    out = []
    for a in snap["workflow_activities"]:
        start = _parse_iso(a.get("planned_start"))
        if not start or a.get("status") not in ("not_started", "ready"):
            continue
        if a.get("actual_start"):
            continue
        if start >= now:
            continue
        days_late = (now - start).days
        sev = "critical" if days_late >= 7 else "warning"
        out.append(_finding(
            rule_id="schedule.planned_start_missed",
            domain="schedule", severity=sev, confidence="high",
            observation=(f"'{a['name']}' was planned to start "
                         f"{days_late} day(s) ago but has not started."),
            reasoning=("planned_start is in the past, actual_start is empty "
                       "and workflow status is still "
                       f"'{a.get('status')}'. Every day of slip on this "
                       "activity pushes each dependent activity by at "
                       "least the same amount."),
            recommended_action=(f"Confirm whether '{a['name']}' has started "
                                "on site; if it has, record the actual start "
                                "date — if not, resolve whatever is holding "
                                "it and re-plan the downstream schedule."),
            evidence=[_ev("workflow_activity", a["id"],
                          f"planned_start={a.get('planned_start')}, "
                          f"status={a.get('status')}")],
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("schedule.planned_finish_missed")
def _r_planned_finish_missed(snap: dict) -> list[dict]:
    now = _parse_iso(snap["generated_at"])
    out = []
    for a in snap["workflow_activities"]:
        finish = _parse_iso(a.get("planned_finish"))
        if not finish or a.get("status") == "completed" or a.get("actual_finish"):
            continue
        if finish >= now:
            continue
        days_late = (now - finish).days
        sev = "critical" if days_late >= 7 else "warning"
        dependents = [x["name"] for x in snap["workflow_activities"]
                      if a["id"] in (x.get("depends_on_activity_ids") or [])]
        out.append(_finding(
            rule_id="schedule.planned_finish_missed",
            domain="schedule", severity=sev, confidence="high",
            observation=(f"'{a['name']}' is {days_late} day(s) past its "
                         "planned finish and is not complete."),
            reasoning=("planned_finish has passed with status "
                       f"'{a.get('status')}'. "
                       + (f"It gates {len(dependents)} downstream "
                          f"activit{'y' if len(dependents) == 1 else 'ies'} "
                          f"({', '.join(dependents[:3])}"
                          f"{'…' if len(dependents) > 3 else ''}) — this is "
                          "a live critical-path risk."
                          if dependents else
                          "No modelled activity depends on it, so the risk "
                          "is contained to this activity's own scope.")),
            recommended_action=(f"Get a completion forecast for '{a['name']}' "
                                "from the site team and update planned dates "
                                "for the affected downstream activities."),
            evidence=[_ev("workflow_activity", a["id"],
                          f"planned_finish={a.get('planned_finish')}, "
                          f"status={a.get('status')}")],
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("construction_logic.successor_not_started")
def _r_successor_not_started(snap: dict) -> list[dict]:
    """The generalized 'excavation done, no PCC activity -> begin PCC'
    rule. Uses the project's OWN dependency graph (denormalized from the
    admin-curated Knowledge Core), not a hardcoded sequence: any activity
    whose dependencies were ALL completed >= STALLED_SUCCESSOR_DAYS ago
    and which still hasn't moved is dead time on the critical chain."""
    now = _parse_iso(snap["generated_at"])
    by_id = {a["id"]: a for a in snap["workflow_activities"]}
    out = []
    for a in snap["workflow_activities"]:
        if a.get("status") not in ("ready", "not_started"):
            continue
        deps = [by_id.get(d) for d in (a.get("depends_on_activity_ids") or [])]
        deps = [d for d in deps if d]
        if not deps or any(d.get("status") != "completed" for d in deps):
            continue
        unlocked_at = max(
            (_parse_iso(d.get("status_updated_at")) or now for d in deps),
        )
        idle_days = (now - unlocked_at).days
        if idle_days < STALLED_SUCCESSOR_DAYS:
            continue
        dep_names = ", ".join(d["name"] for d in deps)
        out.append(_finding(
            rule_id="construction_logic.successor_not_started",
            domain="construction_logic",
            severity="warning" if idle_days < 7 else "critical",
            confidence="high",
            observation=(f"{dep_names} complete for {idle_days} day(s); "
                         f"'{a['name']}' has not begun."),
            reasoning=("Every dependency of this activity is completed, so "
                       "the construction sequence allows it to proceed. "
                       f"{idle_days} idle day(s) since the last dependency "
                       "finished is unrecovered time on this chain of work."),
            recommended_action=f"Begin '{a['name']}', or record the reason "
                               "it cannot start (mark it blocked) so the "
                               "delay is visible and attributable.",
            evidence=(
                [_ev("workflow_activity", a["id"],
                     f"status={a.get('status')}")] +
                [_ev("workflow_activity", d["id"],
                     f"dependency completed at {d.get('status_updated_at')}")
                 for d in deps]
            ),
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("construction_logic.activity_blocked")
def _r_activity_blocked(snap: dict) -> list[dict]:
    out = []
    for a in snap["workflow_activities"]:
        if a.get("status") != "blocked":
            continue
        blocked_since = a.get("status_updated_at")
        out.append(_finding(
            rule_id="construction_logic.activity_blocked",
            domain="construction_logic", severity="warning",
            confidence="high",
            observation=f"'{a['name']}' is marked blocked.",
            reasoning=("A blocked workflow activity halts its entire "
                       "downstream dependency chain until resolved. Marked "
                       f"blocked at {blocked_since} by "
                       f"{a.get('status_updated_by_user_name') or 'unknown'}."),
            recommended_action=("Identify and clear the blocker, or "
                                "re-sequence dependent work around it."),
            evidence=[_ev("workflow_activity", a["id"],
                          f"blocked since {blocked_since}")],
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("quality.completed_without_inspection")
def _r_completed_without_inspection(snap: dict) -> list[dict]:
    """Inference over ABSENCE of evidence, therefore medium confidence:
    an activity flagged requires_inspection in the Knowledge Core is
    completed, and no inspection-category operational item exists in the
    project dated after that activity plausibly began. The inspection may
    have happened off-system — the recommendation is to VERIFY, not to
    assert a violation."""
    inspections = [i for i in snap["operational_items"]
                   if i.get("category") == "inspection"]
    out = []
    for a in snap["workflow_activities"]:
        if not a.get("requires_inspection") or a.get("status") != "completed":
            continue
        started = (_parse_iso(a.get("actual_start"))
                   or _parse_iso(a.get("created_at")))
        covered = any(
            (_parse_iso(i.get("created_at")) or started) >= started
            for i in inspections
        ) if started else bool(inspections)
        if covered:
            continue
        out.append(_finding(
            rule_id="quality.completed_without_inspection",
            domain="quality", severity="warning", confidence="medium",
            observation=(f"'{a['name']}' requires inspection and is marked "
                         "complete, but no inspection is recorded in Atlas "
                         "for this period."),
            reasoning=("The Activity Library flags this activity "
                       "requires_inspection. Atlas has no inspection-category "
                       "operational item dated after the activity began. "
                       "Confidence is medium: the inspection may have "
                       "happened but not been recorded."),
            recommended_action=(f"Verify an inspection of '{a['name']}' was "
                                "performed; record it in Atlas, or raise an "
                                "inspection item before dependent work "
                                "conceals the workmanship."),
            evidence=[_ev("workflow_activity", a["id"],
                          "requires_inspection=true, status=completed"),
                      _ev("query", None,
                          "no inspection operational item found in project "
                          "after activity start")],
            subject_id=a["id"],
            affected_activity_id=a["id"], affected_activity_name=a["name"],
        ))
    return out


@rule("safety.unresolved_high_priority")
def _r_safety_unresolved(snap: dict) -> list[dict]:
    now = _parse_iso(snap["generated_at"])
    out = []
    for i in _active(snap["operational_items"]):
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
            domain="safety", severity="critical", confidence="high",
            observation=(f"{i.get('priority').capitalize()}-priority safety "
                         f"observation '{i.get('title')}' has been open for "
                         f"{int(hours_open)} hours."),
            reasoning=("A high/critical safety observation left unresolved "
                       f"past {SAFETY_UNRESOLVED_HOURS}h is exposure the "
                       "company is knowingly carrying — it was reported, "
                       "recorded, and not closed."),
            recommended_action=("Escalate for immediate resolution and "
                                "record the corrective action on the item."),
            evidence=[_ev("operational_item", i["id"],
                          f"status={i.get('status')}, "
                          f"priority={i.get('priority')}, "
                          f"created_at={i.get('created_at')}")],
            subject_id=i["id"],
        ))
    return out


@rule("procurement.material_lead_time")
def _r_material_lead_time(snap: dict) -> list[dict]:
    now = _parse_iso(snap["generated_at"])
    out = []
    for i in _active(snap["operational_items"]):
        if i.get("category") != "material_requirement":
            continue
        req = _parse_iso(i.get("required_by"))
        if not req:
            continue
        days_left = (req - now).days
        if days_left > MATERIAL_LEAD_TIME_DAYS:
            continue
        overdue = req < now
        out.append(_finding(
            rule_id="procurement.material_lead_time",
            domain="procurement",
            severity="critical" if overdue else "warning",
            confidence="high",
            observation=(f"Material requirement '{i.get('title')}' is "
                         + ("past its required date and still "
                            f"{i.get('status')}." if overdue else
                            f"required in {max(days_left, 0)} day(s) and "
                            f"still {i.get('status')}.")),
            reasoning=("An unfulfilled material requirement inside the "
                       "procurement lead-time window is the most common "
                       "precursor to an idle-crew day: work stops the "
                       "morning the material is not on site."),
            recommended_action=("Confirm the purchase order and delivery "
                                "date with the vendor now; if delivery will "
                                "miss the required date, re-sequence the "
                                "dependent work today rather than on the "
                                "morning it fails."),
            evidence=[_ev("operational_item", i["id"],
                          f"required_by={i.get('required_by')}, "
                          f"status={i.get('status')}")],
            subject_id=i["id"],
        ))
    return out


@rule("management.stale_open_item")
def _r_stale_open_item(snap: dict) -> list[dict]:
    now = _parse_iso(snap["generated_at"])
    out = []
    for i in _active(snap["operational_items"]):
        last = _parse_iso(i.get("last_updated_at")) or _parse_iso(i.get("created_at"))
        if not last:
            continue
        idle_days = (now - last).days
        if idle_days < STALE_ITEM_DAYS:
            continue
        out.append(_finding(
            rule_id="management.stale_open_item",
            domain="management", severity="advisory", confidence="high",
            observation=(f"'{i.get('title')}' ({i.get('category')}) has had "
                         f"no activity for {idle_days} days and is still "
                         f"{i.get('status')}."),
            reasoning=("Open items nobody has touched in over a week are "
                       "either silently resolved (and polluting every "
                       "operational metric) or silently stuck (and about to "
                       "resurface as a bigger problem)."),
            recommended_action=("Follow up with the owner: close it if it is "
                                "done, or update/escalate it if it is stuck."),
            evidence=[_ev("operational_item", i["id"],
                          f"last_updated_at={i.get('last_updated_at')}, "
                          f"status={i.get('status')}")],
            subject_id=i["id"],
        ))
    return out


@rule("client_communication.progress_update_due")
def _r_client_update_due(snap: dict) -> list[dict]:
    """Milestone signal: meaningful completion momentum in the last
    MILESTONE_WINDOW_DAYS with no client-facing item raised since. Low/
    medium confidence by design — the PM may have updated the client
    through channels Atlas cannot see."""
    now = _parse_iso(snap["generated_at"])
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
    client_touch = any(
        i.get("category") == "client_approval"
        and (_parse_iso(i.get("created_at")) or oldest) >= oldest
        for i in snap["operational_items"]
    )
    if client_touch:
        return []
    names = ", ".join(a["name"] for a in recent_done[:4])
    proj = snap["project"]
    return [_finding(
        rule_id="client_communication.progress_update_due",
        domain="client_communication", severity="advisory",
        confidence="medium",
        observation=(f"{len(recent_done)} activities completed in the last "
                     f"{MILESTONE_WINDOW_DAYS} days ({names}"
                     f"{'…' if len(recent_done) > 4 else ''}) with no "
                     "client-facing item raised since."),
        reasoning=("Sustained completion momentum is exactly what clients "
                    "pay to hear about, and proactively reported progress "
                    "builds the goodwill that later absorbs bad news. "
                    "Confidence is medium: the client may have been updated "
                    "outside Atlas."),
        recommended_action=("Send the client a progress update covering the "
                            "recently completed work, and record any "
                            "approvals it triggers in Atlas."),
        evidence=[_ev("workflow_activity", a["id"],
                      f"completed {a.get('status_updated_at')}")
                  for a in recent_done[:6]],
        subject_id=f"{proj.get('id')}:{now.date().isocalendar()[:2]}",
    )]


def evaluate_rules(snapshot: dict) -> list[dict]:
    """Run every registered rule over a snapshot. Pure orchestration of
    pure functions — a single misbehaving rule is logged and skipped, the
    rest of the run survives (same failure-isolation instinct as the
    Intelligence worker's per-event error handling)."""
    findings: list[dict] = []
    for rule_id, fn in _RULES:
        try:
            findings.extend(fn(snapshot))
        except Exception:
            logger.exception(f"CRE rule '{rule_id}' failed; skipping")
    return findings


def list_rule_ids() -> list[str]:
    return [rid for rid, _ in _RULES]


# ---------------------------------------------------------------------------
# Project health — a derived, never-stored projection (recomputed on read,
# like operations_engine.derive_health, so it can never go stale).
# ---------------------------------------------------------------------------

def compute_project_health(snapshot: dict, open_insights: list[dict]) -> dict:
    acts = snapshot["workflow_activities"]
    items = _active(snapshot["operational_items"])
    now = _parse_iso(snapshot["generated_at"])

    total = len(acts)
    completed = sum(1 for a in acts if a.get("status") == "completed")
    blocked = sum(1 for a in acts if a.get("status") == "blocked")
    overdue_acts = sum(
        1 for a in acts
        if a.get("status") != "completed"
        and (_parse_iso(a.get("planned_finish")) or now) < now
    )
    overdue_items = sum(1 for i in items if i.get("health") == "overdue")
    critical_insights = sum(1 for x in open_insights
                            if x.get("severity") == "critical")

    score = 100
    score -= 15 * blocked
    score -= 10 * overdue_acts
    score -= 5 * overdue_items
    score -= 10 * critical_insights
    score = max(0, min(100, score))
    status = "green" if score >= 80 else ("amber" if score >= 55 else "red")

    drivers = []
    if blocked:
        drivers.append(f"{blocked} blocked workflow activit{'y' if blocked == 1 else 'ies'}")
    if overdue_acts:
        drivers.append(f"{overdue_acts} activit{'y' if overdue_acts == 1 else 'ies'} past planned finish")
    if overdue_items:
        drivers.append(f"{overdue_items} overdue operational item(s)")
    if critical_insights:
        drivers.append(f"{critical_insights} open critical insight(s)")

    return {
        "score": score,
        "status": status,
        "drivers": drivers,
        "progress": {
            "activities_total": total,
            "activities_completed": completed,
            "percent_complete": round(100 * completed / total, 1) if total else None,
        },
        "open_insights": len(open_insights),
        "computed_at": snapshot["generated_at"],
    }


# ---------------------------------------------------------------------------
# Optional AI review pass — additive, never required, never blocking.
# ---------------------------------------------------------------------------

AI_PROMPT_NAME = "atlas_cre_reviewer"
AI_PROMPT_VERSION = "1.0"
AI_MODEL = "gpt-4o"

AI_SYSTEM_PROMPT = """You are the reasoning reviewer of Project Atlas, a \
Construction Operating System. You receive a compact JSON snapshot of one \
construction project (workflow activities with dependencies and dates, open \
operational items, recent event stats) plus the deterministic findings \
already produced by rule-based reasoning.

Your job: identify AT MOST 3 ADDITIONAL cross-cutting observations the \
rules missed — patterns across multiple signals, not restatements of \
individual findings. Never invent facts not present in the snapshot.

Return ONLY a JSON array (possibly empty). Each element:
{"observation": str, "reasoning": str, "recommended_action": str,
 "confidence": "low"|"medium"|"high",
 "severity": "info"|"advisory"|"warning"|"critical",
 "evidence_ids": [ids of snapshot documents this is based on]}

Be conservative: an empty array is a perfectly good answer."""


def _snapshot_digest(snapshot: dict, findings: list[dict]) -> str:
    """Compact the snapshot for the LLM: ids + reasoning-relevant fields
    only, never raw assets or personal data beyond what the rules see."""
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


async def _ai_review(snapshot: dict, findings: list[dict]) -> list[dict]:
    """Optional LLM pass. Mirrors intelligence_engine's patterns exactly:
    LlmChat via core.llm_compat, markdown-fence stripping, and — the
    important part — total failure isolation: any exception here returns
    [] and the deterministic findings stand alone."""
    if not EMERGENT_LLM_KEY:
        return []
    try:
        from core.llm_compat import LlmChat, UserMessage  # lazy: keeps rule tests import-light
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
            if conf not in CONFIDENCES or sev not in SEVERITIES:
                continue
            out.append(_finding(
                rule_id="ai.cross_project_review",
                domain="ai_observation", severity=sev, confidence=conf,
                observation=str(obs.get("observation", ""))[:500],
                reasoning=str(obs.get("reasoning", ""))[:1000],
                recommended_action=str(obs.get("recommended_action", ""))[:500],
                evidence=[_ev("ai_reference", str(r), "cited by AI reviewer")
                          for r in (obs.get("evidence_ids") or [])[:8]],
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

async def run_reasoning(project_id: str, *, actor: dict,
                        include_ai: bool = False) -> dict:
    """Execute one reasoning pass: snapshot -> rules (-> optional AI) ->
    dedupe against open insights -> persist new insights + run audit doc.
    Idempotent: rerunning on an unchanged project refreshes rather than
    duplicates."""
    project = await _assert_project_visible(project_id, actor)
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
        "rules_evaluated": list_rule_ids(),
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
    await db.reasoning_runs.insert_one({**run_doc})

    open_now = await list_insights(project_id, status="open")
    return {
        "run": run_doc,
        "health": compute_project_health(snapshot, open_now),
        "insights_new": [i for i in open_now if i["id"] in set(new_ids)],
    }


async def list_insights(project_id: str, *, status: Optional[str] = None,
                        domain: Optional[str] = None,
                        limit: int = 500) -> list[dict]:
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
    """Record the human decision on an insight. The engine only ever
    advises; this is where the human's verdict lands — appended to the
    insight's own status_history so the trail is complete."""
    if new_status not in INSIGHT_STATUSES:
        raise ReasoningError(
            f"Invalid status '{new_status}'. Must be one of {sorted(INSIGHT_STATUSES)}")
    insight = await get_insight(insight_id)
    if not insight:
        raise ReasoningNotFoundError(f"Insight '{insight_id}' not found")
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


async def project_health(project_id: str, *, user: dict) -> dict:
    await _assert_project_visible(project_id, user)
    snapshot = await build_project_snapshot(project_id)
    open_now = await list_insights(project_id, status="open")
    return compute_project_health(snapshot, open_now)


async def list_runs(project_id: str, *, user: dict, limit: int = 50) -> list[dict]:
    await _assert_project_visible(project_id, user)
    return await db.reasoning_runs.find(
        {"project_id": project_id}, {"_id": 0}).sort(
        "started_at", -1).to_list(limit)
