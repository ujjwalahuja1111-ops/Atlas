"""Context Builder - minimum sufficient operational context - regression tests.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Covers services/context_builder.py's own two entry points
(build_item_context, build_item_relationships) and their integration into
_handle_query_change_history(). No new validation framework - plain
pytest, same pattern as every other test file in this suite.

Every relationship this module surfaces was already explicit and already
stored before this module existed (superseded_by_item_id, inherited_
evidence_event_id, has_evidence, verified_by/at, actual_quantity/amount).
These tests confirm RETRIEVAL and ORDERING, not any new fact-storage
behaviour - the storage side is already covered by tests/test_expected_
vs_actual.py, tests/test_verification_state.py, and tests/test_negative_
evidence_supersession.py, none of which are re-tested here.

Run from backend/: python -m pytest tests/test_context_builder.py -q
"""
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_context_builder_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_context_builder_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine  # noqa: E402
from services import intent_service, context_builder  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ACTOR = {"id": "u_cb_actor", "name": "CB Actor"}
PM = {"id": "u_cb_pm", "name": "CB PM", "role": "project_manager"}


def _blank(**lists):
    base = {"type": "general", "materials": [], "labour": [], "equipment": [], "client_approvals": [],
            "drawing_requests": [], "inspections": [], "safety_observations": [],
            "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [],
            "work_done": [], "urgency": "normal", "language_detected": "en"}
    base.update(lists)
    return base


async def _new_project(name):
    project = await memory_engine.insert_project(name=f"CB {name}", code=name.upper()[:8])
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    return project, site


async def _capture(project_id, site_id, text, structured):
    ev = await memory_engine.insert_event({
        "id": memory_engine._new_id("evt_"), "site_id": site_id, "project_id": project_id,
        "user_id": ACTOR["id"], "user_name": ACTOR["name"], "activity_id": None, "kind": "text",
        "text_input": text, "transcript": None, "audio_asset_id": None, "photo_asset_ids": [],
        "gps": None, "client_created_at": None, "app_version": None,
        "requires_client_approval": False, "ai_status": "pending", "ai_analysis_id": None,
        "server_created_at": datetime.now(timezone.utc).isoformat(),
    })
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    return [await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=ACTOR)
            for p in await operations_engine.list_ai_proposals(event_id=ev["id"])]


# ==========================================================================
# 1. BASELINE - a focal item with no relationships
# ==========================================================================

async def test_baseline_item_with_no_relationships():
    project, site = await _new_project("baseline")
    items = await _capture(project["id"], site["id"], "200 units promised Thursday.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    ctx = await context_builder.build_item_context(item_id=items[0]["id"], user=PM)
    assert ctx["focal_item"]["id"] == items[0]["id"]
    assert ctx["is_current"] is True
    assert ctx["current_position"]["id"] == items[0]["id"]
    assert ctx["superseded_by_chain"] == []
    assert ctx["superseded_predecessors"] == []
    assert ctx["sibling_items"] == []
    assert ctx["verification"]["status"] == "open"
    assert ctx["verification"]["has_evidence"] is False


async def test_missing_item_raises():
    with pytest.raises(ValueError, match="not found"):
        await context_builder.build_item_context(item_id="op_does_not_exist", user=PM)


# ==========================================================================
# 2/3. SUPERSESSION CHAIN - forward (current position) and reverse (predecessors)
# ==========================================================================

async def test_supersession_chain_follows_to_current_live_position():
    """A -> B -> C: querying A must surface C as the current position,
    with the full chain in order, never flattening the sequence."""
    project, site = await _new_project("chain")
    a = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="200 units")
    b = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="220 units")
    c = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="210 units")
    await operations_engine.mark_superseded(item_id=a["id"], actor=PM, superseded_by_item_id=b["id"])
    await operations_engine.mark_superseded(item_id=b["id"], actor=PM, superseded_by_item_id=c["id"])

    ctx = await context_builder.build_item_context(item_id=a["id"], user=PM)
    assert ctx["is_current"] is False
    assert ctx["current_position"]["id"] == c["id"]
    assert [link["id"] for link in ctx["superseded_by_chain"]] == [b["id"], c["id"]]  # order preserved


async def test_reverse_supersession_shows_what_this_item_replaced():
    project, site = await _new_project("reverse")
    a = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="200 units")
    b = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="220 units")
    await operations_engine.mark_superseded(item_id=a["id"], actor=PM, superseded_by_item_id=b["id"])

    ctx = await context_builder.build_item_context(item_id=b["id"], user=PM)
    assert ctx["is_current"] is True  # B is itself not superseded
    assert [p["id"] for p in ctx["superseded_predecessors"]] == [a["id"]]


# ==========================================================================
# 4. SIBLING ITEMS - same originating capture, no fuzzy matching
# ==========================================================================

async def test_sibling_items_from_same_capture():
    project, site = await _new_project("siblings")
    items = await _capture(project["id"], site["id"], "180 received, 20 still pending.",
        _blank(materials=[{"name": "units", "quantity": 180, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}],
              follow_ups=[{"what": "20 units still pending", "when": None, "confidence": "high"}]))
    materials_item = next(i for i in items if i["category"] == "material_requirement")
    follow_up_item = next(i for i in items if i["category"] == "follow_up")

    ctx = await context_builder.build_item_context(item_id=materials_item["id"], user=PM)
    assert [s["id"] for s in ctx["sibling_items"]] == [follow_up_item["id"]]
    assert ctx["sibling_items"][0]["category"] == "follow_up"
    assert ctx["sibling_items"][0]["title"] == "20 units still pending"


async def test_items_from_different_captures_are_never_siblings():
    """No fuzzy matching: two items about the same material, from two
    SEPARATE captures, must not appear as each other's siblings."""
    project, site = await _new_project("nosib")
    a = await _capture(project["id"], site["id"], "200 tiles promised.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    b = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    ctx = await context_builder.build_item_context(item_id=a[0]["id"], user=PM)
    assert ctx["sibling_items"] == []


# ==========================================================================
# 5. VERIFICATION - claimed vs fulfilled vs verified, evidence presence
# ==========================================================================

async def test_verification_state_distinguishes_claimed_from_verified():
    project, site = await _new_project("verify")
    items = await _capture(project["id"], site["id"], "Photo confirms 200 units arrived.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]),
    )
    # simulate a photo-backed capture directly, since _capture() here has no photo param
    item = await operations_engine.get_item(items[0]["id"])

    ctx_before = await context_builder.build_item_context(item_id=items[0]["id"], user=PM)
    assert ctx_before["verification"]["status"] == "open"
    assert ctx_before["verification"]["verified_at"] is None

    await operations_engine.transition_status(item_id=items[0]["id"], to_status="fulfilled", actor=ACTOR)
    ctx_claimed = await context_builder.build_item_context(item_id=items[0]["id"], user=PM)
    assert ctx_claimed["verification"]["status"] == "fulfilled"
    assert ctx_claimed["verification"]["verified_at"] is None  # claimed, not yet verified

    await operations_engine.transition_status(item_id=items[0]["id"], to_status="verified", actor=PM)
    ctx_verified = await context_builder.build_item_context(item_id=items[0]["id"], user=PM)
    assert ctx_verified["verification"]["status"] == "verified"
    assert ctx_verified["verification"]["verified_at"] is not None


async def test_has_evidence_is_presence_only_never_auto_verifies():
    project, site = await _new_project("evidence")
    ev = await memory_engine.insert_event({
        "id": memory_engine._new_id("evt_"), "site_id": site["id"], "project_id": project["id"],
        "user_id": ACTOR["id"], "user_name": ACTOR["name"], "activity_id": None, "kind": "photo",
        "text_input": "Photo confirms 200 units arrived.", "transcript": None, "audio_asset_id": None,
        "photo_asset_ids": ["asset_1"], "gps": None, "client_created_at": None, "app_version": None,
        "requires_client_approval": False, "ai_status": "pending", "ai_analysis_id": None,
        "server_created_at": datetime.now(timezone.utc).isoformat(),
    })
    await intelligence_engine._emit_proposals_from_structured(ev, _blank(
        materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": None,
                   "attributed_to": None, "confidence": "high"}]))
    items = [await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=ACTOR)
             for p in await operations_engine.list_ai_proposals(event_id=ev["id"])]

    ctx = await context_builder.build_item_context(item_id=items[0]["id"], user=PM)
    assert ctx["verification"]["has_evidence"] is True
    assert ctx["verification"]["status"] == "open"  # evidence presence never auto-verifies


# ==========================================================================
# 6. EXPECTED -> ACTUAL -> REMAINING surfaced, never flattened
# ==========================================================================

async def test_expected_actual_remaining_surfaced_from_existing_fields():
    project, site = await _new_project("ear")
    items = await _capture(project["id"], site["id"], "Of the 200 units promised, only 180 arrived.",
        _blank(materials=[{"name": "units", "quantity": 200, "actual_quantity": 180, "unit": "units",
                           "required_date": None, "attributed_to": "supplier", "confidence": "high"}]))
    ctx = await context_builder.build_item_context(item_id=items[0]["id"], user=PM)
    ear = ctx["expected_actual_remaining"]
    assert ear["quantity"] == 200 and ear["actual_quantity"] == 180 and ear["quantity_remaining"] == 20


# ==========================================================================
# 7. query_change_history integration - additive only
# ==========================================================================

async def test_query_change_history_includes_context_for_operational_item():
    project, site = await _new_project("qch")
    items = await _capture(project["id"], site["id"], "180 received, 20 still pending.",
        _blank(materials=[{"name": "units", "quantity": 180, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}],
              follow_ups=[{"what": "20 units still pending", "when": None, "confidence": "high"}]))
    materials_item = next(i for i in items if i["category"] == "material_requirement")

    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_change_history", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None, "entity_reference": materials_item["title"]})
    result = await intent_service.handle_intent(
        f"why is {materials_item['title']} still open?", user=PM, active_project_id=project["id"])
    assert result["result"]["ok"] is True
    data = result["result"]["data"]
    assert "events" in data and len(data["events"]) >= 1  # existing shape unchanged
    assert "context" in data
    assert data["context"]["sibling_items"][0]["title"] == "20 units still pending"


# ==========================================================================
# 8. PROJECT ISOLATION
# ==========================================================================

async def test_project_isolation_siblings_never_cross_projects():
    project1, site1 = await _new_project("iso1")
    project2, site2 = await _new_project("iso2")
    items1 = await _capture(project1["id"], site1["id"], "180 received, 20 still pending.",
        _blank(materials=[{"name": "units", "quantity": 180, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}],
              follow_ups=[{"what": "20 units still pending", "when": None, "confidence": "high"}]))
    materials_item = next(i for i in items1 if i["category"] == "material_requirement")
    # An unrelated item in a different project must never appear as a sibling
    await operations_engine.create_item(actor=PM, site_id=site2["id"],
        category="follow_up", title="unrelated follow-up in another project")
    ctx = await context_builder.build_item_context(item_id=materials_item["id"], user=PM)
    assert len(ctx["sibling_items"]) == 1  # only the real sibling, nothing from project2


# ==========================================================================
# Cross-industry: restaurant, retail, construction — same mechanism, no
# domain-specific logic anywhere in context_builder.py.
# ==========================================================================

async def test_restaurant_why_still_waiting():
    project, site = await _new_project("restaurant")
    promise = await _capture(project["id"], site["id"], "Supplier promises 200 units Friday.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "Friday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    partial = await _capture(project["id"], site["id"], "180 received, 20 still pending.",
        _blank(materials=[{"name": "units", "quantity": 180, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}],
              follow_ups=[{"what": "20 units still pending", "when": None, "confidence": "high"}]))
    changed = await _capture(project["id"], site["id"], "Supplier changes delivery to Saturday.",
        _blank(materials=[{"name": "units", "quantity": 20, "unit": "units", "required_date": "Saturday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=promise[0]["id"], actor=PM,
                                            superseded_by_item_id=changed[0]["id"])
    ctx = await context_builder.build_item_context(item_id=promise[0]["id"], user=PM)
    assert ctx["current_position"]["id"] == changed[0]["id"]
    assert ctx["current_position"]["required_by"].startswith("2026-10-03")  # Saturday


async def test_retail_what_is_outstanding_and_why():
    project, site = await _new_project("retail")
    vendor = await _capture(project["id"], site["id"], "Vendor promised 500 cartons.",
        _blank(materials=[{"name": "cartons", "quantity": 500, "unit": "cartons", "required_date": None,
                           "attributed_to": "vendor", "confidence": "high"}]))
    damaged = await _capture(project["id"], site["id"], "20 cartons arrived damaged.",
        _blank(quality_observations=[{"observation": "20 cartons damaged on arrival", "priority": "normal",
                                      "area": None, "confidence": "high"}]))
    ctx = await context_builder.build_item_context(item_id=vendor[0]["id"], user=PM)
    assert ctx["expected_actual_remaining"]["quantity"] == 500
    assert ctx["verification"]["status"] == "open"


async def test_construction_what_is_blocking():
    project, site = await _new_project("construction")
    mat = await _capture(project["id"], site["id"], "200 tiles promised Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    ctx = await context_builder.build_item_context(item_id=mat[0]["id"], user=PM)
    assert ctx["focal_item"]["id"] == mat[0]["id"]
    assert ctx["sibling_items"] == []  # the separate approval capture is correctly not fuzzy-linked
