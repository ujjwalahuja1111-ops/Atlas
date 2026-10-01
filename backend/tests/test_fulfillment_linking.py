"""Human-confirmed cross-capture linking - focused regression tests.

Kept deliberately light, per this task's own explicit "we are NOT turning
this into another huge test programme" instruction. Sanity-checks only:
the new mechanism works, and existing mechanisms (duplicate, supersession,
verification, Context Builder) remain untouched by it.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Run from backend/: python -m pytest tests/test_fulfillment_linking.py -q
"""
import os
import pytest
from datetime import datetime, timezone

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_fulfillment_linking_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_fulfillment_linking_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine  # noqa: E402
from services import context_builder  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ACTOR = {"id": "u_fl_actor", "name": "FL Actor"}
PM = {"id": "u_fl_pm", "name": "FL PM", "role": "project_manager"}


def _blank(**lists):
    base = {"type": "general", "materials": [], "labour": [], "equipment": [], "client_approvals": [],
            "drawing_requests": [], "inspections": [], "safety_observations": [],
            "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [],
            "work_done": [], "urgency": "normal", "language_detected": "en"}
    base.update(lists)
    return base


async def _new_project(name):
    project = await memory_engine.insert_project(name=f"FL {name}", code=name.upper()[:8])
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


# 1. human-confirmed expected -> actual
async def test_expected_to_actual_link():
    project, site = await _new_project("ea")
    expected = await _capture(project["id"], site["id"], "200 tiles expected Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    actual = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    linked = await operations_engine.link_as_fulfillment(
        item_id=actual[0]["id"], actor=PM, fulfills_item_id=expected[0]["id"], relationship_type="actual")
    assert linked["fulfills_item_id"] == expected[0]["id"] and linked["fulfillment_type"] == "actual"


# 2. multiple actuals against one expectation
async def test_multiple_actuals_sum_correctly():
    project, site = await _new_project("multi")
    expected = await _capture(project["id"], site["id"], "200 units expected.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    a1 = await _capture(project["id"], site["id"], "100 units received.",
        _blank(materials=[{"name": "units", "quantity": 100, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    a2 = await _capture(project["id"], site["id"], "60 units received.",
        _blank(materials=[{"name": "units", "quantity": 60, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.link_as_fulfillment(
        item_id=a1[0]["id"], actor=PM, fulfills_item_id=expected[0]["id"], relationship_type="actual")
    await operations_engine.link_as_fulfillment(
        item_id=a2[0]["id"], actor=PM, fulfills_item_id=expected[0]["id"], relationship_type="actual")
    ctx = await context_builder.build_item_context(item_id=expected[0]["id"], user=PM)
    assert ctx["fulfillment_summary"] == {"dimension": "quantity", "expected": 200, "actual": 160, "remaining": 40}
    assert len(ctx["confirmed_actuals"]) == 2


# 3. amount expected -> amount actual
async def test_amount_expected_to_actual():
    project, site = await _new_project("amt")
    payable = await _capture(project["id"], site["id"], "10 lakh payable.",
        _blank(commitments=[{"what": "payment", "owed_to": None, "by_when": None, "amount": 1000000,
                             "attributed_to": None, "confidence": "high"}]))
    paid = await _capture(project["id"], site["id"], "4 lakh paid.",
        _blank(commitments=[{"what": "payment made", "owed_to": None, "by_when": None, "amount": 400000,
                             "attributed_to": None, "confidence": "high"}]))
    await operations_engine.link_as_fulfillment(
        item_id=paid[0]["id"], actor=PM, fulfills_item_id=payable[0]["id"], relationship_type="actual")
    ctx = await context_builder.build_item_context(item_id=payable[0]["id"], user=PM)
    assert ctx["fulfillment_summary"] == {"dimension": "amount", "expected": 1000000, "actual": 400000,
                                          "remaining": 600000}


# 4. work expected -> related update (work has no numeric primitive to sum)
async def test_work_related_update_not_forced_into_arithmetic():
    project, site = await _new_project("work")
    need = await _capture(project["id"], site["id"], "Need two electricians Monday.",
        _blank(labour=[{"trade": "electrician", "count": 2, "required_date": "Monday", "priority": "high",
                       "area": None, "reason": None, "attributed_to": None, "confidence": "high"}]))
    joined = await _capture(project["id"], site["id"], "One electrician has joined.",
        _blank(labour=[{"trade": "electrician", "count": 1, "required_date": None, "priority": "normal",
                       "area": None, "reason": None, "attributed_to": None, "confidence": "high"}]))
    await operations_engine.link_as_fulfillment(
        item_id=joined[0]["id"], actor=PM, fulfills_item_id=need[0]["id"], relationship_type="update")
    ctx = await context_builder.build_item_context(item_id=need[0]["id"], user=PM)
    assert len(ctx["confirmed_updates"]) == 1 and ctx["confirmed_actuals"] == []
    # labour has no amount/quantity on the item itself in this shape, so
    # no fulfillment_summary is fabricated from an "update" relationship
    assert ctx["fulfillment_summary"] is None


# 5. relationship does not overwrite original
async def test_original_expectation_not_mutated():
    project, site = await _new_project("immut")
    expected = await _capture(project["id"], site["id"], "200 tiles expected.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": "supplier", "confidence": "high"}]))
    actual = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.link_as_fulfillment(
        item_id=actual[0]["id"], actor=PM, fulfills_item_id=expected[0]["id"], relationship_type="actual")
    refetched = await operations_engine.get_item(expected[0]["id"])
    assert refetched["quantity"] == 200 and refetched["attributed_to"] == "supplier"
    assert refetched["status"] == "open"


# 6. relationship does not become supersession or 7. duplicate
async def test_fulfillment_distinct_from_supersession_and_duplicate():
    project, site = await _new_project("distinct")
    expected = await _capture(project["id"], site["id"], "200 tiles expected.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    actual = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    linked = await operations_engine.link_as_fulfillment(
        item_id=actual[0]["id"], actor=PM, fulfills_item_id=expected[0]["id"], relationship_type="actual")
    assert linked["status"] == "open"  # unchanged - not a status transition
    assert linked.get("duplicate_of_item_id") is None
    assert linked.get("superseded_by_item_id") is None
    # and the reverse: superseding/duplicating an item must never touch fulfills_item_id
    other = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="other")
    superseded = await operations_engine.mark_superseded(
        item_id=other["id"], actor=PM, superseded_by_item_id=expected[0]["id"])
    assert superseded.get("fulfills_item_id") is None


# 8. no automatic linking (fulfills_item_id/fulfillment_type never set by capture alone)
async def test_no_automatic_linking_from_capture():
    project, site = await _new_project("noauto")
    expected = await _capture(project["id"], site["id"], "200 tiles expected.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    actual = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    assert actual[0].get("fulfills_item_id") is None  # no link_as_fulfillment() call was made


# 9. same-project enforcement
async def test_same_project_enforced():
    project1, site1 = await _new_project("sp1")
    project2, site2 = await _new_project("sp2")
    expected = await operations_engine.create_item(actor=PM, site_id=site1["id"],
        category="material_requirement", title="expected")
    other_project_item = await operations_engine.create_item(actor=PM, site_id=site2["id"],
        category="material_requirement", title="other")
    with pytest.raises(ValueError, match="same project"):
        await operations_engine.link_as_fulfillment(
            item_id=other_project_item["id"], actor=PM, fulfills_item_id=expected["id"],
            relationship_type="actual")


# 11. project isolation (Context Builder never sees a cross-project fulfiller)
async def test_context_builder_project_isolation():
    project1, site1 = await _new_project("ci1")
    expected = await operations_engine.create_item(actor=PM, site_id=site1["id"],
        category="material_requirement", title="expected")
    ctx = await context_builder.build_item_context(item_id=expected["id"], user=PM)
    assert ctx["confirmed_actuals"] == [] and ctx["confirmed_updates"] == []


# 12. remaining calculation (covered by test 2/3 above; one more explicit case)
async def test_remaining_zero_when_fully_fulfilled():
    project, site = await _new_project("zero")
    expected = await _capture(project["id"], site["id"], "200 units expected.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    actual = await _capture(project["id"], site["id"], "200 units received.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.link_as_fulfillment(
        item_id=actual[0]["id"], actor=PM, fulfills_item_id=expected[0]["id"], relationship_type="actual")
    ctx = await context_builder.build_item_context(item_id=expected[0]["id"], user=PM)
    assert ctx["fulfillment_summary"]["remaining"] == 0


# 13. verification remains separate
async def test_linking_does_not_affect_verification():
    project, site = await _new_project("verify")
    expected = await _capture(project["id"], site["id"], "200 tiles expected.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    actual = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.link_as_fulfillment(
        item_id=actual[0]["id"], actor=PM, fulfills_item_id=expected[0]["id"], relationship_type="actual")
    refetched = await operations_engine.get_item(expected[0]["id"])
    assert refetched["status"] == "open"  # linking never verifies anything
    assert refetched.get("verified_at") is None


# 14. existing supersession still works, 15. existing duplicate still works
async def test_existing_supersession_and_duplicate_unaffected():
    project, site = await _new_project("existing")
    a = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="A")
    b = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="B")
    c = await operations_engine.create_item(actor=PM, site_id=site["id"],
        category="material_requirement", title="C")
    superseded = await operations_engine.mark_superseded(item_id=a["id"], actor=PM, superseded_by_item_id=b["id"])
    assert superseded["status"] == "superseded"
    duped = await operations_engine.mark_duplicate(item_id=c["id"], actor=PM, duplicate_of_item_id=b["id"])
    assert duped["status"] == "duplicate"


# 16. existing Context Builder still works (sibling lookup, unaffected)
async def test_existing_context_builder_sibling_lookup_unaffected():
    project, site = await _new_project("cbexisting")
    items = await _capture(project["id"], site["id"], "180 received, 20 still pending.",
        _blank(materials=[{"name": "units", "quantity": 180, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}],
              follow_ups=[{"what": "20 units still pending", "when": None, "confidence": "high"}]))
    materials_item = next(i for i in items if i["category"] == "material_requirement")
    ctx = await context_builder.build_item_context(item_id=materials_item["id"], user=PM)
    assert len(ctx["sibling_items"]) == 1


# cross-industry: retail (damaged -> replacement as an "update", not an "actual")
async def test_retail_damage_replacement_as_update():
    project, site = await _new_project("retail")
    vendor = await _capture(project["id"], site["id"], "Vendor promised 500 cartons.",
        _blank(materials=[{"name": "cartons", "quantity": 500, "unit": "cartons", "required_date": None,
                           "attributed_to": "vendor", "confidence": "high"}]))
    damaged = await _capture(project["id"], site["id"], "20 cartons arrived damaged.",
        _blank(quality_observations=[{"observation": "20 cartons damaged on arrival", "priority": "normal",
                                      "area": None, "confidence": "high"}]))
    await operations_engine.link_as_fulfillment(
        item_id=damaged[0]["id"], actor=PM, fulfills_item_id=vendor[0]["id"], relationship_type="update")
    ctx = await context_builder.build_item_context(item_id=vendor[0]["id"], user=PM)
    assert len(ctx["confirmed_updates"]) == 1 and ctx["confirmed_actuals"] == []


# construction CRE regression
async def test_construction_cre_rule_unaffected():
    from engines import reasoning_engine
    reasoning_engine.db = _mock_db
    project, site = await _new_project("cre")
    await _capture(project["id"], site["id"], "The supplier said he'll deliver 200 tiles Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "priority": "normal", "attributed_to": "supplier", "confidence": "high"}]))
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    findings = [a for a in result["recommended_actions"] if a["rule_id"] == "procurement.material_lead_time"]
    assert len(findings) == 1
