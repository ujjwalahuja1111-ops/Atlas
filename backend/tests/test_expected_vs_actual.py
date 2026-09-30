"""Expected vs Actual / Partial Fulfillment investigation - regression tests.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Covers the two changes this investigation made, both traced and justified
before implementation (see the investigation's own final report):

1. work_done data-loss bug fixed: a completed-work fact ("Rahul delivered
   the API portion") previously had no emission branch at all and was
   silently dropped before ever reaching storage. Now routes to the
   existing "general" category (no new category invented).

2. actual_quantity (materials/equipment) and amount/actual_amount
   (commitments): a small, paired extension for EXPLICIT, same-statement
   expected-vs-actual variance ("of the 200 tiles promised, only 180
   arrived"). Deliberately does NOT attempt to link two separate,
   independent captures - that would require guessing which earlier
   promise a bare "180 arrived" refers to, which the investigation found
   no safe way to do deterministically. Two independent captures remain
   two independent, unlinked items, exactly as before this investigation.

Run from backend/: python -m pytest tests/test_expected_vs_actual.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_expected_vs_actual_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_expected_vs_actual_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine  # noqa: E402
from services import intent_service  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


PM = {"id": "u_eva_pm", "name": "EVA PM", "role": "project_manager"}
ACTOR = {"id": "u_eva_actor", "name": "EVA Actor"}


def _blank(**lists):
    base = {"type": "general", "materials": [], "labour": [], "equipment": [], "client_approvals": [],
            "drawing_requests": [], "inspections": [], "safety_observations": [],
            "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [],
            "work_done": [], "urgency": "normal", "language_detected": "en"}
    base.update(lists)
    return base


async def _pipeline(text, structured, name="eva", when=None):
    when = when or datetime.now(timezone.utc)
    project = await memory_engine.insert_project(name=f"EVA {name}", code=name.upper()[:8])
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    return project, site, await _capture(project["id"], site["id"], text, structured, when)


async def _capture(project_id, site_id, text, structured, when=None):
    """Reuses an existing project/site - needed whenever a test wants two
    captures genuinely landing in the SAME project (e.g. for actor_history
    aggregation), rather than _pipeline()'s own fresh-project-per-call
    convenience."""
    when = when or datetime.now(timezone.utc)
    ev = await memory_engine.insert_event({
        "id": memory_engine._new_id("evt_"), "site_id": site_id, "project_id": project_id,
        "user_id": ACTOR["id"], "user_name": ACTOR["name"], "activity_id": None, "kind": "text",
        "text_input": text, "transcript": None, "audio_asset_id": None, "photo_asset_ids": [],
        "gps": None, "client_created_at": None, "app_version": None,
        "requires_client_approval": False, "ai_status": "pending", "ai_analysis_id": None,
        "server_created_at": when.isoformat(),
    })
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    return [await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=ACTOR)
            for p in await operations_engine.list_ai_proposals(event_id=ev["id"])]


# ==========================================================================
# A. WORK DONE - the data-loss bug
# ==========================================================================

async def test_work_done_fact_persists():
    project, site, items = await _pipeline(
        "Rahul delivered the API portion.",
        _blank(work_done=["Rahul delivered the API portion"]), "worka")
    assert len(items) == 1
    assert items[0]["category"] == "general"
    assert "API portion" in items[0]["title"]


async def test_work_done_never_fabricates_when_empty():
    project, site, items = await _pipeline("Nothing happened today.", _blank(), "workempty")
    assert items == []


# ==========================================================================
# B. PARTIAL WORK - both facts persist, earlier commitment untouched
# ==========================================================================

async def test_partial_work_both_facts_persist_and_commitment_not_closed():
    project, site, commit_items = await _pipeline(
        "Rahul committed to deliver the backend module Monday.",
        _blank(commitments=[{"what": "deliver the backend module", "owed_to": None, "by_when": "Monday",
                             "attributed_to": "Rahul", "confidence": "high"}]), "workb")
    original = commit_items[0]

    later_items = await _capture(commit_items[0]["project_id"], commit_items[0]["site_id"],
        "Rahul delivered only the API portion Monday; authentication is still pending.",
        _blank(work_done=["Rahul delivered the API portion"],
              follow_ups=[{"what": "authentication portion still pending", "when": None, "confidence": "high"}]))

    refetched = await operations_engine.get_item(original["id"])
    assert refetched["status"] == "open"  # never silently closed
    categories = {i["category"] for i in later_items}
    assert categories == {"general", "follow_up"}
    assert len(later_items) == 2  # both facts, not merged, not dropped


# ==========================================================================
# C/D. Quantity: independent promise and actual, no fabricated link
# ==========================================================================

async def test_quantity_promise_then_separate_actual_stay_independent():
    project, site, promised = await _pipeline(
        "Supplier confirmed 200 tiles for Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]), "cd")
    arrived = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    assert promised[0]["id"] != arrived[0]["id"]
    assert promised[0].get("actual_quantity") is None  # never fabricated onto the promise
    assert arrived[0].get("actual_quantity") is None   # never fabricated onto the arrival either
    assert promised[0]["quantity"] == 200 and arrived[0]["quantity"] == 180


# ==========================================================================
# E. Explicit, same-statement quantity variance
# ==========================================================================

async def test_explicit_quantity_variance_computes_remaining():
    project, site, items = await _pipeline(
        "Of the 200 tiles promised, only 180 arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "actual_quantity": 180, "unit": "pieces",
                           "required_date": None, "attributed_to": "supplier", "confidence": "high"}]), "e")
    item = items[0]
    assert item["quantity"] == 200 and item["actual_quantity"] == 180
    metrics = operations_engine.compute_metrics(item)
    assert metrics["quantity_remaining"] == 20


async def test_actual_quantity_never_carried_over_without_quantity():
    """Safety discipline: a bare actual_quantity with no expected quantity
    on the SAME entry must never be stored - it would be meaningless
    without something to compare against."""
    project, site, items = await _pipeline(
        "180 tiles arrived, not sure how many were promised.",
        _blank(materials=[{"name": "tiles", "quantity": None, "actual_quantity": 180, "unit": "pieces",
                           "required_date": None, "attributed_to": None, "confidence": "high"}]), "eguard")
    assert items[0].get("quantity") is None
    assert items[0].get("actual_quantity") is None  # not carried over - no paired expected value


async def test_quantity_remaining_never_fabricated_with_only_one_number():
    project, site, items = await _pipeline(
        "Supplier confirmed 200 tiles for Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]), "eguard2")
    metrics = operations_engine.compute_metrics(items[0])
    assert metrics["quantity_remaining"] is None


# ==========================================================================
# F/G. Payment: independent payable and paid facts
# ==========================================================================

async def test_payment_promise_then_separate_payment_stay_independent():
    project, site, payable = await _pipeline(
        "10 lakh is payable to the contractor.",
        _blank(commitments=[{"what": "payment to contractor", "owed_to": "contractor", "by_when": None,
                             "amount": 1000000, "attributed_to": None, "confidence": "high"}]), "fg")
    paid = await _capture(project["id"], site["id"], "4 lakh has been paid.",
        _blank(commitments=[{"what": "payment made", "owed_to": None, "by_when": None,
                             "amount": 400000, "attributed_to": None, "confidence": "high"}]))
    assert payable[0]["id"] != paid[0]["id"]
    assert payable[0].get("actual_amount") is None
    assert payable[0]["amount"] == 1000000 and paid[0]["amount"] == 400000


# ==========================================================================
# H. Explicit, same-statement payment variance
# ==========================================================================

async def test_explicit_payment_variance_computes_remaining():
    project, site, items = await _pipeline(
        "Of the 10 lakh payable, 4 lakh has been paid.",
        _blank(commitments=[{"what": "payment to contractor", "owed_to": "contractor", "by_when": None,
                             "amount": 1000000, "actual_amount": 400000, "attributed_to": None,
                             "confidence": "high"}]), "h")
    item = items[0]
    assert item["amount"] == 1000000 and item["actual_amount"] == 400000
    metrics = operations_engine.compute_metrics(item)
    assert metrics["amount_remaining"] == 600000


async def test_actual_amount_never_carried_over_without_amount():
    project, site, items = await _pipeline(
        "4 lakh has been paid, the original amount wasn't mentioned.",
        _blank(commitments=[{"what": "payment made", "owed_to": None, "by_when": None,
                             "amount": None, "actual_amount": 400000, "attributed_to": None,
                             "confidence": "high"}]), "hguard")
    assert items[0].get("amount") is None
    assert items[0].get("actual_amount") is None


# ==========================================================================
# I. No fabrication - multiple similar commitments, no auto-pick
# ==========================================================================

async def test_multiple_similar_commitments_never_auto_linked():
    project, site, a1 = await _pipeline(
        "Supplier confirmed 200 tiles for Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]), "i")
    a2 = await _capture(project["id"], site["id"], "Supplier confirmed another 150 tiles for Friday.",
        _blank(materials=[{"name": "tiles", "quantity": 150, "unit": "pieces", "required_date": "Friday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    arrived = await _capture(project["id"], site["id"], "180 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    ids = {a1[0]["id"], a2[0]["id"], arrived[0]["id"]}
    assert len(ids) == 3  # three genuinely independent items
    for item in (a1[0], a2[0], arrived[0]):
        assert item.get("actual_quantity") is None  # none of the three was silently picked as a match


# ==========================================================================
# J. History - both fields remain visible
# ==========================================================================

async def test_history_shows_both_expected_and_actual_fields():
    project, site, items = await _pipeline(
        "Of the 10 lakh payable, 4 lakh has been paid.",
        _blank(commitments=[{"what": "payment to contractor", "owed_to": "contractor", "by_when": None,
                             "amount": 1000000, "actual_amount": 400000, "attributed_to": None,
                             "confidence": "high"}]), "j")
    item = items[0]
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_change_history", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None, "entity_reference": item["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {item['title']}?", user=PM, active_project_id=project["id"])
    assert result["result"]["ok"] is True
    fields = result["result"]["data"]["events"][0]["fields"]
    assert fields.get("amount") == 1000000
    assert fields.get("actual_amount") == 400000


# ==========================================================================
# K. actor_history - no double-counting
# ==========================================================================

async def test_actor_history_counts_each_capture_once_never_doubled():
    project, site, promised = await _pipeline(
        "Supplier confirmed 200 tiles for Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]), "k")
    arrived = await _capture(project["id"], site["id"], "180 tiles arrived from the supplier.",
        _blank(materials=[{"name": "tiles", "quantity": 180, "unit": "pieces", "required_date": None,
                           "attributed_to": "supplier", "confidence": "high"}]))
    history = await operations_engine.actor_history(project["id"], user=PM, attributed_to="supplier")
    assert history["total_commitments"] == 2  # two real captures, each counted exactly once


async def test_actor_history_items_surface_remaining_when_present():
    project, site, items = await _pipeline(
        "Of the 200 tiles promised, only 180 arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "actual_quantity": 180, "unit": "pieces",
                           "required_date": None, "attributed_to": "supplier", "confidence": "high"}]), "kremain")
    history = await operations_engine.actor_history(project["id"], user=PM, attributed_to="supplier")
    entry = next(i for i in history["items"] if i["id"] == items[0]["id"])
    assert entry["quantity_remaining"] == 20


# ==========================================================================
# L. Construction regression - reuses the same real CRE rule already
# proven in prior sessions, confirming this investigation's changes did
# not alter the fields procurement.material_lead_time depends on.
# ==========================================================================

async def test_construction_cre_rule_unaffected_by_this_investigation():
    from engines import reasoning_engine
    project, site, items = await _pipeline(
        "The supplier said he'll deliver 200 tiles Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "priority": "normal", "attributed_to": "supplier", "confidence": "high"}]), "l")
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    findings = [a for a in result["recommended_actions"] if a["rule_id"] == "procurement.material_lead_time"]
    assert len(findings) == 1
