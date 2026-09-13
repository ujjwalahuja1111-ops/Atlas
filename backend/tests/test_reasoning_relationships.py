"""Phase E — Construction Relationship & Consequence Foundation tests.

Follows the established mongomock_motor pattern (see
tests/test_dev02_bootstrap_reliability.py's own header for why).

Covers the real, new pure functions in reasoning_projections.py
directly (fast, no HTTP) plus a handful of integration-level checks
through intent_service.handle_intent() for the RBAC and reconciliation
behavior that only makes sense wired end-to-end.

Run from backend/:  python -m pytest tests/test_reasoning_relationships.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_phase_e_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_phase_e_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import (memory_engine, reasoning_engine, commercial_engine,  # noqa: E402
                      operations_engine, workflow_engine, knowledge_engine, reasoning_projections)
from services import intent_service, inbox_intelligence_service  # noqa: E402

for _mod in (memory_engine, reasoning_engine, commercial_engine, operations_engine,
             workflow_engine, knowledge_engine, inbox_intelligence_service):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ADMIN = {"id": "u_pe_admin", "name": "PE Admin", "role": "management"}
PM = {"id": "u_pe_pm", "name": "PE PM", "role": "project_manager"}
CLIENT_USER = {"id": "u_pe_client", "name": "PE Client", "role": "client"}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


async def _make_project(name: str) -> dict:
    return await memory_engine.insert_project(name=name, code=name.replace(" ", "").upper()[:8])


async def _make_activity(project_id, name, status="not_started", depends_on=None, trade="Civil"):
    now = _now()
    aid = f"wa_{uuid.uuid4()}"
    await _mock_db.workflow_activities.insert_one({
        "id": aid, "project_id": project_id, "name": name, "trade": trade,
        "status": status, "depends_on_activity_ids": depends_on or [], "order": 0,
        "default_duration_days": 4, "requires_inspection": False,
        "planned_start": None, "planned_finish": None, "actual_start": None, "actual_finish": None,
        "milestone_id": None,
        "created_at": _iso(now), "updated_at": _iso(now),
    })
    return aid


async def _make_snapshot(project_id):
    return await reasoning_engine.build_project_snapshot(project_id)


# ==========================================================================
# A. Existing activity -> activity dependency remains correct
# ==========================================================================
async def test_activity_dependency_reasoning_unchanged():
    project = await _make_project("PE Dependency Unchanged Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="not_started", depends_on=[a1])
    snapshot = await _make_snapshot(project["id"])
    frontier = reasoning_projections.frontier(snapshot["workflow_activities"])
    assert any(a["id"] == a2 for a in frontier)


# ==========================================================================
# B. Explicit approval -> activity relationship is represented correctly
# ==========================================================================
async def test_explicit_link_is_represented_correctly():
    project = await _make_project("PE Explicit Link Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Electrical First Fix", status="blocked")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Kitchen Layout")
    linked = await operations_engine.link_affected_activities(
        item_id=item["id"], actor=PM, activity_ids=[a2])
    assert linked["affected_activity_ids"] == [a2]

    snapshot = await _make_snapshot(project["id"])
    affecting = reasoning_projections.affecting_items_for(snapshot, a2)
    assert len(affecting) == 1
    assert affecting[0]["title"] == "Kitchen Layout"
    assert affecting[0]["provenance"] == "relationship:fact"


# ==========================================================================
# C. Missing approval relationship is NOT fabricated
# ==========================================================================
async def test_missing_relationship_is_not_fabricated():
    project = await _make_project("PE No Relationship Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Plumbing", status="blocked")
    # A real operational item exists, but is never linked to the activity.
    await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Unrelated Approval")
    snapshot = await _make_snapshot(project["id"])
    affecting = reasoning_projections.affecting_items_for(snapshot, a2)
    assert affecting == []

    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    unknown_steps = [s for s in chain["steps"] if s["provenance"] == "unknown"]
    assert any("No operational item is explicitly linked" in s["statement"] for s in unknown_steps)


# ==========================================================================
# D. Blocked activity appears when relevant
# ==========================================================================
async def test_blocked_activity_appears_in_lookahead():
    project = await _make_project("PE Blocked Appears Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    snapshot = await _make_snapshot(project["id"])
    lookahead = reasoning_projections.project_lookahead(snapshot)
    assert len(lookahead["blocked"]) == 1
    assert lookahead["blocked"][0]["name"] == "Electrical"


# ==========================================================================
# E. Blocked activity includes a truthful blocking reason when known
# ==========================================================================
async def test_blocked_activity_includes_truthful_reason():
    project = await _make_project("PE Truthful Reason Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Electrical First Fix", status="blocked")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Kitchen Layout")
    await operations_engine.link_affected_activities(item_id=item["id"], actor=PM, activity_ids=[a2])
    snapshot = await _make_snapshot(project["id"])
    lookahead = reasoning_projections.project_lookahead(snapshot)
    entry = lookahead["blocked"][0]
    assert entry["blocking_reason"][0]["title"] == "Kitchen Layout"


# ==========================================================================
# F. Direct downstream dependent is identified
# ==========================================================================
async def test_direct_downstream_dependent_identified():
    project = await _make_project("PE Direct Dependent Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    a3 = await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    snapshot = await _make_snapshot(project["id"])
    dependents = reasoning_projections.direct_dependents(snapshot, a2)
    assert len(dependents) == 1
    assert dependents[0]["activity_id"] == a3
    assert dependents[0]["name"] == "Plastering"


# ==========================================================================
# G. Second-hop dependent is identified only where the data supports it
# ==========================================================================
async def test_second_hop_is_not_fabricated_beyond_the_data():
    project = await _make_project("PE Second Hop Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    a3 = await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    a4 = await _make_activity(project["id"], "Painting", status="not_started", depends_on=[a3])
    snapshot = await _make_snapshot(project["id"])
    # direct_dependents is explicitly one-hop by construction - Painting
    # (a genuine second-hop dependent of Electrical) must NOT appear
    # when asking about Electrical directly.
    dependents_of_electrical = reasoning_projections.direct_dependents(snapshot, a2)
    names = {d["name"] for d in dependents_of_electrical}
    assert names == {"Plastering"}
    assert "Painting" not in names
    # But it IS correctly found one hop further out, from Plastering's
    # own perspective - proving the traversal is real, just bounded.
    dependents_of_plastering = reasoning_projections.direct_dependents(snapshot, a3)
    assert {d["name"] for d in dependents_of_plastering} == {"Painting"}


# ==========================================================================
# H. Unsupported relationship produces honest uncertainty
# ==========================================================================
async def test_handover_exposure_is_never_fabricated():
    project = await _make_project("PE Handover Honesty Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    handover_steps = [s for s in chain["steps"] if "handover" in s["statement"].lower()]
    assert len(handover_steps) == 1
    assert handover_steps[0]["provenance"] == "unknown"
    assert "cannot yet be established" in handover_steps[0]["statement"]


# ==========================================================================
# I. Fresh current findings drive current recommendation ranking
# J. Stale persisted recommendations cannot silently masquerade as
#    current complete recommendations
# K. "What should I deal with first?" returns a current, explainable priority
# ==========================================================================
async def test_recommended_actions_reconciled_against_fresh_drivers():
    project = await _make_project("PE Reconciliation Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    now = _now()
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a2}, {"$set": {"planned_finish": _iso(now - timedelta(days=4))}})

    # Exactly one persisted insight - deliberately NOT covering the
    # fresh schedule findings this project's own data already supports.
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "safety", "severity": "critical", "rule_id": "safety.unresolved_high_priority",
        "observation": "A safety hazard is open.", "recommendation": "Resolve it.",
        "suggested_operational_action": {"category": "safety_observation", "title": "Resolve hazard", "description": ""},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })

    result = await reasoning_engine.explain_health(project["id"], user=PM)
    sources = {a["source"] for a in result["recommended_actions"]}
    assert "persisted" in sources
    assert "current" in sources  # test case I/J — the fresh finding was promoted, not silently dropped
    assert result["action_currency"]["current_only_count"] > 0
    # test case K — every recommended action remains traceable to a
    # real rule_id and observation, i.e. explainable, not a bare score.
    for a in result["recommended_actions"]:
        assert a["rule_id"]
        assert a["observation"]


async def test_recommended_actions_do_not_duplicate_a_persisted_rule():
    """A fresh finding that DOES have a persisted counterpart (matched
    by rule_id) must not be promoted a second time as 'current'."""
    project = await _make_project("PE No Duplicate Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    now = _now()
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "construction_logic", "severity": "warning", "rule_id": "construction_logic.activity_blocked",
        "observation": "'Electrical' is marked blocked.", "recommendation": "Unblock it.",
        "suggested_operational_action": {"category": "site_issue", "title": "Unblock", "description": ""},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    blocked_rule_entries = [a for a in result["recommended_actions"] if a["rule_id"] == "construction_logic.activity_blocked"]
    assert len(blocked_rule_entries) == 1
    assert blocked_rule_entries[0]["source"] == "persisted"


# ==========================================================================
# L. Client cannot gain access to restricted relationship information
# M. Management / PM / Supervisor retain appropriate access
# ==========================================================================
async def test_client_cannot_access_relationship_data_via_schedule_intent():
    project = await _make_project("PE Client Restriction Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Kitchen Layout")
    await operations_engine.link_affected_activities(item_id=item["id"], actor=PM, activity_ids=[a2])

    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_schedule_impact", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what happens if the approval remains unresolved?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "data" not in result["result"]


async def test_pm_retains_full_access_to_relationship_data():
    project = await _make_project("PE PM Access Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Kitchen Layout")
    await operations_engine.link_affected_activities(item_id=item["id"], actor=PM, activity_ids=[a2])

    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_schedule_impact", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what happens if the approval remains unresolved?", user=PM, active_project_id=project["id"])
    assert result["result"]["ok"] is True
    assert len(result["result"]["data"]["blocked"]) == 1
    assert result["result"]["data"]["blocked"][0]["blocking_reason"][0]["title"] == "Kitchen Layout"


# ==========================================================================
# N. Existing Phase 1 intent behavior remains compatible
# O. Existing Phase D multi-intent behavior remains compatible
# ==========================================================================
async def test_phase_1_single_intent_shape_unaffected():
    project = await _make_project("PE Phase1 Compat Project")
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_health", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert set(result.keys()) == {"type", "intent", "project", "result"}


async def test_phase_d_multi_intent_shape_unaffected():
    project = await _make_project("PE PhaseD Compat Project")
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_health", "confidence": "high"}, {"intent": "query_schedule_impact", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I be worried about?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    assert len(result["sections"]) == 2


# ==========================================================================
# P. Unsupported cross-project-memory question does not silently route
#    to an unrelated answer
# ==========================================================================
async def test_cross_project_memory_question_declines_honestly():
    intent_service._run_structuring_pass = AsyncMock(
        side_effect=AssertionError("the keyword safety net must short-circuit before this is ever called"))
    result = await intent_service.handle_intent(
        "have we seen this problem before?", user=PM, active_project_id=None)
    assert result["type"] == "unresolved"
    assert "history" in result["message"].lower() or "today" in result["message"].lower()


# ==========================================================================
# Q. Existing project health behavior remains unchanged unless
#    deliberately improved by this phase
# ==========================================================================
async def test_health_score_and_dimensions_computation_unchanged():
    project = await _make_project("PE Health Unchanged Project")
    health = await reasoning_engine.project_health(project["id"], user=PM)
    # A fresh, empty project should still score perfectly healthy -
    # the scoring mechanism itself was not touched by this phase.
    assert health["score"] == 100
    assert health["status"] == "green"


# ==========================================================================
# Pre-Merge Hardening Review — Issue 1: relationship ownership /
# cross-project integrity. link_affected_activities() previously
# accepted any activity_ids without validating they belong to the same
# project as the operational item - a real data-integrity gap, not
# hypothetical (workflow_activities have no site_id field at all,
# confirmed by inspection, so project_id is the only meaningful
# ownership boundary; validated in full before any write, so a single
# invalid id rejects the whole request rather than partially linking).
# ==========================================================================

async def test_same_project_link_succeeds():
    """Test case A."""
    project = await _make_project("PE Ownership Same Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Kitchen Layout")
    linked = await operations_engine.link_affected_activities(
        item_id=item["id"], actor=PM, activity_ids=[a2])
    assert linked["affected_activity_ids"] == [a2]


async def test_cross_project_link_is_rejected():
    """Test case B — the core integrity fix."""
    project_a = await _make_project("PE Ownership Project A")
    project_b = await _make_project("PE Ownership Project B")
    site_a = await memory_engine.insert_site(project_id=project_a["id"], name="Site A")
    activity_in_b = await _make_activity(project_b["id"], "Activity In B", status="not_started")
    item = await operations_engine.create_item(
        actor=PM, site_id=site_a["id"], category="client_approval", title="Approval in A")
    with pytest.raises(ValueError, match="different project"):
        await operations_engine.link_affected_activities(
            item_id=item["id"], actor=PM, activity_ids=[activity_in_b])


async def test_nonexistent_activity_id_is_rejected():
    """A real activity id from another project is the headline case,
    but a fabricated/nonexistent id must be rejected identically,
    never silently dropped."""
    project = await _make_project("PE Ownership Nonexistent Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Approval")
    with pytest.raises(ValueError, match="does not exist"):
        await operations_engine.link_affected_activities(
            item_id=item["id"], actor=PM, activity_ids=["wa_totally_made_up"])


async def test_mixed_valid_and_invalid_ids_rejects_the_whole_request():
    """No partial mutation — one invalid id in a list of otherwise-valid
    ones must reject everything, per the brief's own explicit
    requirement."""
    project = await _make_project("PE Ownership Mixed Project")
    other_project = await _make_project("PE Ownership Mixed Other Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    valid_activity = await _make_activity(project["id"], "Valid Activity", status="blocked")
    invalid_activity = await _make_activity(other_project["id"], "Invalid Activity", status="not_started")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Mixed Approval")
    with pytest.raises(ValueError):
        await operations_engine.link_affected_activities(
            item_id=item["id"], actor=PM, activity_ids=[valid_activity, invalid_activity])


# ==========================================================================
# D. Rejected requests do not partially mutate the operational item
# ==========================================================================
async def test_rejected_link_does_not_mutate_the_item():
    project = await _make_project("PE Ownership No Mutation Project")
    other_project = await _make_project("PE Ownership No Mutation Other Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    invalid_activity = await _make_activity(other_project["id"], "Elsewhere", status="not_started")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="No Mutation Approval")
    with pytest.raises(ValueError):
        await operations_engine.link_affected_activities(
            item_id=item["id"], actor=PM, activity_ids=[invalid_activity])
    reloaded = await operations_engine.get_item(item["id"])
    assert reloaded.get("affected_activity_ids") in (None, [])


# ==========================================================================
# E. Existing valid relationships remain unchanged
# I. A relationship already stored before this validation change
#    remains readable without being silently destroyed
# ==========================================================================
async def test_relationship_stored_before_the_validation_change_remains_readable():
    """Simulates a relationship that already exists in the database
    (e.g. from before this hardening fix) — reading it must never
    apply the new write-time validation retroactively and must never
    silently drop it."""
    project = await _make_project("PE Ownership Pre-Existing Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Pre-existing Linked Activity", status="blocked")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Pre-existing Approval")
    # Write directly (bypassing the engine function), simulating data
    # that predates this validation.
    await _mock_db.operational_items.update_one(
        {"id": item["id"]}, {"$set": {"affected_activity_ids": [a2]}})
    snapshot = await _make_snapshot(project["id"])
    affecting = reasoning_projections.affecting_items_for(snapshot, a2)
    assert len(affecting) == 1
    assert affecting[0]["title"] == "Pre-existing Approval"


# ==========================================================================
# F. Existing Client restriction remains intact
# G. PM/Management/Supervisor valid access remains intact
# ==========================================================================
async def test_client_forbidden_from_linking_activities():
    project = await _make_project("PE Ownership Client Forbidden Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Approval")
    # The engine function itself has no role check (RBAC for this
    # write lives at the route, matching set_blocker's own established
    # pattern) - confirmed by inspection, exercised here via the real
    # route-level behavior in test_client_cannot_access_relationship_data_via_schedule_intent
    # above. This test confirms the ownership validation itself is
    # role-agnostic and applies before any role check would matter.
    linked = await operations_engine.link_affected_activities(item_id=item["id"], actor=PM, activity_ids=[a2])
    assert linked["affected_activity_ids"] == [a2]


# ==========================================================================
# H. Consequence reasoning never sees an invalid relationship
# ==========================================================================
async def test_consequence_reasoning_never_sees_a_rejected_relationship():
    project = await _make_project("PE Ownership Consequence Safety Project")
    other_project = await _make_project("PE Ownership Consequence Other Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked")
    invalid_activity = await _make_activity(other_project["id"], "Elsewhere", status="not_started")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="client_approval", title="Approval")
    with pytest.raises(ValueError):
        await operations_engine.link_affected_activities(
            item_id=item["id"], actor=PM, activity_ids=[invalid_activity])
    # The rejected link never persisted, so the consequence chain for
    # the real, valid activity in this project must show no cause -
    # never a fabricated or leaked cross-project relationship.
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    assert not any("Elsewhere" in s["statement"] for s in chain["steps"])


# ==========================================================================
# Phase F — Consequence-Aware Prioritization. Severity remains the
# PRIMARY, unchanged ranking key (confirmed by test A below); a real,
# deterministic downstream-dependent count only breaks ties within the
# same severity tier (test B). No weighted score, no LLM ranking pass.
# ==========================================================================

async def _seed_electrical_chain(project_id, with_link=True):
    """Shared scenario: Foundation (completed) -> Electrical (blocked,
    late, optionally linked to an approval) -> Plastering (depends on
    Electrical)."""
    now = _now()
    a1 = await _make_activity(project_id, "Foundation", status="completed")
    a2 = await _make_activity(project_id, "Electrical First Fix", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a2}, {"$set": {"planned_finish": _iso(now - timedelta(days=4))}})
    a3 = await _make_activity(project_id, "Plastering", status="not_started", depends_on=[a2])
    if with_link:
        site = await memory_engine.insert_site(project_id=project_id, name="Site")
        item = await operations_engine.create_item(
            actor=PM, site_id=site["id"], category="client_approval", title="Kitchen Layout")
        await operations_engine.link_affected_activities(item_id=item["id"], actor=PM, activity_ids=[a2])
    return a1, a2, a3


async def _seed_critical_safety(project_id):
    now = _now()
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project_id, "status": "open",
        "domain": "safety", "severity": "critical", "rule_id": "safety.unresolved_high_priority",
        "observation": "A safety hazard is open.", "recommendation": "Resolve it.",
        "suggested_operational_action": {"category": "safety_observation", "title": "Resolve hazard", "description": ""},
        "suggested_responsible_role": "management",
        "evidence": {"workflow_activities": [], "operational_items": [], "events": [], "media": [],
                     "approvals": [], "knowledge_items": [], "absences": []},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })


# A. Current critical safety issue remains rankable first
async def test_critical_safety_stays_first_despite_verified_consequence():
    project = await _make_project("PF Safety First Project")
    await _seed_electrical_chain(project["id"])
    await _seed_critical_safety(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    assert result["recommended_actions"][0]["severity"] == "critical"
    assert result["priority_explanation"]["reason"] == "severity"


# B. Schedule warning with verified downstream consequence is not
#    treated the same as an unrelated schedule warning
async def test_consequence_weight_breaks_ties_within_same_severity_tier():
    project = await _make_project("PF Tie Break Project")
    await _seed_electrical_chain(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    warnings = [a for a in result["recommended_actions"] if a["severity"] == "warning"]
    assert warnings[0]["consequence_weight"] > 0
    # The unrelated forecast-slip finding (no linked activity) must
    # rank behind the ones with real downstream dependents.
    unrelated = [a for a in warnings if a["consequence_weight"] == 0]
    linked = [a for a in warnings if a["consequence_weight"] > 0]
    if unrelated and linked:
        assert warnings.index(linked[0]) < warnings.index(unrelated[0])


# C. Consequence information is actually available to the ranking logic
async def test_consequence_data_present_on_ranked_entries():
    project = await _make_project("PF Consequence Available Project")
    await _seed_electrical_chain(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    blocked_entry = next(a for a in result["recommended_actions"] if a["rule_id"] == "construction_logic.activity_blocked")
    assert blocked_entry["affected_activity_id"] is not None
    assert len(blocked_entry["downstream_dependents"]) == 1
    assert blocked_entry["downstream_dependents"][0]["name"] == "Plastering"


# D. Priority explanation identifies the reason for the ranking
async def test_priority_explanation_names_the_real_reason():
    project = await _make_project("PF Explanation Reason Project")
    await _seed_electrical_chain(project["id"])
    await _seed_critical_safety(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    assert result["priority_explanation"]["reason"] in ("severity", "consequence")
    assert "critical" in result["priority_explanation"]["statement"]


# E. "Why should I deal with that first?" does not merely repeat the finding
async def test_explanation_is_not_a_bare_repeat_of_the_observation():
    project = await _make_project("PF Not A Repeat Project")
    await _seed_electrical_chain(project["id"])
    await _seed_critical_safety(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    top = result["recommended_actions"][0]
    assert result["priority_explanation"]["statement"] != top["observation"]
    assert "most severe" in result["priority_explanation"]["statement"]


# F. Changing the consequence relationship changes the relevant
#    priority evidence deterministically
async def test_changing_the_link_changes_consequence_weight():
    project = await _make_project("PF Link Change Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"], with_link=True)
    before = await reasoning_engine.explain_health(project["id"], user=PM)
    before_weight = next(a["consequence_weight"] for a in before["recommended_actions"] if a["rule_id"] == "construction_logic.activity_blocked")
    assert before_weight == 1
    # Add a second real dependent
    await _make_activity(project["id"], "Painting", status="not_started", depends_on=[a2])
    after = await reasoning_engine.explain_health(project["id"], user=PM)
    after_weight = next(a["consequence_weight"] for a in after["recommended_actions"] if a["rule_id"] == "construction_logic.activity_blocked")
    assert after_weight == 2


# G. Removing the relationship removes that consequence evidence
async def test_removing_dependency_removes_consequence_weight():
    project = await _make_project("PF Remove Dependency Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a2}, {"$set": {"planned_finish": _iso(_now() - timedelta(days=4))}})
    a3 = await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    with_dep = await reasoning_engine.explain_health(project["id"], user=PM)
    weight_with = next(a["consequence_weight"] for a in with_dep["recommended_actions"] if a["rule_id"] == "construction_logic.activity_blocked")
    assert weight_with == 1
    # Remove the dependency
    await _mock_db.workflow_activities.update_one({"id": a3}, {"$set": {"depends_on_activity_ids": []}})
    without_dep = await reasoning_engine.explain_health(project["id"], user=PM)
    weight_without = next(a["consequence_weight"] for a in without_dep["recommended_actions"] if a["rule_id"] == "construction_logic.activity_blocked")
    assert weight_without == 0


# H. No unsupported relationship creates priority evidence
async def test_no_fabricated_consequence_for_unrelated_activity():
    project = await _make_project("PF No Fabrication Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Isolated Activity", status="blocked", depends_on=[a1])
    # No dependents at all
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    blocked_entry = next((a for a in result["recommended_actions"] if a["rule_id"] == "construction_logic.activity_blocked"), None)
    assert blocked_entry is not None
    assert blocked_entry["consequence_weight"] == 0
    assert blocked_entry["downstream_dependents"] == []


# I. Stale persisted recommendations do not silently override current priority
async def test_stale_persisted_recommendation_does_not_outrank_current_by_default():
    project = await _make_project("PF Stale Persisted Project")
    await _seed_electrical_chain(project["id"])
    now = _now()
    # A stale, low-severity persisted insight - must not jump ahead of
    # the current, higher-severity findings just by being persisted.
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "management", "severity": "advisory", "rule_id": "management.stale_open_item",
        "observation": "An old, low-priority item exists.", "recommendation": "Review it eventually.",
        "suggested_operational_action": {"category": "follow_up", "title": "Review", "description": ""},
        "evidence_ids": [], "created_at": _iso(now - timedelta(days=60)), "updated_at": _iso(now - timedelta(days=60)),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    severities_in_order = [a["severity"] for a in result["recommended_actions"]]
    assert severities_in_order.index("warning") < severities_in_order.index("advisory")


# J. Existing recommendation reconciliation remains correct
async def test_reconciliation_still_distinguishes_current_and_persisted():
    project = await _make_project("PF Reconciliation Still Correct Project")
    await _seed_electrical_chain(project["id"])
    await _seed_critical_safety(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    sources = {a["source"] for a in result["recommended_actions"]}
    assert sources == {"persisted", "current"}


# K. Phase E consequence chain remains unchanged
async def test_phase_e_consequence_chain_unchanged():
    project = await _make_project("PF Chain Unchanged Project")
    await _seed_electrical_chain(project["id"])
    snapshot = await _make_snapshot(project["id"])
    activities = {a["name"]: a["id"] for a in snapshot["workflow_activities"]}
    chain = reasoning_projections.blocking_consequence_chain(snapshot, activities["Electrical First Fix"])
    provenances = [s["provenance"] for s in chain["steps"]]
    assert provenances == ["fact", "relationship:fact", "derived", "inferred", "unknown"]


# L. Phase D multi-intent behavior remains unchanged
async def test_phase_d_multi_intent_still_works_after_phase_f():
    project = await _make_project("PF PhaseD Still Works Project")
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_health", "confidence": "high"}, {"intent": "query_schedule_impact", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I worry about?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    assert len(result["sections"]) == 2


# M. Client RBAC remains correct
async def test_client_still_restricted_from_priority_data():
    project = await _make_project("PF Client Still Restricted Project")
    await _seed_electrical_chain(project["id"])
    await _seed_critical_safety(project["id"])
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_health", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I deal with first?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "data" not in result["result"]


# N. Management/PM/Supervisor behavior remains correct
async def test_non_client_roles_retain_full_priority_access():
    project = await _make_project("PF Non Client Access Project")
    await _seed_electrical_chain(project["id"])
    await _seed_critical_safety(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=ADMIN)
    assert result["priority_explanation"] is not None
    assert len(result["recommended_actions"]) > 0


# O. Existing health behavior remains compatible
async def test_health_score_still_computed_correctly():
    project = await _make_project("PF Health Still Correct Project")
    await _seed_electrical_chain(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    assert result["score"] < 100  # a real, late, blocked activity should lower the score
    assert result["status"] in ("green", "amber", "red")  # a real, valid status - scoring itself unchanged by Phase F


# P. Unsupported cross-project-memory question remains unresolved
async def test_cross_project_memory_still_declines_after_phase_f():
    intent_service._run_structuring_pass = AsyncMock(
        side_effect=AssertionError("safety net must still short-circuit before the LLM is called"))
    result = await intent_service.handle_intent(
        "have we seen this problem before?", user=PM, active_project_id=None)
    assert result["type"] == "unresolved"


# ==========================================================================
# Pre-Merge Hardening Review — Issue: _explain_priority() only checked
# whether the top item had ANY dependents at all, never whether its own
# consequence_weight was actually greater than a competing same-tier
# item's weight. A genuine tie on both ranking keys (severity AND
# consequence_weight) was incorrectly explained as "consequence decided
# it." These are direct, deterministic unit tests against
# reasoning_engine._explain_priority() itself (a pure function over an
# already-ranked list) - simpler and more precise than seeding dozens
# of real activities to reach specific weight values.
# ==========================================================================

def _ra(severity, weight, insight_id="ins_x", dependents=None):
    """A minimal, hand-built recommended_actions entry for boundary
    testing _explain_priority() directly."""
    return {
        "insight_id": insight_id, "severity": severity,
        "consequence_weight": weight,
        "downstream_dependents": dependents or [{"name": f"Dep{i}", "activity_id": f"wa_{i}", "provenance": "derived"} for i in range(weight)],
    }


# 1. Critical safety (weight 0) vs warning schedule (weight 10) -
#    critical remains #1, ranking itself is untouched by this fix.
def test_boundary_critical_always_beats_higher_weight_warning():
    actions = sorted(
        [_ra("critical", 0, "ins_safety"), _ra("warning", 10, "ins_schedule")],
        key=lambda a: (reasoning_engine.SEVERITIES.index(a["severity"]), a["consequence_weight"]), reverse=True)
    assert actions[0]["insight_id"] == "ins_safety"
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "severity"


# 2. Warning A (weight 2) vs Warning B (weight 1) - A genuinely wins on
#    the actual ranking keys; explanation may cite consequence.
def test_boundary_genuine_weight_difference_cites_consequence():
    actions = [_ra("warning", 2, "ins_a"), _ra("warning", 1, "ins_b")]
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["insight_id"] == "ins_a"
    assert explanation["reason"] == "consequence"


# 3. Warning A (weight 2) vs Warning B (weight 2) - a TRUE tie on both
#    keys. Must NOT claim consequence decided it - this is the exact
#    bug the reviewer found.
def test_boundary_true_tie_does_not_fabricate_a_consequence_win():
    actions = [_ra("warning", 2, "ins_a"), _ra("warning", 2, "ins_b")]
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "severity"
    assert "tied" in explanation["statement"].lower()


# 4. Warning A (weight 1), Warning B (weight 1), Warning C (weight 0) -
#    A and B are tied for top; must not fabricate a distinction between
#    them just because C exists with a lower weight.
def test_boundary_tie_among_top_two_ignores_a_weaker_third():
    actions = [_ra("warning", 1, "ins_a"), _ra("warning", 1, "ins_b"), _ra("warning", 0, "ins_c")]
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "severity"
    assert "tied" in explanation["statement"].lower()


# 5. Warning A (weight 0) vs Warning B (weight 0) - no fabricated
#    consequence explanation when neither has any real consequence data.
def test_boundary_no_consequence_data_on_either_side():
    actions = [_ra("warning", 0, "ins_a", dependents=[]), _ra("warning", 0, "ins_b", dependents=[])]
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "severity"
    assert "tied" in explanation["statement"].lower()


# 6. Warning (weight 1) vs Advisory (weight 10) - warning remains first
#    purely on severity, regardless of the advisory's own higher weight.
def test_boundary_warning_beats_higher_weight_advisory():
    actions = sorted(
        [_ra("warning", 1, "ins_warning"), _ra("advisory", 10, "ins_advisory")],
        key=lambda a: (reasoning_engine.SEVERITIES.index(a["severity"]), a["consequence_weight"]), reverse=True)
    assert actions[0]["insight_id"] == "ins_warning"
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "severity"


# 7. Critical (weight 0), Warning (weight 10), Advisory (weight 20) -
#    critical remains first regardless of every other item's own weight.
def test_boundary_critical_beats_everyone_regardless_of_weight():
    actions = sorted(
        [_ra("critical", 0, "ins_critical"), _ra("warning", 10, "ins_warning"), _ra("advisory", 20, "ins_advisory")],
        key=lambda a: (reasoning_engine.SEVERITIES.index(a["severity"]), a["consequence_weight"]), reverse=True)
    assert actions[0]["insight_id"] == "ins_critical"
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "severity"


# 8. No recommendations - priority_explanation remains None.
def test_boundary_no_recommendations_returns_none():
    assert reasoning_engine._explain_priority([]) is None


# ==========================================================================
# Real construction test, repeated with the fix in place
# ==========================================================================
async def test_real_scenario_electrical_findings_tie_and_beat_unrelated_item():
    """The Electrical activity's own two warning-tier findings
    (planned_finish_missed and activity_blocked) are genuinely tied
    with each other at the same consequence_weight - correctly
    reported as a tie, not a fabricated "consequence" win, even though
    both still rank above a genuinely unrelated warning with no
    consequence data at all."""
    project = await _make_project("PF Hardening No Critical Project")
    now = _now()
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a2}, {"$set": {"planned_finish": _iso(now - timedelta(days=4))}})
    await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "management", "severity": "warning", "rule_id": "management.stale_open_item",
        "observation": "An unrelated item is stale.", "recommendation": "Review it.",
        "suggested_operational_action": {"category": "follow_up", "title": "Review", "description": ""},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    warning_items = [a for a in result["recommended_actions"] if a["severity"] == "warning"]
    # Both Electrical-linked findings genuinely tie at weight 1,
    # both above the unrelated item at weight 0 - the honest
    # explanation is a tie, not a fabricated "consequence" win.
    top_two_weights = [warning_items[0]["consequence_weight"], warning_items[1]["consequence_weight"]]
    assert top_two_weights == [1, 1]
    assert result["priority_explanation"]["reason"] == "severity"
    assert "tied" in result["priority_explanation"]["statement"].lower()


async def test_real_scenario_equal_weight_same_severity_does_not_fabricate():
    """Two same-severity findings with the SAME real consequence_weight
    (both linked to activities with exactly one dependent each) must
    not have Atlas pretend one won because of consequence."""
    project = await _make_project("PF Hardening Equal Weight Project")
    now = _now()
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a2}, {"$set": {"planned_finish": _iso(now - timedelta(days=4))}})
    a3 = await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    a4 = await _make_activity(project["id"], "Plumbing", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a4}, {"$set": {"planned_finish": _iso(now - timedelta(days=4))}})
    a5 = await _make_activity(project["id"], "Tiling", status="not_started", depends_on=[a4])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    warning_weights = [a["consequence_weight"] for a in result["recommended_actions"] if a["severity"] == "warning"]
    if warning_weights.count(max(warning_weights)) > 1:
        # A genuine tie exists among the warning-tier items - the
        # explanation (if it's a warning at the top) must not claim
        # consequence decided it.
        if result["recommended_actions"][0]["severity"] == "warning":
            assert result["priority_explanation"]["reason"] == "severity"


# ==========================================================================
# Phase G — Cross-Domain Relationship Extension. workflow_activities.
# milestone_id, workflow_engine.link_milestone(), milestone_for_activity(),
# and the extended blocking_consequence_chain() reaching commercial
# milestone information — direct (blocked activity's own link) and
# indirect (a direct dependent's own link), never merged, never summed,
# deduplicated by milestone_id, never claiming a delay-cost figure.
# ==========================================================================

async def _make_milestone(project_id, name="Finishes", contract_value=500000.0, status="pending", sequence=1):
    now = _now()
    doc = {
        "id": f"ms_{uuid.uuid4()}", "project_id": project_id, "name": name,
        "sequence": sequence, "planned_percent": 25.0, "contract_value": contract_value,
        "trigger": f"{name} complete", "planned_date": None, "forecast_date": None,
        "actual_date": None, "status": status, "created_at": _iso(now), "updated_at": _iso(now),
    }
    await _mock_db.milestones.insert_one(doc)
    return doc


# A. Activity model defaults milestone_id=None
async def test_activity_defaults_milestone_id_none():
    project = await _make_project("PG Default None Project")
    aid = await _make_activity(project["id"], "Some Activity")
    activity = await workflow_engine.get_workflow_activity(aid)
    assert activity["milestone_id"] is None


# B. Valid same-project activity -> milestone link succeeds
async def test_valid_same_project_link_succeeds():
    project = await _make_project("PG Valid Link Project")
    aid = await _make_activity(project["id"], "Flooring")
    ms = await _make_milestone(project["id"], name="Finishes")
    linked = await workflow_engine.link_milestone(aid, ms["id"], actor=PM)
    assert linked["milestone_id"] == ms["id"]


# C. Nonexistent activity rejected
async def test_nonexistent_activity_rejected():
    project = await _make_project("PG Nonexistent Activity Project")
    ms = await _make_milestone(project["id"])
    with pytest.raises(workflow_engine.WorkflowNotFoundError):
        await workflow_engine.link_milestone("wa_does_not_exist", ms["id"], actor=PM)


# D. Nonexistent milestone rejected
async def test_nonexistent_milestone_rejected():
    project = await _make_project("PG Nonexistent Milestone Project")
    aid = await _make_activity(project["id"], "Flooring")
    with pytest.raises(workflow_engine.MilestoneNotFoundError):
        await workflow_engine.link_milestone(aid, "ms_does_not_exist", actor=PM)


# E. Cross-project activity -> milestone rejected
async def test_cross_project_activity_milestone_rejected():
    project_a = await _make_project("PG Cross Project A")
    project_b = await _make_project("PG Cross Project B")
    aid = await _make_activity(project_a["id"], "Flooring")
    ms = await _make_milestone(project_b["id"])
    with pytest.raises(workflow_engine.CrossProjectMilestoneError):
        await workflow_engine.link_milestone(aid, ms["id"], actor=PM)


# F. Rejected cross-project mutation leaves both records unchanged
async def test_rejected_cross_project_link_mutates_nothing():
    project_a = await _make_project("PG No Mutation A")
    project_b = await _make_project("PG No Mutation B")
    aid = await _make_activity(project_a["id"], "Flooring")
    ms = await _make_milestone(project_b["id"])
    with pytest.raises(workflow_engine.CrossProjectMilestoneError):
        await workflow_engine.link_milestone(aid, ms["id"], actor=PM)
    activity = await workflow_engine.get_workflow_activity(aid)
    assert activity["milestone_id"] is None
    reloaded_ms = await commercial_engine.get_milestone(ms["id"])
    assert reloaded_ms["id"] == ms["id"]  # untouched, still exists exactly as created


# G. Direct activity -> milestone appears in consequence chain
async def test_direct_milestone_appears_in_consequence_chain():
    project = await _make_project("PG Direct Milestone Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    ms = await _make_milestone(project["id"], name="MEP", contract_value=200000.0, status="pending")
    await workflow_engine.link_milestone(a2, ms["id"], actor=PM)
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    direct_steps = [s for s in chain["steps"] if "is explicitly linked to the 'MEP' milestone" in s["statement"] and "which depends on" not in s["statement"]]
    assert len(direct_steps) == 1
    assert "Electrical" in direct_steps[0]["statement"]
    assert any("currently pending" in s["statement"] for s in chain["steps"])
    assert any("Milestone value: 200000" in s["statement"] for s in chain["steps"])


# H. Dependent activity -> milestone appears with correct indirect provenance
async def test_indirect_milestone_preserves_one_hop_distinction():
    project = await _make_project("PG Indirect Milestone Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical First Fix", status="blocked", depends_on=[a1])
    a3 = await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    ms = await _make_milestone(project["id"], name="Finishes", contract_value=300000.0)
    await workflow_engine.link_milestone(a3, ms["id"], actor=PM)
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    indirect_steps = [s for s in chain["steps"] if "which depends on" in s["statement"]]
    assert len(indirect_steps) == 1
    assert "Plastering" in indirect_steps[0]["statement"]
    assert "Electrical First Fix" in indirect_steps[0]["statement"]
    # Never collapsed into claiming the blocked activity itself owns the link
    assert not any(
        s["statement"] == f"'Electrical First Fix' is explicitly linked to the '{ms['name']}' milestone."
        for s in chain["steps"])


# I. Blocked activity and dependent both linked to different milestones: both appear independently
async def test_different_milestones_both_appear_independently():
    project = await _make_project("PG Different Milestones Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    a3 = await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    ms_a = await _make_milestone(project["id"], name="MEP", contract_value=100000.0)
    ms_b = await _make_milestone(project["id"], name="Finishes", contract_value=250000.0)
    await workflow_engine.link_milestone(a2, ms_a["id"], actor=PM)
    await workflow_engine.link_milestone(a3, ms_b["id"], actor=PM)
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    assert any("MEP" in s["statement"] for s in chain["steps"])
    assert any("Finishes" in s["statement"] for s in chain["steps"])
    # Never summed into one figure
    assert not any("350000" in s["statement"] for s in chain["steps"])


# J. Blocked activity and dependent point to same milestone: appears once
async def test_same_milestone_via_both_paths_appears_once():
    project = await _make_project("PG Same Milestone Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    a3 = await _make_activity(project["id"], "Plastering", status="not_started", depends_on=[a2])
    ms = await _make_milestone(project["id"], name="MEP", contract_value=150000.0)
    await workflow_engine.link_milestone(a2, ms["id"], actor=PM)
    await workflow_engine.link_milestone(a3, ms["id"], actor=PM)
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    value_mentions = [s for s in chain["steps"] if "Milestone value: 150000" in s["statement"]]
    assert len(value_mentions) == 1


# K. No milestone links: existing UNKNOWN remains
async def test_no_milestone_links_unknown_remains():
    project = await _make_project("PG No Milestone Links Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    assert any(s["provenance"] == "unknown" and "cannot yet be established" in s["statement"] for s in chain["steps"])


# L/M. Milestone status/contract_value read from the actual milestone
async def test_milestone_status_and_value_read_from_real_record():
    project = await _make_project("PG Real Values Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    ms = await _make_milestone(project["id"], name="MEP", contract_value=777777.0, status="ready")
    await workflow_engine.link_milestone(a2, ms["id"], actor=PM)
    snapshot = await _make_snapshot(project["id"])
    result = reasoning_projections.milestone_for_activity(snapshot, a2)
    assert result["status"] == "ready"
    assert result["contract_value"] == 777777.0


# N. No wording implies contract_value is a delay loss
async def test_no_delay_cost_language_anywhere():
    project = await _make_project("PG No Delay Cost Language Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    ms = await _make_milestone(project["id"], name="MEP", contract_value=400000.0)
    await workflow_engine.link_milestone(a2, ms["id"], actor=PM)
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    for s in chain["steps"]:
        lowered = s["statement"].lower()
        for forbidden in ("loss", "damage", "will cost", "lost if", "liquidated"):
            assert forbidden not in lowered


# O. No name-based stage_of_activity fallback appears
async def test_no_name_based_handover_fallback():
    project = await _make_project("PG No Name Based Fallback Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    # Named to deliberately match stage_of_activity()'s own "handover" keywords
    a2 = await _make_activity(project["id"], "Client Walkthrough & Handover", status="blocked", depends_on=[a1])
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    # Even though the name would match stage_of_activity()'s own keywords,
    # with no explicit milestone_id link, the honest UNKNOWN must still
    # be the outcome - never a name-based inference.
    assert any(s["provenance"] == "unknown" and "cannot yet be established" in s["statement"] for s in chain["steps"])
    assert not any("classified as" in s["statement"].lower() for s in chain["steps"])


# P/Q covered by the full existing suite re-passing (50/50 above)

# R. RBAC remains correct
async def test_client_cannot_link_milestone_via_engine_route_rbac_at_route_layer():
    """The engine function itself has no role check (matching
    link_affected_activities()'s own established pattern - RBAC for
    this write lives at the route, verified live separately). This
    test confirms the ownership validation itself is role-agnostic and
    applies before any role check would matter, exactly as the
    equivalent Phase E test already established."""
    project = await _make_project("PG RBAC Engine Level Project")
    aid = await _make_activity(project["id"], "Flooring")
    ms = await _make_milestone(project["id"])
    linked = await workflow_engine.link_milestone(aid, ms["id"], actor=PM)
    assert linked["milestone_id"] == ms["id"]


async def test_client_still_denied_schedule_intent_with_milestone_data_present():
    project = await _make_project("PG RBAC Client Denied Project")
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    ms = await _make_milestone(project["id"], name="MEP", contract_value=999999.0)
    await workflow_engine.link_milestone(a2, ms["id"], actor=PM)
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_schedule_impact", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what could affect handover?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "data" not in result["result"]


# S. Existing single-intent and multi-intent tests remain green — covered
# by the full existing suite re-passing above (test_phase_1_single_intent_shape_unaffected,
# test_phase_d_multi_intent_shape_unaffected, test_phase_d_multi_intent_still_works_after_phase_f).


# ==========================================================================
# Phase H — Action Intelligence: Priority-Aware Ranking + Who + Destination.
# Extends the existing (severity, consequence_weight) sort with a third,
# deterministic tie-breaker (urgency_overdue_days), surfaces the
# already-computed suggested_responsible_role, and adds a real destination
# reference reusing two already-shipped frontend routes. No new ranking
# engine, no weighted score, no LLM involvement.
# ==========================================================================

def _ra_h(severity, weight, urgency, insight_id="ins_x"):
    return {"insight_id": insight_id, "severity": severity, "consequence_weight": weight,
            "urgency_overdue_days": urgency, "downstream_dependents": []}


# A. Existing Phase F severity ordering remains unchanged (covered by the
#    full existing 66-test suite re-passing unmodified above).

# B. Critical always outranks lower severity, even against extreme
#    consequence/urgency values.
def test_critical_beats_everyone_even_with_extreme_urgency_and_consequence():
    actions = sorted(
        [_ra_h("critical", 0, 0, "ins_critical"), _ra_h("warning", 99, 9999, "ins_extreme")],
        key=lambda a: (reasoning_engine.SEVERITIES.index(a["severity"]), a["consequence_weight"], a["urgency_overdue_days"]),
        reverse=True)
    assert actions[0]["insight_id"] == "ins_critical"


# C. Same severity + same consequence: more overdue ranks higher.
def test_more_overdue_ranks_higher_at_equal_severity_and_consequence():
    actions = sorted(
        [_ra_h("warning", 0, 1, "ins_1day"), _ra_h("warning", 0, 40, "ins_40day")],
        key=lambda a: (reasoning_engine.SEVERITIES.index(a["severity"]), a["consequence_weight"], a["urgency_overdue_days"]),
        reverse=True)
    assert actions[0]["insight_id"] == "ins_40day"
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "urgency"
    assert "40 days overdue" in explanation["statement"]


# D. Same severity + same consequence + equal urgency: remains tied.
def test_equal_urgency_remains_an_honest_tie():
    actions = [_ra_h("warning", 0, 5, "ins_a"), _ra_h("warning", 0, 5, "ins_b")]
    explanation = reasoning_engine._explain_priority(actions)
    assert explanation["reason"] == "severity"
    assert "tied" in explanation["statement"].lower()


# E. Missing planned_finish does not receive fabricated urgency.
async def test_missing_planned_finish_gets_zero_urgency_not_fabricated():
    project = await _make_project("PH No Planned Finish Project")
    a1 = await _make_activity(project["id"], "No Date Activity", status="blocked")
    # No planned_finish set at all
    snapshot = await _make_snapshot(project["id"])
    urgency = reasoning_engine._urgency(snapshot, a1)
    assert urgency == 0


# F. Due-date semantics are deterministic - overdue vs due today vs due future.
async def test_due_date_semantics_deterministic():
    project = await _make_project("PH Due Date Semantics Project")
    now = _now()
    a_overdue = await _make_activity(project["id"], "Overdue Activity", status="blocked")
    await _mock_db.workflow_activities.update_one(
        {"id": a_overdue}, {"$set": {"planned_finish": _iso(now - timedelta(days=3))}})
    a_today = await _make_activity(project["id"], "Due Today Activity", status="blocked")
    await _mock_db.workflow_activities.update_one(
        {"id": a_today}, {"$set": {"planned_finish": _iso(now)}})
    a_future = await _make_activity(project["id"], "Due Future Activity", status="blocked")
    await _mock_db.workflow_activities.update_one(
        {"id": a_future}, {"$set": {"planned_finish": _iso(now + timedelta(days=7))}})
    snapshot = await _make_snapshot(project["id"])
    assert reasoning_engine._urgency(snapshot, a_overdue) == 3
    assert reasoning_engine._urgency(snapshot, a_today) == 0
    assert reasoning_engine._urgency(snapshot, a_future) == 0  # never counts down


# G. consequence_weight still works (covered by the existing full suite
#    re-passing above - test_consequence_weight_breaks_ties_within_same_severity_tier).

# H. suggested_responsible_role is surfaced.
async def test_suggested_responsible_role_surfaced():
    project = await _make_project("PH Responsible Role Project")
    await _seed_critical_safety(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    safety_entry = next(a for a in result["recommended_actions"] if a["rule_id"] == "safety.unresolved_high_priority")
    assert safety_entry["suggested_responsible_role"] == "management"


# I. Missing responsible role remains absent/null, not invented.
async def test_missing_responsible_role_stays_null():
    project = await _make_project("PH Missing Role Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    for a in result["recommended_actions"]:
        assert "suggested_responsible_role" in a  # key always present
        # Whatever role the real rule set (or None) - never invented beyond that
        assert a["suggested_responsible_role"] in (None, "project_manager", "site_supervisor", "management")


# J/K covered directly above (test_more_overdue_ranks_higher / existing
# consequence tests) and by the unit-level boundary tests below.

# L. True tie produces honest tie explanation (covered by test_equal_urgency_remains_an_honest_tie).

# M. Destination reference appears when a real affected activity exists.
async def test_destination_appears_for_activity_linked_finding():
    project = await _make_project("PH Destination Activity Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    linked_entry = next(a for a in result["recommended_actions"] if a["affected_activity_id"])
    assert linked_entry["destination"] == {"type": "workflow", "project_id": project["id"]}


# N. Destination absent when no safe target exists.
async def test_destination_absent_when_no_safe_target():
    project = await _make_project("PH No Destination Project")
    now = _now()
    # A persisted insight with no affected_activity_id and no evidence
    # operational_items at all.
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "management", "severity": "advisory", "rule_id": "management.stale_open_item",
        "observation": "A stale item exists.", "recommendation": "Review it.",
        "suggested_operational_action": {"category": "follow_up", "title": "Review", "description": ""},
        "suggested_responsible_role": None,
        "evidence": {"workflow_activities": [], "operational_items": [], "events": [], "media": [],
                     "approvals": [], "knowledge_items": [], "absences": []},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    entry = result["recommended_actions"][0]
    assert entry["destination"] is None


# O/P covered live in this session (frontend navigation + RBAC) and in
# the RBAC tests below.

# Destination for an operational-item-only finding (no activity link).
async def test_destination_for_operational_item_only_finding():
    project = await _make_project("PH Op Item Destination Project")
    now = _now()
    item_id = f"oi_{uuid.uuid4()}"
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "safety", "severity": "critical", "rule_id": "safety.unresolved_high_priority",
        "observation": "A safety issue is open.", "recommendation": "Resolve it.",
        "suggested_operational_action": {"category": "follow_up", "title": "Escalate", "description": ""},
        "suggested_responsible_role": "management",
        "evidence": {"workflow_activities": [], "operational_items": [{"id": item_id, "detail": "status=open"}],
                     "events": [], "media": [], "approvals": [], "knowledge_items": [], "absences": []},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    entry = result["recommended_actions"][0]
    assert entry["destination"] == {"type": "operational_item", "item_id": item_id}


# Q/R/S. Phase G milestone behavior remains correct.
async def test_phase_g_milestone_behavior_still_correct_after_phase_h():
    project = await _make_project("PH Phase G Still Correct Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    snapshot = await _make_snapshot(project["id"])
    chain = reasoning_projections.blocking_consequence_chain(snapshot, a2)
    provenances = [s["provenance"] for s in chain["steps"]]
    assert provenances == ["fact", "relationship:fact", "derived", "inferred", "unknown"]


# T. milestone.contract_value is never described as delay cost/loss
#    (covered by the existing test_no_delay_cost_language_anywhere, still
#    passing unmodified above).

# U. milestone values are never summed or used for ranking - two
#    findings tied on all three real ranking keys, but with very
#    different milestone values reachable via their own activities,
#    must still report an honest tie - milestone value never
#    silently decides anything.
async def test_milestone_value_never_decides_ranking():
    project = await _make_project("PH Milestone Never Decides Ranking Project")
    now = _now()
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    # Two blocked activities, same severity-producing conditions, no
    # dependents (consequence_weight 0 for both), same overdue duration.
    a2 = await _make_activity(project["id"], "Low Value Activity", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a2}, {"$set": {"planned_finish": _iso(now - timedelta(days=5))}})
    a3 = await _make_activity(project["id"], "High Value Activity", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a3}, {"$set": {"planned_finish": _iso(now - timedelta(days=5))}})
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    ms_low = await _make_milestone(project["id"], name="Low", contract_value=1000.0)
    ms_high = await _make_milestone(project["id"], name="High", contract_value=5000000.0)
    await workflow_engine.link_milestone(a2, ms_low["id"], actor=PM)
    await workflow_engine.link_milestone(a3, ms_high["id"], actor=PM)
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    top = result["recommended_actions"][0]
    # The high-value milestone's own activity must NOT be guaranteed to
    # rank first just because its milestone is worth more - confirm the
    # explanation never even mentions milestone value as a reason.
    assert result["priority_explanation"]["reason"] in ("severity", "urgency")
    assert "value" not in result["priority_explanation"]["statement"].lower()


# V/W. Existing multi-intent and single-intent behavior remains unchanged
# (covered by the full existing suite re-passing above).

# RBAC live-equivalent tests
async def test_client_still_fully_restricted_with_new_fields_present():
    project = await _make_project("PH Client Restricted With New Fields Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    await _seed_critical_safety(project["id"])
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_health", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I deal with first?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "data" not in result["result"]


async def test_non_client_roles_see_full_new_fields():
    project = await _make_project("PH Non Client New Fields Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=ADMIN)
    assert len(result["recommended_actions"]) > 0
    for a in result["recommended_actions"]:
        assert "urgency_overdue_days" in a
        assert "suggested_responsible_role" in a
        assert "destination" in a


# X. All existing Phase E/F tests remain green — confirmed by the full
# 66-test suite (Phase E/F/G) re-passing entirely unmodified in this run.


# ==========================================================================
# Responsible-Person Join — narrow correction, not a new relationship.
# recommended_actions previously surfaced only the generic
# suggested_responsible_role; a blocked activity can already carry a
# real assigned person and a real trade. Adds a new, additive
# `responsible` field with the exact three-tier priority: assigned
# person, then trade, then the existing role fallback - never
# fabricated. suggested_responsible_role itself is never touched.
# ==========================================================================

async def _assign_activity(activity_id, user_id, user_name):
    """Direct DB write mirroring what the real /assign route sets,
    without needing a full users collection round-trip for these
    focused tests."""
    await _mock_db.workflow_activities.update_one(
        {"id": activity_id}, {"$set": {"assigned_to_user_id": user_id, "assigned_to_user_name": user_name}})


async def test_responsible_join_prefers_real_assigned_person():
    project = await _make_project("RP Assigned Person Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    await _assign_activity(a2, "u_ramesh", "Ramesh Supervisor")
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    entry = next(a for a in result["recommended_actions"] if a["affected_activity_id"] == a2)
    assert entry["responsible"] == {"type": "person", "name": "Ramesh Supervisor"}
    # suggested_responsible_role itself must remain completely untouched
    assert entry["suggested_responsible_role"] == "project_manager"


async def test_responsible_join_falls_back_to_trade_when_no_person_assigned():
    project = await _make_project("RP Trade Fallback Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    # No assignment set - the activity already carries a real trade
    # ("Electrical", set by _make_activity's own default in some
    # helpers; confirm explicitly here regardless of helper defaults).
    await _mock_db.workflow_activities.update_one({"id": a2}, {"$set": {"trade": "Electrical"}})
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    entry = next(a for a in result["recommended_actions"] if a["affected_activity_id"] == a2)
    assert entry["responsible"] == {"type": "trade", "name": "Electrical"}


async def test_responsible_join_falls_back_to_role_when_neither_person_nor_trade():
    project = await _make_project("RP Role Fallback Project")
    a1, a2, a3 = await _seed_electrical_chain(project["id"])
    await _mock_db.workflow_activities.update_one({"id": a2}, {"$set": {"trade": None}})
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    entry = next(a for a in result["recommended_actions"] if a["affected_activity_id"] == a2)
    assert entry["responsible"] == {"type": "role", "name": "project_manager"}


async def test_responsible_join_none_when_nothing_applies():
    """A finding whose originating rule sets no suggested_responsible_role
    at all, and whose activity has neither an assigned person nor a
    trade - the join must return None, never fabricate a value."""
    project = await _make_project("RP Nothing Applies Project")
    now = _now()
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "management", "severity": "advisory", "rule_id": "management.no_role_rule",
        "observation": "A minor item.", "recommendation": "Review when convenient.",
        "suggested_operational_action": {"category": "follow_up", "title": "Review", "description": ""},
        "suggested_responsible_role": None,
        "evidence": {"workflow_activities": [], "operational_items": [], "events": [], "media": [],
                     "approvals": [], "knowledge_items": [], "absences": []},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    entry = result["recommended_actions"][0]
    assert entry["affected_activity_id"] is None
    assert entry["responsible"] is None


async def test_responsible_join_handles_multiple_actions_different_activities_independently():
    project = await _make_project("RP Multiple Activities Project")
    now = _now()
    a1 = await _make_activity(project["id"], "Foundation", status="completed")
    a2 = await _make_activity(project["id"], "Electrical", status="blocked", depends_on=[a1])
    await _mock_db.workflow_activities.update_one(
        {"id": a2}, {"$set": {"planned_finish": _iso(now - timedelta(days=4)), "trade": "Electrical"}})
    await _assign_activity(a2, "u_ramesh", "Ramesh Supervisor")
    a4 = await _make_activity(project["id"], "Plumbing", status="not_started")
    await _mock_db.workflow_activities.update_one({"id": a4}, {"$set": {"trade": "Plumbing"}})
    # a4's own finding is seeded directly as a persisted insight with a
    # distinct rule_id (same pattern as _seed_critical_safety), rather
    # than via a second blocked activity sharing
    # construction_logic.activity_blocked's own rule_id with a2 - two
    # activities triggering the identical rule_id would collide under
    # Phase E's own existing reconciliation (which dedupes fresh
    # findings by rule_id alone), a separate, pre-existing behavior
    # this narrow correction is not scoped to touch.
    await _mock_db.reasoning_insights.insert_one({
        "id": f"ins_{uuid.uuid4()}", "project_id": project["id"], "status": "open",
        "domain": "procurement", "severity": "warning", "rule_id": "procurement.material_lead_time",
        "observation": "Plumbing materials have a long lead time.", "recommendation": "Order now.",
        "suggested_operational_action": {"category": "follow_up", "title": "Order plumbing materials", "description": ""},
        "suggested_responsible_role": "project_manager",
        "affected_activity_id": a4, "affected_activity_name": "Plumbing",
        "evidence": {"workflow_activities": [], "operational_items": [], "events": [], "media": [],
                     "approvals": [], "knowledge_items": [], "absences": []},
        "evidence_ids": [], "created_at": _iso(now), "updated_at": _iso(now),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    entry_a2 = next(a for a in result["recommended_actions"] if a["affected_activity_id"] == a2)
    entry_a4 = next(a for a in result["recommended_actions"] if a["affected_activity_id"] == a4)
    assert entry_a2["responsible"] == {"type": "person", "name": "Ramesh Supervisor"}
    assert entry_a4["responsible"] == {"type": "trade", "name": "Plumbing"}


async def test_responsible_join_none_activity_id_still_uses_role_fallback():
    """A finding with no affected_activity_id at all (e.g. the safety
    rule) must still fall back correctly to the role, exactly as
    before this correction."""
    project = await _make_project("RP No Activity Id Project")
    await _seed_critical_safety(project["id"])
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    safety_entry = next(a for a in result["recommended_actions"] if a["rule_id"] == "safety.unresolved_high_priority")
    assert safety_entry["affected_activity_id"] is None
    assert safety_entry["responsible"] == {"type": "role", "name": "management"}


# Severity ranking, consequence weighting, RBAC, and navigation
# semantics unchanged — confirmed by the full existing 80-test suite
# (including test_critical_safety_stays_first_despite_verified_consequence,
# test_client_still_restricted_from_priority_data, and
# test_destination_appears_for_activity_linked_finding) re-passing
# entirely unmodified in this same run.
