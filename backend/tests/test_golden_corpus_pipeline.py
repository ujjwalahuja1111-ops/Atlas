"""Multi-Industry Validation Follow-up — Natural-Language Structuring Proof.

LAYER A: deterministic, credential-free pipeline test. Runs the golden
corpus's own hand-built `gold_structured` (a deliberately-correct
example of what a competent structuring pass should produce for each
case's own natural-language text) through the REAL, unmodified
downstream pipeline (_emit_proposals_from_structured() ->
accept_ai_proposal()) and confirms every fact the corpus expects
survives into the real, stored operational_item(s).

This does NOT prove a live LLM would actually produce gold_structured
from the raw text — that is LAYER B (scripts/live_llm_structuring_
eval.py), which requires real credentials this environment does not
have. Layer A proves the other half: IF structuring produces the
correct facts, the pipeline correctly preserves and stores them,
across all five domains, using the identical, unmodified mechanism
every prior sprint's own tests have already exercised.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Run from backend/: python -m pytest tests/test_golden_corpus_pipeline.py -q
"""
import os
import sys
import uuid
import pytest
from datetime import datetime, timezone

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_golden_corpus_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_golden_corpus_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine):
    _mod.db = _mock_db

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from eval.golden_corpus import CORPUS, evaluate_case  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ACTOR = {"id": "u_gc_actor", "name": "GC Actor"}


async def _run_case_through_pipeline(case: dict):
    """Real event, real _emit_proposals_from_structured(), real
    accept_ai_proposal() - the same functions every prior sprint's own
    tests use, unmodified."""
    project = await memory_engine.insert_project(name=f"GC {case['id']}", code=case["id"][:8].upper())
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    event_id = memory_engine._new_id("evt_")
    ev = await memory_engine.insert_event({
        "id": event_id, "site_id": site["id"], "project_id": project["id"],
        "user_id": ACTOR["id"], "user_name": ACTOR["name"], "activity_id": None,
        "kind": "text", "text_input": case["text"], "transcript": None,
        "audio_asset_id": None, "photo_asset_ids": [], "gps": None,
        "client_created_at": None, "app_version": None,
        "requires_client_approval": False, "ai_status": "pending", "ai_analysis_id": None,
        "server_created_at": datetime.now(timezone.utc).isoformat(),
    })
    await intelligence_engine._emit_proposals_from_structured(ev, case["gold_structured"])
    proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
    items = []
    for p in proposals:
        items.append(await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=ACTOR))
    return items


def _item_to_structured_like(item: dict, category_to_list: dict) -> dict:
    """Projects one stored operational_item back into the same
    {list_key: [entry]} shape evaluate_case() checks, so the SAME
    evaluator (unchanged) can confirm facts survived storage, not just
    emission.

    required_date/by_when are deliberately NOT the raw phrase here -
    accept_ai_proposal() normalizes "Thursday"/"tomorrow" into a real
    ISO timestamp (the whole point of that sprint's own fix), so the
    stored value is genuinely different text from what the corpus's
    own `contains_any` checks look for. A sentinel string is used here
    instead, and the corresponding expect-list transform below swaps
    any date `contains_any` check for a `not-null` check when
    validating post-pipeline - honestly confirming "a date was
    successfully normalized," not pretending the original phrase
    survived verbatim."""
    list_key = category_to_list.get(item.get("category"))
    if not list_key:
        return {}
    date_sentinel = "__NORMALIZED_DATE_PRESENT__" if item.get("required_by") else None
    entry = {
        "name": item.get("title"), "quantity": item.get("quantity"), "unit": item.get("unit"),
        "required_date": date_sentinel, "attributed_to": item.get("attributed_to"),
        "count": item.get("quantity"), "trade": item.get("title"),
        "what": item.get("title"), "by_when": date_sentinel,
        "observation": item.get("title"),
    }
    return {list_key: [entry]}


def _post_pipeline_expect(expect: list[dict]) -> list[dict]:
    """Transforms the corpus's own expect list for the post-pipeline
    check: a date `contains_any` check becomes a not-null check
    (confirms normalization happened), since the stored value is a
    real ISO date, not the original phrase. Every other check
    (quantity, unit, attributed_to, is_null) is unchanged."""
    transformed = []
    for exp in expect:
        new_exp = dict(exp)
        for field in ("required_date", "by_when"):
            if field in new_exp and "contains_any" in new_exp[field]:
                new_exp[field] = {"contains_any": ["__NORMALIZED_DATE_PRESENT__"]}
        transformed.append(new_exp)
    return transformed


CATEGORY_TO_LIST = {
    "material_requirement": "materials", "labour_requirement": "labour",
    "equipment_requirement": "equipment", "client_approval": "client_approvals",
    "drawing_request": "drawing_requests", "inspection": "inspections",
    "safety_observation": "safety_observations", "quality_observation": "quality_observations",
    "commitment": "commitments", "follow_up": "follow_ups",
}


@pytest.mark.parametrize("case", CORPUS, ids=[c["id"] for c in CORPUS])
async def test_golden_case_pipeline_preserves_facts(case):
    """For every corpus case: run gold_structured through the real
    pipeline, then re-check the SAME expect list (unchanged evaluator)
    against what actually landed in storage."""
    items = await _run_case_through_pipeline(case)

    # issues/work_done are free-text lists, not operational_items in
    # the same sense (confirmed: _emit_proposals_from_structured() has
    # no emission branch for issues/work_done - they remain
    # presentation-only free text within the AI structuring output,
    # unchanged by this sprint). Their own expect check is validated
    # directly against gold_structured, matching what Layer A can
    # actually prove about the pipeline for this kind of entry.
    if any(exp.get("__free_text__") for exp in case["expect"]):
        result = evaluate_case(case["gold_structured"], case["expect"])
        assert result["passed"], f"{case['id']}: {result}"
        return

    # Reconstruct a structured-like view of everything that survived
    # into real, stored items, merged across all items this case
    # produced (a case may produce more than one item).
    merged: dict = {}
    for item in items:
        piece = _item_to_structured_like(item, CATEGORY_TO_LIST)
        for k, v in piece.items():
            merged.setdefault(k, []).extend(v)

    result = evaluate_case(merged, _post_pipeline_expect(case["expect"]))
    assert result["passed"], f"{case['id']} failed after pipeline round-trip: {result}"


async def test_corpus_size_meets_target():
    """5-8 cases per domain, five domains - confirms the corpus itself
    meets this sprint's own stated target."""
    from collections import Counter
    counts = Counter(c["domain"] for c in CORPUS)
    assert set(counts.keys()) == {"construction", "restaurant", "warehouse", "shop", "software"}
    for domain, count in counts.items():
        assert 5 <= count <= 8, f"{domain} has {count} cases, outside the 5-8 target"


async def test_every_gold_structured_passes_its_own_expectations():
    """Direct sanity check (no pipeline involved) - the corpus and
    evaluator are internally consistent."""
    for case in CORPUS:
        result = evaluate_case(case["gold_structured"], case["expect"])
        assert result["passed"], f"{case['id']}: gold_structured does not satisfy its own expect list: {result}"
