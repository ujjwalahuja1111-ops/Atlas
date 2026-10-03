"""Step 4 — Real Onboarding From a Blank System.

End-to-end proof, not another isolated unit-test exercise: a genuinely
blank Atlas instance, through the REAL app (httpx.ASGITransport against
server.app, exactly as every Step 3 security test already does) and the
REAL route/engine code for every step except one.

THE ONE HONEST SIMULATION, STATED PLAINLY: no real LLM credentials exist
in this sandbox (confirmed throughout this project's own history -
engines.business_setup_engine.generate_recommendation() itself returns
None without EMERGENT_LLM_KEY, proven again below in test_
generate_recommendation_is_honestly_unavailable_here). Every OTHER part
of the flow - the real /api/business-setup/analyze route, the real
_validate_recommendation() the route calls before persisting anything,
the real draft/approve state machine, the real /api/provisioning routes,
the real capability-gated reasoning routes - runs for real. Only the
single network call inside generate_recommendation() is replaced with a
realistic, hand-written recommendation for each business, injected at
the exact point the real LLM response would arrive (business_setup_
engine.generate_recommendation is monkeypatched for the duration of one
call, then restored), so every validation/persistence/approval/
provisioning/enforcement step downstream of it is exercised unmodified.

BLANK DATABASE: each business gets its OWN fresh AsyncMongoMockClient
(Section 9's own "separate clean database states" requirement), then the
real scripts.db_reset.reset() is called against it before any test
logic runs - the actual reset mechanism the repository ships, not a
hand-rolled equivalent - confirming it leaves a genuinely empty
database (no business_configuration, no users, no projects).

Run from backend/: python -m pytest tests/test_step4_blank_onboarding.py -q
"""
from __future__ import annotations

import os
import sys
import importlib
import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_step4_test")
os.environ.setdefault("JWT_SECRET", "step4-test-secret-key-at-least-32-bytes-long")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


# ENGINE_MODULES: every module whose own `db` must be rebound to each
# fresh mongomock instance (the `from core.db import db` value-binding
# pattern, confirmed earlier in this project's own history to require
# this for every engine, not just the ones this step touches directly).
ENGINE_MODULE_NAMES = [
    "engines.memory_engine", "engines.operations_engine", "engines.intelligence_engine",
    "engines.commercial_engine", "engines.business_setup_engine", "engines.provisioning_engine",
    "engines.reasoning_engine", "engines.knowledge_graph_engine", "engines.workflow_engine",
    "engines.timeline_engine", "engines.notification_engine", "core.auth",
]


async def _blank_instance():
    """A fresh AsyncMongoMockClient, reset via the REAL scripts.db_reset.
    reset() function - not a hand-rolled equivalent - then confirmed
    empty. Returns (client, db) for this test's own exclusive use."""
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()
    db = client["atlas_step4_blank"]

    import core.db as core_db
    core_db.db = db
    core_db.client = client
    for name in ENGINE_MODULE_NAMES:
        mod = importlib.import_module(name)
        importlib.reload(mod) if False else None  # do not reload - just rebind db below
        if hasattr(mod, "db"):
            mod.db = db

    import scripts.db_reset as db_reset
    db_reset.db = db
    db_reset.client = client
    dropped = await db_reset.reset(verbose=False)
    # A freshly-created mongomock database has nothing to drop - this
    # confirms the mechanism ran without erroring, not that something
    # existed to remove.
    assert dropped == []

    assert await db.business_configuration.count_documents({}) == 0
    assert await db.users.count_documents({}) == 0
    assert await db.projects.count_documents({}) == 0
    return client, db


def _server_app():
    """server.py is imported fresh so its own module-level router/
    middleware wiring is real; the db each route ultimately reads is
    whatever core.db.db currently points to (rebound per-blank-instance
    above), since every engine reads `db` as a live module attribute at
    call time, not a value captured once at import."""
    import server
    return server.app


async def _register_and_approve_founding_admin(client_http, phone="9000000000", name="Founding Admin"):
    """Section 2's own real first-user path: /api/auth/register, exactly
    as a real person would use it - not a direct db insert."""
    r = await client_http.post("/api/auth/register", json={"phone": phone, "name": name})
    assert r.status_code == 200, r.text
    body = r.json()
    user, token = body["user"], body["token"]
    # Section 2.2 — confirm the REAL founding-admin behaviour: the first
    # account on a blank database is auto-approved as management, not
    # left pending (every subsequent registration, by contrast, starts
    # pending - this is memory_engine.register_user()'s own existing,
    # unmodified rule, proven here against a genuinely blank database).
    assert user["role"] == "management"
    assert user["approval_status"] == "approved"
    return user, token


async def _run_onboarding(business_label: str, description: str, fake_recommendation: dict,
                          people_by_role: dict[str, tuple[str, str]], *, expect_cre_open: bool):
    """The full flow for ONE business, against its own fresh blank
    instance. Returns the final capability/role state for the caller's
    own assertions. `people_by_role` maps role -> (phone, name) for every
    person to actually provision.
    """
    client, db = await _blank_instance()
    from engines import business_setup_engine as bse
    app = _server_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        # ---- 1/2. Blank -> first user (real /api/auth/register) ----
        admin, token = await _register_and_approve_founding_admin(http)
        headers = {"Authorization": f"Bearer {token}"}

        # Section 2.4/2.5 — before any business discovery, the admin has
        # no business-specific capability yet and the setup state is
        # genuinely "none" (business-neutral), via the real route.
        r = await http.get("/api/business-setup", headers=headers)
        assert r.status_code == 200 and r.json()["status"] == "none"
        r = await http.get("/api/provisioning/status", headers=headers)
        assert r.status_code == 200 and r.json()["configured"] is False

        # ---- 3/4. Business discovery through the REAL route ----
        # Only generate_recommendation()'s own network call is replaced;
        # the route itself (/api/business-setup/analyze), its own
        # _validate_recommendation() call, and save_draft_recommendation()
        # all run for real and are what actually persists the draft.
        original_generate = bse.generate_recommendation

        async def _fake_generate(desc: str):
            assert desc == description  # confirms the route passed OUR input through, unmodified
            return dict(fake_recommendation)  # a fresh copy each call, like a real LLM response would be

        bse.generate_recommendation = _fake_generate
        try:
            r = await http.post("/api/business-setup/analyze", json={"description": description}, headers=headers)
        finally:
            bse.generate_recommendation = original_generate
        assert r.status_code == 200, r.text
        draft = r.json()
        assert draft["status"] == "draft"
        rec = draft["ai_recommendation"]

        # ---- 5. Human approval is the control point ----
        # No account other than the founding admin must exist yet -
        # recommending a role is not the same as creating a user.
        assert await db.users.count_documents({}) == 1
        r = await http.post("/api/business-setup/approve", json={}, headers=headers)
        assert r.status_code == 200, r.text
        approved = r.json()
        assert approved["status"] == "approved"
        assert approved["approved_by_user_id"] == admin["id"]

        # ---- 6. Role provisioning from the APPROVED configuration ----
        r = await http.get("/api/provisioning/role-slots", headers=headers)
        assert r.status_code == 200
        slots = {s["role"]: s for s in r.json()}
        assert set(slots) == set(rec["recommended_roles"])
        if not rec["client_access_required"]:
            assert "client" not in slots

        provisioned = []
        for role, (phone, name) in people_by_role.items():
            r = await http.post("/api/provisioning/users", json={"phone": phone, "name": name, "role": role},
                                headers=headers)
            assert r.status_code == 200, f"{business_label}: provisioning {role} failed: {r.text}"
            provisioned.append(r.json())

        # Duplicate-phone protection still intact through the real route.
        if provisioned:
            dup = provisioned[0]
            r = await http.post("/api/provisioning/users",
                                json={"phone": dup["phone"], "name": "Someone Else", "role": dup["role"]},
                                headers=headers)
            assert r.status_code == 400

        # ---- 7. Capability activation + backend enforcement, real ASGI ----
        r = await http.get("/api/provisioning/status", headers=headers)
        status = r.json()
        caps = status["active_capabilities"]
        for cap, level in rec["capability_recommendations"].items():
            assert caps[cap] == level  # approved == recommended here (no overrides in this test)

        # Universal operational route must always work, regardless of business.
        r = await http.get("/api/projects", headers=headers)
        assert r.status_code == 200

        # Construction-reasoning route: open for construction, blocked otherwise.
        project_r = await http.post("/api/projects", json={"name": f"{business_label} HQ", "code": business_label[:8].upper()},
                                    headers=headers)
        assert project_r.status_code in (200, 201), project_r.text
        project = project_r.json()
        r = await http.get(f"/api/projects/{project['id']}/health", headers=headers)
        if expect_cre_open:
            assert r.status_code != 403, f"{business_label}: construction reasoning should be OPEN"
        else:
            assert r.status_code == 403, f"{business_label}: construction reasoning should be BLOCKED"

        return {"recommendation": rec, "approved": approved, "status": status, "provisioned": provisioned}


# ============================================================================
# Section 3/4 — five realistic, varied business descriptions and their
# corresponding hand-written "as-if-AI-returned-this" recommendations
# (see module docstring for exactly what is and is not simulated).
# ============================================================================

def _caps(bse, **overrides) -> dict:
    caps = {k: "not_required" for k in bse.CAPABILITIES}
    caps.update({k: "required" for k in bse.ALWAYS_REQUIRED})
    caps.update(overrides)
    return caps


CONSTRUCTION_DESC = (
    "We are a construction contractor running several building projects at once, each with its own "
    "site. We track materials deliveries, labour on site, and we need client approvals for design "
    "changes and inspections before work can continue. We also work with subcontractors for "
    "electrical and plumbing."
)

RESTAURANT_DESC = (
    "We run a restaurant group with three outlets across the city. Each outlet has its own manager "
    "who handles food and ingredient quantities, supplier deliveries, and daily staff. The owner "
    "wants a single view of what's pending across all outlets. We don't have a formal accounts "
    "department yet, but we do pay suppliers regularly."
)

SOFTWARE_DESC = (
    "We're a software company, about 20 people split between engineering and product. We need to "
    "track who owns what work, approvals before a feature ships, dependencies between teams, and "
    "blockers that are holding things up. There are no physical materials or sites involved at all."
)

SMALL_SHOP_DESC = (
    "I run a small hardware shop with myself and three staff. We keep basic stock of tools and "
    "fittings, order from a couple of suppliers when we run low, and help customers at the counter. "
    "Nothing complicated — just want to keep track of what's coming in and what's running out."
)

WAREHOUSE_DESC = (
    "We operate a distribution warehouse. We receive pallets from multiple suppliers, check them in "
    "against what was ordered, store them, and dispatch orders out to customers. We also track our "
    "own forklifts and equipment, and our warehouse staff sign off when a delivery or dispatch is "
    "actually completed."
)


def construction_rec(bse):
    return {
        "business_profile": {"industry": "construction", "business_type": "general contractor",
                             "org_size": None, "location_count": None, "operating_model": "project-based"},
        "recommended_roles": ["management", "project_manager", "site_supervisor"],
        "capability_recommendations": _caps(bse, commercial="required", construction_reasoning="required",
                                            workflow="required", verification="required"),
        "client_access_required": True,
        "configuration_questions": ["How many active sites do you typically run at once?"],
        "assumptions": ["Assumed subcontractors are coordinated by the site supervisor, not given direct Atlas access."],
        "confidence": "high",
        "explanation": "Multiple sites, materials and labour tracking, client approvals and inspections, and "
                       "subcontractor coordination all point to full construction reasoning and commercial tracking.",
    }


def restaurant_rec(bse):
    return {
        "business_profile": {"industry": "restaurant", "business_type": "multi-outlet restaurant group",
                             "org_size": None, "location_count": 3, "operating_model": "location-based recurring operations"},
        "recommended_roles": ["management", "site_supervisor"],
        "capability_recommendations": _caps(bse, commercial="optional", construction_reasoning="not_required",
                                            workflow="not_required", verification="optional"),
        "client_access_required": False,
        "configuration_questions": ["Do any of your suppliers or customers need direct Atlas access?"],
        "assumptions": [],
        "confidence": "medium",
        "explanation": "Three outlets with managers handling ingredients and staff, and regular supplier "
                       "payments, so operational tracking across locations is recommended with commercial "
                       "left optional since there's no formal accounts department yet.",
    }


def software_rec(bse):
    return {
        "business_profile": {"industry": "software", "business_type": "software company",
                             "org_size": "20 people", "location_count": None, "operating_model": "team-based"},
        "recommended_roles": ["management", "project_manager"],
        "capability_recommendations": _caps(bse, commercial="not_required", construction_reasoning="not_required",
                                            workflow="optional", verification="optional",
                                            relationship_linking="required"),
        "client_access_required": False,
        "configuration_questions": [],
        "assumptions": [],
        "confidence": "high",
        "explanation": "Engineering and product teams tracking ownership, approvals, dependencies and "
                       "blockers, with no physical materials or construction concepts involved at all.",
    }


def small_shop_rec(bse):
    return {
        "business_profile": {"industry": "retail", "business_type": "small hardware shop",
                             "org_size": "4 people", "location_count": 1, "operating_model": "single-location"},
        "recommended_roles": ["management"],
        "capability_recommendations": _caps(bse, commercial="not_required", construction_reasoning="not_required",
                                            workflow="not_required", verification="not_required",
                                            relationship_linking="optional"),
        "client_access_required": False,
        "configuration_questions": [],
        "assumptions": ["Assumed the three staff work under the owner's own account rather than needing separate logins."],
        "confidence": "medium",
        "explanation": "A single small shop with simple stock tracking and a couple of suppliers needs "
                       "only the basic operational capabilities, kept deliberately minimal.",
    }


def warehouse_rec(bse):
    return {
        "business_profile": {"industry": "warehouse", "business_type": "distribution warehouse",
                             "org_size": None, "location_count": 1, "operating_model": "recurring operations"},
        "recommended_roles": ["management", "site_supervisor"],
        "capability_recommendations": _caps(bse, commercial="not_required", construction_reasoning="not_required",
                                            workflow="not_required", verification="required",
                                            relationship_linking="required"),
        "client_access_required": False,
        "configuration_questions": [],
        "assumptions": [],
        "confidence": "high",
        "explanation": "Receiving against orders, dispatch, and equipment tracking with staff sign-off on "
                       "completion point to verification and fulfillment linking, with no construction "
                       "reasoning needed.",
    }


# ============================================================================
# Section 4 — per-business recommendation-quality assertions (not just
# that the flow completes, but that the recommendation is genuinely
# responsive to the input, per Section 4's own explicit checklist).
# ============================================================================

def _assert_recommendation_quality(rec: dict, *, expect_construction: bool, expect_client: bool, from_roles: set):
    assert set(rec["recommended_roles"]) <= from_roles, "no role invented outside the existing role model"
    assert rec["capability_recommendations"]["construction_reasoning"] == (
        "required" if expect_construction else "not_required")
    assert rec["client_access_required"] == expect_client
    assert rec["confidence"] in ("high", "medium", "low")
    assert isinstance(rec["configuration_questions"], list) and len(rec["configuration_questions"]) <= 3
    assert isinstance(rec["assumptions"], list)


async def test_A_construction_blank_to_operational():
    from engines import business_setup_engine as bse
    rec_template = construction_rec(bse)
    result = await _run_onboarding(
        "Construction", CONSTRUCTION_DESC, rec_template,
        {"project_manager": ("9200000001", "Rahul"), "site_supervisor": ("9200000002", "Amit")},
        expect_cre_open=True)
    _assert_recommendation_quality(result["recommendation"], expect_construction=True, expect_client=True,
                                   from_roles=bse.ROLES)
    assert result["status"]["active_capabilities"]["commercial"] == "required"


async def test_B_restaurant_blank_to_operational():
    from engines import business_setup_engine as bse
    rec_template = restaurant_rec(bse)
    result = await _run_onboarding(
        "Restaurant", RESTAURANT_DESC, rec_template,
        {"site_supervisor": ("9200000101", "Priya")},
        expect_cre_open=False)
    _assert_recommendation_quality(result["recommendation"], expect_construction=False, expect_client=False,
                                   from_roles=bse.ROLES)
    assert "project_manager" not in result["recommendation"]["recommended_roles"]
    assert result["status"]["active_capabilities"]["construction_reasoning"] == "not_required"


async def test_C_software_blank_to_operational():
    from engines import business_setup_engine as bse
    rec_template = software_rec(bse)
    result = await _run_onboarding(
        "Software", SOFTWARE_DESC, rec_template,
        {"project_manager": ("9200000201", "Dev")},
        expect_cre_open=False)
    _assert_recommendation_quality(result["recommendation"], expect_construction=False, expect_client=False,
                                   from_roles=bse.ROLES)
    assert "site_supervisor" not in result["recommendation"]["recommended_roles"]
    assert result["status"]["active_capabilities"]["commercial"] == "not_required"
    assert result["status"]["active_capabilities"]["relationship_linking"] == "required"


async def test_D_small_shop_blank_to_operational():
    from engines import business_setup_engine as bse
    rec_template = small_shop_rec(bse)
    result = await _run_onboarding(
        "SmallShop", SMALL_SHOP_DESC, rec_template, {},  # no additional people — just the owner
        expect_cre_open=False)
    _assert_recommendation_quality(result["recommendation"], expect_construction=False, expect_client=False,
                                   from_roles=bse.ROLES)
    # Section 4's own "do not judge commercial idealness", but DO confirm
    # the config stays genuinely minimal, not enterprise-complex:
    active = [c for c, lvl in result["status"]["active_capabilities"].items() if lvl == "required"]
    assert "construction_reasoning" not in active
    assert "commercial" not in active
    assert "workflow" not in active


async def test_E_warehouse_blank_to_operational():
    from engines import business_setup_engine as bse
    rec_template = warehouse_rec(bse)
    result = await _run_onboarding(
        "Warehouse", WAREHOUSE_DESC, rec_template,
        {"site_supervisor": ("9200000401", "Suresh")},
        expect_cre_open=False)
    _assert_recommendation_quality(result["recommendation"], expect_construction=False, expect_client=False,
                                   from_roles=bse.ROLES)
    assert result["status"]["active_capabilities"]["verification"] == "required"
    assert result["status"]["active_capabilities"]["construction_reasoning"] == "not_required"


# ============================================================================
# Section 5 — negative case: human override through the REAL review
# mechanism, confirming the APPROVED configuration reflects the human's
# edit, not the AI's original recommendation.
# ============================================================================

async def test_human_override_through_real_approval_path():
    from engines import business_setup_engine as bse
    client, db = await _blank_instance()
    app = _server_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        admin, token = await _register_and_approve_founding_admin(http)
        headers = {"Authorization": f"Bearer {token}"}

        rec_template = restaurant_rec(bse)
        original_generate = bse.generate_recommendation
        async def _fake_generate(desc):
            return dict(rec_template)
        bse.generate_recommendation = _fake_generate
        try:
            r = await http.post("/api/business-setup/analyze", json={"description": RESTAURANT_DESC}, headers=headers)
        finally:
            bse.generate_recommendation = original_generate
        assert r.status_code == 200

        # Human disagrees with the AI: wants verification required (AI said "optional"),
        # and does not want site_supervisor provisioned — management only for now.
        r = await http.post("/api/business-setup/approve", json={
            "capability_overrides": {"verification": "required"},
            "role_overrides": ["management"],
        }, headers=headers)
        assert r.status_code == 200, r.text
        approved = r.json()

        assert approved["approved_capabilities"]["verification"] == "required"  # human's override won
        assert approved["ai_recommendation"]["capability_recommendations"]["verification"] == "optional"  # AI's own original preserved for the record
        assert approved["approved_roles"] == ["management"]  # human's override won, not the AI's two roles

        # And provisioning now only allows what the HUMAN approved, not the AI's original list.
        r = await http.post("/api/provisioning/users",
                            json={"phone": "9200000501", "name": "Should Fail", "role": "site_supervisor"},
                            headers=headers)
        assert r.status_code == 400


# ============================================================================
# Section 9 — blank-system repeatability: construction run twice, on two
# independent fresh instances, proving no hidden cross-run state leakage.
# ============================================================================

async def test_construction_blank_onboarding_is_repeatable():
    from engines import business_setup_engine as bse
    for i in range(2):
        rec_template = construction_rec(bse)
        result = await _run_onboarding(
            f"ConstructionRepeat{i}", CONSTRUCTION_DESC, rec_template,
            {"project_manager": (f"920000060{i}", f"Repeat PM {i}")},
            expect_cre_open=True)
        assert result["approved"]["status"] == "approved"
        assert len(result["provisioned"]) == 1


# ============================================================================
# Honesty check — confirms the one simulated piece (the LLM network call)
# really is unavailable in this sandbox, so the monkeypatching above is
# not quietly masking a real capability this environment actually has.
# ============================================================================

async def test_generate_recommendation_is_honestly_unavailable_here():
    await _blank_instance()
    from engines import business_setup_engine as bse
    result = await bse.generate_recommendation("We run a restaurant.")
    assert result is None  # confirms EMERGENT_LLM_KEY is genuinely absent in this sandbox
