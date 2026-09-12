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
