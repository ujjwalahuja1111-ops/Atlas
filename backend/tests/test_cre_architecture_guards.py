"""CRE architecture guards (Sprint 01C — merge readiness).

These tests don't verify features; they verify the ARCHITECTURE — the
invariants CRE_ARCHITECTURE.md declares permanent. They are cheap, pure,
and intended to fail loudly if any future sprint (or merge) erodes a
boundary:

  1. Layer purity, by source scan: the projection layer touches no
     database and no async I/O; the engine mutates ONLY its own three
     collections; routes never touch the database at all.
  2. Role-vocabulary drift: CRE's gates and suggested roles must match
     the FAC-04 frozen role model exactly — the class of breakage this
     sprint's audit actually found and fixed.
  3. Full-registry contract: ONE snapshot that fires every registered
     rule, with every finding checked against the complete schema-v2
     contract (evidence, structured confidence, reasoning chain).
  4. Determinism and replayability: identical snapshot in, byte-identical
     reasoning out — twice — with the snapshot itself unmutated.
  5. Non-contradiction: rules that reason about the same situation must
     pull in the same direction (begin-vs-hold consolidation).

Run from backend/:  python -m pytest tests/test_cre_architecture_guards.py -q
"""
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engines import memory_engine
from engines import reasoning_engine as cre
from engines import reasoning_projections as proj

BACKEND = Path(__file__).resolve().parents[1]
ENGINE_SRC = (BACKEND / "engines" / "reasoning_engine.py").read_text()
PROJ_SRC = (BACKEND / "engines" / "reasoning_projections.py").read_text()
ROUTES_SRC = (BACKEND / "routes" / "reasoning.py").read_text()

NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def days_ago(n):
    return iso(NOW - timedelta(days=n))


def days_ahead(n):
    return iso(NOW + timedelta(days=n))


# ---------------------------------------------------------------------------
# 1. Layer purity — enforced against the source itself
# ---------------------------------------------------------------------------

def test_projection_layer_is_pure():
    """The projection layer must stay a pure computation module: no
    database handle, no engine import (dependency direction is engine ->
    projections, never back), and no async I/O of any kind."""
    imports = "\n".join(l for l in PROJ_SRC.splitlines()
                        if re.match(r"\s*(import |from )", l))
    assert "core.db" not in imports
    assert "reasoning_engine" not in imports
    assert "async def" not in PROJ_SRC
    assert "await " not in PROJ_SRC


CRE_OWNED_COLLECTIONS = {"reasoning_insights", "reasoning_runs",
                         "construction_memory"}
_MUTATORS = ("insert_one", "insert_many", "update_one", "update_many",
             "replace_one", "delete_one", "delete_many", "create_index",
             "drop")


def test_engine_mutates_only_its_own_collections():
    """The structural read-only guarantee, verified at the source level:
    every mutating database call in the engine targets a CRE-owned
    collection. This is what makes 'CRE never modifies project state,
    workflow or operations' a property, not a promise."""
    for coll, method in re.findall(r"db\.(\w+)\.(\w+)\(", ENGINE_SRC):
        if method in _MUTATORS:
            assert coll in CRE_OWNED_COLLECTIONS, (
                f"engine mutates non-CRE collection: db.{coll}.{method}")


def test_routes_never_touch_the_database_or_engine_privates():
    """Routes stay thin: HTTP <-> engine translation only. All data
    access and all visibility checks live inside the engine."""
    assert "db." not in ROUTES_SRC
    assert "core.db" not in ROUTES_SRC
    assert "._assert_project_visible" not in ROUTES_SRC


# ---------------------------------------------------------------------------
# 2. Role-vocabulary drift guard (FAC-04 frozen model)
# ---------------------------------------------------------------------------

def test_cre_role_vocabulary_matches_the_frozen_model():
    frozen = {"management", "project_manager", "site_supervisor", "client"}
    assert memory_engine.ROLES == frozen, (
        "the platform role model changed — re-audit every CRE gate")
    # suggested owners are exactly the internal roles
    assert cre.SUGGESTED_ROLES == frozen - {"client"}
    # the gates in routes reference only frozen-model roles
    for role in re.findall(r'role[\"\']?\]?\s*(?:==|not in|in)\s*'
                           r'[\(\"\']+([a-z_\", ]+)', ROUTES_SRC):
        for token in re.findall(r"[a-z_]+", role):
            assert token in frozen, f"stale role literal in routes: {token}"


# ---------------------------------------------------------------------------
# Shared: one snapshot that fires EVERY registered rule
# ---------------------------------------------------------------------------

def _act(id_, name, status, **kw):
    a = {"id": id_, "project_id": "proj_g", "name": name, "status": status,
         "depends_on_activity_ids": [], "planned_start": None,
         "planned_finish": None, "actual_start": None, "actual_finish": None,
         "requires_inspection": False, "status_updated_at": days_ago(1),
         "created_at": days_ago(40), "trade": None, "order": 0,
         "knowledge_activity_id": None, "phase_id": None,
         "status_updated_by_user_name": "Guard"}
    a.update(kw)
    return a


def _item(id_, category, **kw):
    i = {"id": id_, "project_id": "proj_g", "site_id": "site_g",
         "category": category, "title": f"{category} {id_}", "status": "open",
         "priority": "normal", "health": "on_track", "required_by": None,
         "created_at": days_ago(1), "last_updated_at": days_ago(1),
         "assigned_to_user_id": None}
    i.update(kw)
    return i


def _all_rules_snapshot():
    acts = [
        # forecast history: planned 5d, actual 10d -> productivity 2.0
        _act("h1", "Ground floor slab", "completed",
             planned_start=days_ago(30), planned_finish=days_ago(25),
             actual_start=days_ago(30), actual_finish=days_ago(20),
             status_updated_at=days_ago(20)),
        # successor_not_started: Excavation done 5d, PCC untouched
        _act("exc", "Excavation", "completed", status_updated_at=days_ago(5)),
        _act("pcc", "PCC", "ready", depends_on_activity_ids=["exc"]),
        # planned_start_missed
        _act("foot", "Footings", "ready", planned_start=days_ago(3)),
        # planned_finish_missed
        _act("brick", "Brickwork", "in_progress",
             planned_finish=days_ago(2)),
        # blocked
        _act("wp", "Waterproofing", "blocked"),
        # quality: completed requires_inspection, no inspection item
        _act("slab2", "First floor slab", "completed",
             requires_inspection=True, actual_start=days_ago(12),
             status_updated_at=days_ago(2)),
        # forecast slip: in progress, planned 5d at 2.0x from 2d ago
        # -> finish NOW+8d vs planned NOW+3d (project forecast slip 5d)
        _act("col", "Columns", "in_progress",
             planned_start=days_ago(2), planned_finish=days_ahead(3),
             actual_start=days_ago(2)),
        # client update momentum (>=3 completed in 7 days, incl. above)
        _act("m1", "Kitchen tiles", "completed", status_updated_at=days_ago(2)),
        _act("m2", "Bedroom paint", "completed", status_updated_at=days_ago(2)),
    ]
    items = [
        _item("saf", "safety_observation", priority="critical",
              created_at=days_ago(2)),
        _item("mat", "material_requirement", required_by=days_ago(1)),
        _item("stale", "site_issue", last_updated_at=days_ago(10)),
    ]
    return {
        "schema_version": cre.SNAPSHOT_SCHEMA_VERSION,
        "generated_at": iso(NOW),
        "project": {"id": "proj_g", "name": "Guard Villa"},
        "sites": [{"id": "site_g", "project_id": "proj_g"}],
        "workflow_activities": acts,
        "operational_items": items,
        "recent_events": [],
        "event_assets": {},
        "recent_proposals": [],
        "stage": proj.infer_project_stage(acts),
    }


# ---------------------------------------------------------------------------
# 3. Full-registry contract — every rule fires, every finding explains
# ---------------------------------------------------------------------------

def test_every_registered_rule_fires_and_honours_the_full_contract():
    snap = _all_rules_snapshot()
    findings = cre.evaluate_rules(snap)
    fired = {f["rule_id"] for f in findings}
    registered = {r["id"] for r in cre.list_rules()}
    assert fired == registered, (
        f"rules never exercised by the guard snapshot: {registered - fired}")

    for f in findings:
        rid = f["rule_id"]
        # reasoning chain
        for key in ("observation", "risk", "recommendation"):
            assert f.get(key), f"{rid}: missing {key}"
        # explicit evidence, all kinds present, never empty overall
        assert list(f["evidence"].keys()) == cre.EVIDENCE_KINDS, rid
        assert any(f["evidence"].values()), f"{rid}: conclusion w/o evidence"
        # structured, explained confidence
        c = f["confidence"]
        assert c["level"] in cre.CONFIDENCE_LEVELS and c["reason"], rid
        for lst in ("missing_evidence", "assumptions", "contradictions"):
            assert isinstance(c[lst], list), rid
        # suggestions: deterministic rules always carry owner + due date
        assert f["suggested_responsible_role"] in cre.SUGGESTED_ROLES, rid
        assert f["suggested_due_date"], rid
        assert f["project_stage"] == snap["stage"]["current"], rid
        assert f["dedupe_key"].startswith(rid + ":"), rid


# ---------------------------------------------------------------------------
# 4. Determinism, replayability, snapshot consistency
# ---------------------------------------------------------------------------

def _dumps(x):
    return json.dumps(x, sort_keys=True, default=str)


def test_reasoning_is_deterministic_and_never_mutates_the_snapshot():
    snap = _all_rules_snapshot()
    pristine = copy.deepcopy(snap)

    passes = []
    for _ in range(2):
        passes.append({
            "findings": cre.evaluate_rules(snap),
            "health": cre.compute_project_health(snap),
            "lookahead": proj.project_lookahead(snap),
            "forecast": proj.delay_forecast(snap),
            "briefing": proj.compose_daily_briefing(snap, []),
            "client_summary": proj.compose_client_summary(snap),
            "blocking": proj.blocking_impact(snap),
            "stage": proj.infer_project_stage(snap["workflow_activities"]),
        })
    assert _dumps(passes[0]) == _dumps(passes[1]), (
        "identical snapshot must produce byte-identical reasoning")
    assert _dumps(snap) == _dumps(pristine), (
        "reasoning must never mutate its input snapshot")


def test_reasoning_uses_the_snapshot_clock_not_the_wall_clock():
    """Replayability: the same snapshot evaluated at any later time gives
    the same answer, because all reasoning is anchored to the snapshot's
    own generated_at."""
    snap = _all_rules_snapshot()
    a = _dumps(cre.evaluate_rules(snap))
    assert proj.snapshot_now(snap) == datetime.fromisoformat(
        snap["generated_at"])
    b = _dumps(cre.evaluate_rules(copy.deepcopy(snap)))
    assert a == b


# ---------------------------------------------------------------------------
# 5. Non-contradiction — overlapping rules pull in the same direction
# ---------------------------------------------------------------------------

def test_start_advice_is_readiness_aware_never_contradicting_material_hold():
    """When the sequence says 'X can start' but the material pipeline
    says 'hold', the successor rule must recommend clearing the gaps —
    never a bare 'Begin X' that contradicts the frontier-gap rule's
    'hold the start decision'."""
    snap = _all_rules_snapshot()
    findings = cre.evaluate_rules(snap)
    successor = [f for f in findings
                 if f["rule_id"] == "construction_logic.successor_not_started"]
    gap = [f for f in findings
           if f["rule_id"] == "procurement.frontier_material_gap"]
    assert successor and gap, "both overlapping rules must fire here"
    for f in successor:
        assert not f["recommendation"].startswith("Begin"), (
            "successor rule must defer to readiness gaps")
        assert "Clear" in f["recommendation"]

    # and with a clean pipeline, the plain 'Begin' advice returns
    clean = _all_rules_snapshot()
    clean["operational_items"] = [
        i for i in clean["operational_items"]
        if i["category"] != "material_requirement"]
    successor2 = [f for f in cre.evaluate_rules(clean)
                  if f["rule_id"] == "construction_logic.successor_not_started"]
    assert successor2 and all(f["recommendation"].startswith("Begin")
                              for f in successor2)


def test_client_update_dedupe_key_is_stable_across_weeks():
    """Regression guard for the audit's idempotency fix: the client-
    communication insight's identity must not rotate with the calendar
    week (which minted weekly duplicates while one was still open)."""
    snap = _all_rules_snapshot()
    (f,) = [x for x in cre.evaluate_rules(snap)
            if x["rule_id"] == "client_communication.progress_update_due"]
    assert f["dedupe_key"] == "client_communication.progress_update_due:proj_g"
