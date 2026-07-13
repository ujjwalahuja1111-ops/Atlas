"""CRE deterministic rule layer — pure unit tests (Sprints 01 / 01A).

These exercise the Construction Reasoning Engine's rule registry
DIRECTLY, with hand-built snapshots and zero I/O — no Mongo, no HTTP, no
AI. Possible because every rule is a pure function (snapshot ->
findings); these tests are the proof that property holds.

Sprint 01A additions pinned here: the schema-v2 insight contract
(explicit evidence sections incl. absences, structured explainable
confidence, the observation -> risk -> recommendation -> suggested
action/role/due-date chain), explicit rule->domain metadata, and the
five-dimension reasoned project health model.

Run from backend/:  python -m pytest tests/test_cre_rules.py -q
"""
from datetime import datetime, timedelta, timezone

from engines import reasoning_engine as cre
from engines.operations_engine import CATEGORIES as OPS_CATEGORIES


NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def days_ago(n: float) -> str:
    return iso(NOW - timedelta(days=n))


def days_ahead(n: float) -> str:
    return iso(NOW + timedelta(days=n))


def snap(activities=None, items=None, events=None, event_assets=None) -> dict:
    return {
        "schema_version": cre.SNAPSHOT_SCHEMA_VERSION,
        "generated_at": iso(NOW),
        "project": {"id": "proj_1", "name": "Test Villa"},
        "sites": [{"id": "site_1", "project_id": "proj_1"}],
        "workflow_activities": activities or [],
        "operational_items": items or [],
        "recent_events": events or [],
        "event_assets": event_assets or {},
        "recent_proposals": [],
    }


def activity(id_, name, status, *, deps=(), planned_start=None,
             planned_finish=None, actual_start=None, actual_finish=None,
             requires_inspection=False, status_updated_at=None,
             created_at=None, phase_id=None, knowledge_activity_id=None):
    return {
        "id": id_, "project_id": "proj_1", "name": name, "status": status,
        "depends_on_activity_ids": list(deps),
        "planned_start": planned_start, "planned_finish": planned_finish,
        "actual_start": actual_start, "actual_finish": actual_finish,
        "requires_inspection": requires_inspection,
        "status_updated_at": status_updated_at or days_ago(1),
        "created_at": created_at or days_ago(30),
        "phase_id": phase_id, "order": 0,
        "knowledge_activity_id": knowledge_activity_id,
        "status_updated_by_user_name": "Tester",
    }


def op_item(id_, category, status="open", *, priority="normal",
            required_by=None, created_at=None, last_updated_at=None,
            title=None):
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


def ev_ids(finding, kind):
    return [r["id"] for r in finding["evidence"][kind]]


# ---------------------------------------------------------------------------
# The schema-v2 insight contract
# ---------------------------------------------------------------------------

def test_every_finding_carries_the_full_v2_contract():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed",
                     status_updated_at=days_ago(5)),
            activity("a2", "PCC", "ready", deps=["a1"]),
            activity("a3", "Slab Pour", "completed",
                     requires_inspection=True, actual_start=days_ago(10)),
        ],
        items=[op_item("op1", "material_requirement",
                       required_by=days_ago(1))],
    )
    findings = cre.evaluate_rules(s)
    assert len(findings) >= 3, "scenario must produce several findings"
    for f in findings:
        assert f["schema_version"] == cre.INSIGHT_SCHEMA_VERSION
        # reasoning chain: observation -> risk -> recommendation ->
        # suggested action -> suggested role -> suggested due date
        for key in ("observation", "risk", "recommendation"):
            assert f.get(key), f"finding missing '{key}': {f['rule_id']}"
        action = f["suggested_operational_action"]
        assert action and action["category"] in OPS_CATEGORIES
        assert action["title"] and action["description"]
        assert f["suggested_responsible_role"] in cre.SUGGESTED_ROLES
        assert f["suggested_due_date"] > s["generated_at"]
        # explicit evidence section: all seven kinds ALWAYS present
        assert list(f["evidence"].keys()) == cre.EVIDENCE_KINDS
        assert any(f["evidence"][k] for k in cre.EVIDENCE_KINDS), \
            "conclusions alone are not allowed — evidence must exist"
        for kind in cre.EVIDENCE_KINDS:
            for ref in f["evidence"][kind]:
                assert set(ref) == {"id", "detail"} and ref["detail"]
        # structured, explainable confidence
        c = f["confidence"]
        assert c["level"] in cre.CONFIDENCE_LEVELS
        assert c["reason"], "confidence must explain WHY"
        for lst in ("missing_evidence", "assumptions", "contradictions"):
            assert isinstance(c[lst], list)
        assert f["domain"] in cre.DOMAINS
        assert f["severity"] in cre.SEVERITIES
        assert f["dedupe_key"].startswith(f["rule_id"] + ":")


def test_suggested_due_date_tracks_severity():
    critical = snap(activities=[
        activity("a1", "Footings", "not_started", planned_start=days_ago(10)),
    ])
    advisory = snap(items=[
        op_item("op1", "site_issue", last_updated_at=days_ago(10)),
    ])
    (fc,) = by_rule(cre.evaluate_rules(critical),
                    "schedule.planned_start_missed")
    (fa,) = by_rule(cre.evaluate_rules(advisory),
                    "management.stale_open_item")
    assert fc["severity"] == "critical"
    assert fc["suggested_due_date"] == iso(NOW + timedelta(days=1))
    assert fa["severity"] == "advisory"
    assert fa["suggested_due_date"] == iso(NOW + timedelta(days=7))


# ---------------------------------------------------------------------------
# Explicit domain organization (metadata)
# ---------------------------------------------------------------------------

def test_every_rule_declares_exactly_one_known_domain():
    rules = cre.list_rules()
    assert len(rules) == 11  # 9 from Sprint 01 + forecast + frontier-gap (01B)
    for r in rules:
        assert r["domain"] in cre.DOMAINS
        assert r["description"]
    # reserved, rule-less domains exist as metadata only
    used = {r["domain"] for r in rules}
    assert {"commercial", "documentation", "resource_planning"} <= \
        cre.DOMAINS - used


def test_findings_never_leave_their_rules_domain():
    s = snap(activities=[activity("a1", "X", "blocked")],
             items=[op_item("op1", "safety_observation", priority="critical",
                            created_at=days_ago(2))])
    by_id = {r["id"]: r["domain"] for r in cre.list_rules()}
    for f in cre.evaluate_rules(s):
        assert f["domain"] == by_id[f["rule_id"]]


# ---------------------------------------------------------------------------
# Schedule rules
# ---------------------------------------------------------------------------

def test_planned_start_missed_fires_only_for_unstarted_past_dates():
    s = snap(activities=[
        activity("a1", "Footings", "ready", planned_start=days_ago(3)),
        activity("a2", "Columns", "in_progress", planned_start=days_ago(3)),
        activity("a3", "Slab", "ready", planned_start=days_ahead(2)),
        activity("a4", "Walls", "ready"),
    ])
    hits = by_rule(cre.evaluate_rules(s), "schedule.planned_start_missed")
    assert [f["affected_activity_id"] for f in hits] == ["a1"]
    assert hits[0]["confidence"]["level"] == "high"
    assert hits[0]["severity"] == "warning"
    # no linked site events -> that gap is named as missing evidence
    assert hits[0]["confidence"]["missing_evidence"]
    assert hits[0]["confidence"]["contradictions"] == []


def test_planned_start_missed_escalates_to_critical_after_a_week():
    s = snap(activities=[
        activity("a1", "Footings", "not_started", planned_start=days_ago(10)),
    ])
    (f,) = by_rule(cre.evaluate_rules(s), "schedule.planned_start_missed")
    assert f["severity"] == "critical"


def test_linked_site_events_become_corroborating_and_contradictory_evidence():
    s = snap(
        activities=[activity("a1", "Footings", "ready",
                             planned_start=days_ago(3))],
        events=[{"id": "evt1", "site_id": "site_1", "type": "photo",
                 "ai_status": "completed",
                 "server_created_at": days_ago(1), "activity_id": "a1"}],
        event_assets={"evt1": ["asset1", "asset2"]},
    )
    (f,) = by_rule(cre.evaluate_rules(s), "schedule.planned_start_missed")
    assert ev_ids(f, "events") == ["evt1"]
    assert set(ev_ids(f, "media")) == {"asset1", "asset2"}
    # events linked to a "not started" activity point the other way:
    assert f["confidence"]["contradictions"]
    assert f["confidence"]["missing_evidence"] == []


def test_planned_finish_missed_names_downstream_dependents_as_risk():
    s = snap(activities=[
        activity("a1", "Brickwork", "in_progress", planned_finish=days_ago(2)),
        activity("a2", "Plastering", "not_started", deps=["a1"]),
    ])
    (f,) = by_rule(cre.evaluate_rules(s), "schedule.planned_finish_missed")
    assert "Plastering" in f["risk"]
    assert f["affected_activity_name"] == "Brickwork"
    assert set(ev_ids(f, "workflow_activities")) == {"a1", "a2"}


# ---------------------------------------------------------------------------
# Construction logic — generalized "excavation done, begin PCC"
# ---------------------------------------------------------------------------

def test_successor_not_started_fires_after_stall_window():
    s = snap(activities=[
        activity("a1", "Excavation", "completed",
                 status_updated_at=days_ago(cre.STALLED_SUCCESSOR_DAYS + 1),
                 knowledge_activity_id="ki_exc"),
        activity("a2", "PCC", "ready", deps=["a1"],
                 knowledge_activity_id="ki_pcc"),
    ])
    (f,) = by_rule(cre.evaluate_rules(s),
                   "construction_logic.successor_not_started")
    assert f["affected_activity_name"] == "PCC"
    assert "Begin 'PCC'" in f["recommendation"]
    assert f["suggested_operational_action"]["title"] == "Start 'PCC'"
    assert f["suggested_responsible_role"] == "supervisor"
    # evidence references successor + completed dependency + the
    # Knowledge Core items the sequence came from
    assert set(ev_ids(f, "workflow_activities")) == {"a1", "a2"}
    assert set(ev_ids(f, "knowledge_items")) == {"ki_exc", "ki_pcc"}


def test_successor_not_started_respects_stall_window_and_incomplete_deps():
    s = snap(activities=[
        activity("a1", "Excavation", "completed", status_updated_at=days_ago(1)),
        activity("a2", "PCC", "ready", deps=["a1"]),
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
    assert f["severity"] == "warning"
    # a recorded human judgment, not an inference
    assert f["confidence"]["level"] == "high"
    assert "human" in f["confidence"]["reason"]


# ---------------------------------------------------------------------------
# Quality — absence-of-evidence must be explainably medium confidence
# ---------------------------------------------------------------------------

def test_completed_without_inspection_explains_its_uncertainty():
    s = snap(activities=[
        activity("a1", "Slab Pour", "completed", requires_inspection=True,
                 actual_start=days_ago(10), knowledge_activity_id="ki_slab"),
    ])
    (f,) = by_rule(cre.evaluate_rules(s),
                   "quality.completed_without_inspection")
    c = f["confidence"]
    assert c["level"] == "medium"
    assert "ABSENCE" in c["reason"] or "absence" in c["reason"].lower()
    assert c["missing_evidence"], "must name what would raise confidence"
    assert c["assumptions"], "must name what it takes on faith"
    # negative evidence is explicit
    assert f["evidence"]["absences"]
    assert ev_ids(f, "knowledge_items") == ["ki_slab"]
    assert f["suggested_operational_action"]["category"] == "inspection"


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
# Safety / procurement / management / client communication
# ---------------------------------------------------------------------------

def test_unresolved_high_priority_safety_item_is_critical():
    s = snap(items=[
        op_item("op1", "safety_observation", priority="critical",
                created_at=days_ago(2)),
        op_item("op2", "safety_observation", priority="high",
                created_at=iso(NOW - timedelta(hours=2))),
        op_item("op3", "safety_observation", status="closed",
                priority="critical", created_at=days_ago(5)),
    ])
    hits = by_rule(cre.evaluate_rules(s), "safety.unresolved_high_priority")
    assert [ev_ids(f, "operational_items")[0] for f in hits] == ["op1"]
    assert hits[0]["severity"] == "critical"
    assert hits[0]["suggested_responsible_role"] == "management"


def test_material_lead_time_window_and_overdue_severity():
    s = snap(items=[
        op_item("op1", "material_requirement", required_by=days_ahead(1)),
        op_item("op2", "material_requirement", required_by=days_ago(1)),
        op_item("op3", "material_requirement", required_by=days_ahead(30)),
        op_item("op4", "material_requirement", status="fulfilled",
                required_by=days_ago(1)),
    ])
    hits = {ev_ids(f, "operational_items")[0]: f
            for f in by_rule(cre.evaluate_rules(s),
                             "procurement.material_lead_time")}
    assert set(hits) == {"op1", "op2"}
    assert hits["op1"]["severity"] == "warning"
    assert hits["op2"]["severity"] == "critical"
    # vendor/PO status is honestly named as missing evidence
    assert hits["op2"]["confidence"]["missing_evidence"]


def test_stale_open_item_advisory():
    s = snap(items=[
        op_item("op1", "site_issue", last_updated_at=days_ago(10)),
        op_item("op2", "site_issue", last_updated_at=days_ago(2)),
    ])
    hits = by_rule(cre.evaluate_rules(s), "management.stale_open_item")
    assert [ev_ids(f, "operational_items")[0] for f in hits] == ["op1"]
    assert hits[0]["severity"] == "advisory"


def test_client_update_recommended_after_completion_momentum():
    acts = [activity(f"a{i}", f"Activity {i}", "completed",
                     status_updated_at=days_ago(2)) for i in range(4)]
    s = snap(activities=acts)
    (f,) = by_rule(cre.evaluate_rules(s),
                   "client_communication.progress_update_due")
    assert f["confidence"]["level"] == "medium"
    assert f["evidence"]["absences"]
    assert f["suggested_responsible_role"] == "management"


def test_client_update_suppressed_when_client_item_already_raised():
    acts = [activity(f"a{i}", f"Activity {i}", "completed",
                     status_updated_at=days_ago(2)) for i in range(4)]
    s = snap(activities=acts,
             items=[op_item("op1", "client_approval", created_at=days_ago(1))])
    assert not by_rule(cre.evaluate_rules(s),
                       "client_communication.progress_update_due")


# ---------------------------------------------------------------------------
# Dedupe + failure isolation
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


# ---------------------------------------------------------------------------
# Project health — five reasoned dimensions, pure, not AI, never stored
# ---------------------------------------------------------------------------

def test_health_dimensions_math_and_weakest_dimension_pull():
    s = snap(
        activities=[
            activity("a1", "Excavation", "completed"),
            activity("a2", "PCC", "blocked"),                       # schedule -12
            activity("a3", "Brickwork", "in_progress",
                     planned_finish=days_ago(2)),                   # schedule -12
        ],
        items=[op_item("op1", "safety_observation", priority="critical",
                       created_at=days_ago(2))],                    # safety -35
    )
    h = cre.compute_project_health(s)
    d = h["dimensions"]
    assert set(d) == {"schedule", "quality", "safety",
                      "communication", "operational"}
    assert d["schedule"]["score"] == 76
    assert d["safety"]["score"] == 65
    assert d["quality"]["score"] == 100
    assert d["communication"]["score"] == 100
    assert d["operational"]["score"] == 100
    # mean 88.2, min 65 -> overall leans to the weakest dimension: 77
    assert h["score"] == 77
    assert h["status"] == "amber"
    # each dimension explains itself
    for dim in d.values():
        assert dim["explanation"]
    assert len(d["schedule"]["contributing_factors"]) == 2
    assert d["safety"]["contributing_factors"][0]["severity"] == "critical"
    assert d["quality"]["contributing_factors"] == []
    assert h["progress"]["activities_completed"] == 1
    assert h["drivers"]


def test_health_is_green_and_driverless_when_nothing_is_wrong():
    s = snap(activities=[activity("a1", "Excavation", "completed")])
    h = cre.compute_project_health(s)
    assert h["score"] == 100 and h["status"] == "green"
    assert h["drivers"] == []
    assert all(dim["score"] == 100 for dim in h["dimensions"].values())


def test_health_reuses_precomputed_findings_when_given():
    s = snap(activities=[activity("a1", "X", "blocked")])
    findings = cre.evaluate_rules(s)
    assert cre.compute_project_health(s, findings) == \
        cre.compute_project_health(s)
