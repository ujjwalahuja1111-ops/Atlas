"""AI Engine / Role Configuration (Step 3) — focused validation.

Deliberately small, per this sprint's own instruction to not optimize for
enormous test counts: proves the contract (role slots derived from the
APPROVED configuration only, no provisioning without approval, client
role genuinely unavailable when not approved, capability gating is
backend-enforced not merely a UI signal, existing data/users survive).

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Run from backend/: python -m pytest tests/test_provisioning.py -q
"""
import os
import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_provisioning_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_provisioning_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import business_setup_engine as bse, memory_engine as me, provisioning_engine as pe  # noqa: E402

for _mod in (bse, me, pe):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ADMIN = {"id": "u_prov_admin", "name": "Founding Admin"}


def _blank_caps(**overrides) -> dict:
    caps = {k: "not_required" for k in bse.CAPABILITIES}
    caps.update({k: "required" for k in bse.ALWAYS_REQUIRED})
    caps.update(overrides)
    return caps


CONSTRUCTION_NO_CLIENT = {
    "business_profile": {"industry": "construction", "business_type": "contractor", "org_size": "small",
                         "location_count": None, "operating_model": "project-based"},
    "recommended_roles": ["management", "project_manager", "site_supervisor"],
    "capability_recommendations": _blank_caps(commercial="required", construction_reasoning="required"),
    "client_access_required": False, "configuration_questions": [], "assumptions": [],
    "confidence": "high", "explanation": "Internal construction contractor.",
}

SOFTWARE_NO_COMMERCIAL = {
    "business_profile": {"industry": "software", "business_type": "software company", "org_size": "25 people",
                         "location_count": None, "operating_model": "team-based"},
    "recommended_roles": ["management"],
    "capability_recommendations": _blank_caps(relationship_linking="required"),
    "client_access_required": False, "configuration_questions": [], "assumptions": [], "confidence": "high",
    "explanation": "Software team, no physical materials.",
}


async def _reset():
    await _mock_db.business_configuration.delete_many({})
    await _mock_db.users.delete_many({})


# --------------------------------------------------------------- fail-safe

async def test_cannot_provision_without_an_approved_configuration():
    await _reset()
    with pytest.raises(ValueError, match="No approved business configuration"):
        await pe.get_required_role_slots()
    with pytest.raises(ValueError, match="No approved business configuration"):
        await pe.provision_user(actor=ADMIN, phone="9000000001", name="X", role="management")


async def test_draft_only_configuration_cannot_provision():
    await _reset()
    await bse.save_draft_recommendation(description="x", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    with pytest.raises(ValueError, match="No approved business configuration"):
        await pe.get_required_role_slots()


# --------------------------------------------------------------- role slots

async def test_role_slots_match_approved_roles_only():
    await _reset()
    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    slots = await pe.get_required_role_slots()
    roles = {s["role"] for s in slots}
    assert roles == {"management", "project_manager", "site_supervisor"}
    assert "client" not in roles
    assert all(s["filled_count"] == 0 for s in slots)


# -------------------------------------------------------------- provisioning

async def test_provision_user_creates_a_real_approved_account():
    await _reset()
    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    user = await pe.provision_user(actor=ADMIN, phone="9000000002", name="Rahul", role="project_manager")
    assert user["role"] == "project_manager"
    assert user["approval_status"] == "approved"
    assert user["is_active"] is True
    assert user["scope_projects"] is True  # least privilege by default for non-management

    looked_up = await me.get_user_by_phone("9000000002")
    assert looked_up is not None and looked_up["approval_status"] == "approved"


async def test_provisioned_count_reflects_in_role_slots():
    await _reset()
    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    await pe.provision_user(actor=ADMIN, phone="9000000003", name="Rahul", role="project_manager")
    slots = await pe.get_required_role_slots()
    by_role = {s["role"]: s["filled_count"] for s in slots}
    assert by_role["project_manager"] == 1
    assert by_role["site_supervisor"] == 0


async def test_duplicate_phone_rejected():
    await _reset()
    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    await pe.provision_user(actor=ADMIN, phone="9000000004", name="Rahul", role="project_manager")
    with pytest.raises(ValueError, match="already exists"):
        await pe.provision_user(actor=ADMIN, phone="9000000004", name="Someone Else", role="site_supervisor")


# -------------------------------------------------------------- client access

async def test_client_role_unavailable_when_client_access_not_approved():
    await _reset()
    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)  # client_access_required is False
    slots = await pe.get_required_role_slots()
    assert "client" not in {s["role"] for s in slots}
    with pytest.raises(ValueError, match="Client access is not part"):
        await pe.provision_user(actor=ADMIN, phone="9000000005", name="SomeClient", role="client")


async def test_client_role_available_when_explicitly_approved():
    await _reset()
    rec = dict(CONSTRUCTION_NO_CLIENT)
    rec["client_access_required"] = True
    rec["recommended_roles"] = ["management", "client"]
    await bse.save_draft_recommendation(description="construction w/ client", recommendation=rec, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    slots = await pe.get_required_role_slots()
    assert "client" in {s["role"] for s in slots}
    user = await pe.provision_user(actor=ADMIN, phone="9000000006", name="Real Client", role="client")
    assert user["role"] == "client"


async def test_role_not_in_approved_roles_rejected_even_if_globally_valid():
    """Section 6's own "only required role slots" enforced in the WRITE
    path, not merely the UI: site_supervisor is a real, valid RBAC role,
    but this configuration never approved it."""
    await _reset()
    rec = dict(SOFTWARE_NO_COMMERCIAL)  # only "management" approved
    await bse.save_draft_recommendation(description="software", recommendation=rec, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    with pytest.raises(ValueError, match="not one of the approved roles"):
        await pe.provision_user(actor=ADMIN, phone="9000000007", name="X", role="site_supervisor")


# -------------------------------------------------------------- capabilities

async def test_construction_capability_never_active_for_software_business():
    await _reset()
    await bse.save_draft_recommendation(description="software", recommendation=SOFTWARE_NO_COMMERCIAL, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    assert await pe.is_capability_active("construction_reasoning") is False
    assert await pe.is_capability_active("commercial") is False
    assert await pe.is_capability_active("relationship_linking") is True


async def test_commercial_active_for_construction_business():
    await _reset()
    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    assert await pe.is_capability_active("commercial") is True
    assert await pe.is_capability_active("construction_reasoning") is True


async def test_capability_check_fails_closed_without_approved_configuration():
    await _reset()
    assert await pe.is_capability_active("commercial") is False
    assert await pe.get_active_capabilities() == {}


# -------------------------------------------------------------- workspace status

async def test_workspace_status_before_and_after_provisioning():
    await _reset()
    unconfigured = await pe.get_workspace_status()
    assert unconfigured == {"configured": False}

    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    status = await pe.get_workspace_status()
    assert status["configured"] is True
    assert status["all_roles_filled"] is False

    for i, role in enumerate(["management", "project_manager", "site_supervisor"]):
        await pe.provision_user(actor=ADMIN, phone=f"900000001{i}", name=f"Person {i}", role=role)
    status2 = await pe.get_workspace_status()
    assert status2["all_roles_filled"] is True


# -------------------------------------------------------------- data survival

async def test_existing_users_and_projects_survive_provisioning():
    """Section 20's own explicit migration-safety requirement: existing
    data must never be destroyed by this module."""
    await _reset()
    existing_project = await me.insert_project(name="Pre-existing Project", code="PREEXIST")
    existing_user = await me.upsert_user(phone="9111111111", name="Pre-existing User", role="site_supervisor")

    await bse.save_draft_recommendation(description="construction", recommendation=CONSTRUCTION_NO_CLIENT, actor=ADMIN)
    await bse.approve_configuration(actor=ADMIN)
    await pe.provision_user(actor=ADMIN, phone="9000000020", name="New Person", role="project_manager")

    projects = await me.list_projects()
    assert any(p["id"] == existing_project["id"] for p in projects)
    still_there = await me.get_user(existing_user["id"])
    assert still_there is not None and still_there["name"] == "Pre-existing User"
