"""Verification State investigation - regression tests.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Covers the two changes this investigation made, both traced and justified
before implementation (see the investigation's own final report):

1. has_evidence (operational_items): whether the capture an item came from
   had a photo attached. Computed once at creation (the source event is
   immutable, so this can never go stale). PRESENCE only - never a claim
   that the evidence proves anything, and never promotes status.

2. transition_status()'s own new guard: the actor who marked an item
   "fulfilled" cannot also be the one who transitions it to "verified".
   "verified" already existed as a status with its own verified_by/
   verified_at fields before this investigation - confirmed live, before
   any change, that self-verification succeeded with no guard at all. The
   fix is the guard, not a new field or a new status.

No new collection, no new ontology, no automatic promotion of status from
text content, no change to Expected -> Actual -> Remaining, no work on
supersession/correction.

Run from backend/: python -m pytest tests/test_verification_state.py -q
"""
import os
import pytest
from datetime import datetime, timezone

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_verification_state_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_verification_state_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine, reasoning_engine  # noqa: E402
from services import intent_service  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine, reasoning_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


FIELD_STAFF = {"id": "u_vs_field", "name": "VS Field Staff", "role": "field_staff"}
PM = {"id": "u_vs_pm", "name": "VS PM", "role": "project_manager"}


def _blank(**lists):
    base = {"type": "general", "materials": [], "labour": [], "equipment": [], "client_approvals": [],
            "drawing_requests": [], "inspections": [], "safety_observations": [],
            "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [],
            "work_done": [], "urgency": "normal", "language_detected": "en"}
    base.update(lists)
    return base


async def _capture(project_id, site_id, text, structured, photo_asset_ids=None, actor=FIELD_STAFF):
    ev = await memory_engine.insert_event({
        "id": memory_engine._new_id("evt_"), "site_id": site_id, "project_id": project_id,
        "user_id": actor["id"], "user_name": actor["name"], "activity_id": None,
        "kind": "photo" if photo_asset_ids else "text",
        "text_input": text, "transcript": None, "audio_asset_id": None,
        "photo_asset_ids": photo_asset_ids or [], "gps": None, "client_created_at": None,
        "app_version": None, "requires_client_approval": False, "ai_status": "pending",
        "ai_analysis_id": None, "server_created_at": datetime.now(timezone.utc).isoformat(),
    })
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    return [await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=actor)
            for p in await operations_engine.list_ai_proposals(event_id=ev["id"])]


async def _new_project(name):
    project = await memory_engine.insert_project(name=f"VS {name}", code=name.upper()[:8])
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    return project, site


# ==========================================================================
# A. Ordinary claimed completion
# ==========================================================================

async def test_A_ordinary_claimed_completion():
    project, site = await _new_project("a")
    items = await _capture(project["id"], site["id"], "200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    item = await operations_engine.transition_status(item_id=items[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    assert item["status"] == "fulfilled"
    assert item["verified_by_user_id"] is None and item["verified_at"] is None
    assert item["has_evidence"] is False


# ==========================================================================
# B. Supplier/third-party attributed completion - attribution is NOT verification
# ==========================================================================

async def test_B_attributed_completion_is_still_only_claimed():
    project, site = await _new_project("b")
    items = await _capture(project["id"], site["id"], "Supplier says 200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": "supplier", "confidence": "high"}]))
    item = await operations_engine.transition_status(item_id=items[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    assert item["attributed_to"] == "supplier"
    assert item["status"] == "fulfilled"  # attribution alone never implies verified
    assert item["verified_by_user_id"] is None


# ==========================================================================
# C. Completion with evidence - presence of evidence does not auto-verify
# ==========================================================================

async def test_C_evidence_present_does_not_auto_verify():
    project, site = await _new_project("c")
    items = await _capture(project["id"], site["id"], "Photo confirms 200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]),
        photo_asset_ids=["asset_1"])
    assert items[0]["has_evidence"] is True
    item = await operations_engine.transition_status(item_id=items[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    assert item["status"] == "fulfilled"  # evidence present, but NOT promoted to verified
    assert item["verified_by_user_id"] is None


async def test_C_no_photo_means_no_evidence():
    project, site = await _new_project("cneg")
    items = await _capture(project["id"], site["id"], "200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    assert items[0]["has_evidence"] is False


# ==========================================================================
# D. Explicit human verification
# ==========================================================================

async def test_D_explicit_verification_by_a_different_person():
    project, site = await _new_project("d")
    items = await _capture(project["id"], site["id"], "200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.transition_status(item_id=items[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    item = await operations_engine.transition_status(item_id=items[0]["id"], to_status="verified", actor=PM)
    assert item["status"] == "verified"
    assert item["verified_by_user_id"] == PM["id"]
    assert item["verified_at"] is not None
    # the original claim is never overwritten - append-only history
    history = await operations_engine.list_events_for_item(items[0]["id"])
    kinds = [e["kind"] for e in history]
    assert "fulfilled" in kinds and "verified" in kinds


# ==========================================================================
# E. "Done but not checked" - stays at the same default as any other claim
# ==========================================================================

async def test_E_done_but_not_checked_stays_unverified_by_default():
    project, site = await _new_project("e")
    items = await _capture(project["id"], site["id"], "200 tiles are done, but I haven't checked yet.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    item = await operations_engine.transition_status(item_id=items[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    # No special handling needed: the default (fulfilled, not verified) IS
    # the correct representation of "done but not checked" - confirming the
    # system never claims more certainty than it has by default.
    assert item["status"] == "fulfilled"
    assert item["verified_by_user_id"] is None


async def test_E_text_claiming_verified_does_not_auto_set_the_real_status():
    """Even '...and verified' in the text itself must not promote status -
    a verbal claim is not independent verification."""
    project, site = await _new_project("e2")
    items = await _capture(project["id"], site["id"], "200 tiles are done and verified.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    assert items[0]["status"] == "open"  # nothing auto-promotes from text content


# ==========================================================================
# F. Attempted invalid verification transition - the new guard itself
# ==========================================================================

async def test_F_self_verification_is_blocked():
    project, site = await _new_project("f")
    items = await _capture(project["id"], site["id"], "200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.transition_status(item_id=items[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    with pytest.raises(ValueError, match="cannot also verify"):
        await operations_engine.transition_status(item_id=items[0]["id"], to_status="verified", actor=FIELD_STAFF)
    # confirm the item was NOT silently moved to verified by the failed attempt
    item = await operations_engine.get_item(items[0]["id"])
    assert item["status"] == "fulfilled"
    assert item["verified_by_user_id"] is None


async def test_F_illegal_status_transition_still_rejected_as_before():
    """Regression guard: the new check must not interfere with the
    existing, unrelated transition-table validation."""
    project, site = await _new_project("f2")
    items = await _capture(project["id"], site["id"], "200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    with pytest.raises(ValueError, match="not allowed"):
        await operations_engine.transition_status(item_id=items[0]["id"], to_status="verified", actor=PM)  # open -> verified: illegal


# ==========================================================================
# G. Expected -> Actual -> Remaining regression
# ==========================================================================

async def test_G_expected_actual_remaining_unaffected_by_verification_fields():
    project, site = await _new_project("g")
    items = await _capture(project["id"], site["id"], "Of the 200 tiles promised, only 180 arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "actual_quantity": 180, "unit": "pieces",
                           "required_date": None, "attributed_to": "supplier", "confidence": "high"}]))
    item = items[0]
    assert item["quantity"] == 200 and item["actual_quantity"] == 180
    assert operations_engine.compute_metrics(item)["quantity_remaining"] == 20
    assert item["has_evidence"] is False  # unrelated field, present and correct
    assert item["verified_by_user_id"] is None


# ==========================================================================
# H. actor_history regression
# ==========================================================================

async def test_H_actor_history_verified_count_and_item_fields():
    project, site = await _new_project("h")
    claimed = await _capture(project["id"], site["id"], "Supplier says 200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": "supplier", "confidence": "high"}]))
    confirmed = await _capture(project["id"], site["id"], "Supplier says 150 more tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 150, "unit": "pieces", "required_date": None,
                           "attributed_to": "supplier", "confidence": "high"}]))
    await operations_engine.transition_status(item_id=claimed[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    await operations_engine.transition_status(item_id=confirmed[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    await operations_engine.transition_status(item_id=confirmed[0]["id"], to_status="verified", actor=PM)

    history = await operations_engine.actor_history(project["id"], user=PM, attributed_to="supplier")
    assert history["fulfilled_count"] == 2       # unchanged meaning: both are fulfilled
    assert history["verified_count"] == 1        # new: only one was independently confirmed
    by_id = {i["id"]: i for i in history["items"]}
    assert by_id[confirmed[0]["id"]]["verified_at"] is not None
    assert by_id[claimed[0]["id"]]["verified_at"] is None


# ==========================================================================
# I. query_change_history regression
# ==========================================================================

async def test_I_query_change_history_surfaces_has_evidence():
    from unittest.mock import AsyncMock
    project, site = await _new_project("i")
    items = await _capture(project["id"], site["id"], "Photo confirms 200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]),
        photo_asset_ids=["asset_1"])
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_change_history", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None, "entity_reference": items[0]["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {items[0]['title']}?", user=PM, active_project_id=project["id"])
    assert result["result"]["ok"] is True
    fields = result["result"]["data"]["events"][0]["fields"]
    assert fields.get("has_evidence") is True


async def test_I_no_evidence_omits_the_field_entirely():
    from unittest.mock import AsyncMock
    project, site = await _new_project("ineg")
    items = await _capture(project["id"], site["id"], "150 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 150, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_change_history", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None, "entity_reference": items[0]["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {items[0]['title']}?", user=PM, active_project_id=project["id"])
    fields = result["result"]["data"]["events"][0]["fields"]
    assert "has_evidence" not in fields


# ==========================================================================
# J. my_day / management attention regression
# ==========================================================================

async def test_J_my_day_distinguishes_awaiting_verification_from_recently_completed():
    project, site = await _new_project("j")
    claimed = await _capture(project["id"], site["id"], "200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    confirmed = await _capture(project["id"], site["id"], "150 more tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 150, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.transition_status(item_id=claimed[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    await operations_engine.transition_status(item_id=confirmed[0]["id"], to_status="fulfilled", actor=FIELD_STAFF)
    await operations_engine.transition_status(item_id=confirmed[0]["id"], to_status="verified", actor=PM)

    summary = await operations_engine.operational_center(site_id=site["id"])
    awaiting_ids = {i["id"] for i in summary["awaiting_verification"]}
    completed_ids = {i["id"] for i in summary["recently_completed"]}
    assert claimed[0]["id"] in awaiting_ids and claimed[0]["id"] not in completed_ids
    assert confirmed[0]["id"] in completed_ids and confirmed[0]["id"] not in awaiting_ids


# ==========================================================================
# K. Construction CRE regression
# ==========================================================================

async def test_K_construction_cre_rule_unaffected():
    project, site = await _new_project("k")
    await _capture(project["id"], site["id"], "The supplier said he'll deliver 200 tiles Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "priority": "normal", "attributed_to": "supplier", "confidence": "high"}]))
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    findings = [a for a in result["recommended_actions"] if a["rule_id"] == "procurement.material_lead_time"]
    assert len(findings) == 1
