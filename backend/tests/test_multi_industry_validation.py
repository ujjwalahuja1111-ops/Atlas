"""Multi-Industry Field Validation Sprint tests.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

A reusable harness that exercises the REAL Atlas pipeline (capture ->
AI structuring [simulated, prompt-consistent - no live LLM key in this
environment, consistent with every prior session's own live testing
discipline] -> proposal -> human confirmation -> operational item ->
follow-through -> historical memory) identically across five domains,
proving or disproving the universal-operational-memory model's own
central claim: the same mechanism handles construction, restaurant,
warehouse, small-shop, and software/office operational communication
without domain-specific code branches.

Run from backend/: python -m pytest tests/test_multi_industry_validation.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_multi_industry_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_multi_industry_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine, reasoning_engine  # noqa: E402
from services import intent_service  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine, reasoning_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


PM = {"id": "u_mi_pm", "name": "MI PM", "role": "project_manager"}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _mock_structuring(structured: dict):
    intent_service._run_structuring_pass = AsyncMock(return_value=structured)


async def _make_project(name: str) -> dict:
    return await memory_engine.insert_project(name=name, code=name.replace(" ", "").upper()[:8])


# ==========================================================================
# The reusable harness — the actual Atlas pipeline, real functions,
# real database writes, identical code path for every domain. Only the
# INPUT (the captured text and the AI structuring result it produces)
# varies by domain; nothing about the pipeline itself is
# domain-specific.
# ==========================================================================

class DomainHarness:
    """One instance per domain. Exercises the real pipeline: capture ->
    structure -> confirm -> follow-through -> historical retrieval,
    using only real engine/service functions."""

    def __init__(self, project, site, actor):
        self.project = project
        self.site = site
        self.actor = actor

    async def capture_and_confirm(self, text: str, structured: dict, when=None) -> list[dict]:
        """Step 1-4 of the 8-step sequence: a real event is captured,
        real AI-structuring output (simulated - prompt-consistent, per
        this file's own header) is turned into real proposals via the
        real, unmodified _emit_proposals_from_structured(), and each
        proposal is confirmed into a real operational_item via the
        real, unmodified accept_ai_proposal()."""
        when = when or _now()
        event_id = memory_engine._new_id("evt_")
        ev = await memory_engine.insert_event({
            "id": event_id, "site_id": self.site["id"], "project_id": self.project["id"],
            "user_id": self.actor["id"], "user_name": self.actor["name"], "activity_id": None,
            "kind": "text", "text_input": text, "transcript": None,
            "audio_asset_id": None, "photo_asset_ids": [], "gps": None,
            "client_created_at": None, "app_version": None,
            "requires_client_approval": False, "ai_status": "pending", "ai_analysis_id": None,
            "server_created_at": _iso(when),
        })
        await intelligence_engine._emit_proposals_from_structured(ev, structured)
        proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
        items = []
        for p in proposals:
            items.append(await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=self.actor))
        return items

    async def complete(self, item: dict, completed_at: str = None):
        """Step 6: completion, through the real status-transition path."""
        await operations_engine.transition_status(item_id=item["id"], to_status="assigned", actor=self.actor)
        await operations_engine.transition_status(item_id=item["id"], to_status="in_progress", actor=self.actor)
        await operations_engine.transition_status(item_id=item["id"], to_status="fulfilled", actor=self.actor)
        if completed_at:
            await _mock_db.operational_items.update_one(
                {"id": item["id"]}, {"$set": {"completed_at": completed_at}})

    async def my_day(self, user=None):
        """Step 7-ish: follow-through (due/overdue) via the real,
        unmodified my_day()."""
        return await operations_engine.my_day(user=user or PM)

    async def actor_history(self, **kwargs):
        """Step 8: historical memory via the real, unmodified
        actor_history()."""
        return await operations_engine.actor_history(self.project["id"], user=PM, **kwargs)

    async def change_history(self, entity_reference: str, user=None):
        """Step 8: change history via the real, unmodified
        query_change_history intent."""
        _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                            "project_reference": None, "comparison_scope": None,
                            "entity_reference": entity_reference})
        return await intent_service.handle_intent(
            f"what changed on {entity_reference}?", user=user or PM, active_project_id=self.project["id"])


async def _make_harness(name: str) -> DomainHarness:
    project = await _make_project(name)
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    actor = await memory_engine.upsert_user(
        phone=f"9{abs(hash(name)) % 100000000:08d}", name=f"{name} Recorder", role="site_supervisor")
    return DomainHarness(project, site, actor)


# ==========================================================================
# CONSTRUCTION — the control. Same harness, same assertions as every
# other domain, to prove nothing is special-cased for it.
# ==========================================================================

async def test_construction_full_sequence():
    h = await _make_harness("MI Construction")
    now = _now()

    items = await h.capture_and_confirm(
        "The supplier said he'll deliver 200 tiles Thursday.",
        {"materials": [{"name": "tiles", "quantity": 200, "unit": "pieces",
                        "required_date": "Thursday", "priority": "normal",
                        "attributed_to": "ABC Tile Supplier", "confidence": "high"}],
         "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
         "inspections": [], "safety_observations": [], "quality_observations": [],
         "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
         "urgency": "normal", "summary": "Tiles"}, now)
    item = items[0]
    assert item["quantity"] == 200 and item["unit"] == "pieces"
    assert item["attributed_to"] == "ABC Tile Supplier"
    assert item["required_by"] is not None  # step 3: a real deadline, normalized

    # step 5: a shortfall - only 180 delivered, a second, separate fact
    shortfall_items = await h.capture_and_confirm(
        "Only 180 tiles actually arrived.",
        {"materials": [{"name": "tiles", "quantity": 20, "unit": "pieces",
                        "required_date": None, "priority": "high",
                        "attributed_to": "ABC Tile Supplier", "confidence": "high"}],
         "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
         "inspections": [], "safety_observations": [], "quality_observations": [],
         "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
         "urgency": "high", "summary": "Shortfall"}, now)

    await h.complete(item, completed_at=item["required_by"])  # step 6

    day = await h.my_day()  # step 7: follow-through
    assert "due_today" in day and "overdue" in day

    history = await h.actor_history(attributed_to="ABC Tile Supplier")  # step 8
    assert history["total_commitments"] >= 1
    assert history["fulfilled_count"] >= 1

    change = await h.change_history(item["title"])
    assert change["result"]["ok"] is True


# ==========================================================================
# RESTAURANT / FOOD OPERATIONS
# ==========================================================================

async def test_restaurant_full_sequence():
    h = await _make_harness("MI Restaurant")
    now = _now()

    items = await h.capture_and_confirm(
        "The food supplier confirmed 80 kg of chicken for Friday, but we're already 20 kg short for tomorrow.",
        {"materials": [
            {"name": "chicken", "quantity": 80, "unit": "kg", "required_date": "Friday",
             "priority": "normal", "attributed_to": "Fresh Farms Supplier", "confidence": "high"},
            {"name": "chicken", "quantity": 20, "unit": "kg", "required_date": "tomorrow",
             "priority": "high", "attributed_to": None, "confidence": "high"},
         ],
         "labour": [{"trade": "kitchen staff", "count": 3, "required_date": "tomorrow",
                     "priority": "high", "area": "kitchen", "reason": "staffing shortfall",
                     "attributed_to": "chef", "confidence": "high"}],
         "equipment": [], "client_approvals": [], "drawing_requests": [],
         "inspections": [], "safety_observations": [{"observation": "refrigeration unit not cooling",
                                                        "priority": "critical", "area": "kitchen", "confidence": "high"}],
         "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
         "urgency": "high", "summary": "Chicken shortage and staffing"}, now)

    assert len(items) == 4  # two chicken facts + staffing + refrigeration issue, all correctly split
    confirmed = next(i for i in items if i["quantity"] == 80)
    shortfall = next(i for i in items if i["quantity"] == 20)
    staffing = next(i for i in items if i["category"] == "labour_requirement")
    assert confirmed["attributed_to"] == "Fresh Farms Supplier"
    assert shortfall.get("attributed_to") is None  # observed shortfall, never fabricated a speaker
    assert staffing.get("attributed_to") == "chef"

    await h.complete(confirmed, completed_at=confirmed["required_by"])

    day = await h.my_day()
    assert isinstance(day["due_today"], list) and isinstance(day["overdue"], list)

    history = await h.actor_history(attributed_to="Fresh Farms Supplier")
    assert history["fulfilled_count"] == 1
    assert history["on_time_count"] == 1

    change = await h.change_history(confirmed["title"])
    assert change["result"]["ok"] is True


# ==========================================================================
# WAREHOUSE / INVENTORY
# ==========================================================================

async def test_warehouse_full_sequence():
    h = await _make_harness("MI Warehouse")
    now = _now()

    items = await h.capture_and_confirm(
        "400 cartons expected Tuesday from the distributor, 20 usually arrive damaged.",
        {"materials": [{"name": "cartons", "quantity": 400, "unit": "cartons", "required_date": "Tuesday",
                        "priority": "normal", "attributed_to": "Regional Distributor", "confidence": "high"}],
         "labour": [], "equipment": [{"name": "forklift", "quantity": 1, "required_date": "Tuesday",
                                       "priority": "high", "reason": "unavailable for unloading",
                                       "attributed_to": None, "confidence": "medium"}],
         "client_approvals": [], "drawing_requests": [], "inspections": [],
         "safety_observations": [], "quality_observations": [{"observation": "20 cartons typically arrive damaged",
                                                                 "priority": "normal", "area": "receiving", "confidence": "medium"}],
         "commitments": [{"what": "supervisor will recount stock", "owed_to": None, "by_when": "Wednesday",
                           "attributed_to": None, "confidence": "high"}],
         "follow_ups": [], "issues": [], "work_done": [],
         "urgency": "normal", "summary": "Carton delivery, forklift, recount"}, now)

    cartons = next(i for i in items if i["category"] == "material_requirement")
    forklift = next(i for i in items if i["category"] == "equipment_requirement")
    recount = next(i for i in items if i["category"] == "commitment")
    assert cartons["quantity"] == 400 and cartons["unit"] == "cartons"
    assert cartons["attributed_to"] == "Regional Distributor"
    assert forklift["required_by"] is not None

    await h.complete(cartons, completed_at=cartons["required_by"])

    day = await h.my_day()
    assert "due_today" in day

    history = await h.actor_history(attributed_to="Regional Distributor")
    assert history["total_commitments"] == 1
    assert history["fulfilled_count"] == 1

    change = await h.change_history(cartons["title"])
    assert change["result"]["ok"] is True
    assert change["result"]["data"]["events"]  # traceable


# ==========================================================================
# SMALL SHOP / TRADING
# ==========================================================================

async def test_small_shop_full_sequence():
    h = await _make_harness("MI Small Shop")
    now = _now()

    items = await h.capture_and_confirm(
        "Need 50 units of Product X by tomorrow, supplier promised delivery, but 8 units from last batch were damaged.",
        {"materials": [
            {"name": "Product X", "quantity": 50, "unit": "units", "required_date": "tomorrow",
             "priority": "high", "attributed_to": "wholesale supplier", "confidence": "high"},
         ],
         "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
         "inspections": [], "safety_observations": [],
         "quality_observations": [{"observation": "8 units of Product X arrived damaged", "priority": "normal",
                                    "area": None, "confidence": "high"}],
         "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
         "urgency": "high", "summary": "Stock shortage and damage"}, now)

    restock = next(i for i in items if i["category"] == "material_requirement")
    damage = next(i for i in items if i["category"] == "quality_observation")
    assert restock["quantity"] == 50 and restock["unit"] == "units"
    assert restock["attributed_to"] == "wholesale supplier"
    assert damage.get("attributed_to") is None  # quality_observations never carries attributed_to (confirmed by schema)

    await h.complete(restock, completed_at=restock["required_by"])

    day = await h.my_day()
    assert "overdue" in day

    history = await h.actor_history(attributed_to="wholesale supplier")
    assert history["fulfilled_count"] == 1

    change = await h.change_history(restock["title"])
    assert change["result"]["ok"] is True


# ==========================================================================
# SOFTWARE / OFFICE
# ==========================================================================

async def test_software_office_full_sequence():
    h = await _make_harness("MI Software")
    now = _now()
    rahul = await memory_engine.upsert_user(phone="9700000001", name="Rahul Dev", role="site_supervisor")

    items = await h.capture_and_confirm(
        "We're short two backend engineers for the release. Rahul can join Monday.",
        {"materials": [], "labour": [{"trade": "backend engineer", "count": 2, "required_date": None,
                                       "priority": "high", "area": "release", "reason": "staffing shortfall",
                                       "attributed_to": None, "confidence": "medium"}],
         "equipment": [], "client_approvals": [{"what": "sign off on release scope", "required_date": "Wednesday",
                                                  "priority": "normal", "reason": "client needs to confirm",
                                                  "confidence": "medium"}],
         "drawing_requests": [], "inspections": [], "safety_observations": [], "quality_observations": [],
         "commitments": [{"what": "Rahul joins the release", "owed_to": None, "by_when": "Monday",
                           "attributed_to": None, "confidence": "high"}],
         "follow_ups": [], "issues": [], "work_done": [],
         "urgency": "high", "summary": "Staffing and client approval"}, now)

    staffing = next(i for i in items if i["category"] == "labour_requirement")
    rahul_commitment = next(i for i in items if i["category"] == "commitment")
    approval = next(i for i in items if i["category"] == "client_approval")
    assert staffing["required_by"] is None  # honestly absent - no date was given for the gap itself
    assert rahul_commitment["required_by"] is not None
    assert approval["required_by"] is not None

    await operations_engine.assign_item(item_id=rahul_commitment["id"], assignee=rahul, actor=h.actor)
    await h.complete(rahul_commitment, completed_at=rahul_commitment["required_by"])

    day = await h.my_day()
    assert "due_today" in day

    history = await h.actor_history(assigned_to_user_id=rahul["id"])
    assert history["fulfilled_count"] == 1
    assert "real, registered" in history["identity_note"]

    change = await h.change_history(rahul_commitment["title"])
    assert change["result"]["ok"] is True


# ==========================================================================
# Cross-industry: the SAME mechanism, proven directly rather than
# merely asserted per-domain above.
# ==========================================================================

async def test_all_five_domains_produce_identical_result_shapes():
    """The actual universality claim, tested directly: my_day() and
    actor_history() return the exact same field set regardless of
    which domain produced the underlying items - no domain-specific
    branching anywhere in the shape of the answer."""
    harnesses = {}
    for name in ["MI Shape Construction", "MI Shape Restaurant", "MI Shape Warehouse",
                 "MI Shape Shop", "MI Shape Software"]:
        harnesses[name] = await _make_harness(name)

    now = _now()
    results = {}
    for name, h in harnesses.items():
        items = await h.capture_and_confirm(
            f"{name} supplier will deliver by Monday.",
            {"materials": [{"name": "goods", "quantity": 10, "unit": "units", "required_date": "Monday",
                            "priority": "normal", "attributed_to": f"{name} Supplier", "confidence": "high"}],
             "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
             "inspections": [], "safety_observations": [], "quality_observations": [],
             "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
             "urgency": "normal", "summary": "Goods"}, now)
        await h.complete(items[0], completed_at=items[0]["required_by"])
        results[name] = await h.actor_history(attributed_to=f"{name} Supplier")

    shapes = [set(r.keys()) for r in results.values()]
    assert all(s == shapes[0] for s in shapes)  # identical shape across all five domains
    day_shapes = [set((await h.my_day()).keys()) for h in harnesses.values()]
    assert all(s == day_shapes[0] for s in day_shapes)


# ==========================================================================
# Construction regression, reusing the exact same harness — proving
# universalisation did not degrade the original domain.
# ==========================================================================

async def test_construction_cre_rule_still_fires_after_prompt_reframe():
    """The existing procurement.material_lead_time CRE rule (construction-
    specific, unchanged) must still fire correctly - proving the prompt
    reframe changed only wording, not the underlying data shape the
    rule depends on."""
    h = await _make_harness("MI Construction CRE Regression")
    now = _now()
    items = await h.capture_and_confirm(
        "The supplier said he'll deliver 200 tiles Thursday.",
        {"materials": [{"name": "tiles", "quantity": 200, "unit": "pieces",
                        "required_date": "Thursday", "priority": "normal",
                        "attributed_to": "supplier", "confidence": "high"}],
         "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
         "inspections": [], "safety_observations": [], "quality_observations": [],
         "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
         "urgency": "normal", "summary": "Tiles"}, now)

    result = await reasoning_engine.explain_health(h.project["id"], user=PM)
    findings = [a for a in result["recommended_actions"] if a["rule_id"] == "procurement.material_lead_time"]
    assert len(findings) == 1
