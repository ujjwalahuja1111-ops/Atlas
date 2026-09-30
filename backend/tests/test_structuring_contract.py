"""Structuring contract tests (product patch: routing, hedges, day words).

Why this file exists: the 3-run live evaluation showed three real harms, all
traced to what the structuring prompt did (or did not) say:

  1. A quantified goods promise was sometimes filed ONLY as a `commitments`
     entry (which has no quantity/unit fields, so "200 tiles" / "80 kg" never
     reached the item), sometimes filed in BOTH `materials` and `commitments`
     (two items for one promise; quantity and attribution split across them).
  2. A hedge ("probably") made the model report confidence "medium", and
     Atlas only stores quantity / unit / attributed_to at "high" - so a
     hedged supplier promise was stored with none of them.
  3. The model converted day words into calendar dates ("kal" ->
     2023-10-29). It does not know today's date, the dates were invented and
     in the wrong year, and Atlas accepts an explicit ISO date at face value -
     so a promise for tomorrow was stored as a 2023 date and showed overdue.

Two kinds of test, kept honest about what they can prove:
  * FIXTURE tests replay the model outputs actually seen in the live run
    (copied from the report) through the real pipeline and pin what Atlas
    stores - they document WHY the prompt rules exist.
  * CONTRACT tests pin the prompt rules and confirm the JSON shape the
    pipeline consumes did not change.
None of this proves how a live model responds to the new wording; that is
verified by re-running scripts.live_llm_structuring_eval --runs 3.

Run from backend/: python -m pytest tests/test_structuring_contract.py -q
"""
import os
import re
import pytest
from datetime import datetime, timezone

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_structuring_contract_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_structuring_contract_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine  # noqa: E402
from engines.intelligence_engine import EVENT_SYSTEM_PROMPT as _RAW_PROMPT  # noqa: E402

# Phrase checks ignore line wrapping; the schema-shape checks use the raw text.
PROMPT = re.sub(r"\s+", " ", _RAW_PROMPT)

for _mod in (memory_engine, operations_engine, intelligence_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


PM = {"id": "u_sc_pm", "name": "SC PM", "role": "project_manager"}
ACTOR = {"id": "u_sc_actor", "name": "SC Actor"}
MONDAY = datetime(2026, 9, 28, 9, 0, 0, tzinfo=timezone.utc)   # capture time for exact date checks


def _blank(**lists):
    base = {"type": "general", "materials": [], "labour": [], "equipment": [], "client_approvals": [],
            "drawing_requests": [], "inspections": [], "safety_observations": [],
            "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [],
            "work_done": [], "urgency": "normal", "language_detected": "en"}
    base.update(lists)
    return base


async def _pipeline(text, structured, when=None, name="sc"):
    """Real event -> real _emit_proposals_from_structured -> real accept_ai_proposal."""
    when = when or datetime.now(timezone.utc)
    project = await memory_engine.insert_project(name=f"SC {name}", code=name.upper()[:8])
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    ev = await memory_engine.insert_event({
        "id": memory_engine._new_id("evt_"), "site_id": site["id"], "project_id": project["id"],
        "user_id": ACTOR["id"], "user_name": ACTOR["name"], "activity_id": None, "kind": "text",
        "text_input": text, "transcript": None, "audio_asset_id": None, "photo_asset_ids": [],
        "gps": None, "client_created_at": None, "app_version": None,
        "requires_client_approval": False, "ai_status": "pending", "ai_analysis_id": None,
        "server_created_at": when.isoformat(),
    })
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    items = [await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=ACTOR)
             for p in await operations_engine.list_ai_proposals(event_id=ev["id"])]
    return project, items


# ==========================================================================
# CONTRACT: the prompt's rules exist, and the JSON shape did not change
# ==========================================================================

BASELINE_KEYS = {"type", "title", "summary", "materials", "labour", "equipment", "client_approvals",
                 "drawing_requests", "inspections", "safety_observations", "quality_observations",
                 "commitments", "follow_ups", "issues", "work_done", "urgency", "language_detected"}

BASELINE_FIELDS = {
    # Expected vs Actual investigation added actual_quantity (materials,
    # equipment) and amount/actual_amount (commitments) - the smallest
    # extension for explicit, same-statement expected-vs-actual variance
    # (see test_actual_quantity_only_paired_with_quantity_* below for the
    # safety discipline). Every other field, and every other list, is
    # unchanged from the prior baseline.
    "materials": "name quantity actual_quantity unit required_date priority trade area reason attributed_to confidence",
    "labour": "trade count required_date priority area reason attributed_to confidence",
    "equipment": "name quantity actual_quantity required_date priority reason attributed_to confidence",
    "client_approvals": "what required_date priority reason confidence",
    "drawing_requests": "drawing revision priority reason confidence",
    "inspections": "what required_date priority reason confidence",
    "safety_observations": "observation priority area confidence",
    "quality_observations": "observation priority area confidence",
    "commitments": "what owed_to by_when amount actual_amount attributed_to confidence",
    "follow_ups": "what when confidence",
}


def _schema_region():
    return _RAW_PROMPT.split("Return ONLY a JSON object with these keys:")[1].split("CRITICAL RULES:")[0]


def test_json_keys_and_per_list_fields_are_unchanged():
    region = _schema_region()
    assert set(re.findall(r"^- (\w+):", region, flags=re.M)) == BASELINE_KEYS
    for key, fields in BASELINE_FIELDS.items():
        m = re.search(rf"^- {key}: .*?list of \{{([^}}]*)\}}", region, flags=re.M)
        assert m, key
        assert [f.strip() for f in m.group(1).split(",")] == fields.split(), key


def test_goods_promises_are_defined_as_materials_and_other_promises_as_commitments():
    assert "including goods someone has promised or confirmed to deliver" in PROMPT
    assert "that is not a delivery of goods and not already covered above" in PROMPT


def test_one_fact_one_list_rule_is_present():
    assert "Record each fact ONCE" in PROMPT
    assert "ONE `materials` entry" in PROMPT
    assert "Do NOT also add a `commitments` entry for the same delivery" in PROMPT
    assert "set attributed_to to whoever made the promise" in PROMPT
    assert "Two different quantities or dates in one sentence are two separate `materials` entries" in PROMPT


def test_hedge_does_not_lower_confidence_but_vagueness_does():
    assert 'A hedge about whether it will actually happen ("probably", "hopefully", "should") does NOT lower it' in PROMPT
    assert 'vagueness about the facts ("we might be short on something soon") does' in PROMPT


def test_day_words_are_copied_never_converted_to_calendar_dates():
    assert "NEVER convert a day word into a calendar date or ISO timestamp" in PROMPT
    assert "you do not know today's date" in PROMPT
    assert "Write a calendar date only if the speaker literally said one" in PROMPT
    assert "leave it out of the date field" in PROMPT
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b", PROMPT), "the prompt must not embed a date"


def test_attribution_semantics_were_not_weakened():
    assert "ONLY when the speaker is explicitly quoting or relaying someone else's statement" in PROMPT
    assert "Leave null when" in PROMPT and "their own count of stock on hand" in PROMPT


def test_day_words_the_prompt_asks_for_all_normalise_deterministically():
    n = operations_engine._normalize_date_phrase
    got = {w: n(w, reference=MONDAY) for w in ("today", "tomorrow", "Monday", "Thursday", "Friday")}
    assert all(got.values()), got
    assert got["tomorrow"].startswith("2026-09-29") and got["Thursday"].startswith("2026-10-01")
    assert got["Friday"].startswith("2026-10-02") and got["today"].startswith("2026-09-28")


def test_documented_limits_that_motivate_the_english_day_word_and_no_clock_time_rules():
    """These forms do NOT normalise today, which is why the prompt asks for the
    English day word and for clock times to stay out of the date field."""
    n = operations_engine._normalize_date_phrase
    assert n("kal", reference=MONDAY) is None
    assert n("tomorrow 7 AM", reference=MONDAY) is None
    assert n("7 AM tomorrow", reference=MONDAY) is None


# ==========================================================================
# DESIRED SHAPE (what the rules ask for) survives the real pipeline intact
# ==========================================================================

async def test_quantified_supplier_promise_as_one_materials_item_keeps_everything():
    st = _blank(materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                            "priority": "normal", "attributed_to": "supplier", "confidence": "high"}])
    project, items = await _pipeline("Supplier says he'll send 200 tiles by Thursday.", st, MONDAY, "one")
    assert len(items) == 1
    it = items[0]
    assert (it["category"], it["quantity"], it["unit"], it["attributed_to"]) == \
        ("material_requirement", 200, "pieces", "supplier")
    assert it["required_by"].startswith("2026-10-01")
    hist = await operations_engine.actor_history(project["id"], user=PM, attributed_to="supplier")
    assert hist["total_commitments"] == 1     # one promise counts once


async def test_two_facts_in_one_sentence_are_two_materials_items():
    st = _blank(materials=[
        {"name": "chicken", "quantity": 80, "unit": "kg", "required_date": "Friday", "priority": "normal",
         "attributed_to": "food supplier", "confidence": "high"},
        {"name": "chicken", "quantity": 20, "unit": "kg", "required_date": "tomorrow", "priority": "high",
         "attributed_to": None, "confidence": "high"}])
    _, items = await _pipeline("The food supplier confirmed 80 kg chicken for Friday but we're already "
                               "20 kg short for tomorrow.", st, MONDAY, "two")
    by_qty = {i["quantity"]: i for i in items}
    assert len(items) == 2 and set(by_qty) == {80, 20}
    assert by_qty[80]["attributed_to"] == "food supplier" and by_qty[80]["required_by"].startswith("2026-10-02")
    assert by_qty[20].get("attributed_to") is None and by_qty[20]["required_by"].startswith("2026-09-29")


# ==========================================================================
# FIXTURES: model outputs actually seen in the live run -> what Atlas stored
# ==========================================================================

async def test_live_fixture_hedged_promise_at_medium_confidence_stores_no_quantity_unit_or_attribution():
    """construction_1, live run 1: 'probably' -> confidence 'medium' on every entry."""
    st = _blank(
        materials=[{"name": "tiles", "quantity": 200, "unit": "pieces", "required_date": "Thursday",
                    "priority": "normal", "attributed_to": "supplier", "confidence": "medium"}],
        commitments=[{"what": "Send 200 tiles", "owed_to": None, "by_when": "Thursday",
                      "attributed_to": "supplier", "confidence": "medium"}])
    _, items = await _pipeline("Supplier says he'll send 200 tiles by Thursday, probably.", st, MONDAY, "hedge")
    for it in items:
        assert it.get("quantity") is None and it.get("unit") is None and it.get("attributed_to") is None


async def test_live_fixture_delivery_filed_only_as_commitment_has_no_quantity():
    """restaurant_1, live run 1: the 80 kg delivery went to commitments."""
    st = _blank(
        materials=[{"name": "chicken", "quantity": 20, "unit": "kg", "required_date": "tomorrow",
                    "priority": "high", "attributed_to": None, "confidence": "high"}],
        commitments=[{"what": "80 kg chicken delivery", "owed_to": None, "by_when": "Friday",
                      "attributed_to": "food supplier", "confidence": "high"}])
    _, items = await _pipeline("The food supplier confirmed 80 kg chicken for Friday but we're already "
                               "20 kg short for tomorrow.", st, MONDAY, "commit")
    commitment = next(i for i in items if i["category"] == "commitment")
    assert commitment.get("quantity") is None and commitment.get("unit") is None   # "80 kg" only in text
    assert "80 kg" in commitment["title"]


async def test_live_fixture_double_filing_makes_two_items_and_splits_quantity_from_attribution():
    """shop_1, live run 3: same promise in materials (no attribution) AND commitments (attribution)."""
    st = _blank(
        materials=[{"name": "Product X", "quantity": 50, "unit": "units", "required_date": "tomorrow",
                    "priority": "high", "attributed_to": None, "confidence": "high"}],
        commitments=[{"what": "Delivery of 50 units of Product X", "owed_to": None, "by_when": "tomorrow",
                      "attributed_to": "supplier", "confidence": "high"}])
    _, items = await _pipeline("Need 50 units of Product X by tomorrow, supplier promised delivery.",
                               st, MONDAY, "split")
    mat = next(i for i in items if i["category"] == "material_requirement")
    com = next(i for i in items if i["category"] == "commitment")
    assert len(items) == 2
    assert mat["quantity"] == 50 and mat.get("attributed_to") is None
    assert com["attributed_to"] == "supplier" and com.get("quantity") is None


async def test_live_fixture_model_made_iso_date_is_stored_as_past_date_and_looks_overdue():
    """shop_5, live run 1: 'kal' was turned into 2023-10-29. Atlas takes an explicit date at face value."""
    st = _blank(commitments=[{"what": "deliver goods", "owed_to": None, "by_when": "2023-10-29",
                              "attributed_to": "supplier", "confidence": "high"}])
    _, items = await _pipeline("Supplier bola kal tak maal bhej dega.", st, None, "isodate")
    item = items[0]
    assert item["required_by"].startswith("2023-10-29")
    overdue_ids = {i["id"] for i in (await operations_engine.my_day(user=PM))["overdue"]}
    assert item["id"] in overdue_ids


# ==========================================================================
# ISSUES ROUTING: priority is no longer force-set, unlike before
# ==========================================================================

async def test_issue_priority_follows_the_utterance_not_a_hardcoded_value():
    """Real pipeline harm found while investigating damage-routing drift
    (shop_2/warehouse_6 live evidence): an observation the model classified
    as `issues` was ALWAYS stored priority "high", regardless of the
    model's own urgency judgment or its own per-entry priority field on
    every other list - while the identical fact filed under
    `quality_observations` correctly kept the model's own priority. This
    silently inflated my_day()'s own high_priority_work with routine
    observations whenever the model chose `issues`, a confirmed
    inconsistency with every other list's own existing default (`prio =
    priority or global_urgency or "normal"` in intelligence_engine.add()).
    Fixed by removing the hardcoded value so `issues` uses the SAME
    fallback every other list already uses - not by trying to force the
    model's own list choice, since the prompt already says "damage" under
    quality_observations and live evidence showed the model still
    sometimes chooses issues anyway."""
    st = _blank(issues=["8 units came in damaged from the last batch"], urgency="normal")
    _, items = await _pipeline("8 units came in damaged from the last batch.", st, MONDAY, "issuelow")
    assert items[0]["category"] == "site_issue"
    assert items[0]["priority"] == "normal"   # follows the utterance's own urgency, not forced high


async def test_issue_priority_still_reflects_high_urgency_utterances():
    st = _blank(issues=["forklift is completely broken, nothing can move"], urgency="high")
    _, items = await _pipeline("Forklift is completely broken, nothing can move.", st, MONDAY, "issuehigh")
    assert items[0]["priority"] == "high"   # a genuinely urgent utterance is still high - not suppressed


async def test_issue_priority_defaults_to_normal_with_no_urgency_signal_at_all():
    st = _blank(issues=["dispatch delayed by rain"])   # urgency left at _blank()'s own "normal" default
    _, items = await _pipeline("Dispatch delayed by rain.", st, MONDAY, "issuedefault")
    assert items[0]["priority"] == "normal"


async def test_quality_observation_priority_was_and_remains_the_models_own_value():
    """Regression guard: this fix touches only the `issues` emission branch;
    quality_observations already respected the model's own priority and
    must continue to."""
    st = _blank(quality_observations=[{"observation": "minor scuff on 2 cartons", "priority": "low",
                                       "area": "receiving", "confidence": "high"}])
    _, items = await _pipeline("Minor scuff on 2 cartons.", st, MONDAY, "qualow")
    assert items[0]["category"] == "quality_observation"
    assert items[0]["priority"] == "low"


async def test_issue_never_appears_in_actor_history_unaffected_by_this_fix():
    """site_issue was already excluded from ACTOR_COMMITMENT_CATEGORIES;
    confirms this fix does not change that."""
    project, _ = await _pipeline("Dispatch delayed by rain.",
                                 _blank(issues=["dispatch delayed by rain"]), MONDAY, "issuehistory")
    assert "site_issue" not in operations_engine.ACTOR_COMMITMENT_CATEGORIES


async def test_same_promise_with_the_day_word_stored_as_a_future_date_not_overdue():
    st = _blank(commitments=[{"what": "deliver goods", "owed_to": None, "by_when": "tomorrow",
                              "attributed_to": "supplier", "confidence": "high"}])
    _, items = await _pipeline("Supplier says he'll deliver goods tomorrow.", st, None, "daywordok")
    item = items[0]
    assert item["required_by"] > datetime.now(timezone.utc).isoformat()
    overdue_ids = {i["id"] for i in (await operations_engine.my_day(user=PM))["overdue"]}
    assert item["id"] not in overdue_ids
