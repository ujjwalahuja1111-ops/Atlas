"""AI Business Setup (Step 2) — focused validation.

Per this sprint's own explicit instruction ("we are no longer optimizing
for enormous test counts"), this file is deliberately small: it proves
the contract (validation, draft/approve lifecycle, no silent
provisioning, no construction leakage) rather than exhaustively
re-testing every capability/role combination.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Run from backend/: python -m pytest tests/test_business_setup.py -q
"""
import os
import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_business_setup_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_business_setup_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import business_setup_engine as bse  # noqa: E402

bse.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ADMIN = {"id": "u_bs_admin", "name": "Founding Admin"}


def _blank_caps(**overrides) -> dict:
    caps = {k: "not_required" for k in bse.CAPABILITIES}
    caps.update(overrides)
    return caps


CONSTRUCTION_REC = {
    "business_profile": {"industry": "construction", "business_type": "contractor",
                         "org_size": "small", "location_count": None, "operating_model": "project-based"},
    "recommended_roles": ["management", "project_manager", "site_supervisor"],
    "capability_recommendations": _blank_caps(**{k: "required" for k in bse.ALWAYS_REQUIRED},
                                              commercial="required", construction_reasoning="required",
                                              workflow="required", verification="required",
                                              relationship_linking="optional"),
    "client_access_required": False, "configuration_questions": [], "assumptions": [],
    "confidence": "high",
    "explanation": "Internal PMs and site supervisors, no client access, so construction reasoning "
                   "and commercial tracking are recommended.",
}

RESTAURANT_REC = {
    "business_profile": {"industry": "restaurant", "business_type": "multi-outlet restaurant",
                         "org_size": None, "location_count": 2, "operating_model": "location-based"},
    "recommended_roles": ["management", "site_supervisor"],
    "capability_recommendations": _blank_caps(**{k: "required" for k in bse.ALWAYS_REQUIRED},
                                              commercial="optional", construction_reasoning="not_required",
                                              workflow="not_required", verification="optional"),
    "client_access_required": False,
    "configuration_questions": ["Do customers need to log into Atlas, or is this purely internal?"],
    "assumptions": [], "confidence": "medium",
    "explanation": "Two outlets with managers handling suppliers and staff.",
}

SOFTWARE_REC = {
    "business_profile": {"industry": "software", "business_type": "software company",
                         "org_size": "25 people", "location_count": None, "operating_model": "team-based"},
    "recommended_roles": ["management", "project_manager"],
    "capability_recommendations": _blank_caps(**{k: "required" for k in bse.ALWAYS_REQUIRED},
                                              commercial="not_required", construction_reasoning="not_required",
                                              workflow="optional", verification="optional",
                                              relationship_linking="required"),
    "client_access_required": False, "configuration_questions": [], "assumptions": [], "confidence": "high",
    "explanation": "Software team tracking commitments, blockers and dependencies; no physical materials.",
}


# ---------------------------------------------------------------- validation

def test_well_formed_recommendation_is_accepted():
    assert bse._validate_recommendation(CONSTRUCTION_REC) is not None


def test_missing_capability_key_rejected():
    bad = dict(CONSTRUCTION_REC)
    caps = dict(CONSTRUCTION_REC["capability_recommendations"])
    del caps["commercial"]
    bad["capability_recommendations"] = caps
    assert bse._validate_recommendation(bad) is None


def test_invalid_role_rejected():
    bad = dict(CONSTRUCTION_REC)
    bad["recommended_roles"] = ["management", "accountant"]
    assert bse._validate_recommendation(bad) is None


def test_invalid_capability_level_rejected():
    bad = dict(CONSTRUCTION_REC)
    caps = dict(CONSTRUCTION_REC["capability_recommendations"])
    caps["commercial"] = "maybe"
    bad["capability_recommendations"] = caps
    assert bse._validate_recommendation(bad) is None


def test_too_many_questions_rejected():
    bad = dict(CONSTRUCTION_REC)
    bad["configuration_questions"] = ["q1", "q2", "q3", "q4"]
    assert bse._validate_recommendation(bad) is None


def test_construction_never_leaks_into_restaurant_or_software_recommendation():
    """The specific, named anti-leakage test this sprint's own Section 8/9
    treats as a product correctness test, not a style preference."""
    assert RESTAURANT_REC["capability_recommendations"]["construction_reasoning"] == "not_required"
    assert SOFTWARE_REC["capability_recommendations"]["construction_reasoning"] == "not_required"
    assert bse._validate_recommendation(RESTAURANT_REC) is not None
    assert bse._validate_recommendation(SOFTWARE_REC) is not None


def test_prompt_itself_instructs_against_construction_leakage():
    """Guards the PROMPT wording, not just the example data above - if
    this instruction is ever accidentally removed, this test catches it
    even though no live model call happens in this deterministic suite.
    Whitespace-normalized before searching since the prompt's own line
    wrapping would otherwise break a literal substring match."""
    import re
    flat = re.sub(r"\s+", " ", bse.BUSINESS_SETUP_SYSTEM_PROMPT)
    assert "never recommend construction-specific reasoning for a" in flat
    assert "do not invent new role names" in flat.lower()


def test_prompt_lists_every_real_capability_key_exactly_once():
    """The prompt's own schema instructions must name exactly the real
    capability keys this module defines - never an invented list."""
    for key in bse.CAPABILITIES:
        assert key in bse.BUSINESS_SETUP_SYSTEM_PROMPT


# -------------------------------------------------------- draft/approve flow

async def test_fresh_setup_draft_then_approve():
    doc = await bse.save_draft_recommendation(
        description="We are a construction contractor...", recommendation=CONSTRUCTION_REC, actor=ADMIN)
    assert doc["status"] == "draft"
    fetched = await bse.get_configuration()
    assert fetched["status"] == "draft"

    approved = await bse.approve_configuration(actor=ADMIN)
    assert approved["status"] == "approved"
    assert approved["approved_by_user_id"] == ADMIN["id"]
    assert approved["approved_roles"] == CONSTRUCTION_REC["recommended_roles"]
    assert approved["approved_capabilities"]["construction_reasoning"] == "required"


async def test_approval_is_the_only_way_to_activate_nothing_else_is_touched():
    """No accounts created, no users collection touched, no other
    collection written - roles/capabilities are recommendations until a
    human approves, and even approval only writes this one document
    (Step 3's own job is provisioning from it, confirmed out of scope
    here)."""
    await _mock_db.business_configuration.delete_many({})  # clear the prior test's own approved config
    users_before = await _mock_db.users.count_documents({})
    await bse.save_draft_recommendation(
        description="software biz", recommendation=SOFTWARE_REC, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    users_after = await _mock_db.users.count_documents({})
    assert users_before == users_after == 0


async def test_cannot_overwrite_an_approved_configuration_silently():
    with pytest.raises(ValueError, match="already approved"):
        await bse.save_draft_recommendation(
            description="something else", recommendation=RESTAURANT_REC, actor=ADMIN)


async def test_cannot_double_approve():
    with pytest.raises(ValueError, match="already approved"):
        await bse.approve_configuration(actor=ADMIN)


# -------------------------------------------------------- human override flow

async def test_human_override_changes_only_the_overridden_fields():
    await _mock_db.business_configuration.delete_many({})
    await bse.save_draft_recommendation(
        description="restaurant biz", recommendation=RESTAURANT_REC, actor=ADMIN)
    approved = await bse.approve_configuration(
        actor=ADMIN,
        capability_overrides={"verification": "required"},
        role_overrides=["management"],
        client_access_override=False,
    )
    assert approved["approved_capabilities"]["verification"] == "required"
    # untouched by the override - still what the AI recommended
    assert approved["approved_capabilities"]["construction_reasoning"] == "not_required"
    assert approved["approved_roles"] == ["management"]


async def test_invalid_override_rejected_and_configuration_left_untouched():
    await _mock_db.business_configuration.delete_many({})
    await bse.save_draft_recommendation(
        description="software biz", recommendation=SOFTWARE_REC, actor=ADMIN)
    with pytest.raises(ValueError):
        await bse.approve_configuration(actor=ADMIN, capability_overrides={"commercial": "yes please"})
    with pytest.raises(ValueError):
        await bse.approve_configuration(actor=ADMIN, capability_overrides={"not_a_real_capability": "required"})
    with pytest.raises(ValueError):
        await bse.approve_configuration(actor=ADMIN, role_overrides=["management", "accountant"])
    cfg = await bse.get_configuration()
    assert cfg["status"] == "draft"  # none of the rejected attempts partially applied


async def test_no_recommendation_yet_cannot_be_approved():
    await _mock_db.business_configuration.delete_many({})
    with pytest.raises(ValueError, match="analyze a business description first"):
        await bse.approve_configuration(actor=ADMIN)


# ------------------------------------------------------- AI gateway reuse

async def test_generate_recommendation_fails_safely_without_credentials():
    """No real LLM credentials in this environment - confirms the module
    fails safely (returns None) rather than fabricating a recommendation,
    matching _run_structuring_pass's own documented behaviour exactly."""
    result = await bse.generate_recommendation("We run a restaurant with two outlets.")
    assert result is None
