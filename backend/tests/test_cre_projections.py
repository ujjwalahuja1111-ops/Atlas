"""CRE construction-intelligence projections — pure unit tests (Sprint 01B).

Covers the projection layer (engines/reasoning_projections.py) and the
two Sprint 01B rules with hand-built snapshots and zero I/O: stage
inference, look-ahead + readiness, the deterministic delay forecast
(exact math), briefing and client-summary composition, blocking impact,
construction-memory records, and the multi-project interface stub.

Run from backend/:  python -m pytest tests/test_cre_projections.py -q
"""
from datetime import datetime, timedelta, timezone

import pytest

from engines import reasoning_engine as cre
from engines import reasoning_projections as proj


NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat()


def days_ago(n):
    return iso(NOW - timedelta(days=n))


def days_ahead(n):
    return iso(NOW + timedelta(days=n))


def snap(activities=None, items=None, events=None, project_id="proj_1"):
    acts = activities or []
    return {
        "schema_version": cre.SNAPSHOT_SCHEMA_VERSION,
        "generated_at": iso(NOW),
        "project": {"id": project_id, "name": "Test Villa"},
        "sites": [{"id": "site_1", "project_id": project_id}],
        "workflow_activities": acts,
        "operational_items": items or [],
        "recent_events": events or [],
        "event_assets": {},
        "recent_proposals": [],
        "stage": proj.infer_project_stage(acts),
    }


def activity(id_, name, status, *, deps=(), planned_start=None,
             planned_finish=None, actual_start=None, actual_finish=None,
             requires_inspection=False, status_updated_at=None, trade=None,
             order=0):
    return {
        "id": id_, "project_id": "proj_1", "name": name, "status": status,
        "depends_on_activity_ids": list(deps),
        "planned_start": planned_start, "planned_finish": planned_finish,
        "actual_start": actual_start, "actual_finish": actual_finish,
        "requires_inspection": requires_inspection,
        "status_updated_at": status_updated_at or days_ago(1),
        "created_at": days_ago(30), "trade": trade, "order": order,
        "knowledge_activity_id": None, "phase_id": None,
        "status_updated_by_user_name": "Tester",
    }


def op_item(id_, category, status="open", *, priority="normal",
            required_by=None, created_at=None, title=None):
    created = created_at or days_ago(1)
    return {
        "id": id_, "project_id": "proj_1", "site_id": "site_1",
        "category": category, "title": title or f"{category} {id_}",
        "status": status, "priority": priority, "health": "on_track",
        "required_by": required_by, "created_at": created,
        "last_updated_at": created, "assigned_to_user_id": None,
    }


# ---------------------------------------------------------------------------
# 1. Stage awareness
# ---------------------------------------------------------------------------

def test_stage_of_activity_keyword_classification():
    cases = {
        "Excavation up to founding level": "excavation",
        "PCC below footings": "foundation",
        "Slab shuttering & casting": "rcc_structure",
        "Brickwork ground floor": "masonry",
        "Terrace waterproofing": "waterproofing",
        "Electrical conduiting": "mep",
        "Internal plastering": "finishes",
        "Snag list & testing": "testing_commissioning",
        "Final cleaning and handover": "handover",
    }
    for name, expected in cases.items():
        assert proj.stage_of_activity({"name": name}) == expected, name
    assert proj.stage_of_activity({"name": "Mystery task"}) is None
    # trade contributes to classification too
    assert proj.stage_of_activity(
        {"name": "First fix", "trade": "plumbing"}) == "mep"


def test_project_stage_inference():
    # no activities at all -> pre-construction
    assert proj.infer_project_stage([])["current"] == "pre_construction"

    # excavation done, foundation pending -> foundation
    s = proj.infer_project_stage([
        activity("a1", "Excavation", "completed"),
        activity("a2", "PCC", "ready", deps=["a1"]),
    ])
    assert s["current"] == "foundation"
    assert s["progress"]["excavation"]["completed"] == 1

    # work in flight wins over earliest-incomplete: masonry in progress
    # while a foundation activity is still open
    s = proj.infer_project_stage([
        activity("a1", "PCC", "ready"),
        activity("a2", "Brickwork", "in_progress"),
    ])
    assert s["current"] == "masonry"
    assert "in progress" in s["reason"]

    # everything classified complete -> handover
    s = proj.infer_project_stage([
        activity("a1", "Excavation", "completed"),
        activity("a2", "Internal plastering", "completed"),
    ])
    assert s["current"] == "handover"


def test_every_insight_knows_the_current_stage():
    s = snap(activities=[
        activity("a1", "Excavation", "completed",
                 status_updated_at=days_ago(5)),
        activity("a2", "PCC", "ready", deps=["a1"]),
    ])
    findings = cre.evaluate_rules(s)
    assert findings
    assert all(f["project_stage"] == "foundation" for f in findings)


# ---------------------------------------------------------------------------
# 2 + 3 + 6. Look-ahead, readiness, quality readiness
# ---------------------------------------------------------------------------

def test_lookahead_identifies_next_expected_with_why_and_preparation():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed",
                     status_updated_at=days_ago(2), requires_inspection=True,
                     actual_start=days_ago(10)),
            activity("a2", "PCC", "ready", deps=["a1"], order=2),
        ],
        items=[op_item("op1", "material_requirement", title="Cement OPC 53",
                       required_by=days_ahead(1))],
    )
    look = proj.project_lookahead(s)
    nxt = look["next_expected"]
    assert nxt["name"] == "PCC"
    assert "Excavation" in nxt["why_expected"]
    checks = {c["check"]: c for c in nxt["prerequisites"]}
    # predecessor requires inspection, none recorded -> not ready
    assert checks["predecessor_inspection"]["status"] == "not_ready"
    assert "Excavation" in checks["predecessor_inspection"]["detail"]
    # material inside lead window -> not ready
    assert checks["materials_available"]["status"] == "not_ready"
    # honesty about the unmodelled
    assert checks["checklist_complete"]["status"] == "unknown"
    assert nxt["ready"] is False
    assert nxt["possible_blockers"]
    assert any("inspection" in p.lower()
               for p in nxt["recommended_preparation"])
    assert look["ready_now"] == []


def test_lookahead_declares_readiness_when_no_gaps():
    s = snap(activities=[
        activity("a1", "Excavation", "completed", status_updated_at=days_ago(1)),
        activity("a2", "PCC", "ready", deps=["a1"]),
    ])
    look = proj.project_lookahead(s)
    assert look["next_expected"]["ready"] is True
    assert look["ready_now"] == ["Ready for PCC"]
    assert look["stage"]["current"] == "foundation"


# ---------------------------------------------------------------------------
# 4. Delay forecast — deterministic, exact math
# ---------------------------------------------------------------------------

def _dated_history():
    return [
        # planned 5d, actual 10d -> productivity sample 2.0
        activity("h1", "Excavation", "completed",
                 planned_start=days_ago(20), planned_finish=days_ago(15),
                 actual_start=days_ago(20), actual_finish=days_ago(10)),
        # planned 2d, actual 4d -> sample 2.0 (median ratio 2.0)
        activity("h2", "PCC", "completed", deps=["h1"],
                 planned_start=days_ago(10), planned_finish=days_ago(8),
                 actual_start=days_ago(10), actual_finish=days_ago(6)),
        # in progress: started 2d ago, planned 5d -> forecast 10d from
        # start -> finish NOW+8d vs planned NOW+3d
        activity("c1", "Columns", "in_progress", deps=["h2"],
                 planned_start=days_ago(2), planned_finish=days_ahead(3),
                 actual_start=days_ago(2)),
        # not started: waits for c1 (NOW+8d) then 5d planned * 2.0 ->
        # finish NOW+18d vs planned NOW+8d
        activity("c2", "Slab casting", "not_started", deps=["c1"],
                 planned_start=days_ahead(3), planned_finish=days_ahead(8)),
    ]


def test_delay_forecast_math_and_confidence():
    fc = proj.delay_forecast(snap(activities=_dated_history()))
    assert fc["productivity_ratio"] == 2.0
    assert fc["productivity_samples"] == 2
    assert fc["planned_date_coverage"] == 1.0
    assert fc["planned_completion"] == days_ahead(8)
    assert fc["forecast_completion"] == days_ahead(18)
    assert fc["forecast_slip_days"] == 10.0
    # dependency propagation: the not-started successor slips most
    assert fc["per_activity"][0]["name"] == "Slab casting"
    assert fc["per_activity"][0]["forecast_slip_days"] == 10.0
    assert fc["per_activity"][1]["forecast_slip_days"] == 5.0
    # 2 samples + full coverage -> medium, with reasons and assumptions
    c = fc["confidence"]
    assert c["level"] == "medium"
    assert "measured" in c["reason"]
    assert any("optimistic" in a for a in c["assumptions"])
    assert c["missing_evidence"]  # wants more samples


def test_forecast_slip_rule_fires_from_the_forecast():
    s = snap(activities=_dated_history())
    hits = [f for f in cre.evaluate_rules(s)
            if f["rule_id"] == "schedule.forecast_finish_slip"]
    assert len(hits) == 1
    f = hits[0]
    assert f["severity"] == "warning"          # 10d slip: >=3, <14
    assert f["confidence"]["level"] == "medium"
    assert f["suggested_responsible_role"] == "management"
    assert "10 day(s)" in f["observation"]
    assert f["dedupe_key"] == "schedule.forecast_finish_slip:proj_1"
    # cites the worst forecast slips as evidence
    assert f["evidence"]["workflow_activities"][0]["id"] == "c2"


def test_forecast_rule_silent_without_material_slip_or_dates():
    quiet = snap(activities=[
        activity("a1", "Excavation", "completed"),
        activity("a2", "PCC", "in_progress", deps=["a1"],
                 planned_start=days_ago(1), planned_finish=days_ahead(5)),
    ])
    assert not [f for f in cre.evaluate_rules(quiet)
                if f["rule_id"] == "schedule.forecast_finish_slip"]
    undated = snap(activities=[activity("a1", "Excavation", "in_progress")])
    fc = proj.delay_forecast(undated)
    assert fc["forecast_slip_days"] is None
    assert fc["confidence"]["level"] == "low"


# ---------------------------------------------------------------------------
# 5. Material readiness rule
# ---------------------------------------------------------------------------

def test_frontier_material_gap_rule():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed",
                     status_updated_at=days_ago(1)),
            activity("a2", "Slab casting", "ready", deps=["a1"]),
        ],
        items=[op_item("op1", "material_requirement", title="TMT steel 8mm",
                       required_by=days_ago(1)),
               op_item("op2", "material_requirement", title="Cement",
                       required_by=days_ahead(30))],  # outside window
    )
    hits = [f for f in cre.evaluate_rules(s)
            if f["rule_id"] == "procurement.frontier_material_gap"]
    assert len(hits) == 1
    f = hits[0]
    assert "Slab casting" in f["observation"]
    assert [r["id"] for r in f["evidence"]["operational_items"]] == ["op1"]
    assert f["confidence"]["level"] == "medium"
    assert "activity-to-material mapping" in \
        f["confidence"]["missing_evidence"][0]
    # no frontier or no gaps -> silent
    no_frontier = snap(activities=[activity("a1", "X", "in_progress")],
                       items=[op_item("op1", "material_requirement",
                                      required_by=days_ago(1))])
    assert not [x for x in cre.evaluate_rules(no_frontier)
                if x["rule_id"] == "procurement.frontier_material_gap"]


# ---------------------------------------------------------------------------
# 8 (building block). Blocking impact
# ---------------------------------------------------------------------------

def test_blocking_impact_counts_transitive_downstream_work():
    s = snap(activities=[
        activity("a1", "Waterproofing", "blocked"),
        activity("a2", "Screed", "not_started", deps=["a1"]),
        activity("a3", "Tiling", "not_started", deps=["a2"]),
        activity("a4", "Painting", "in_progress"),  # independent
    ])
    impact = proj.blocking_impact(s)
    assert impact[0]["name"] == "Waterproofing"
    assert impact[0]["downstream_activities_held"] == 2
    assert impact[0]["reason"] == "blocked"


# ---------------------------------------------------------------------------
# 9. Daily briefing
# ---------------------------------------------------------------------------

def test_daily_briefing_composition():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed",
                     status_updated_at=iso(NOW - timedelta(hours=5))),
            activity("a2", "PCC", "ready", deps=["a1"]),
            activity("a3", "Waterproofing", "blocked"),
            activity("a4", "Brickwork", "in_progress",
                     planned_finish=days_ahead(4)),
        ],
        items=[
            op_item("op1", "client_approval", title="Tile selection"),
            op_item("op2", "material_requirement", required_by=days_ahead(2)),
            op_item("op3", "safety_observation", priority="high"),
        ],
    )
    fake_insights = [
        {"id": "i1", "severity": "critical", "status": "open",
         "observation": "obs-critical", "recommendation": "act",
         "created_at": days_ago(1), "suggested_due_date": days_ahead(1)},
        {"id": "i2", "severity": "advisory", "status": "open",
         "observation": "obs-advisory", "recommendation": "act",
         "created_at": days_ago(2), "suggested_due_date": days_ahead(7)},
    ]
    b = proj.compose_daily_briefing(s, fake_insights)
    assert [x["name"] for x in b["completed_yesterday"]] == ["Excavation"]
    assert b["todays_priorities"][0]["severity"] == "critical"
    assert [x["name"] for x in b["blocked_activities"]] == ["Waterproofing"]
    assert b["required_decisions"]["open_insights_awaiting_review"] == 2
    assert b["required_decisions"]["pending_client_approvals"] == 1
    assert [m["name"] for m in b["upcoming_milestones"]] == ["Brickwork"]
    assert b["client_actions"][0]["title"] == "Tile selection"
    assert len(b["material_risks"]) == 1
    assert len(b["safety_reminders"]) == 1
    assert b["next_expected"]["name"] == "PCC"


# ---------------------------------------------------------------------------
# 10. Client communication intelligence
# ---------------------------------------------------------------------------

def test_client_summary_is_plain_english_and_leaks_no_internals():
    s = snap(
        activities=[
            activity("wfa_a1", "Excavation", "completed",
                     status_updated_at=days_ago(2), requires_inspection=True,
                     actual_start=days_ago(10)),
            activity("wfa_a2", "Foundation PCC", "ready", deps=["wfa_a1"]),
        ],
        items=[op_item("op_secret", "safety_observation", priority="critical",
                       created_at=days_ago(3))],
    )
    cs = proj.compose_client_summary(s)
    text = cs["summary_text"]
    assert "excavation" in text.lower() and "completed" in text.lower()
    # the sprint's flagship translation: next work framed with its gate
    assert "being prepared for foundation pcc" in text.lower()
    assert "expected to begin once" in text.lower()
    assert "quality checks" in text.lower()  # inspection gate, plain English
    # never leaks internal ids, item titles, or safety operational detail
    assert "wfa_" not in text and "op_" not in text
    assert "safety" not in text.lower()
    assert "review" in cs["disclaimer"].lower()


def test_client_summary_when_ready_and_when_empty():
    ready = snap(activities=[
        activity("a1", "Excavation", "completed", status_updated_at=days_ago(1)),
        activity("a2", "PCC", "ready", deps=["a1"]),
    ])
    text = proj.compose_client_summary(ready)["summary_text"].lower()
    assert "ready for pcc" in text and "expected to begin shortly" in text
    empty = proj.compose_client_summary(snap())
    assert empty["sentences"]  # never an empty message


# ---------------------------------------------------------------------------
# 7. Multi-project awareness — interface only
# ---------------------------------------------------------------------------

def test_project_digest_shape_and_compare_stub():
    s = snap(activities=[activity("a1", "Excavation", "completed",
                                  status_updated_at=days_ago(3))])
    findings = cre.evaluate_rules(s)
    d = proj.project_digest(s, findings, cre.compute_project_health(s, findings))
    assert d["project_id"] == "proj_1"
    assert d["stage"] == "handover"
    assert d["health_score"] == 100
    assert d["last_activity_at"] == days_ago(3)
    assert set(d["finding_counts"]) == {"critical", "warning",
                                        "advisory", "info"}
    with pytest.raises(NotImplementedError):
        proj.compare_projects_at_stage([d], "foundation")


# ---------------------------------------------------------------------------
# 11. Construction memory — structure capture, no learning
# ---------------------------------------------------------------------------

def test_memory_record_structure():
    a = activity("a1", "Slab casting", "completed",
                 planned_start=days_ago(12), planned_finish=days_ago(7),
                 actual_start=days_ago(12), actual_finish=days_ago(4),
                 trade="rcc")
    s = snap(
        activities=[a],
        items=[
            op_item("op1", "material_requirement", created_at=days_ago(9)),
            op_item("op2", "client_approval", created_at=days_ago(8)),
            op_item("op3", "site_issue", created_at=days_ago(6)),
            op_item("op4", "site_issue", created_at=days_ago(1)),  # outside
        ],
    )
    m = proj.build_memory_record(a, s)
    assert m["schema_version"] == proj.MEMORY_SCHEMA_VERSION
    assert m["stage"] == "rcc_structure"
    assert m["planned_duration_days"] == 5.0
    assert m["actual_duration_days"] == 8.0
    assert m["variance_days"] == 3.0
    assert m["material_delay_item_ids"] == ["op1"]
    assert m["approval_item_ids"] == ["op2"]
    assert m["issue_item_ids"] == ["op3"]
    # explicit placeholders until the sources exist — structure complete
    assert m["weather_impacts"] == [] and m["labour_count"] is None
