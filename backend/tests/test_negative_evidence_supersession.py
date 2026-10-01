"""Negative Evidence + Correction/Supersession investigation - regression tests.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

NEGATIVE EVIDENCE: traced to already work correctly once routed to
follow_ups (survives storage, never force-escalated, gets a distinct
"schedule" impact category from issues' own "quality" one downstream).
The one genuine gap was that follow_ups had no definition in the prompt at
all; this adds one. No schema change.

CORRECTION/SUPERSESSION: traced to have NO representation at all before
this investigation - two captures about the same evolving fact become two
permanently independent, unlinked items. The smallest safe fix mirrors
mark_duplicate()'s own exact, already-proven pattern: a new "superseded"
status, a superseded_by_item_id reference field, and a new, explicit,
human-triggered mark_superseded() function. NEVER called by the AI
structuring pipeline and NEVER inferred from text content, even strong
words like "actually" or "correction" - identifying WHICH earlier item a
correction refers to is not something Atlas can safely guess from text
alone (see the investigation's own report). Two separate captures remain
two independent items unless and until a human explicitly links them.

Run from backend/: python -m pytest tests/test_negative_evidence_supersession.py -q
"""
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_neg_ev_supersession_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_neg_ev_supersession_test"]
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


ACTOR = {"id": "u_ns_actor", "name": "NS Actor"}
PM = {"id": "u_ns_pm", "name": "NS PM", "role": "project_manager"}


def _blank(**lists):
    base = {"type": "general", "materials": [], "labour": [], "equipment": [], "client_approvals": [],
            "drawing_requests": [], "inspections": [], "safety_observations": [],
            "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [],
            "work_done": [], "urgency": "normal", "language_detected": "en"}
    base.update(lists)
    return base


async def _new_project(name):
    project = await memory_engine.insert_project(name=f"NS {name}", code=name.upper()[:8])
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
# PART 1 — NEGATIVE EVIDENCE
# ==========================================================================

# 1. negative evidence is preserved
async def test_1_negative_evidence_preserved():
    project, site = await _new_project("neg1")
    items = await _capture(project["id"], site["id"], "Still haven't received the 20 cases.",
        _blank(follow_ups=[{"what": "20 cases still not received", "when": None, "confidence": "high"}]))
    assert len(items) == 1
    assert "not received" in items[0]["title"] or "20 cases" in items[0]["title"]


# 2. negative evidence is not automatically converted into an Issue
async def test_2_negative_evidence_is_not_an_issue():
    project, site = await _new_project("neg2")
    items = await _capture(project["id"], site["id"], "No approval yet.",
        _blank(follow_ups=[{"what": "approval still pending", "when": None, "confidence": "high"}]))
    assert items[0]["category"] == "follow_up"
    assert items[0]["category"] != "site_issue"


async def test_2b_a_genuine_problem_still_becomes_an_issue():
    """Control: the distinction is preserved both ways - negative evidence
    (absence) must not become an issue, and a genuine problem must still
    become one."""
    project, site = await _new_project("neg2b")
    items = await _capture(project["id"], site["id"], "The machine is still down.",
        _blank(issues=["machine still down"]))
    assert items[0]["category"] == "site_issue"


async def test_2c_follow_up_and_issue_get_distinct_impact_categories():
    from services.daily_site_report_service import _CATEGORY_TO_IMPACT
    assert _CATEGORY_TO_IMPACT["follow_up"] == "schedule"
    assert _CATEGORY_TO_IMPACT["site_issue"] == "quality"
    assert _CATEGORY_TO_IMPACT["follow_up"] != _CATEGORY_TO_IMPACT["site_issue"]


# Cross-industry negative evidence
@pytest.mark.parametrize("domain,text", [
    ("restaurant", "20 kg chicken still hasn't arrived."),
    ("mega_store", "Supplier hasn't sent the remaining 50 units."),
    ("construction", "20 tiles are still pending."),
    ("software", "Credentials still haven't arrived."),
])
async def test_cross_industry_negative_evidence(domain, text):
    project, site = await _new_project(f"negx_{domain}")
    items = await _capture(project["id"], site["id"], text,
        _blank(follow_ups=[{"what": text.rstrip("."), "when": None, "confidence": "high"}]))
    assert len(items) == 1
    assert items[0]["category"] == "follow_up"


# ==========================================================================
# PART 2 — CORRECTION / SUPERSESSION (mark_superseded mechanism)
# ==========================================================================

# 3. explicit correction preserves original claim
async def test_3_correction_preserves_original_claim():
    project, site = await _new_project("corr3")
    old = await _capture(project["id"], site["id"], "Supplier will deliver 200 units Thursday.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Actually make that 220.",
        _blank(materials=[{"name": "units", "quantity": 220, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"], note="corrected to 220")
    refetched_old = await operations_engine.get_item(old[0]["id"])
    assert refetched_old["quantity"] == 200  # original claim never altered
    assert refetched_old["status"] == "superseded"
    assert refetched_old["superseded_by_item_id"] == new[0]["id"]


# 4. explicit date correction preserves old and current dates
async def test_4_date_correction_preserves_both_dates():
    project, site = await _new_project("corr4")
    old = await _capture(project["id"], site["id"], "Delivery Thursday.",
        _blank(materials=[{"name": "goods", "quantity": None, "unit": None, "required_date": "Thursday",
                           "attributed_to": None, "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Correction — Friday.",
        _blank(materials=[{"name": "goods", "quantity": None, "unit": None, "required_date": "Friday",
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    old_item = await operations_engine.get_item(old[0]["id"])
    new_item = await operations_engine.get_item(new[0]["id"])
    assert old_item["required_by"].startswith("2026-10-01")   # Thursday, unchanged
    assert new_item["required_by"].startswith("2026-10-02")   # Friday
    assert old_item["status"] == "superseded"


# 5. explicit quantity correction preserves old and current quantity
async def test_5_quantity_correction_preserves_both_quantities():
    project, site = await _new_project("corr5")
    old = await _capture(project["id"], site["id"], "We received 200.",
        _blank(materials=[{"name": "goods", "quantity": 200, "unit": None, "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Correction, only 180 arrived.",
        _blank(materials=[{"name": "goods", "quantity": 180, "unit": None, "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    assert old[0]["quantity"] == 200 and new[0]["quantity"] == 180
    old_item = await operations_engine.get_item(old[0]["id"])
    assert old_item["quantity"] == 200  # history preserved, not overwritten to 180


# 6. explicit actor correction preserves old and current actor
async def test_6_actor_correction_preserves_both_actors():
    project, site = await _new_project("corr6")
    old = await _capture(project["id"], site["id"], "Rahul will finish it Monday.",
        _blank(commitments=[{"what": "finish it", "owed_to": None, "by_when": "Monday",
                             "attributed_to": "Rahul", "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Actually Priya is doing it Wednesday.",
        _blank(commitments=[{"what": "finish it", "owed_to": None, "by_when": "Wednesday",
                             "attributed_to": "Priya", "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    old_item = await operations_engine.get_item(old[0]["id"])
    assert old_item["attributed_to"] == "Rahul"   # never overwritten to Priya
    assert new[0]["attributed_to"] == "Priya"


# 7. explicit supersession is distinguishable from contradiction
async def test_7_supersession_distinguishable_from_contradiction():
    """Supersession: explicitly marked via mark_superseded, status changes.
    Contradiction (test 8): no explicit correction call - both items stay
    'open', neither is marked superseded. The presence/absence of a
    superseded_by_item_id IS the distinguishing signal."""
    project, site = await _new_project("corr7")
    old = await _capture(project["id"], site["id"], "Delivery Thursday.",
        _blank(materials=[{"name": "goods", "quantity": None, "unit": None, "required_date": "Thursday",
                           "attributed_to": None, "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Correction — Friday.",
        _blank(materials=[{"name": "goods", "quantity": None, "unit": None, "required_date": "Friday",
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    old_item = await operations_engine.get_item(old[0]["id"])
    assert old_item["status"] == "superseded" and old_item["superseded_by_item_id"] is not None


# 8. contradiction remains unresolved when there is no explicit correction
async def test_8_contradiction_remains_unresolved_without_explicit_correction():
    project, site = await _new_project("corr8")
    claim_a = await _capture(project["id"], site["id"], "He says 200 arrived.",
        _blank(materials=[{"name": "goods", "quantity": 200, "unit": None, "required_date": None,
                           "attributed_to": "he", "confidence": "high"}]))
    claim_b = await _capture(project["id"], site["id"], "She says only 180 arrived.",
        _blank(materials=[{"name": "goods", "quantity": 180, "unit": None, "required_date": None,
                           "attributed_to": "she", "confidence": "high"}]))
    # NO mark_superseded call - this is a genuine, unresolved contradiction
    item_a = await operations_engine.get_item(claim_a[0]["id"])
    item_b = await operations_engine.get_item(claim_b[0]["id"])
    assert item_a["status"] == "open" and item_b["status"] == "open"
    assert item_a["superseded_by_item_id"] is None and item_b["superseded_by_item_id"] is None
    assert item_a["quantity"] == 200 and item_b["quantity"] == 180  # both claims preserved, neither wins


# 9. separate new event is not mistaken for correction
async def test_9_new_event_not_mistaken_for_correction():
    """'Another 20 arrived today' is a NEW fact, not a correction of an
    earlier one - confirmed nothing here automatically marks it as
    superseding anything; it is just a third, independent item."""
    project, site = await _new_project("corr9")
    first = await _capture(project["id"], site["id"], "200 tiles arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    second = await _capture(project["id"], site["id"], "Another 20 arrived today.",
        _blank(materials=[{"name": "tiles", "quantity": 20, "unit": "pieces", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    item1 = await operations_engine.get_item(first[0]["id"])
    item2 = await operations_engine.get_item(second[0]["id"])
    assert item1["status"] == "open" and item2["status"] == "open"  # neither auto-superseded
    assert item1["superseded_by_item_id"] is None and item2["superseded_by_item_id"] is None


# 10. partial actual remains Expected -> Actual -> Remaining (F. PARTIAL ACTUAL)
async def test_10_partial_actual_unaffected_by_supersession_mechanism():
    project, site = await _new_project("corr10")
    items = await _capture(project["id"], site["id"], "180 of the 200 arrived.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "actual_quantity": 180, "unit": "pieces",
                           "required_date": None, "attributed_to": None, "confidence": "high"}]))
    item = items[0]
    assert item["quantity"] == 200 and item["actual_quantity"] == 180
    assert operations_engine.compute_metrics(item)["quantity_remaining"] == 20
    assert item["status"] == "open"  # not superseded - this is explicit same-statement variance, unrelated


# 11. project isolation remains intact
async def test_11_project_isolation_for_supersession():
    project1, site1 = await _new_project("iso1")
    project2, site2 = await _new_project("iso2")
    old = await operations_engine.create_item(actor=PM, site_id=site1["id"],
        category="material_requirement", title="200 tiles")
    other_project_item = await operations_engine.create_item(actor=PM, site_id=site2["id"],
        category="material_requirement", title="unrelated item")
    with pytest.raises(ValueError, match="same project"):
        await operations_engine.mark_superseded(item_id=old["id"], actor=PM,
                                                 superseded_by_item_id=other_project_item["id"])


# 12. query_change_history preserves chronological history
async def test_12_query_change_history_preserves_chronology_and_shows_supersession():
    project, site = await _new_project("corr12")
    old = await _capture(project["id"], site["id"], "200 units Thursday.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "Thursday",
                           "attributed_to": None, "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Actually 220 units Friday.",
        _blank(materials=[{"name": "units", "quantity": 220, "unit": "units", "required_date": "Friday",
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"], note="corrected")
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_change_history", "confidence": "high"}],
        "project_reference": None, "comparison_scope": None, "entity_reference": old[0]["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {old[0]['title']}?", user=PM, active_project_id=project["id"])
    assert result["result"]["ok"] is True
    events = result["result"]["data"]["events"]
    whats = [e["what"] for e in events]
    assert "superseded_by" in whats
    superseded_row = next(e for e in events if e["what"] == "superseded_by")
    assert superseded_row["to"] == new[0]["id"]
    assert superseded_row["to_title"] == new[0]["title"]
    # chronological: creation event must come before the supersession event
    assert events.index([e for e in events if e["what"] != "superseded_by"][0]) < events.index(superseded_row)


# 13. actor_history does not double-count superseded claims as fulfilled work
async def test_13_actor_history_excludes_superseded_from_fulfilled_and_open():
    project, site = await _new_project("corr13")
    old = await _capture(project["id"], site["id"], "Supplier confirmed 200 units Thursday.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Supplier corrected it to 220 units Friday.",
        _blank(materials=[{"name": "units", "quantity": 220, "unit": "units", "required_date": "Friday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    history = await operations_engine.actor_history(project["id"], user=PM, attributed_to="supplier")
    assert history["total_commitments"] == 2        # both captures genuinely happened
    assert history["fulfilled_count"] == 0           # the superseded one was never actually fulfilled
    assert history["still_open_count"] == 1          # only the current (220) one is still open - not 2


# 14. My Day / management attention does not treat superseded expectations as currently actionable
async def test_14_operational_center_excludes_superseded_from_open():
    project, site = await _new_project("corr14")
    old = await _capture(project["id"], site["id"], "200 units Thursday.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "Thursday",
                           "attributed_to": None, "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Actually 220 units Friday.",
        _blank(materials=[{"name": "units", "quantity": 220, "unit": "units", "required_date": "Friday",
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    center = await operations_engine.operational_center(site_id=site["id"])
    open_ids = {i["id"] for i in center["open"]}
    assert old[0]["id"] not in open_ids       # the stale 200-unit claim is not actionable
    assert new[0]["id"] in open_ids           # the current 220-unit claim is


async def test_14b_superseded_item_health_is_completed_not_overdue():
    """Guard against the derive_health() regression this investigation
    fixed: a superseded item with a now-past required_by must not show
    as overdue."""
    project, site = await _new_project("corr14b")
    old = await _capture(project["id"], site["id"], "200 units today.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "today",
                           "attributed_to": None, "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Actually 220 units next week.",
        _blank(materials=[{"name": "units", "quantity": 220, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    assert operations_engine.derive_health(await operations_engine.get_item(old[0]["id"])) == "completed"


# 15. construction CRE regression remains green
async def test_15_construction_cre_rule_unaffected_by_supersession():
    project, site = await _new_project("corr15")
    await _capture(project["id"], site["id"], "The supplier said he'll deliver 200 tiles Thursday.",
        _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                           "priority": "normal", "attributed_to": "supplier", "confidence": "high"}]))
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    findings = [a for a in result["recommended_actions"] if a["rule_id"] == "procurement.material_lead_time"]
    assert len(findings) == 1


# ==========================================================================
# Cross-industry correction/supersession (Part 6)
# ==========================================================================

@pytest.mark.parametrize("domain,original,correction,orig_qty,new_qty", [
    ("restaurant", "Chicken delivery was 80 kg.", "Actually only 60 kg came.", 80, 60),
    ("mega_store", "Supplier promised 200 units Thursday.", "Correction, make it 220.", 200, 220),
    ("construction", "200 tiles Thursday.", "Actually make it 220 Friday.", 200, 220),
])
async def test_cross_industry_quantity_correction(domain, original, correction, orig_qty, new_qty):
    project, site = await _new_project(f"corrx_{domain}")
    old = await _capture(project["id"], site["id"], original,
        _blank(materials=[{"name": "goods", "quantity": orig_qty, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], correction,
        _blank(materials=[{"name": "goods", "quantity": new_qty, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    old_item = await operations_engine.get_item(old[0]["id"])
    assert old_item["quantity"] == orig_qty    # original preserved
    assert new[0]["quantity"] == new_qty        # current is the new value
    assert old_item["status"] == "superseded"


async def test_cross_industry_software_actor_correction():
    project, site = await _new_project("corrx_software")
    old = await _capture(project["id"], site["id"], "Rahul will finish Monday.",
        _blank(commitments=[{"what": "finish task", "owed_to": None, "by_when": "Monday",
                             "attributed_to": "Rahul", "confidence": "high"}]))
    new = await _capture(project["id"], site["id"], "Actually Priya is doing it Wednesday.",
        _blank(commitments=[{"what": "finish task", "owed_to": None, "by_when": "Wednesday",
                             "attributed_to": "Priya", "confidence": "high"}]))
    await operations_engine.mark_superseded(item_id=old[0]["id"], actor=PM,
                                            superseded_by_item_id=new[0]["id"])
    old_item = await operations_engine.get_item(old[0]["id"])
    assert old_item["attributed_to"] == "Rahul"
    assert new[0]["attributed_to"] == "Priya"


# ==========================================================================
# PATCH HARDENING — supersession relationship invariants
#
# Traced before changing anything: self-rejection already existed
# (confirmed live). Three genuine gaps were confirmed live and fixed:
#   B. CYCLE: A->B then B->A succeeded, creating a 2-cycle where neither
#      item is current.
#   C. TARGET STATE: an item could be "superseded by" a target that was
#      itself already superseded/duplicate/cancelled/archived - pointing
#      "the current position" at a dead end.
#   D. IDEMPOTENCY: an identical repeat call raised rather than being a
#      safe no-op.
# B and C turned out to be the SAME fix: once a superseding target must
# be live (not superseded/duplicate/cancelled/archived), a cycle of any
# depth becomes mathematically impossible - closing a cycle always
# requires reusing an already-superseded item as a target, which the
# target-state rule alone already forbids. No separate graph-traversal
# code was added; proven live (not merely asserted) for 2- and 3-item
# cycles and a valid, non-cyclic chain.
#
# This pass also found and fixed an unrelated, pre-existing regression
# from the original supersession commit: mark_duplicate() itself had
# been accidentally deleted when mark_superseded() was inserted above
# it (confirmed by diff against the prior commit) - restored verbatim.
# test_duplicate_mechanism_still_works guards against this specifically,
# since no existing test exercised operations_engine.mark_duplicate()
# directly before this pass.
# ==========================================================================

async def test_self_supersede_rejected():
    project, site = await _new_project("hard_self")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="A")
    with pytest.raises(ValueError, match="cannot supersede itself"):
        await operations_engine.mark_superseded(
            item_id=item["id"], actor=PM, superseded_by_item_id=item["id"])


async def test_two_item_cycle_rejected():
    project, site = await _new_project("hard_cycle2")
    a = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="A")
    b = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="B")
    await operations_engine.mark_superseded(item_id=a["id"], actor=PM, superseded_by_item_id=b["id"])
    with pytest.raises(ValueError, match="itself superseded"):
        await operations_engine.mark_superseded(item_id=b["id"], actor=PM, superseded_by_item_id=a["id"])
    # A's own claim must remain exactly as it was - the rejected attempt
    # must not have mutated anything.
    a_after = await operations_engine.get_item(a["id"])
    assert a_after["status"] == "superseded" and a_after["superseded_by_item_id"] == b["id"]
    b_after = await operations_engine.get_item(b["id"])
    assert b_after["status"] == "open" and b_after.get("superseded_by_item_id") is None


async def test_three_item_cycle_rejected():
    """A deeper chain attempting to close a cycle (A->B, B->C, C->A) is
    rejected too, by the same target-state rule - no separate cycle
    walk needed, proven here rather than assumed."""
    project, site = await _new_project("hard_cycle3")
    a = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="A")
    b = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="B")
    c = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="C")
    await operations_engine.mark_superseded(item_id=a["id"], actor=PM, superseded_by_item_id=b["id"])
    await operations_engine.mark_superseded(item_id=b["id"], actor=PM, superseded_by_item_id=c["id"])
    with pytest.raises(ValueError, match="itself superseded"):
        await operations_engine.mark_superseded(item_id=c["id"], actor=PM, superseded_by_item_id=a["id"])


async def test_valid_sequential_correction_chain_A_to_B_to_C():
    """A legitimate, non-cyclic correction chain (each correction pointing
    forward to a genuinely new, live item) must keep working."""
    project, site = await _new_project("hard_chain")
    a = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="200 units")
    b = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="220 units")
    c = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="210 units")
    a2 = await operations_engine.mark_superseded(item_id=a["id"], actor=PM, superseded_by_item_id=b["id"])
    b2 = await operations_engine.mark_superseded(item_id=b["id"], actor=PM, superseded_by_item_id=c["id"])
    c_final = await operations_engine.get_item(c["id"])
    assert a2["status"] == "superseded" and a2["superseded_by_item_id"] == b["id"]
    assert b2["status"] == "superseded" and b2["superseded_by_item_id"] == c["id"]
    assert c_final["status"] == "open"  # C is the current, live position
    assert c_final.get("superseded_by_item_id") is None


@pytest.mark.parametrize("bad_status", ["superseded", "duplicate", "cancelled", "archived"])
async def test_invalid_target_state_rejected(bad_status):
    project, site = await _new_project(f"hard_target_{bad_status}")
    source = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="source")
    target = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="target")
    if bad_status in ("superseded", "duplicate"):
        other = await operations_engine.create_item(
            actor=PM, site_id=site["id"], category="material_requirement", title="other")
        if bad_status == "superseded":
            await operations_engine.mark_superseded(item_id=target["id"], actor=PM,
                                                     superseded_by_item_id=other["id"])
        else:
            await operations_engine.mark_duplicate(item_id=target["id"], actor=PM,
                                                    duplicate_of_item_id=other["id"])
    else:
        await operations_engine.transition_status(item_id=target["id"], to_status=bad_status, actor=PM)
    with pytest.raises(ValueError, match=f"itself {bad_status}"):
        await operations_engine.mark_superseded(item_id=source["id"], actor=PM,
                                                 superseded_by_item_id=target["id"])
    # the rejected attempt must not have mutated the source item
    source_after = await operations_engine.get_item(source["id"])
    assert source_after["status"] == "open"


async def test_repeated_identical_supersession_is_a_safe_noop():
    project, site = await _new_project("hard_idem")
    source = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="source")
    target = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="target")
    first = await operations_engine.mark_superseded(item_id=source["id"], actor=PM,
                                                     superseded_by_item_id=target["id"], note="first")
    events_after_first = await operations_engine.list_events_for_item(source["id"])
    second = await operations_engine.mark_superseded(item_id=source["id"], actor=PM,
                                                      superseded_by_item_id=target["id"], note="second")
    events_after_second = await operations_engine.list_events_for_item(source["id"])
    assert second["status"] == "superseded" and second["superseded_by_item_id"] == target["id"]
    assert len(events_after_first) == len(events_after_second)  # no duplicate event logged


async def test_repeated_supersession_with_different_target_still_rejected():
    """Idempotency only covers an IDENTICAL repeat - changing the target
    after the fact is a genuine, ambiguous state change, not a retry."""
    project, site = await _new_project("hard_idem_diff")
    source = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="source")
    target1 = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="target1")
    target2 = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="target2")
    await operations_engine.mark_superseded(item_id=source["id"], actor=PM, superseded_by_item_id=target1["id"])
    with pytest.raises(ValueError, match="not allowed"):
        await operations_engine.mark_superseded(item_id=source["id"], actor=PM, superseded_by_item_id=target2["id"])
    unchanged = await operations_engine.get_item(source["id"])
    assert unchanged["superseded_by_item_id"] == target1["id"]  # still points to the original target


async def test_same_project_rejection_still_green():
    """Existing guard (E.), unchanged - re-confirmed here alongside the
    new invariants rather than assumed from the earlier test file."""
    project1, site1 = await _new_project("hard_proj1")
    project2, site2 = await _new_project("hard_proj2")
    source = await operations_engine.create_item(
        actor=PM, site_id=site1["id"], category="material_requirement", title="source")
    other_project_target = await operations_engine.create_item(
        actor=PM, site_id=site2["id"], category="material_requirement", title="target")
    with pytest.raises(ValueError, match="same project"):
        await operations_engine.mark_superseded(item_id=source["id"], actor=PM,
                                                 superseded_by_item_id=other_project_target["id"])


async def test_history_unmutated_through_a_rejected_cycle_attempt():
    """F. HISTORY: the original item's own claimed fields are never
    altered by a rejected operation, and the ledger is never rewritten -
    only ever appended to."""
    project, site = await _new_project("hard_history")
    a = await _capture(project["id"], site["id"], "Supplier confirmed 200 units Thursday.",
        _blank(materials=[{"name": "units", "quantity": 200, "unit": "units", "required_date": "Thursday",
                           "attributed_to": "supplier", "confidence": "high"}]))
    b = await _capture(project["id"], site["id"], "Actually 220 units.",
        _blank(materials=[{"name": "units", "quantity": 220, "unit": "units", "required_date": None,
                           "attributed_to": None, "confidence": "high"}]))
    events_before = len(await operations_engine.list_events_for_item(a[0]["id"]))
    await operations_engine.mark_superseded(item_id=a[0]["id"], actor=PM, superseded_by_item_id=b[0]["id"])
    try:
        await operations_engine.mark_superseded(item_id=b[0]["id"], actor=PM, superseded_by_item_id=a[0]["id"])
    except ValueError:
        pass
    a_after = await operations_engine.get_item(a[0]["id"])
    events_after = await operations_engine.list_events_for_item(a[0]["id"])
    assert a_after["quantity"] == 200  # original claim never altered
    assert a_after["attributed_to"] == "supplier"
    assert len(events_after) == events_before + 1  # only the successful supersession appended, nothing rewritten


async def test_duplicate_mechanism_still_works():
    """Guard against the regression this hardening pass found and fixed:
    mark_duplicate() was accidentally deleted when mark_superseded() was
    inserted above it in the original commit. No existing test called
    operations_engine.mark_duplicate() directly before this pass."""
    project, site = await _new_project("hard_dup_regression")
    item = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="original")
    other = await operations_engine.create_item(
        actor=PM, site_id=site["id"], category="material_requirement", title="canonical")
    result = await operations_engine.mark_duplicate(
        item_id=item["id"], actor=PM, duplicate_of_item_id=other["id"], note="same report")
    assert result["status"] == "duplicate"
    assert result["duplicate_of_item_id"] == other["id"]
