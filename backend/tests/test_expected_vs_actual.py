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

from engines import memory_engine, operations_engine, intelligence_engine, commercial_engine  # noqa: E402
from services import intent_service  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine, commercial_engine):
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
# MONEY-MODEL INVESTIGATION — architectural separation from commercial_engine
# ==========================================================================

async def test_payable_captured_examples_A_through_F():
    """The six examples from the money-model investigation, each run
    through the real pipeline, confirming every phrasing is captured as
    a remembered operational fact (never touching commercial_engine)."""
    project = await memory_engine.insert_project(name="EVA money", code="EVAMONEY")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")

    # A. "10 lakh is payable to the contractor."
    a = await _capture(project["id"], site["id"], "10 lakh is payable to the contractor.",
        _blank(commitments=[{"what": "payment to contractor", "owed_to": "contractor", "by_when": None,
                             "amount": 1000000, "attributed_to": None, "confidence": "high"}]))
    assert a[0]["amount"] == 1000000 and a[0]["category"] == "commitment"

    # B. "4 lakh has been paid."
    b = await _capture(project["id"], site["id"], "4 lakh has been paid.",
        _blank(commitments=[{"what": "payment made", "owed_to": None, "by_when": None,
                             "amount": 400000, "attributed_to": None, "confidence": "high"}]))
    assert b[0]["amount"] == 400000 and b[0]["id"] != a[0]["id"]

    # C. "Of the 10 lakh payable, 4 lakh has been paid."
    c = await _capture(project["id"], site["id"], "Of the 10 lakh payable, 4 lakh has been paid.",
        _blank(commitments=[{"what": "payment to contractor", "owed_to": "contractor", "by_when": None,
                             "amount": 1000000, "actual_amount": 400000, "attributed_to": None,
                             "confidence": "high"}]))
    assert operations_engine.compute_metrics(c[0])["amount_remaining"] == 600000

    # D. "Client paid 4 lakh today." - a completed act, same pattern as B.
    d = await _capture(project["id"], site["id"], "Client paid 4 lakh today.",
        _blank(commitments=[{"what": "client payment", "owed_to": None, "by_when": None,
                             "amount": 400000, "attributed_to": "client", "confidence": "high"}]))
    assert d[0]["amount"] == 400000 and d[0].get("attributed_to") == "client"

    # E. "Contractor says 6 lakh is still due." - attributed, relayed claim.
    e = await _capture(project["id"], site["id"], "Contractor says 6 lakh is still due.",
        _blank(commitments=[{"what": "amount still due", "owed_to": None, "by_when": None,
                             "amount": 600000, "attributed_to": "contractor", "confidence": "high"}]))
    assert e[0]["amount"] == 600000 and e[0].get("attributed_to") == "contractor"

    # F. "Invoice for 2.5 lakh received."
    f = await _capture(project["id"], site["id"], "Invoice for 2.5 lakh received.",
        _blank(commitments=[{"what": "invoice received", "owed_to": None, "by_when": None,
                             "amount": 250000, "attributed_to": None, "confidence": "high"}]))
    assert f[0]["amount"] == 250000

    # Every one of the six is its own independent item - confirmed no
    # fabricated link, consistent with the quantity side's own discipline.
    ids = {x[0]["id"] for x in (a, b, c, d, e, f)}
    assert len(ids) == 6


async def test_amount_carry_over_is_generic_not_gated_to_commitment_category():
    """Storage-layer proof for the architecture question itself: the
    amount/actual_amount carry-over in accept_ai_proposal() does not check
    the proposal's own category at all - it is a generic, operational_
    item-level field pair, exactly like quantity/unit/attributed_to
    already are. Proven directly by exercising it through a different
    category (client_approval) via the proposal mechanism itself, not by
    reading the source."""
    project = await memory_engine.insert_project(name="EVA generic", code="EVAGEN")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    ev = await memory_engine.insert_event({
        "id": memory_engine._new_id("evt_"), "site_id": site["id"], "project_id": project["id"],
        "user_id": ACTOR["id"], "user_name": ACTOR["name"], "activity_id": None, "kind": "text",
        "text_input": "Client needs to approve the 5 lakh change order.", "transcript": None,
        "audio_asset_id": None, "photo_asset_ids": [], "gps": None, "client_created_at": None,
        "app_version": None, "requires_client_approval": False, "ai_status": "pending",
        "ai_analysis_id": None, "server_created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Directly insert a client_approval proposal carrying "amount" in its own
    # details, bypassing the prompt schema (which does not currently expose
    # amount on client_approvals) - this isolates the STORAGE layer's own
    # behaviour from the prompt's own routing choice.
    await operations_engine.insert_ai_proposal({
        "id": operations_engine._new_id("prop_"), "event_id": ev["id"], "site_id": site["id"],
        "project_id": project["id"], "category": "client_approval", "title": "Approve 5 lakh change order",
        "description": "", "suggested_priority": "high", "suggested_owner_role": "project_manager",
        "confidence": "high", "source_snippet": "", "details": {"what": "approve change order", "amount": 500000},
    })
    proposal = (await operations_engine.list_ai_proposals(event_id=ev["id"]))[0]
    item = await operations_engine.accept_ai_proposal(proposal_id=proposal["id"], actor=ACTOR)
    assert item["category"] == "client_approval"
    assert item["amount"] == 500000  # carried over despite not being a "commitment"


async def test_no_duplicate_monetary_source_of_truth():
    """The core architectural guarantee: capturing a monetary operational
    fact through the universal pipeline never touches commercial_engine's
    own collections, and vice versa - the two models share no state."""
    project = await memory_engine.insert_project(name="EVA separation", code="EVASEP")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    before_prs = await _mock_db.payment_requests.count_documents({})
    before_pays = await _mock_db.payments.count_documents({})

    await _capture(project["id"], site["id"], "10 lakh is payable to the contractor.",
        _blank(commitments=[{"what": "payment to contractor", "owed_to": "contractor", "by_when": None,
                             "amount": 1000000, "attributed_to": None, "confidence": "high"}]))

    assert await _mock_db.payment_requests.count_documents({}) == before_prs  # untouched
    assert await _mock_db.payments.count_documents({}) == before_pays          # untouched


async def test_existing_commercial_payment_request_behaviour_unchanged():
    """The real, pre-existing commercial_engine workflow (milestone ->
    payment_request -> record_payment -> remaining -> status) still works
    exactly as before this investigation - proves the formal commercial
    model was not touched, only traced."""
    project = await memory_engine.insert_project(name="EVA commercial", code="EVACOMM")
    await commercial_engine.create_contract(
        actor=PM, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=180)
    milestone = await commercial_engine.create_milestone(
        actor=PM, project_id=project["id"], name="M1", sequence=1,
        planned_percent=100, trigger="manual", contract_value=1000000)
    await commercial_engine.transition_milestone_status(milestone["id"], "ready", actor=PM)
    await commercial_engine.transition_milestone_status(milestone["id"], "achieved", actor=PM)
    pr = await commercial_engine.create_payment_request(
        actor=PM, project_id=project["id"], milestone_id=milestone["id"],
        amount=1000000, raised_date="2026-09-01", due_date="2026-09-15")
    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=PM)
    await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=PM)
    await commercial_engine.transition_payment_request_status(pr["id"], "sent", actor=PM)
    await commercial_engine.record_payment(
        actor=PM, payment_request_id=pr["id"], amount=400000, date="2026-09-10", method="bank_transfer")
    payments = await commercial_engine.list_payments_for_request(pr["id"])
    total_received = sum(p["amount"] for p in payments)
    remaining = pr["amount"] - total_received
    updated_pr = await commercial_engine.get_payment_request(pr["id"])
    assert total_received == 400000 and remaining == 600000
    assert updated_pr["status"] == "partially_paid"  # unchanged, pre-existing behaviour


async def test_actor_history_unattributed_payment_fact_does_not_appear():
    """Requirement 7, confirmed precisely: an unattributed completed-
    payment statement ("4 lakh has been paid", no attributed_to) never
    shows up in any specific person's own actor_history - because
    actor_history filters by attributed_to match, and this fact has none.
    Only an explicitly attributed commitment (the original "10 lakh
    payable to the contractor", attributed to the contractor) counts."""
    project = await memory_engine.insert_project(name="EVA attrib", code="EVAATTR")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    payable = await _capture(project["id"], site["id"], "Contractor confirmed 10 lakh payable.",
        _blank(commitments=[{"what": "payment to contractor", "owed_to": None, "by_when": None,
                             "amount": 1000000, "attributed_to": "contractor", "confidence": "high"}]))
    await _capture(project["id"], site["id"], "4 lakh has been paid.",
        _blank(commitments=[{"what": "payment made", "owed_to": None, "by_when": None,
                             "amount": 400000, "attributed_to": None, "confidence": "high"}]))
    history = await operations_engine.actor_history(project["id"], user=PM, attributed_to="contractor")
    assert history["total_commitments"] == 1  # only the attributed one
    assert history["items"][0]["id"] == payable[0]["id"]


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
