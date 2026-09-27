"""Golden multi-industry natural-language corpus + fact-level evaluator.

Multi-Industry Validation Follow-up — Natural-Language Structuring Proof.

This module defines WHAT must be extracted, not HOW. It is shared by:
  - tests/test_golden_corpus_pipeline.py (Layer A: deterministic,
    credential-free — proves the downstream pipeline preserves facts
    once correctly structured; runs in normal CI).
  - scripts/live_llm_structuring_eval.py (Layer B: calls the actual
    _structure() function against a live LLM when credentials are
    available; NOT part of normal CI, never claimed to have "passed"
    unless genuinely executed).

Each corpus case is natural, sometimes messy operational language —
not clean specification syntax — with an `expect` list of fact-level
checks. A check only asserts what MUST be true; anything not checked
is intentionally left unconstrained (per this sprint's own explicit
"do not require irrelevant fields to match" instruction).

Evaluation is against the STRUCTURED JSON SHAPE (the dict
EVENT_SYSTEM_PROMPT asks a model to return — the same shape
_emit_proposals_from_structured() consumes) — for Layer A this is a
hand-built, deliberately-correct example of that shape (standing in
for what a competent structuring pass should produce); for Layer B it
is the real model's own actual output.
"""
from __future__ import annotations
from typing import Optional


LIST_KEYS = (
    "materials", "labour", "equipment", "client_approvals", "drawing_requests",
    "inspections", "safety_observations", "quality_observations",
    "commitments", "follow_ups",
)


def _entries_for(structured: dict, list_key: str) -> list[dict]:
    return structured.get(list_key) or []


def _matches(entry: dict, constraints: dict) -> bool:
    for field, check in constraints.items():
        value = entry.get(field)
        if "equals" in check:
            if value != check["equals"]:
                return False
        if "contains_any" in check:
            if value is None:
                return False
            lowered = str(value).lower()
            if not any(term.lower() in lowered for term in check["contains_any"]):
                return False
        if "is_null" in check:
            if check["is_null"] and value is not None:
                return False
            if not check["is_null"] and value is None:
                return False
    return True


def evaluate_case(structured: dict, expect: list[dict]) -> dict:
    """Checks each expected fact against `structured` (the raw
    AI-structuring JSON shape). Returns {"passed": bool, "results":
    [...]} — one result per expectation, each either matched or not,
    with enough detail to see exactly which fact failed and why."""
    results = []
    for exp in expect:
        list_key = exp["list"]
        if exp.get("__free_text__"):
            entries = _entries_for(structured, list_key)
            matched = len(entries) > 0
            results.append({"list": list_key, "constraints": "non-empty free text",
                             "note": exp.get("note"), "matched": matched,
                             "candidates_checked": len(entries)})
            continue
        constraints = {k: v for k, v in exp.items() if k not in ("list", "note", "__free_text__")}
        entries = _entries_for(structured, list_key)
        match = next((e for e in entries if _matches(e, constraints)), None)
        results.append({
            "list": list_key, "constraints": constraints, "note": exp.get("note"),
            "matched": match is not None, "candidates_checked": len(entries),
        })
    passed = all(r["matched"] for r in results)
    return {"passed": passed, "results": results}


# ==========================================================================
# THE CORPUS — natural, messy language. 6-7 cases per domain.
# Field names in each expectation use the exact EVENT_SYSTEM_PROMPT
# JSON keys (quantity, unit, required_date, attributed_to, etc.).
# ==========================================================================

def _blank_structured() -> dict:
    """A structuring result with every key present and empty — the
    baseline every gold example starts from, matching EVENT_SYSTEM_
    PROMPT's own exact key set."""
    return {
        "type": "general", "title": "", "summary": "",
        "materials": [], "labour": [], "equipment": [], "client_approvals": [],
        "drawing_requests": [], "inspections": [], "safety_observations": [],
        "quality_observations": [], "commitments": [], "follow_ups": [],
        "issues": [], "work_done": [], "urgency": "normal", "language_detected": "en",
    }


CORPUS: list[dict] = [
    # ---------------- A. CONSTRUCTION ----------------
    {
        "id": "construction_1_supplier_delivery",
        "domain": "construction",
        "text": "Supplier says he'll send 200 tiles by Thursday, probably.",
        "expect": [
            {"list": "materials", "quantity": {"equals": 200}, "unit": {"contains_any": ["tile"]},
             "required_date": {"contains_any": ["thursday"]},
             "attributed_to": {"contains_any": ["supplier"]}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "tiles", "quantity": 200, "unit": "tiles", "required_date": "Thursday",
             "priority": "normal", "attributed_to": "supplier", "confidence": "high"}]},
    },
    {
        "id": "construction_2_labour_shortfall_hinglish",
        "domain": "construction",
        "text": "Abhi sirf 3 mistry aaye hain site pe, kaam slow chal raha hai.",
        "expect": [
            {"list": "labour", "count": {"equals": 3}},
        ],
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": "mason", "count": 3, "required_date": None, "priority": "normal",
             "area": None, "reason": "short-staffed", "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "construction_3_client_approval_pending",
        "domain": "construction",
        "text": "Drawing approval abhi tak pending hai client se, kaam ruka hua hai.",
        "expect": [
            {"list": "client_approvals", "what": {"contains_any": ["drawing", "approval"]}},
        ],
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "drawing approval", "required_date": None, "priority": "high",
             "reason": "work blocked", "confidence": "high"}]},
    },
    {
        "id": "construction_4_contractor_commitment",
        "domain": "construction",
        "text": "Contractor ne kaha woh kal tak plumbing finish kar dega.",
        "expect": [
            {"list": "commitments", "by_when": {"contains_any": ["tomorrow", "kal"]},
             "attributed_to": {"contains_any": ["contractor"]}},
        ],
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "finish plumbing", "owed_to": None, "by_when": "tomorrow",
             "attributed_to": "contractor", "confidence": "high"}]},
    },
    {
        "id": "construction_5_site_safety_issue",
        "domain": "construction",
        "text": "Site pe ek mazdoor gir gaya, mamooli chot aayi, first aid de diya.",
        "expect": [
            {"list": "safety_observations", "observation": {"contains_any": ["fell", "fall", "gir", "injur", "chot"]}},
        ],
        "gold_structured": {**_blank_structured(), "safety_observations": [
            {"observation": "worker fell, minor injury, first aid given", "priority": "high",
             "area": "site", "confidence": "high"}]},
    },
    {
        "id": "construction_6_urgent_material_today",
        "domain": "construction",
        "text": "We need 50 bags of cement today, it's urgent, work will stop otherwise.",
        "expect": [
            {"list": "materials", "quantity": {"equals": 50}, "unit": {"contains_any": ["bag"]},
             "required_date": {"contains_any": ["today"]}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "cement", "quantity": 50, "unit": "bags", "required_date": "today",
             "priority": "critical", "attributed_to": None, "confidence": "high"}], "urgency": "high"},
    },
    {
        "id": "construction_7_ambiguous_no_fabrication",
        "domain": "construction",
        "text": "Someone mentioned we might be short on materials soon, not sure what exactly.",
        "expect": [
            # No quantity should ever be fabricated for a vague mention.
            {"list": "materials", "quantity": {"is_null": True}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "unspecified material", "quantity": None, "unit": None, "required_date": None,
             "priority": "low", "attributed_to": None, "confidence": "low"}]},
    },

    # ---------------- B. RESTAURANT / FOOD ----------------
    {
        "id": "restaurant_1_confirmed_and_shortfall",
        "domain": "restaurant",
        "text": "The food supplier confirmed 80 kg chicken for Friday but we're already 20 kg short for tomorrow.",
        "expect": [
            {"list": "materials", "quantity": {"equals": 80}, "unit": {"contains_any": ["kg"]},
             "required_date": {"contains_any": ["friday"]}, "attributed_to": {"contains_any": ["supplier"]}},
            {"list": "materials", "quantity": {"equals": 20}, "unit": {"contains_any": ["kg"]},
             "required_date": {"contains_any": ["tomorrow"]}, "attributed_to": {"is_null": True}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "chicken", "quantity": 80, "unit": "kg", "required_date": "Friday",
             "priority": "normal", "attributed_to": "food supplier", "confidence": "high"},
            {"name": "chicken", "quantity": 20, "unit": "kg", "required_date": "tomorrow",
             "priority": "high", "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "restaurant_2_staffing_shortfall",
        "domain": "restaurant",
        "text": "Chef says we're 3 staff short tomorrow for the weekend rush.",
        "expect": [
            {"list": "labour", "count": {"equals": 3}, "required_date": {"contains_any": ["tomorrow"]},
             "attributed_to": {"contains_any": ["chef"]}},
        ],
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": "kitchen staff", "count": 3, "required_date": "tomorrow", "priority": "high",
             "area": "kitchen", "reason": "weekend rush", "attributed_to": "chef", "confidence": "high"}]},
    },
    {
        "id": "restaurant_3_refrigeration_issue",
        "domain": "restaurant",
        "text": "Freezer stopped cooling again, need someone to look at it ASAP.",
        "expect": [
            {"list": "safety_observations", "observation": {"contains_any": ["freezer", "cooling", "refrigerat"]}},
        ],
        "gold_structured": {**_blank_structured(), "safety_observations": [
            {"observation": "freezer not cooling", "priority": "critical", "area": "kitchen", "confidence": "high"}]},
    },
    {
        "id": "restaurant_4_vegetable_supplier_promise",
        "domain": "restaurant",
        "text": "Vegetable supplier promised delivery by 7 AM tomorrow.",
        "expect": [
            {"list": "materials", "required_date": {"contains_any": ["tomorrow"]},
             "attributed_to": {"contains_any": ["supplier"]}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "vegetables", "quantity": None, "unit": None, "required_date": "tomorrow",
             "priority": "normal", "attributed_to": "vegetable supplier", "confidence": "high"}]},
    },
    {
        "id": "restaurant_5_owner_approval_pending",
        "domain": "restaurant",
        "text": "Manager is waiting for the owner's sign-off on the new menu pricing.",
        "expect": [
            {"list": "client_approvals", "what": {"contains_any": ["menu", "pricing", "sign-off", "sign off"]}},
        ],
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "sign-off on new menu pricing", "required_date": None, "priority": "normal",
             "reason": "awaiting owner", "confidence": "high"}]},
    },
    {
        "id": "restaurant_6_observed_shortfall_no_attribution",
        "domain": "restaurant",
        "text": "Only 60 kg of the chicken order actually arrived.",
        "expect": [
            {"list": "materials", "quantity": {"equals": 60}, "attributed_to": {"is_null": True}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "chicken", "quantity": 60, "unit": "kg", "required_date": None,
             "priority": "normal", "attributed_to": None, "confidence": "high"}]},
    },

    # ---------------- C. WAREHOUSE / INVENTORY ----------------
    {
        "id": "warehouse_1_cartons_expected",
        "domain": "warehouse",
        "text": "400 cartons expected Tuesday from the distributor.",
        "expect": [
            {"list": "materials", "quantity": {"equals": 400}, "unit": {"contains_any": ["carton"]},
             "required_date": {"contains_any": ["tuesday"]}, "attributed_to": {"contains_any": ["distributor"]}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "cartons", "quantity": 400, "unit": "cartons", "required_date": "Tuesday",
             "priority": "normal", "attributed_to": "distributor", "confidence": "high"}]},
    },
    {
        "id": "warehouse_2_shortfall_received",
        "domain": "warehouse",
        "text": "Only 380 received today, 20 short from what was ordered.",
        "expect": [
            {"list": "materials", "quantity": {"equals": 380}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "goods received", "quantity": 380, "unit": "cartons", "required_date": None,
             "priority": "normal", "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "warehouse_3_forklift_and_commitment",
        "domain": "warehouse",
        "text": "Forklift is down again, maintenance guy said he'd come today.",
        "expect": [
            {"list": "equipment", "name": {"contains_any": ["forklift"]}},
            {"list": "commitments", "by_when": {"contains_any": ["today"]}},
        ],
        "gold_structured": {**_blank_structured(),
            "equipment": [{"name": "forklift", "quantity": 1, "required_date": None, "priority": "high",
                            "reason": "down again", "attributed_to": None, "confidence": "high"}],
            "commitments": [{"what": "repair forklift", "owed_to": None, "by_when": "today",
                              "attributed_to": "maintenance", "confidence": "high"}]},
    },
    {
        "id": "warehouse_4_dispatch_delay_issue",
        "domain": "warehouse",
        "text": "Dispatch got delayed because of the rain, trucks couldn't load.",
        "expect": [
            {"list": "issues", "__free_text__": True},
        ],
        "gold_structured": {**_blank_structured(), "issues": ["dispatch delayed due to rain, trucks could not load"]},
    },
    {
        "id": "warehouse_5_supervisor_recount_commitment",
        "domain": "warehouse",
        "text": "Supervisor committed to recounting the stock by Wednesday.",
        "expect": [
            {"list": "commitments", "by_when": {"contains_any": ["wednesday"]}},
        ],
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "recount stock", "owed_to": None, "by_when": "Wednesday",
             "attributed_to": "supervisor", "confidence": "high"}]},
    },
    {
        "id": "warehouse_6_damaged_cartons",
        "domain": "warehouse",
        "text": "20 cartons came in damaged this time, more than usual.",
        "expect": [
            {"list": "quality_observations", "observation": {"contains_any": ["damag"]}},
        ],
        "gold_structured": {**_blank_structured(), "quality_observations": [
            {"observation": "20 cartons damaged on arrival", "priority": "normal", "area": "receiving",
             "confidence": "high"}]},
    },

    # ---------------- D. SMALL SHOP / TRADING ----------------
    {
        "id": "shop_1_restock_promised",
        "domain": "shop",
        "text": "Need 50 units of Product X by tomorrow, supplier promised delivery.",
        "expect": [
            {"list": "materials", "quantity": {"equals": 50}, "unit": {"contains_any": ["unit"]},
             "required_date": {"contains_any": ["tomorrow"]}, "attributed_to": {"contains_any": ["supplier"]}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "Product X", "quantity": 50, "unit": "units", "required_date": "tomorrow",
             "priority": "high", "attributed_to": "supplier", "confidence": "high"}]},
    },
    {
        "id": "shop_2_damaged_units",
        "domain": "shop",
        "text": "8 units came in damaged from the last batch.",
        "expect": [
            {"list": "quality_observations", "observation": {"contains_any": ["8", "damag"]}},
        ],
        "gold_structured": {**_blank_structured(), "quality_observations": [
            {"observation": "8 units damaged from last batch", "priority": "normal", "area": None,
             "confidence": "high"}]},
    },
    {
        "id": "shop_3_customer_order_pending",
        "domain": "shop",
        "text": "Customer order is still pending, we're waiting on stock to come in.",
        "expect": [
            {"list": "follow_ups", "what": {"contains_any": ["stock", "order"]}},
        ],
        "gold_structured": {**_blank_structured(), "follow_ups": [
            {"what": "customer order pending stock arrival", "when": None, "confidence": "medium"}]},
    },
    {
        "id": "shop_4_owner_approval_dependency",
        "domain": "shop",
        "text": "Owner needs to approve the new supplier before we place the order.",
        "expect": [
            {"list": "client_approvals", "what": {"contains_any": ["supplier", "approve"]}},
        ],
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "approve new supplier", "required_date": None, "priority": "normal",
             "reason": "blocking order", "confidence": "high"}]},
    },
    {
        "id": "shop_5_hinglish_supplier_promise",
        "domain": "shop",
        "text": "Supplier bola kal tak maal bhej dega.",
        "expect": [
            {"list": "commitments", "by_when": {"contains_any": ["tomorrow", "kal"]},
             "attributed_to": {"contains_any": ["supplier"]}},
        ],
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "send goods", "owed_to": None, "by_when": "tomorrow",
             "attributed_to": "supplier", "confidence": "high"}]},
    },
    {
        "id": "shop_6_ambiguous_no_fabrication",
        "domain": "shop",
        "text": "We keep running short on Product Y sometimes, not always though.",
        "expect": [
            {"list": "materials", "quantity": {"is_null": True}},
        ],
        "gold_structured": {**_blank_structured(), "materials": [
            {"name": "Product Y", "quantity": None, "unit": None, "required_date": None,
             "priority": "low", "attributed_to": None, "confidence": "low"}]},
    },

    # ---------------- E. SOFTWARE / OFFICE ----------------
    {
        "id": "software_1_own_plan_not_attributed",
        "domain": "software",
        "text": "I'll finish the API by Monday.",
        "expect": [
            {"list": "commitments", "by_when": {"contains_any": ["monday"]}, "attributed_to": {"is_null": True}},
        ],
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "finish the API", "owed_to": None, "by_when": "Monday",
             "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "software_2_relayed_claim_attributed",
        "domain": "software",
        "text": "Rahul said he can join Monday.",
        "expect": [
            {"list": "commitments", "by_when": {"contains_any": ["monday"]},
             "attributed_to": {"contains_any": ["rahul"]}},
        ],
        "gold_structured": {**_blank_structured(), "commitments": [
            {"what": "join the team/release", "owed_to": None, "by_when": "Monday",
             "attributed_to": "Rahul", "confidence": "high"}]},
    },
    {
        "id": "software_3_client_approval_pending",
        "domain": "software",
        "text": "Client approval is still pending on the scope doc.",
        "expect": [
            {"list": "client_approvals", "what": {"contains_any": ["scope"]}},
        ],
        "gold_structured": {**_blank_structured(), "client_approvals": [
            {"what": "approve scope doc", "required_date": None, "priority": "normal",
             "reason": "pending", "confidence": "high"}]},
    },
    {
        "id": "software_4_staffing_gap",
        "domain": "software",
        "text": "We're short two backend engineers for the release.",
        "expect": [
            {"list": "labour", "count": {"equals": 2}, "trade": {"contains_any": ["backend", "engineer"]}},
        ],
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": "backend engineer", "count": 2, "required_date": None, "priority": "high",
             "area": "release", "reason": "staffing shortfall", "attributed_to": None, "confidence": "high"}]},
    },
    {
        "id": "software_5_dependency_blocking",
        "domain": "software",
        "text": "The release is blocked on the payments team finishing their API.",
        "expect": [
            {"list": "issues", "__free_text__": True},
        ],
        "gold_structured": {**_blank_structured(), "issues": ["release blocked on payments team's API"]},
    },
    {
        "id": "software_6_ambiguous_no_fabrication",
        "domain": "software",
        "text": "We might need more people on this soon, not sure yet.",
        "expect": [
            {"list": "labour", "count": {"is_null": True}},
        ],
        "gold_structured": {**_blank_structured(), "labour": [
            {"trade": None, "count": None, "required_date": None, "priority": "low",
             "area": None, "reason": "possible future need", "attributed_to": None, "confidence": "low"}]},
    },
]
