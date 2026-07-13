"""CRE projections — pure construction-intelligence computations (Sprint 01B).

Everything in this module is a PURE function over plain-dict snapshots
(built by reasoning_engine.build_project_snapshot): no Mongo, no HTTP,
no AI, no side effects. reasoning_engine imports from this module —
never the reverse — so all of Atlas' construction intelligence stays
unit-testable without a database.

Where CRE's rules answer "what is wrong?", the projections here answer
the forward-looking questions of a Construction Project Intelligence
Layer:

  * infer_project_stage      — where is this project in its lifecycle?
  * project_lookahead        — what should happen next, and is the
                               project ready for it?
  * activity_readiness       — is the project ready to execute this
                               activity? (drawings / inspections /
                               approvals / materials)
  * delay_forecast           — deterministic completion forecast from
                               the project's own measured productivity
                               (no AI estimation)
  * compose_daily_briefing   — the PM's deterministic morning briefing
  * compose_client_summary   — plain-English progress draft for clients
  * project_digest /
    blocking_impact          — portfolio building blocks for executive
                               reasoning
  * compare_projects_at_stage — INTERFACE ONLY: future multi-project
                               comparative intelligence
  * build_memory_record      — construction-memory capture structure
                               (no learning; structure only)

Like every projection in CRE (see project health), nothing here is
stored: recomputed on read, so it can never go stale.
"""
from __future__ import annotations
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value) -> Optional[datetime]:
    """Tolerant ISO parsing (operations_engine._parse_iso convention):
    naive timestamps are assumed UTC; garbage returns None — one bad
    document must never sink a computation."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _days(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# 1. Construction stage awareness
# ---------------------------------------------------------------------------

STAGE_ORDER = [
    "pre_construction", "excavation", "foundation", "rcc_structure",
    "masonry", "waterproofing", "mep", "finishes",
    "testing_commissioning", "handover",
]
STAGE_LABELS = {
    "pre_construction": "Pre-construction",
    "excavation": "Excavation",
    "foundation": "Foundation",
    "rcc_structure": "RCC Structure",
    "masonry": "Masonry",
    "waterproofing": "Waterproofing",
    "mep": "MEP",
    "finishes": "Finishes",
    "testing_commissioning": "Testing & Commissioning",
    "handover": "Handover",
}
# Deterministic classification of an activity into a lifecycle stage by
# name/trade keywords. Deliberately transparent and auditable — no ML.
# When the Knowledge Core later carries explicit stage tags, only
# stage_of_activity changes (stable knowledge interface); everything
# built on top is untouched.
_STAGE_KEYWORDS = [
    ("excavation", ("excavat", "earthwork", "earth work", "dewater")),
    ("foundation", ("pcc", "footing", "foundation", "raft", "pile",
                    "plinth", "anti-termite", "anti termite")),
    ("rcc_structure", ("rcc", "column", "beam", "slab", "shutter",
                       "reinforc", "concret", "casting", "staircase",
                       "lintel")),
    ("masonry", ("masonry", "brick", "block work", "blockwork", "aac")),
    ("waterproofing", ("waterproof", "damp proof", "membrane")),
    ("mep", ("electric", "plumbing", "hvac", "fire fight", "firefight",
             "mep", "conduit", "wiring", "sanitary", "drainage", "duct",
             "cabling")),
    ("finishes", ("plaster", "paint", "putty", "tile", "floor",
                  "carpentr", "door", "window", "false ceiling",
                  "polish", "cladding", "grill", "railing", "granite",
                  "marble")),
    ("testing_commissioning", ("testing", "commission", "snag")),
    ("handover", ("handover", "hand over", "completion certificate",
                  "final cleaning")),
]


def stage_of_activity(activity: dict) -> Optional[str]:
    """Classify one activity into a lifecycle stage (or None if the
    name/trade matches no stage vocabulary)."""
    text = f"{activity.get('name', '')} {activity.get('trade', '')}".lower()
    for stage, keywords in _STAGE_KEYWORDS:
        if any(k in text for k in keywords):
            return stage
    return None


def infer_project_stage(activities: list[dict]) -> dict:
    """Where is the project in its lifecycle? Deterministic inference
    from the workflow itself: the current stage is the earliest lifecycle
    stage (in canonical order) whose activities are not all complete —
    preferring a stage with work actually in flight. Projects with no
    activities are pre_construction; projects with everything complete
    are at handover."""
    per_stage: dict[str, dict] = {}
    unclassified = 0
    for a in activities:
        stage = stage_of_activity(a)
        if stage is None:
            unclassified += 1
            continue
        s = per_stage.setdefault(stage, {"total": 0, "completed": 0,
                                         "in_progress": 0})
        s["total"] += 1
        if a.get("status") == "completed":
            s["completed"] += 1
        elif a.get("status") == "in_progress":
            s["in_progress"] += 1

    if not activities:
        current, reason = "pre_construction", "no workflow activities exist yet"
    elif not per_stage:
        current, reason = "pre_construction", (
            "no activity matched the stage vocabulary")
    else:
        active = [s for s in STAGE_ORDER if s in per_stage
                  and per_stage[s]["in_progress"] > 0]
        incomplete = [s for s in STAGE_ORDER if s in per_stage
                      and per_stage[s]["completed"] < per_stage[s]["total"]]
        if active:
            current = active[0]
            reason = f"work is in progress in {STAGE_LABELS[current]}"
        elif incomplete:
            current = incomplete[0]
            reason = (f"{STAGE_LABELS[current]} is the earliest stage "
                      "with incomplete activities")
        else:
            current = "handover"
            reason = "every stage-classified activity is complete"

    return {
        "current": current,
        "current_label": STAGE_LABELS[current],
        "reason": reason,
        "order": STAGE_ORDER,
        "progress": {s: per_stage[s] for s in STAGE_ORDER if s in per_stage},
        "unclassified_activities": unclassified,
    }


# ---------------------------------------------------------------------------
# Shared micro-logic
# ---------------------------------------------------------------------------

_TERMINAL_ITEM_STATUSES = {"fulfilled", "verified", "closed", "archived",
                           "cancelled", "duplicate"}


def _active_items(items: list[dict]) -> list[dict]:
    return [i for i in items if i.get("status") not in _TERMINAL_ITEM_STATUSES]


def inspection_covered(activity: dict, items: list[dict]) -> bool:
    """Is a requires-inspection activity covered by an inspection-category
    operational item dated after it began? (Shared by the quality rule
    and the readiness checks — one definition of 'covered', everywhere.)"""
    inspections = [i for i in items if i.get("category") == "inspection"]
    started = (_parse_iso(activity.get("actual_start"))
               or _parse_iso(activity.get("created_at")))
    if not started:
        return bool(inspections)
    return any((_parse_iso(i.get("created_at")) or started) >= started
               for i in inspections)


def _frontier(activities: list[dict]) -> list[dict]:
    """Activities the construction sequence allows to start now: not yet
    begun, with every dependency completed (or no dependencies)."""
    by_id = {a["id"]: a for a in activities}
    out = []
    for a in activities:
        if a.get("status") not in ("ready", "not_started"):
            continue
        deps = [by_id.get(d) for d in (a.get("depends_on_activity_ids") or [])]
        deps = [d for d in deps if d]
        if all(d.get("status") == "completed" for d in deps):
            out.append(a)
    return sorted(out, key=lambda a: a.get("order") or 0)


# ---------------------------------------------------------------------------
# 6. Quality / execution readiness
# ---------------------------------------------------------------------------

def activity_readiness(snapshot: dict, activity: dict) -> list[dict]:
    """"Is the project ready to execute this activity?" — a deterministic
    checklist, each check {check, status: ready|not_ready|unknown,
    detail}. Checks that Atlas cannot yet model are reported `unknown`
    with an honest detail rather than silently omitted."""
    acts = {a["id"]: a for a in snapshot["workflow_activities"]}
    items = _active_items(snapshot["operational_items"])
    all_items = snapshot["operational_items"]
    checks = []

    deps = [acts.get(d) for d in (activity.get("depends_on_activity_ids") or [])]
    deps = [d for d in deps if d]
    incomplete = [d["name"] for d in deps if d.get("status") != "completed"]
    checks.append({
        "check": "dependencies_complete",
        "status": "ready" if not incomplete else "not_ready",
        "detail": ("all dependencies completed" if not incomplete else
                   f"waiting on: {', '.join(incomplete)}"),
    })

    uninspected = [d["name"] for d in deps
                   if d.get("requires_inspection")
                   and d.get("status") == "completed"
                   and not inspection_covered(d, all_items)]
    checks.append({
        "check": "predecessor_inspection",
        "status": "not_ready" if uninspected else "ready",
        "detail": (f"no inspection recorded for: {', '.join(uninspected)}"
                   if uninspected else
                   "no predecessor inspection outstanding"),
    })

    open_drawings = [i for i in items if i.get("category") == "drawing_request"]
    checks.append({
        "check": "drawings_available",
        "status": "not_ready" if open_drawings else "ready",
        "detail": (f"{len(open_drawings)} open drawing request(s) in the "
                   "project" if open_drawings else
                   "no open drawing requests"),
    })

    pending_approvals = [i for i in items
                         if i.get("category") == "client_approval"]
    checks.append({
        "check": "client_approval",
        "status": "not_ready" if pending_approvals else "ready",
        "detail": (f"{len(pending_approvals)} client approval(s) pending "
                   "in the project" if pending_approvals else
                   "no client approvals pending"),
    })

    now = _parse_iso(snapshot["generated_at"]) or _now()
    material_gaps = [
        i for i in items
        if i.get("category") == "material_requirement"
        and (_parse_iso(i.get("required_by")) or now) <= now + timedelta(days=3)
    ]
    checks.append({
        "check": "materials_available",
        "status": "not_ready" if material_gaps else "ready",
        "detail": (f"{len(material_gaps)} material requirement(s) unfulfilled "
                   "inside the lead-time window" if material_gaps else
                   "no unfulfilled material requirements in the window"),
    })

    checks.append({
        "check": "checklist_complete",
        "status": "unknown",
        "detail": "execution checklists are not modelled in Atlas yet",
    })
    return checks


# ---------------------------------------------------------------------------
# 2 + 3. Look-ahead intelligence & construction readiness
# ---------------------------------------------------------------------------

def project_lookahead(snapshot: dict) -> dict:
    """What should happen next on this project — and is it ready to?

    For each frontier activity: why it is expected, its readiness
    prerequisites, possible blockers, and recommended preparation. All
    derived from the project's own dependency graph and operational
    ledger; nothing invented."""
    stage = snapshot.get("stage") or infer_project_stage(
        snapshot["workflow_activities"])
    by_id = {a["id"]: a for a in snapshot["workflow_activities"]}
    in_progress = [a for a in snapshot["workflow_activities"]
                   if a.get("status") == "in_progress"]
    blocked = [a for a in snapshot["workflow_activities"]
               if a.get("status") == "blocked"]

    upcoming = []
    ready_names = []
    for a in _frontier(snapshot["workflow_activities"])[:5]:
        deps = [by_id[d] for d in (a.get("depends_on_activity_ids") or [])
                if d in by_id]
        checks = activity_readiness(snapshot, a)
        gaps = [c for c in checks if c["status"] == "not_ready"]
        prep = [f"Resolve: {c['detail']}" for c in gaps]
        if any(d.get("requires_inspection") and d.get("status") == "completed"
               and not inspection_covered(d, snapshot["operational_items"])
               for d in deps):
            pass  # already covered by predecessor_inspection gap -> prep
        if not gaps:
            ready_names.append(a["name"])
        entry = {
            "activity_id": a["id"],
            "name": a["name"],
            "trade": a.get("trade"),
            "stage": stage_of_activity(a),
            "why_expected": (
                f"all dependencies complete ({', '.join(d['name'] for d in deps)})"
                if deps else
                "no dependencies — first in its sequence"),
            "prerequisites": checks,
            "possible_blockers": [c["detail"] for c in gaps] or
                                 ["none identified in Atlas"],
            "recommended_preparation": prep or
                ["confirm crew and start date; no gaps identified"],
            "ready": not gaps,
        }
        upcoming.append(entry)

    return {
        "stage": stage,
        "next_expected": upcoming[0] if upcoming else None,
        "upcoming": upcoming,
        "ready_now": [f"Ready for {n}" for n in ready_names],
        "in_progress": [{"activity_id": a["id"], "name": a["name"]}
                        for a in in_progress],
        "blocked": [{"activity_id": a["id"], "name": a["name"],
                     "since": a.get("status_updated_at")}
                    for a in blocked],
        "computed_at": snapshot["generated_at"],
    }


# ---------------------------------------------------------------------------
# 4. Delay forecast — deterministic, from the project's own measured
# productivity. Not detection (that is the schedule rules' job): forecast.
# No AI estimation.
# ---------------------------------------------------------------------------

def _planned_days(a: dict) -> Optional[float]:
    ps, pf = _parse_iso(a.get("planned_start")), _parse_iso(a.get("planned_finish"))
    if ps and pf and pf > ps:
        return _days(ps, pf)
    return None


def delay_forecast(snapshot: dict) -> dict:
    """Forecast the project's completion deterministically:

        current progress -> historical productivity (median of
        actual/planned duration over this project's completed
        activities) -> dependency propagation in topological order ->
        likely completion vs planned -> confidence.

    Confidence is structural, not stylistic: it scales with how many
    measured productivity samples exist and how much of the workflow
    carries planned dates — and its reason, assumptions, and missing
    evidence are stated."""
    acts = snapshot["workflow_activities"]
    now = _parse_iso(snapshot["generated_at"]) or _now()

    samples = []
    for a in acts:
        if a.get("status") != "completed":
            continue
        pd = _planned_days(a)
        s, f = _parse_iso(a.get("actual_start")), _parse_iso(a.get("actual_finish"))
        if pd and s and f and f > s:
            samples.append(_days(s, f) / pd)
    ratio = round(statistics.median(samples), 3) if samples else 1.0

    dated = [a for a in acts if _planned_days(a) is not None]
    coverage = round(len(dated) / len(acts), 2) if acts else 0.0

    by_id = {a["id"]: a for a in acts}
    order = sorted(acts, key=lambda a: a.get("order") or 0)
    forecast_finish: dict[str, Optional[datetime]] = {}
    # dependency-respecting passes over an order-sorted list (dependency
    # cycles cannot livelock this: unresolved deps fall back below)
    for _ in range(3):
        for a in order:
            aid = a["id"]
            if a.get("status") == "completed":
                forecast_finish[aid] = (_parse_iso(a.get("actual_finish"))
                                        or _parse_iso(a.get("status_updated_at")))
                continue
            dur = _planned_days(a)
            if a.get("status") == "in_progress":
                start = (_parse_iso(a.get("actual_start"))
                         or _parse_iso(a.get("status_updated_at")) or now)
                forecast_finish[aid] = (start + timedelta(days=dur * ratio)
                                        if dur else _parse_iso(a.get("planned_finish")))
                continue
            dep_finishes = [forecast_finish.get(d)
                            for d in (a.get("depends_on_activity_ids") or [])
                            if d in by_id]
            resolved = [d for d in dep_finishes if d]
            start = max(resolved + [now]) if resolved else now
            forecast_finish[aid] = (start + timedelta(days=dur * ratio)
                                    if dur else None)

    per_activity = []
    for a in acts:
        if a.get("status") == "completed":
            continue
        pf, ff = _parse_iso(a.get("planned_finish")), forecast_finish.get(a["id"])
        if pf and ff:
            per_activity.append({
                "activity_id": a["id"], "name": a["name"],
                "planned_finish": a.get("planned_finish"),
                "forecast_finish": _iso(ff),
                "forecast_slip_days": round(_days(pf, ff), 1),
            })
    per_activity.sort(key=lambda x: -x["forecast_slip_days"])

    planned_all = [_parse_iso(a.get("planned_finish")) for a in acts]
    planned_all = [p for p in planned_all if p]
    known_ff = [f for f in forecast_finish.values() if f]
    planned_completion = max(planned_all) if planned_all else None
    forecast_completion = max(known_ff) if known_ff else None
    slip = (round(_days(planned_completion, forecast_completion), 1)
            if planned_completion and forecast_completion else None)

    if len(samples) >= 5 and coverage >= 0.9:
        level = "high"
    elif len(samples) >= 2 and coverage >= 0.5:
        level = "medium"
    else:
        level = "low"
    missing = []
    if len(samples) < 5:
        missing.append(f"more measured activities (have {len(samples)} "
                       "with planned and actual dates)")
    if coverage < 0.9:
        missing.append(f"planned dates on more activities "
                       f"(coverage {coverage:.0%})")

    return {
        "productivity_ratio": ratio,
        "productivity_samples": len(samples),
        "planned_date_coverage": coverage,
        "planned_completion": _iso(planned_completion) if planned_completion else None,
        "forecast_completion": _iso(forecast_completion) if forecast_completion else None,
        "forecast_slip_days": slip,
        "per_activity": per_activity[:10],
        "confidence": {
            "level": level,
            "reason": ("forecast extrapolates this project's own measured "
                       f"productivity (median actual/planned = {ratio} over "
                       f"{len(samples)} completed activities) through the "
                       "dependency graph"),
            "missing_evidence": missing,
            "assumptions": [
                "future productivity resembles measured productivity",
                "blocked and unstarted frontier work begins immediately "
                "(optimistic floor — real slip can only be larger)",
                "activities without planned dates do not extend the "
                "critical chain",
            ],
            "contradictions": [],
        },
        "computed_at": snapshot["generated_at"],
    }


# ---------------------------------------------------------------------------
# 9. PM daily briefing — deterministic morning composition
# ---------------------------------------------------------------------------

def compose_daily_briefing(snapshot: dict, open_insights: list[dict]) -> dict:
    now = _parse_iso(snapshot["generated_at"]) or _now()
    acts = snapshot["workflow_activities"]
    items = _active_items(snapshot["operational_items"])
    look = project_lookahead(snapshot)
    sev_rank = {"critical": 0, "warning": 1, "advisory": 2, "info": 3}

    completed_yesterday = [
        {"activity_id": a["id"], "name": a["name"],
         "at": a.get("status_updated_at")}
        for a in acts if a.get("status") == "completed"
        and (_parse_iso(a.get("status_updated_at")) or now)
        >= now - timedelta(hours=24)
    ]
    priorities = sorted(open_insights, key=lambda i: (
        sev_rank.get(i.get("severity"), 9), i.get("created_at", "")))[:5]
    decisions = [i for i in open_insights if i.get("status") == "open"]
    milestones = [
        {"activity_id": a["id"], "name": a["name"],
         "planned_finish": a.get("planned_finish")}
        for a in acts if a.get("status") != "completed"
        and a.get("planned_finish")
        and now <= (_parse_iso(a.get("planned_finish")) or now)
        <= now + timedelta(days=7)
    ]
    client_actions = [i for i in items if i.get("category") == "client_approval"]
    material_risks = [
        i for i in items if i.get("category") == "material_requirement"
        and i.get("required_by")
        and (_parse_iso(i.get("required_by")) or now)
        <= now + timedelta(days=3)
    ]
    safety = [i for i in items if i.get("category") == "safety_observation"]

    def _item(i):
        return {"item_id": i["id"], "title": i.get("title"),
                "priority": i.get("priority"), "status": i.get("status"),
                "required_by": i.get("required_by")}

    return {
        "project_id": snapshot["project"].get("id"),
        "project_name": snapshot["project"].get("name"),
        "stage": look["stage"]["current"],
        "stage_label": look["stage"]["current_label"],
        "completed_yesterday": completed_yesterday,
        "todays_priorities": [
            {"insight_id": i.get("id"), "severity": i.get("severity"),
             "observation": i.get("observation"),
             "recommendation": i.get("recommendation"),
             "suggested_due_date": i.get("suggested_due_date")}
            for i in priorities],
        "blocked_activities": look["blocked"],
        "required_decisions": {
            "open_insights_awaiting_review": len(decisions),
            "pending_client_approvals": len(client_actions),
        },
        "upcoming_milestones": milestones[:8],
        "next_expected": look["next_expected"],
        "client_actions": [_item(i) for i in client_actions[:8]],
        "material_risks": [_item(i) for i in material_risks[:8]],
        "safety_reminders": [_item(i) for i in safety[:8]],
        "generated_at": snapshot["generated_at"],
    }


# ---------------------------------------------------------------------------
# 10. Client communication intelligence — deterministic plain-English
# progress draft. Operational events -> construction progress -> plain
# English. Template-based; AI may enhance WORDING later, never content.
# ---------------------------------------------------------------------------

def _friendly_list(names: list[str]) -> str:
    names = [n.lower() for n in names]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def compose_client_summary(snapshot: dict) -> dict:
    """A client-facing progress narrative built ONLY from workflow-level
    facts (never raw operational data, safety items, or internal ids in
    the text). Always a DRAFT for human review — CRE prepares the words;
    a human decides to send them."""
    now = _parse_iso(snapshot["generated_at"]) or _now()
    acts = snapshot["workflow_activities"]
    look = project_lookahead(snapshot)
    stage = look["stage"]

    sentences = []
    total = len(acts)
    done = sum(1 for a in acts if a.get("status") == "completed")
    if total:
        sentences.append(
            f"Your project is currently in the {stage['current_label']} "
            f"stage, with {done} of {total} planned activities completed.")

    recent = [a for a in acts if a.get("status") == "completed"
              and (_parse_iso(a.get("status_updated_at")) or now)
              >= now - timedelta(days=7)]
    if recent:
        sentences.append(
            f"Over the past week, the {_friendly_list([a['name'] for a in recent[:4]])} "
            f"work{' has' if len(recent) == 1 else 's have'} been completed "
            "successfully.")

    in_prog = [a["name"] for a in acts if a.get("status") == "in_progress"]
    if in_prog:
        sentences.append(
            f"Work is currently progressing on {_friendly_list(in_prog[:3])}.")

    nxt = look["next_expected"]
    if nxt:
        gaps = [c for c in nxt["prerequisites"] if c["status"] == "not_ready"]
        if gaps:
            waiting = {
                "dependencies_complete": "the preceding works are completed",
                "predecessor_inspection": "final quality checks are completed",
                "drawings_available": "the required drawings are finalized",
                "client_approval": "the pending approvals are received",
                "materials_available": "the required materials arrive on site",
            }
            reasons = [waiting.get(g["check"], "final checks are completed")
                       for g in gaps[:2]]
            sentences.append(
                f"The site is now being prepared for {nxt['name'].lower()}, "
                f"which is expected to begin once {_friendly_list(reasons)}.")
        else:
            sentences.append(
                f"The site is ready for {nxt['name'].lower()}, which is "
                "expected to begin shortly.")

    if not sentences:
        sentences.append("Site preparations are underway; a detailed "
                         "progress update will follow shortly.")

    return {
        "project_id": snapshot["project"].get("id"),
        "project_name": snapshot["project"].get("name"),
        "stage": stage["current"],
        "sentences": sentences,
        "summary_text": " ".join(sentences),
        "disclaimer": ("Deterministic draft generated from workflow facts. "
                       "For human review before sending to the client."),
        "generated_at": snapshot["generated_at"],
    }


# ---------------------------------------------------------------------------
# 7 + 8. Portfolio building blocks (multi-project awareness)
# ---------------------------------------------------------------------------

def blocking_impact(snapshot: dict) -> list[dict]:
    """For every blocked or overdue-finish activity: how much modelled
    work it is holding up (transitive downstream dependents). Answers
    'which activity is blocking the most work?' deterministically."""
    acts = snapshot["workflow_activities"]
    now = _parse_iso(snapshot["generated_at"]) or _now()
    children: dict[str, list[str]] = {}
    for a in acts:
        for d in (a.get("depends_on_activity_ids") or []):
            children.setdefault(d, []).append(a["id"])

    def _downstream(aid: str) -> set[str]:
        seen, stack = set(), list(children.get(aid, []))
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(children.get(x, []))
        return seen

    out = []
    for a in acts:
        overdue = (a.get("status") != "completed" and a.get("planned_finish")
                   and (_parse_iso(a.get("planned_finish")) or now) < now)
        if a.get("status") != "blocked" and not overdue:
            continue
        blocked_ids = _downstream(a["id"])
        incomplete = [x for x in blocked_ids
                      if {b["id"]: b for b in acts}[x].get("status") != "completed"]
        out.append({
            "activity_id": a["id"], "name": a["name"],
            "status": a.get("status"),
            "reason": "blocked" if a.get("status") == "blocked"
                      else "past planned finish",
            "downstream_activities_held": len(incomplete),
        })
    return sorted(out, key=lambda x: -x["downstream_activities_held"])


def project_digest(snapshot: dict, findings: list[dict],
                   health: dict) -> dict:
    """Compact per-project digest — the unit of portfolio reasoning."""
    acts = snapshot["workflow_activities"]
    events = snapshot.get("recent_events", [])
    stamps = ([_parse_iso(a.get("status_updated_at")) for a in acts] +
              [_parse_iso(e.get("server_created_at")) for e in events])
    stamps = [s for s in stamps if s]
    sev = {"critical": 0, "warning": 0, "advisory": 0, "info": 0}
    for f in findings:
        sev[f["severity"]] += 1
    return {
        "project_id": snapshot["project"].get("id"),
        "project_name": snapshot["project"].get("name"),
        "stage": (snapshot.get("stage") or {}).get("current"),
        "health_score": health["score"],
        "health_status": health["status"],
        "progress": health["progress"],
        "finding_counts": sev,
        "last_activity_at": _iso(max(stamps)) if stamps else None,
    }


def compare_projects_at_stage(digests: list[dict], stage: str) -> dict:
    """INTERFACE ONLY (Sprint 01B item 7 — multi-project comparative
    intelligence). Future contract: given portfolio digests, compare
    projects at the same lifecycle stage against each other ('Project B:
    same stage, unusually slow') using measured pace (productivity
    ratios, stage dwell time) — deterministically, against the
    portfolio's own baselines, never invented ones.

    Deliberately not implemented this sprint: honest comparison needs
    stage dwell-time capture (Construction Memory) to accumulate first.
    The signature and digest inputs are frozen now so the future
    implementation slots in without schema changes."""
    raise NotImplementedError(
        "compare_projects_at_stage is an interface reserved for future "
        "multi-project comparative intelligence (Sprint 01B item 7).")


# ---------------------------------------------------------------------------
# 11. Construction memory — capture structure only (NO learning)
# ---------------------------------------------------------------------------

MEMORY_SCHEMA_VERSION = 1


def build_memory_record(activity: dict, snapshot: dict) -> dict:
    """The long-term learning substrate: one record per completed
    activity, capturing what the plan said, what reality did, and what
    surrounded it. Fields Atlas cannot measure yet (weather, labour
    count) are captured as explicit nulls/empties so the schema is
    complete from day one and fills in as capture density grows.
    NOTHING reads these records back in this sprint."""
    start = (_parse_iso(activity.get("actual_start"))
             or _parse_iso(activity.get("created_at")))
    finish = (_parse_iso(activity.get("actual_finish"))
              or _parse_iso(activity.get("status_updated_at")))
    planned = _planned_days(activity)
    actual = _days(start, finish) if start and finish and finish > start else None

    def _in_window(i):
        c = _parse_iso(i.get("created_at"))
        return c and start and finish and start <= c <= finish

    items = snapshot["operational_items"]
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "project_id": snapshot["project"].get("id"),
        "activity_id": activity["id"],
        "knowledge_activity_id": activity.get("knowledge_activity_id"),
        "name": activity["name"],
        "trade": activity.get("trade"),
        "stage": stage_of_activity(activity),
        "planned_duration_days": round(planned, 1) if planned else None,
        "actual_duration_days": round(actual, 1) if actual else None,
        "variance_days": (round(actual - planned, 1)
                          if planned and actual else None),
        "window": {"start": _iso(start) if start else None,
                   "finish": _iso(finish) if finish else None},
        "material_delay_item_ids": [
            i["id"] for i in items
            if i.get("category") == "material_requirement" and _in_window(i)],
        "approval_item_ids": [
            i["id"] for i in items
            if i.get("category") == "client_approval" and _in_window(i)],
        "issue_item_ids": [
            i["id"] for i in items
            if i.get("category") in ("site_issue", "quality_observation",
                                     "safety_observation") and _in_window(i)],
        # explicit placeholders — not modelled in Atlas yet, captured as
        # structure so the record is complete when the sources arrive:
        "weather_impacts": [],
        "labour_count": None,
    }
