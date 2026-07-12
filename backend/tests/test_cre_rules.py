"""CRE deterministic rule layer — pure unit tests (Innovation Sprint 01).

These tests exercise the Construction Reasoning Engine's rule registry
DIRECTLY, with hand-built snapshots and zero I/O — no Mongo, no HTTP, no
AI. That is possible because every rule is a pure function
(snapshot -> findings), which is a deliberate design property of the
engine, and these tests are the proof it holds.

They complement (not replace) tests/test_atlas_cre.py, which verifies the
same engine end-to-end over HTTP against the real running application,
per the project's "do not claim a fix based only on unit tests" rule.

Run from backend/:  python -m pytest tests/test_cre_rules.py -q
"""
from datetime import datetime, timedelta, timezone

from engines import reasoning_engine as cre


NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def days_ago(n: float) -> str:
    return iso(NOW - timedelta(days=n))


def days_ahead(n: float) -> str:
    return iso(NOW + timedelta(days=n))


def snap(activities=None, items=None, events=None) -> dict:
    return {
        "generated_at": iso(NOW),
        "project": {"id": "proj_1", "name": "Test Villa"},
        "sites": [{"id": "site_1", "project_id": "proj_1"}],
        "workflow_activities": activities or [],
        "operational_items": items or [],
        "recent_events": events or [],
    }


def activity(id_, name, status, *, deps=(), planned_start=None,
             planned_finish=None, actual_start=None, actual_finish=None,
             requires_inspection=False, status_updated_at=None,
             created_at=None, phase_id=None) -> dict:
    return {
        "id": id_, "project_id": "proj_1", "name": name, "status": status,
        "depends_on_activity_ids": list(deps),
        "planned_start": planned_start, "planned_finish": planned_finish,
        "actual_start": actual_start, "actual_finish": actual_finish,
        "requires_inspection": requires_inspection,
        "status_updated_at": status_updated_at or days_ago(1),
        "created_at": created_at or days_ago(30),
        "phase_id": phase_id, "order": 0,
        "status_updated_by_user_name": "Tester",
    }


def op_item(id_, category, status="open", *, priority="normal",
            required_by=None, created_at=None, last_updated_at=None,
            title=None) -> dict:
    created = created_at or days_ago(1)
    return {
        "id": id_, "project_id": "proj_1", "site_id": "site_1",
        "category": category, "title": title or f"{category} {id_}",
        "status": status, "priority": priority, "health": "on_track",
        "required_by": required_by, "created_at": created,
        "last_updated_at": last_updated_at or created,
    }


def by_rule(findings, rule_id):
    return [f for f in findings if f["rule_id"] == rule_id]


# ---------------------------------------------------------------------------
# Finding contract — the sprint-mandated recommendation structure
# ---------------------------------------------------------------------------

def test_every_finding_carries_the_full_recommendation_contract():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed",
                     status_updated_at=days_ago(5)),
            activity("a2", "PCC", "ready", deps=["a1"]),
        ],
    )
    findings = cre.evaluate_rules(s)
    assert findings, "scenario must produce at least one finding"
    for f in findings:
        for key in ("rule_id", "domain", "severity", "confidence",
                    "observation", "reasoning", "recommended_action",
                    "evidence", "dedupe_key"):
            assert f.get(key), f"finding missing '{key}': {f}"
        assert f["domain"] in cre.DOMAINS
        assert f["severity"] in cre.SEVERITIES
        assert f["confidence"] in cre.CONFIDENCES
        assert isinstance(f["evidence"], list) and f["evidence"]
        for ev in f["evidence"]:
            assert "kind" in ev and "detail" in ev


# ---------------------------------------------------------------------------
# Schedule rules
# ---------------------------------------------------------------------------

def test_planned_start_missed_fires_only_for_unstarted_past_dates():
    s = snap(activities=[
        activity("a1", "Footings", "ready", planned_start=days_ago(3)),
        activity("a2", "Columns", "in_progress", planned_start=days_ago(3)),
        activity("a3", "Slab", "ready", planned_start=days_ahead(2)),
        activity("a4", "Walls", "ready"),  # no planned date at all
    ])
    hits = by_rule(cre.evaluate_rules(s), "schedule.planned_start_missed")
    assert [f["affected_activity_id"] for f in hits] == ["a1"]
    assert hits[0]["confidence"] == "high"
    assert hits[0]["severity"] == "warning"


def test_planned_start_missed_escalates_to_critical_after_a_week():
    s = snap(activities=[
        activity("a1", "Footings", "not_started", planned_start=days_ago(10)),
    ])
    (f,) = by_rule(cre.evaluate_rules(s), "schedule.planned_start_missed")
    assert f["severity"] == "critical"


def test_planned_finish_missed_names_downstream_dependents_in_reasoning():
    s = snap(activities=[
        activity("a1", "Brickwork", "in_progress", planned_finish=days_ago(2)),
        activity("a2", "Plastering", "not_started", deps=["a1"]),
    ])
    (f,) = by_rule(cre.evaluate_rules(s), "schedule.planned_finish_missed")
    assert "Plastering" in f["reasoning"]
    assert f["affected_activity_name"] == "Brickwork"


# ---------------------------------------------------------------------------
# Construction logic — the generalized "excavation done, begin PCC" rule
# ---------------------------------------------------------------------------

def test_successor_not_started_fires_after_stall_window():
    s = snap(activities=[
        activity("a1", "Excavation", "completed",
                 status_updated_at=days_ago(cre.STALLED_SUCCESSOR_DAYS + 1)),
        activity("a2", "PCC", "ready", deps=["a1"]),
    ])
    (f,) = by_rule(cre.evaluate_rules(s),
                   "construction_logic.successor_not_started")
    assert f["affected_activity_name"] == "PCC"
    assert "Begin 'PCC'" in f["recommended_action"]
    # evidence must reference BOTH the stalled successor and the
    # completed dependency that unlocked it
    ref_ids = {e["ref_id"] for e in f["evidence"]}
    assert {"a1", "a2"} <= ref_ids


def test_successor_not_started_respects_stall_window_and_incomplete_deps():
    s = snap(activities=[
        # unlocked only yesterday — inside the grace window
        activity("a1", "Excavation", "completed", status_updated_at=days_ago(1)),
        activity("a2", "PCC", "ready", deps=["a1"]),
        # dependency not complete — sequence does not allow a start yet
        activity("a3", "Brickwork", "in_progress"),
        activity("a4", "Plastering", "not_started", deps=["a3"],
                 status_updated_at=days_ago(30)),
    ])
    assert not by_rule(cre.evaluate_rules(s),
                       "construction_logic.successor_not_started")


def test_blocked_activity_is_always_surfaced():
    s = snap(activities=[activity("a1", "Waterproofing", "blocked")])
    (f,) = by_rule(cre.evaluate_rules(s),
                   "construction_logic.activity_blocked")
    assert f["severity"] == "warning" and f["confidence"] == "high"


# ---------------------------------------------------------------------------
# Quality — absence-of-evidence rule must be medium confidence
# ---------------------------------------------------------------------------

def test_completed_without_inspection_is_medium_confidence():
    s = snap(activities=[
        activity("a1", "Slab Pour", "completed", requires_inspection=True,
                 actual_start=days_ago(10)),
    ])
    (f,) = by_rule(cre.evaluate_rules(s),
                   "quality.completed_without_inspection")
    assert f["confidence"] == "medium"
    assert "Verify" in f["recommended_action"]


def test_inspection_item_after_activity_start_suppresses_quality_finding():
    s = snap(
        activities=[activity("a1", "Slab Pour", "completed",
                             requires_inspection=True,
                             actual_start=days_ago(10))],
        items=[op_item("op1", "inspection", status="closed",
                       created_at=days_ago(8))],
    )
    assert not by_rule(cre.evaluate_rules(s),
                       "quality.completed_without_inspection")


def test_no_quality_finding_when_inspection_not_required():
    s = snap(activities=[activity("a1", "Painting", "completed")])
    assert not by_rule(cre.evaluate_rules(s),
                       "quality.completed_without_inspection")


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_unresolved_high_priority_safety_item_is_critical():
    s = snap(items=[
        op_item("op1", "safety_observation", priority="critical",
                created_at=days_ago(2)),
        # fresh one inside the 24h window — no alert yet
        op_item("op2", "safety_observation", priority="high",
                created_at=iso(NOW - timedelta(hours=2))),
        # resolved one — never alerts
        op_item("op3", "safety_observation", status="closed",
                priority="critical", created_at=days_ago(5)),
    ])
    hits = by_rule(cre.evaluate_rules(s), "safety.unresolved_high_priority")
    assert [f["evidence"][0]["ref_id"] for f in hits] == ["op1"]
    assert hits[0]["severity"] == "critical"


# ---------------------------------------------------------------------------
# Procurement
# ---------------------------------------------------------------------------

def test_material_lead_time_window_and_overdue_severity():
    s = snap(items=[
        op_item("op1", "material_requirement", required_by=days_ahead(1)),
        op_item("op2", "material_requirement", required_by=days_ago(1)),
        op_item("op3", "material_requirement", required_by=days_ahead(30)),
        op_item("op4", "material_requirement", status="fulfilled",
                required_by=days_ago(1)),
    ])
    hits = {f["evidence"][0]["ref_id"]: f
            for f in by_rule(cre.evaluate_rules(s),
                             "procurement.material_lead_time")}
    assert set(hits) == {"op1", "op2"}
    assert hits["op1"]["severity"] == "warning"
    assert hits["op2"]["severity"] == "critical"


# ---------------------------------------------------------------------------
# Management + client communication
# ---------------------------------------------------------------------------

def test_stale_open_item_advisory():
    s = snap(items=[
        op_item("op1", "site_issue", last_updated_at=days_ago(10)),
        op_item("op2", "site_issue", last_updated_at=days_ago(2)),
    ])
    hits = by_rule(cre.evaluate_rules(s), "management.stale_open_item")
    assert [f["evidence"][0]["ref_id"] for f in hits] == ["op1"]
    assert hits[0]["severity"] == "advisory"


def test_client_update_recommended_after_completion_momentum():
    acts = [activity(f"a{i}", f"Activity {i}", "completed",
                     status_updated_at=days_ago(2)) for i in range(4)]
    s = snap(activities=acts)
    (f,) = by_rule(cre.evaluate_rules(s),
                   "client_communication.progress_update_due")
    assert f["confidence"] == "medium"


def test_client_update_suppressed_when_client_item_already_raised():
    acts = [activity(f"a{i}", f"Activity {i}", "completed",
                     status_updated_at=days_ago(2)) for i in range(4)]
    s = snap(activities=acts,
             items=[op_item("op1", "client_approval", created_at=days_ago(1))])
    assert not by_rule(cre.evaluate_rules(s),
                       "client_communication.progress_update_due")


# ---------------------------------------------------------------------------
# Dedupe keys + failure isolation + health projection
# ---------------------------------------------------------------------------

def test_dedupe_key_is_deterministic_across_runs():
    s = snap(activities=[
        activity("a1", "Footings", "ready", planned_start=days_ago(3)),
    ])
    k1 = cre.evaluate_rules(s)[0]["dedupe_key"]
    k2 = cre.evaluate_rules(s)[0]["dedupe_key"]
    assert k1 == k2 == "schedule.planned_start_missed:a1"


def test_quiet_healthy_project_produces_no_findings():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed", status_updated_at=days_ago(1)),
            activity("a2", "PCC", "in_progress", deps=["a1"],
                     planned_finish=days_ahead(5)),
        ],
        items=[op_item("op1", "material_requirement",
                       required_by=days_ahead(14))],
    )
    assert cre.evaluate_rules(s) == []


def test_malformed_document_never_sinks_the_run():
    s = snap(activities=[
        {"id": "a1", "name": "Garbage", "status": "ready",
         "planned_start": "not-a-date", "depends_on_activity_ids": None},
        activity("a2", "Footings", "ready", planned_start=days_ago(3)),
    ])
    hits = by_rule(cre.evaluate_rules(s), "schedule.planned_start_missed")
    assert [f["affected_activity_id"] for f in hits] == ["a2"]


def test_project_health_projection():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed"),
            activity("a2", "PCC", "blocked"),
            activity("a3", "Brickwork", "in_progress",
                     planned_finish=days_ago(2)),
        ],
        items=[{**op_item("op1", "site_issue"), "health": "overdue"}],
    )
    open_insights = [{"severity": "critical"}]
    h = cre.compute_project_health(s, open_insights)
    # 100 - 15 (blocked) - 10 (overdue activity) - 5 (overdue item)
    # - 10 (critical insight) = 60
    assert h["score"] == 60
    assert h["status"] == "amber"
    assert h["progress"]["activities_completed"] == 1
    assert len(h["drivers"]) == 4


def test_health_is_green_and_driverless_when_nothing_is_wrong():
    s = snap(activities=[activity("a1", "Excavation", "completed")])
    h = cre.compute_project_health(s, [])
    assert h == {**h, "score": 100, "status": "green", "drivers": []}
