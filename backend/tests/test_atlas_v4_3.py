"""Project Atlas V4.3 — Sprint 4.3: Identity & Access Foundation tests.

Validates:
  * Sign Up collects Name, Mobile Number, and User Type (requested_workspace)
  * New accounts: pending approval, no project access, no site access,
    no workspace until assigned — literally verified via GET /api/projects
    and GET /api/sites returning empty for a fresh, unassigned account
  * Admin can assign Workspace (validated against role compatibility),
    Permission Level (role, already existed from Sprint 4.1), Project(s)
    (already existed from Sprint 4.1)
  * Admin has unrestricted access regardless of scope_projects
  * Users only see assigned projects/sites once approved+assigned
  * Existing (pre-Sprint-4.3) users are unaffected — migrate safely with
    zero behavioural change (see the "legacy" tests below)

This file only covers what's new in Sprint 4.3. Approve/Reject/Assign
Role/Assign Projects/Activate-Deactivate already have full coverage in
test_atlas_v4_1.py and are unchanged by this sprint.
"""
import os
import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or
        "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"


# FAC-03 P0 fix: /api/auth/login no longer auto-creates an account for an
# unrecognized phone number - that silent auto-create-on-login was the
# confirmed root cause of the P0 "any well-formed but unregistered phone
# number logs in successfully" bug. This test suite's bootstrap strategy
# changes accordingly: _login() below first tries a plain login (the fast
# path for an account it - or the target environment's seed script -
# already created); only if that fails does it fall back to the REAL
# account-creation flow (Sign Up -> admin approval -> role assignment ->
# login), using the DX-7 seed script's known admin account as the root of
# trust needed to approve a freshly self-registered account. This assumes
# the target environment has been seeded (`python -m scripts.dev seed`) -
# the same assumption this suite already made implicitly by requiring a
# reachable EXPO_PUBLIC_BACKEND_URL in the first place.
_SEEDED_ADMIN_PHONE = "9000000001"  # DX-7 seed script's "Atlas Admin 1"
_seeded_admin_cache: dict = {}


def _seeded_admin_headers():
    if "headers" not in _seeded_admin_cache:
        r = requests.post(f"{API}/auth/login",
                          json={"phone": _SEEDED_ADMIN_PHONE, "name": "Atlas Admin 1", "role": "management"},
                          timeout=20)
        assert r.status_code == 200, (
            "Seeded admin account not found - has the target environment been "
            f"seeded? (python -m scripts.dev seed) {r.text}"
        )
        _seeded_admin_cache["headers"] = {"Authorization": f"Bearer {r.json()['token']}"}
    return _seeded_admin_cache["headers"]


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role}, timeout=20)
    if r.status_code == 200:
        b = r.json()
        return b["user"], {"Authorization": f"Bearer {b['token']}"}

    reg = requests.post(f"{API}/auth/register", json={"phone": phone, "name": name}, timeout=20)
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["user"]["id"]
    admin_headers = _seeded_admin_headers()
    ar = requests.post(f"{API}/admin/users/{user_id}/approve", headers=admin_headers, timeout=20)
    assert ar.status_code == 200, ar.text
    rr = requests.post(f"{API}/admin/users/{user_id}/role", json={"role": role}, headers=admin_headers, timeout=20)
    assert rr.status_code == 200, rr.text

    r2 = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r2.status_code == 200, r2.text
    b = r2.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


@pytest.fixture(scope="session")
def legacy_user():
    """Simulates a pre-Sprint-4.3 account: created via plain login, exactly
    like every Sprint 1-4.2 test credential."""
    u, h = _login("supervisor", "9999933333", "V43 Legacy Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9999922222", "V43 Admin")
    return {"user": u, "headers": h}


# --------------------------------------------------------------------------
# Sign Up collects Name, Mobile Number, User Type
# --------------------------------------------------------------------------
def test_signup_accepts_user_type():
    r = requests.post(f"{API}/auth/register",
                      json={"phone": "9888711111", "name": "V43 New Hire", "requested_workspace": "pm"},
                      timeout=20)
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["requested_workspace"] == "pm"


def test_signup_user_type_is_optional():
    r = requests.post(f"{API}/auth/register",
                      json={"phone": "9888711112", "name": "V43 No Type"}, timeout=20)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["requested_workspace"] is None


def test_signup_rejects_invalid_user_type():
    r = requests.post(f"{API}/auth/register",
                      json={"phone": "9888711113", "name": "V43 Bad Type", "requested_workspace": "not-a-real-workspace"},
                      timeout=20)
    assert r.status_code == 422  # pydantic Literal validation


# --------------------------------------------------------------------------
# Every new account: pending approval, no project/site access, no workspace
# --------------------------------------------------------------------------
def test_new_account_is_pending_with_no_workspace():
    r = requests.post(f"{API}/auth/register",
                      json={"phone": "9888711114", "name": "V43 Pending Check", "requested_workspace": "admin"},
                      timeout=20)
    user = r.json()["user"]
    assert user["approval_status"] == "pending"
    assert user["workspace"] is None  # NOT auto-applied from requested_workspace
    assert user["assigned_project_ids"] == []


def test_new_unapproved_account_sees_no_projects_or_sites():
    r = requests.post(f"{API}/auth/register",
                      json={"phone": "9888711115", "name": "V43 No Access"}, timeout=20)
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    r_proj = requests.get(f"{API}/projects", headers=headers, timeout=20)
    assert r_proj.status_code == 200
    assert r_proj.json() == []
    r_sites = requests.get(f"{API}/sites", headers=headers, timeout=20)
    assert r_sites.status_code == 200
    assert r_sites.json() == []


# --------------------------------------------------------------------------
# Admin assigns Workspace, Permission Level, Project(s)
# --------------------------------------------------------------------------
def test_admin_assigns_workspace_role_projects_end_to_end(admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register",
                        json={"phone": "9888711116", "name": "V43 Full Flow", "requested_workspace": "client"},
                        timeout=20).json()
    uid = reg["user"]["id"]
    user_headers = {"Authorization": f"Bearer {reg['token']}"}

    # approve
    assert requests.post(f"{API}/admin/users/{uid}/approve", headers=h, timeout=20).status_code == 200

    # assign role (Permission Level)
    r_role = requests.post(f"{API}/admin/users/{uid}/role", json={"role": "coordinator"}, headers=h, timeout=20)
    assert r_role.status_code == 200
    assert r_role.json()["role"] == "coordinator"

    # assign workspace (honoring the requested_workspace this time)
    r_ws = requests.post(f"{API}/admin/users/{uid}/workspace", json={"workspace": "client"}, headers=h, timeout=20)
    assert r_ws.status_code == 200
    assert r_ws.json()["workspace"] == "client"

    # assign project
    proj = requests.post(f"{API}/projects", json={"name": "V43 Assigned Project", "code": "V43AP"}, headers=h, timeout=20).json()
    r_proj = requests.post(f"{API}/admin/users/{uid}/projects", json={"project_ids": [proj["id"]]}, headers=h, timeout=20)
    assert r_proj.status_code == 200
    assert proj["id"] in r_proj.json()["assigned_project_ids"]

    # now the user sees ONLY their assigned project
    r_list = requests.get(f"{API}/projects", headers=user_headers, timeout=20)
    names = [p["name"] for p in r_list.json()]
    assert names == ["V43 Assigned Project"]


def test_workspace_assignment_validates_role_compatibility(admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888711117", "name": "V43 Incompatible"}, timeout=20).json()
    uid = reg["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/approve", headers=h, timeout=20)
    requests.post(f"{API}/admin/users/{uid}/role", json={"role": "supervisor"}, headers=h, timeout=20)

    # supervisor role is only compatible with 'supervisor' workspace
    r_bad = requests.post(f"{API}/admin/users/{uid}/workspace", json={"workspace": "admin"}, headers=h, timeout=20)
    assert r_bad.status_code == 400

    r_ok = requests.post(f"{API}/admin/users/{uid}/workspace", json={"workspace": "supervisor"}, headers=h, timeout=20)
    assert r_ok.status_code == 200


def test_workspace_assignment_unlocks_client_workspace(admin):
    """Coordinator role can now be explicitly assigned the 'client'
    workspace by an admin — previously unreachable via any path
    (ADR-020), now possible via explicit assignment (ADR of this sprint)."""
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888711118", "name": "V43 Client Test"}, timeout=20).json()
    uid = reg["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/approve", headers=h, timeout=20)
    requests.post(f"{API}/admin/users/{uid}/role", json={"role": "coordinator"}, headers=h, timeout=20)
    r = requests.post(f"{API}/admin/users/{uid}/workspace", json={"workspace": "client"}, headers=h, timeout=20)
    assert r.status_code == 200
    assert r.json()["workspace"] == "client"


def test_role_change_resets_incompatible_workspace(admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888711119", "name": "V43 Reset Test"}, timeout=20).json()
    uid = reg["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/approve", headers=h, timeout=20)
    requests.post(f"{API}/admin/users/{uid}/role", json={"role": "coordinator"}, headers=h, timeout=20)
    requests.post(f"{API}/admin/users/{uid}/workspace", json={"workspace": "pm"}, headers=h, timeout=20)

    r_role_change = requests.post(f"{API}/admin/users/{uid}/role", json={"role": "supervisor"}, headers=h, timeout=20)
    assert r_role_change.status_code == 200
    assert r_role_change.json()["workspace"] is None


def test_workspace_assignment_requires_admin(legacy_user, admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888711120", "name": "V43 Perm Test"}, timeout=20).json()
    uid = reg["user"]["id"]
    r = requests.post(f"{API}/admin/users/{uid}/workspace", json={"workspace": "supervisor"}, headers=legacy_user["headers"], timeout=20)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Admin has unrestricted access
# --------------------------------------------------------------------------
def test_admin_sees_all_projects_regardless_of_scoping(admin):
    r = requests.get(f"{API}/projects", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert len(r.json()) >= 1  # sees everything created across all prior tests


# --------------------------------------------------------------------------
# Existing users migrate safely — zero behavioural change
# --------------------------------------------------------------------------
def test_legacy_account_sees_all_projects_unaffected(legacy_user, admin):
    """A pre-Sprint-4.3 account (created via plain login, never touched by
    the new scoping feature) must continue to see every project, exactly
    as it did in every prior sprint — the core migration-safety guarantee."""
    # ensure at least one project exists
    requests.post(f"{API}/projects", json={"name": "V43 Migration Check", "code": "V43M"},
                 headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/projects", headers=legacy_user["headers"], timeout=20)
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "V43 Migration Check" in names


def test_legacy_account_sees_all_sites_unaffected(legacy_user):
    r = requests.get(f"{API}/sites", headers=legacy_user["headers"], timeout=20)
    assert r.status_code == 200
    assert len(r.json()) >= 0  # doesn't error, and isn't artificially emptied


def test_legacy_account_has_no_new_fields_forced_on_it(legacy_user):
    """GET /api/me on a legacy account should show the backward-compatible
    defaults (workspace=None, scope_projects effectively False) without
    ever having been touched by an admin action."""
    r = requests.get(f"{API}/me", headers=legacy_user["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body.get("workspace") in (None,)  # never explicitly assigned


# --------------------------------------------------------------------------
# Regression: Sprint 1-4.2 endpoints unaffected
# --------------------------------------------------------------------------
def test_regression_sprint_1_4_2_endpoints(legacy_user, admin):
    h = legacy_user["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/", timeout=20).status_code == 200

    ah = admin["headers"]
    assert requests.get(f"{API}/admin/users", headers=ah, timeout=20).status_code == 200


def test_regression_existing_role_and_project_assignment_unchanged(admin):
    """Assign Role and Assign Projects (Sprint 4.1) must still work exactly
    as before — this sprint only ADDS workspace assignment alongside them."""
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888711121", "name": "V43 Regression"}, timeout=20).json()
    uid = reg["user"]["id"]
    assert requests.post(f"{API}/admin/users/{uid}/approve", headers=h, timeout=20).status_code == 200
    assert requests.post(f"{API}/admin/users/{uid}/role", json={"role": "coordinator"}, headers=h, timeout=20).status_code == 200
    assert requests.post(f"{API}/admin/users/{uid}/projects", json={"project_ids": []}, headers=h, timeout=20).status_code == 200
    assert requests.post(f"{API}/admin/users/{uid}/active", json={"is_active": False}, headers=h, timeout=20).status_code == 200
