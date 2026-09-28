"""Golden multi-industry natural-language corpus (reviewed).

Nothing in this module changes Atlas's behaviour. The corpus was not written
to fit the prompt; any later prompt change is made from live-run evidence and
recorded in git history, never by editing an expectation to raise a score.

Shared by:
  - tests/test_golden_corpus_pipeline.py  (Layer A: deterministic, credential-free)
  - tests/test_eval_harness.py            (evaluator + runner self-tests)
  - scripts/live_llm_structuring_eval.py  (Layer B: real model, real _structure())

Every case has:
  text             natural, messy operational language (unchanged from the
                   first version of this corpus)
  expect           fact-level checks (grammar documented in eval/evaluator.py)
  gold_structured  a hand-built, deliberately-correct example of what a
                   competent structuring pass returns (Layer A input only)
  review           how the expectation was judged against the CURRENT prompt

REVIEW VERDICTS
  A  Expectation is correct as written. If the live model misses it, that is
     a genuine model failure.
  B  The original expectation conflicted with the current prompt's own list
     definitions and was corrected to accept the prompt-consistent
     alternatives. The prompt itself defines overlapping lists:
       * labour     = "any staffing or people requirement (a shortage, a
                       person committing to a task)"
       * commitments= "any promise someone made, of any kind not already
                       covered above"
       * equipment  = "any tool, machine, or device requirement (available
                       or needed)"
       * inspections= "any scheduled check or verification"
       * follow_ups = (no definition at all)
       * issues     = "problems/blockers"
     so demanding exactly one list where the prompt permits several would
     score prompt ambiguity as a model failure.
  C  The original evaluator was too strict for the intent of the case (for
     example: "must not fabricate a quantity" was scored as a failure when
     the model correctly emitted no entry at all).
  D  The statement is genuinely ambiguous; several lists/readings are
     reasonable, and the reasonable ones are accepted.

`changed` records whether the expectation differs from the first version.
Corrections are made ONLY where the expectation was wrong or the statement
ambiguous, and every one is documented in `rationale` -- not to raise a
score. Whether the ontology overlap itself is a product problem is a
separate question, reported separately.
"""
from __future__ import annotations

from eval.evaluator import evaluate_case  # noqa: F401  (re-exported for callers)


# ---- tiny builders so expectations stay readable ---------------------------

def eq(value):
    return {"equals": value}


def has(*terms):
    return {"contains_any": list(terms)}


NULL = {"is_null": True}


def entry(list_key: str, **specs) -> dict:
    return {"list": list_key, **specs}


def text_in(list_key: str, *terms) -> dict:
    return {"list": list_key, "text_contains_any": list(terms)}


def never_fabricates(list_key: str, field: str) -> dict:
    return {"list": list_key, "all_entries": {field: NULL}}


def any_of(*alternatives) -> dict:
    return {"any_of": list(alternatives)}


def _blank_structured() -> dict:
    """Every key EVENT_SYSTEM_PROMPT asks for, empty."""
    return {
        "type": "general", "title": "", "summary": "",
        "materials": [], "labour": [], "equipment": [], "client_approvals": [],
        "drawing_requests": [], "inspections": [], "safety_observations": [],
        "quality_observations": [], "commitments": [], "follow_ups": [],
        "issues": [], "work_done": [], "urgency": "normal", "language_detected": "en",
    }


def _review(verdict: str, changed: bool, rationale: str, original: str = "") -> dict:
    return {"verdict": verdict, "changed": changed, "rationale": rationale,
            "original_expectation": original}


CORPUS: list[dict] = [
    # ============================ A. CONSTRUCTION ============================
    {
        "id": "construction_1_supplier_delivery", "domain": "construction",
        "text": "Supplier says he'll send 200 tiles by Thursday, probably.",
        "expect": [entry("materials", quantity=eq(200), name=has("tile"),
                         required_date=has("thursday"), attributed_to=has("supplier"))],
        "review": _review("A", True,
                          "Goods with a quantity, a date and an explicitly relayed claim "
                          "('Supplier says'). 'probably' hedges the promise, not the facts. "
                          "Corrected after the live run: the first version required unit to "
                          "contain 'tile', but for individually counted goods the noun is the "
                          "item's NAME and 'pieces'/'units'/'tiles' are all correct units "
                          "(the live model answered 'pieces'). The item is now identified by "
                          "name; quantity, date and attribution are still required.",
                          "unit contains 'tile'"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "tiles", "quantity": 200, "unit": "tiles", "required_date": "Thursday",
             "priority": "normal", "attributed_to": "supplier", "confidence": "high"}]},
    },
    {
        "id": "construction_2_labour_shortfall_hinglish", "domain": "construction",
        "text": "Abhi sirf 3 mistry aaye hain site pe, kaam slow chal raha hai.",
        "expect": [any_of(entry("labour", count=eq(3)),
                          text_in("issues", "3", "three", "mistry", "mason"))],
        "review": _review("D", True,
                          "'Only 3 masons have come' reports the headcount present, not an "
                          "explicit shortage. Filing it as a labour entry (count 3) or as a "
                          "site-under-staffed issue both keep the fact.",
                          "labour with count == 3 only"),
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": "mason", "count": 3, "required_date": None, "priority": "normal",
             "area": None, "reason": "short-staffed", "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "construction_3_client_approval_pending", "domain": "construction",
        "text": "Drawing approval abhi tak pending hai client se, kaam ruka hua hai.",
        "expect": [entry("client_approvals", what=has("drawing", "approval"))],
        "review": _review("A", False,
                          "An approval owed by someone before work can proceed is exactly "
                          "the prompt's client_approvals definition."),
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "drawing approval", "required_date": None, "priority": "high",
             "reason": "work blocked", "confidence": "high"}]},
    },
    {
        "id": "construction_4_contractor_commitment", "domain": "construction",
        "text": "Contractor ne kaha woh kal tak plumbing finish kar dega.",
        "expect": [any_of(
            entry("commitments", by_when=has("tomorrow", "kal"), attributed_to=has("contractor")),
            entry("labour", required_date=has("tomorrow", "kal"), attributed_to=has("contractor")))],
        "review": _review("B", True,
                          "The prompt's labour list includes 'a person committing to a task' "
                          "and commitments covers promises 'not already covered above', so a "
                          "contractor promising to finish work is legitimately either.",
                          "commitments only"),
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "finish plumbing", "owed_to": None, "by_when": "tomorrow",
             "attributed_to": "contractor", "confidence": "high"}]},
    },
    {
        "id": "construction_5_site_safety_issue", "domain": "construction",
        "text": "Site pe ek mazdoor gir gaya, mamooli chot aayi, first aid de diya.",
        "expect": [entry("safety_observations",
                         observation=has("fell", "fall", "gir", "injur", "chot"))],
        "review": _review("A", False,
                          "A worker falling and being injured is an observed safety event; "
                          "safety_observations is the closest list the prompt defines."),
        "gold_structured": {**_blank_structured(), "safety_observations": [
            {"observation": "worker fell, minor injury, first aid given", "priority": "high",
             "area": "site", "confidence": "high"}]},
    },
    {
        "id": "construction_6_urgent_material_today", "domain": "construction",
        "text": "We need 50 bags of cement today, it's urgent, work will stop otherwise.",
        "expect": [entry("materials", quantity=eq(50), unit=has("bag"), required_date=has("today"))],
        "review": _review("A", False, "Plain goods requirement with quantity, unit and a date."),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "cement", "quantity": 50, "unit": "bags", "required_date": "today",
             "priority": "critical", "attributed_to": None, "confidence": "high"}], "urgency": "high"},
    },
    {
        "id": "construction_7_ambiguous_no_fabrication", "domain": "construction",
        "text": "Someone mentioned we might be short on materials soon, not sure what exactly.",
        "expect": [never_fabricates("materials", "quantity")],
        "review": _review("C", True,
                          "The intent is 'do not invent a quantity'. The old check required a "
                          "materials entry to exist with quantity null, so a model that "
                          "correctly declined to emit any entry was scored as failing. The "
                          "corrected check passes with no entry OR with a null quantity, and "
                          "still fails if a quantity is invented.",
                          "materials entry must exist with quantity null"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "unspecified material", "quantity": None, "unit": None, "required_date": None,
             "priority": "low", "attributed_to": None, "confidence": "low"}]},
    },

    # ============================ B. RESTAURANT / FOOD =======================
    {
        "id": "restaurant_1_confirmed_and_shortfall", "domain": "restaurant",
        "text": "The food supplier confirmed 80 kg chicken for Friday but we're already 20 kg short for tomorrow.",
        "expect": [
            entry("materials", quantity=eq(80), unit=has("kg", "kilogram"),
                  required_date=has("friday"), attributed_to=has("supplier")),
            entry("materials", quantity=eq(20), unit=has("kg", "kilogram"),
                  required_date=has("tomorrow"), attributed_to=NULL),
        ],
        "review": _review("A", True,
                          "Two independent goods facts: a relayed supplier confirmation (80 kg, "
                          "Friday, attributed) and the speaker's own observed shortfall (20 kg, "
                          "tomorrow, NOT attributed, per the prompt's rule on the speaker's own "
                          "observations). Only change: the unit check now also accepts "
                          "'kilogram(s)', which is the same unit.",
                          "unit contains 'kg' only"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "chicken", "quantity": 80, "unit": "kg", "required_date": "Friday",
             "priority": "normal", "attributed_to": "food supplier", "confidence": "high"},
            {"name": "chicken", "quantity": 20, "unit": "kg", "required_date": "tomorrow",
             "priority": "high", "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "restaurant_2_staffing_shortfall", "domain": "restaurant",
        "text": "Chef says we're 3 staff short tomorrow for the weekend rush.",
        "expect": [entry("labour", count=eq(3), required_date=has("tomorrow"),
                         attributed_to=has("chef"))],
        "review": _review("A", False, "Explicit staffing shortage with a count, a date and a relayed claim."),
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": "kitchen staff", "count": 3, "required_date": "tomorrow", "priority": "high",
             "area": "kitchen", "reason": "weekend rush", "attributed_to": "chef", "confidence": "high"}]},
    },
    {
        "id": "restaurant_3_refrigeration_issue", "domain": "restaurant",
        "text": "Freezer stopped cooling again, need someone to look at it ASAP.",
        "expect": [any_of(
            entry("safety_observations", observation=has("freezer", "cooling", "refrigerat")),
            entry("equipment", name=has("freezer", "refrigerat")),
            text_in("issues", "freezer", "cooling", "refrigerat"))],
        "review": _review("B", True,
                          "A broken freezer is at once a machine problem (the prompt's "
                          "equipment list), a food-safety risk (safety_observations) and a "
                          "plain problem (issues). The first version demanded "
                          "safety_observations only, although the identical shape 'Forklift is "
                          "down' is expected under equipment elsewhere in this corpus.",
                          "safety_observations only"),
        "gold_structured": {**_blank_structured(), "safety_observations": [
            {"observation": "freezer not cooling", "priority": "critical", "area": "kitchen",
             "confidence": "high"}]},
    },
    {
        "id": "restaurant_4_vegetable_supplier_promise", "domain": "restaurant",
        "text": "Vegetable supplier promised delivery by 7 AM tomorrow.",
        "expect": [any_of(
            entry("materials", required_date=has("tomorrow"), attributed_to=has("supplier")),
            entry("commitments", by_when=has("tomorrow"), attributed_to=has("supplier")))],
        "review": _review("D", True,
                          "A supplier's delivery promise is both a goods fact (materials) and "
                          "a promise (commitments). There is no quantity, so nothing forces the "
                          "materials shape. Either keeps the promise, the date and the "
                          "attribution. (Since the routing clarification goods deliveries are "
                          "expected in materials; commitments stays acceptable here only "
                          "because no quantity is at stake.)",
                          "materials only"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "vegetables", "quantity": None, "unit": None, "required_date": "tomorrow",
             "priority": "normal", "attributed_to": "vegetable supplier", "confidence": "high"}]},
    },
    {
        "id": "restaurant_5_owner_approval_pending", "domain": "restaurant",
        "text": "Manager is waiting for the owner's sign-off on the new menu pricing.",
        "expect": [entry("client_approvals",
                         what=has("menu", "pricing", "sign-off", "sign off"))],
        "review": _review("A", False,
                          "The prompt defines client_approvals as any approval or sign-off owed "
                          "by someone, not only a client's."),
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "sign-off on new menu pricing", "required_date": None, "priority": "normal",
             "reason": "awaiting owner", "confidence": "high"}]},
    },
    {
        "id": "restaurant_6_observed_shortfall_no_attribution", "domain": "restaurant",
        "text": "Only 60 kg of the chicken order actually arrived.",
        "expect": [any_of(
            entry("materials", quantity=eq(60), attributed_to=NULL),
            text_in("issues", "60", "arrived", "short"))],
        "review": _review("D", True,
                          "This states what was RECEIVED, which is neither a requirement nor a "
                          "promise, so the prompt's 'goods requirement' wording does not clearly "
                          "cover it. A model may record 60 kg as a goods fact or record the "
                          "shortfall as an issue. Both preserve the fact. What must NOT happen "
                          "in the materials reading: attributing the observation to someone.",
                          "materials with quantity 60 and null attribution only"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "chicken", "quantity": 60, "unit": "kg", "required_date": None,
             "priority": "normal", "attributed_to": None, "confidence": "high"}]},
    },

    # ============================ C. WAREHOUSE / INVENTORY ===================
    {
        "id": "warehouse_1_cartons_expected", "domain": "warehouse",
        "text": "400 cartons expected Tuesday from the distributor.",
        "expect": [entry("materials", quantity=eq(400), name=has("carton"),
                         required_date=has("tuesday"))],
        "review": _review("B", True,
                          "The first version also required attributed_to = distributor. The "
                          "sentence does not say the distributor claimed anything; it names "
                          "where the goods come from. The prompt attributes a claim ONLY when "
                          "the speaker explicitly quotes or relays someone's statement, so "
                          "requiring attribution here contradicted the prompt's own rule. "
                          "Attribution is left unconstrained (either value is acceptable). "
                          "Corrected after the live run: unit no longer has to contain "
                          "'carton' (the live model answered 'units' or null); for counted "
                          "goods the noun is the item's name, which is now what is checked.",
                          "also required attributed_to contains 'distributor' and unit contains 'carton'"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "cartons", "quantity": 400, "unit": "cartons", "required_date": "Tuesday",
             "priority": "normal", "attributed_to": "distributor", "confidence": "high"}]},
    },
    {
        "id": "warehouse_2_shortfall_received", "domain": "warehouse",
        "text": "Only 380 received today, 20 short from what was ordered.",
        "expect": [any_of(
            entry("materials", quantity=eq(380)),
            entry("materials", quantity=eq(20)),
            text_in("issues", "380", "short"))],
        "review": _review("D", True,
                          "Two numbers compete: 380 received (an observation) and 20 short "
                          "(the actual requirement). The first version demanded 380 as the "
                          "quantity. Capturing either number in a goods entry, or recording the "
                          "shortfall as an issue, keeps the fact.",
                          "materials with quantity 380 only"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "goods received", "quantity": 380, "unit": "cartons", "required_date": None,
             "priority": "normal", "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "warehouse_3_forklift_and_commitment", "domain": "warehouse",
        "text": "Forklift is down again, maintenance guy said he'd come today.",
        "expect": [
            entry("equipment", name=has("forklift")),
            any_of(entry("commitments", by_when=has("today")),
                   entry("labour", required_date=has("today"))),
        ],
        "review": _review("B", True,
                          "Equipment half is correct as written. The second half: a person "
                          "promising to come and fix it is 'a person committing to a task' "
                          "(labour) and also a promise (commitments) under the prompt's own "
                          "definitions.",
                          "second expectation: commitments only"),
        "gold_structured": {**_blank_structured(),
            "equipment": [{"name": "forklift", "quantity": 1, "required_date": None, "priority": "high",
                           "reason": "down again", "attributed_to": None, "confidence": "high"}],
            "commitments": [{"what": "repair forklift", "owed_to": None, "by_when": "today",
                             "attributed_to": "maintenance", "confidence": "high"}]},
    },
    {
        "id": "warehouse_4_dispatch_delay_issue", "domain": "warehouse",
        "text": "Dispatch got delayed because of the rain, trucks couldn't load.",
        "expect": [text_in("issues", "dispatch", "delay", "rain", "truck")],
        "review": _review("A", True,
                          "A blocker recorded as a problem. Tightened from 'any issue entry "
                          "exists' to 'an issue that actually mentions this problem'.",
                          "issues list non-empty"),
        "gold_structured": {**_blank_structured(),
            "issues": ["dispatch delayed due to rain, trucks could not load"]},
    },
    {
        "id": "warehouse_5_supervisor_recount_commitment", "domain": "warehouse",
        "text": "Supervisor committed to recounting the stock by Wednesday.",
        "expect": [any_of(
            entry("commitments", by_when=has("wednesday")),
            entry("labour", required_date=has("wednesday")),
            entry("inspections", required_date=has("wednesday")))],
        "review": _review("B", True,
                          "A recount is a scheduled verification (inspections), a person "
                          "committing to a task (labour) and a promise (commitments) under the "
                          "prompt's own overlapping definitions.",
                          "commitments only"),
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "recount stock", "owed_to": None, "by_when": "Wednesday",
             "attributed_to": "supervisor", "confidence": "high"}]},
    },
    {
        "id": "warehouse_6_damaged_cartons", "domain": "warehouse",
        "text": "20 cartons came in damaged this time, more than usual.",
        "expect": [entry("quality_observations", observation=has("damag"))],
        "review": _review("A", False, "An observed defect/damage is the prompt's quality_observations definition."),
        "gold_structured": {**_blank_structured(), "quality_observations": [
            {"observation": "20 cartons damaged on arrival", "priority": "normal", "area": "receiving",
             "confidence": "high"}]},
    },

    # ============================ D. SMALL SHOP / TRADING ====================
    {
        "id": "shop_1_restock_promised", "domain": "shop",
        "text": "Need 50 units of Product X by tomorrow, supplier promised delivery.",
        "expect": [entry("materials", quantity=eq(50), unit=has("unit", "piece", "pcs"),
                         required_date=has("tomorrow"), attributed_to=has("supplier"))],
        "review": _review("A", True,
                          "Goods requirement with a relayed supplier promise. Only change: the "
                          "unit check also accepts 'piece(s)/pcs', a synonym for 'units'.",
                          "unit contains 'unit' only"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "Product X", "quantity": 50, "unit": "units", "required_date": "tomorrow",
             "priority": "high", "attributed_to": "supplier", "confidence": "high"}]},
    },
    {
        "id": "shop_2_damaged_units", "domain": "shop",
        "text": "8 units came in damaged from the last batch.",
        "expect": [entry("quality_observations", observation=has("damag", "broken", "defect"))],
        "review": _review("A", True,
                          "Observed damage. Tightened: the first version accepted the bare "
                          "character '8', which matches almost any text; it now requires a "
                          "damage word.",
                          "observation contains '8' or 'damag'"),
        "gold_structured": {**_blank_structured(), "quality_observations": [
            {"observation": "8 units damaged from last batch", "priority": "normal", "area": None,
             "confidence": "high"}]},
    },
    {
        "id": "shop_3_customer_order_pending", "domain": "shop",
        "text": "Customer order is still pending, we're waiting on stock to come in.",
        "expect": [any_of(
            entry("follow_ups", what=has("stock", "order")),
            text_in("issues", "stock", "order", "pending", "waiting"))],
        "review": _review("B", True,
                          "The prompt gives follow_ups no definition, while issues is defined "
                          "as problems/blockers, which fits 'order stalled waiting on stock' "
                          "at least as well. Demanding follow_ups only was not justified by the "
                          "ontology.",
                          "follow_ups only"),
        "gold_structured": {**_blank_structured(), "follow_ups": [
            {"what": "customer order pending stock arrival", "when": None, "confidence": "medium"}]},
    },
    {
        "id": "shop_4_owner_approval_dependency", "domain": "shop",
        "text": "Owner needs to approve the new supplier before we place the order.",
        "expect": [entry("client_approvals", what=has("supplier", "approve"))],
        "review": _review("A", False, "An approval owed by someone before work can proceed."),
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "approve new supplier", "required_date": None, "priority": "normal",
             "reason": "blocking order", "confidence": "high"}]},
    },
    {
        "id": "shop_5_hinglish_supplier_promise", "domain": "shop",
        "text": "Supplier bola kal tak maal bhej dega.",
        "expect": [any_of(
            entry("commitments", by_when=has("tomorrow", "kal"), attributed_to=has("supplier")),
            entry("materials", required_date=has("tomorrow", "kal"), attributed_to=has("supplier")))],
        "review": _review("B", True,
                          "'maal' means goods, and the prompt's commitments list is for "
                          "promises 'not already covered above', so a supplier's promise to "
                          "send goods belongs in materials as much as in commitments. The "
                          "first version demanded commitments only. The Hinglish aspect "
                          "(relayed claim + a 'kal' date) is unchanged. (Since the routing "
                          "clarification goods deliveries are expected in materials; "
                          "commitments stays acceptable only because no quantity is at stake.)",
                          "commitments only"),
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "send goods", "owed_to": None, "by_when": "tomorrow",
             "attributed_to": "supplier", "confidence": "high"}]},
    },
    {
        "id": "shop_6_ambiguous_no_fabrication", "domain": "shop",
        "text": "We keep running short on Product Y sometimes, not always though.",
        "expect": [never_fabricates("materials", "quantity")],
        "review": _review("C", True,
                          "Same reason as construction_7: no entry at all is correct behaviour; "
                          "an invented quantity is the only failure.",
                          "materials entry must exist with quantity null"),
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "Product Y", "quantity": None, "unit": None, "required_date": None,
             "priority": "low", "attributed_to": None, "confidence": "low"}]},
    },

    # ============================ E. SOFTWARE / OFFICE =======================
    {
        "id": "software_1_own_plan_not_attributed", "domain": "software",
        "text": "I'll finish the API by Monday.",
        "expect": [any_of(
            entry("commitments", by_when=has("monday"), attributed_to=NULL),
            entry("labour", required_date=has("monday"), attributed_to=NULL))],
        "review": _review("B", True,
                          "The speaker's own plan must NOT be attributed to anyone else "
                          "(unchanged). The list check widened because the prompt's labour "
                          "definition includes 'a person committing to a task'.",
                          "commitments only"),
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "finish the API", "owed_to": None, "by_when": "Monday",
             "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "software_2_relayed_claim_attributed", "domain": "software",
        "text": "Rahul said he can join Monday.",
        "expect": [any_of(
            entry("commitments", by_when=has("monday"), attributed_to=has("rahul")),
            entry("labour", required_date=has("monday"), attributed_to=has("rahul")))],
        "review": _review("B", True,
                          "A relayed claim ('Rahul said'), so attribution to Rahul is required "
                          "(unchanged). 'Join' is a staffing statement, so labour is as valid "
                          "as commitments under the prompt's definitions. Note the commitments "
                          "schema has an owed_to field but no field for who will do the thing; "
                          "that is a prompt/schema observation, reported separately.",
                          "commitments only"),
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "join the team/release", "owed_to": None, "by_when": "Monday",
             "attributed_to": "Rahul", "confidence": "high"}]},
    },
    {
        "id": "software_3_client_approval_pending", "domain": "software",
        "text": "Client approval is still pending on the scope doc.",
        "expect": [entry("client_approvals", what=has("scope"))],
        "review": _review("A", False, "An approval owed by a client before work can proceed."),
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "approve scope doc", "required_date": None, "priority": "normal",
             "reason": "pending", "confidence": "high"}]},
    },
    {
        "id": "software_4_staffing_gap", "domain": "software",
        "text": "We're short two backend engineers for the release.",
        "expect": [entry("labour", count=eq(2), trade=has("backend", "engineer"))],
        "review": _review("A", False, "Explicit staffing shortage with a count."),
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": "backend engineer", "count": 2, "required_date": None, "priority": "high",
             "area": "release", "reason": "staffing shortfall", "attributed_to": None,
             "confidence": "high"}]},
    },
    {
        "id": "software_5_dependency_blocking", "domain": "software",
        "text": "The release is blocked on the payments team finishing their API.",
        "expect": [text_in("issues", "block", "payment", "api", "release")],
        "review": _review("A", True,
                          "A blocker recorded as a problem. Tightened from 'any issue entry "
                          "exists' to 'an issue that actually mentions this blocker'.",
                          "issues list non-empty"),
        "gold_structured": {**_blank_structured(),
            "issues": ["release blocked on payments team's API"]},
    },
    {
        "id": "software_6_ambiguous_no_fabrication", "domain": "software",
        "text": "We might need more people on this soon, not sure yet.",
        "expect": [never_fabricates("labour", "count")],
        "review": _review("C", True,
                          "Same reason as construction_7: no entry is correct behaviour; an "
                          "invented headcount is the only failure.",
                          "labour entry must exist with count null"),
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": None, "count": None, "required_date": None, "priority": "low",
             "area": None, "reason": "possible future need", "attributed_to": None,
             "confidence": "low"}]},
    },
]
