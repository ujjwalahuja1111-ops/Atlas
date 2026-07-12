"""Project Atlas V4.1 — Sprint 4.1: Stabilization & QA Pass tests.

Validates:
  * Sign Up (/auth/register) creates a pending, unassigned account
  * Admin User Management: list pending, approve, reject, assign role,
    assign projects, activate/deactivate — all admin-gated
  * Deactivated accounts are hard-blocked at the auth layer (401)
  * Self-service PATCH /api/me (name only, never role/approval/projects)
  * Project DELETE with dependency guard, mirroring the existing Site
    DELETE pattern
  * Knowledge Core stabilization fixes: 404 vs 400 vs 409 status codes,
    batched list enrichment still returns correct data
  * Basic phone format validation on both login and register

FAC-03 P0 note: /auth/login's original "upsert-on-first-use" behaviour
(auto-creating an account for any never-before-seen, well-formatted
phone number) was removed entirely — it was the confirmed root cause of
a real authentication bypass (any well-formed but unregistered phone
logged in successfully as a new Site Supervisor). Login now ONLY
authenticates an existing account; see test_atlas_fac03.py for the
dedicated coverage of the corrected behaviour. This file's own tests
were updated to bootstrap accounts via the real
register->approve->login flow rather than relying on the removed
shortcut — see this file's _login() helper.

This file only covers what's new/changed in Sprint 4.1. See test_atlas_v4.py
for full Construction Knowledge Core coverage, which remains valid —
Sprint 4.1 did not change any of that module's request/response contracts
beyond the status-code and versioning refinements covered here.
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
def supervisor():
    u, h = _login("supervisor", "9999977777", "V41 Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9999966666", "V41 Admin")
    return {"user": u, "headers": h}


# --------------------------------------------------------------------------
# Existing login behaviour for an already-provisioned account (regression guard)
# --------------------------------------------------------------------------
def test_existing_login_unchanged(supervisor):
    assert supervisor["user"]["role"] == "supervisor"
    assert "phone" in supervisor["user"]
    assert "id" in supervisor["user"]


def test_login_phone_validation():
    r = requests.post(f"{API}/auth/login", json={"phone": "not-a-phone", "name": "X"}, timeout=20)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# Sign Up / Pending Approval
# --------------------------------------------------------------------------
def test_register_creates_pending_unassigned_account():
    r = requests.post(f"{API}/auth/register", json={"phone": "9888811111", "name": "New Person"}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["approval_status"] == "pending"
    assert body["user"]["assigned_project_ids"] == []
    assert "token" in body


def test_register_rejects_duplicate_phone():
    requests.post(f"{API}/auth/register", json={"phone": "9888822222", "name": "First"}, timeout=20)
    r = requests.post(f"{API}/auth/register", json={"phone": "9888822222", "name": "Second"}, timeout=20)
    assert r.status_code == 400


def test_register_phone_validation():
    r = requests.post(f"{API}/auth/register", json={"phone": "bad", "name": "X"}, timeout=20)
    assert r.status_code == 400


def test_register_requires_name():
    r = requests.post(f"{API}/auth/register", json={"phone": "9888833333", "name": "  "}, timeout=20)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# Admin User Management
# --------------------------------------------------------------------------
def test_user_management_requires_admin(supervisor):
    r = requests.get(f"{API}/admin/users", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_full_approval_workflow(admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888844444", "name": "Workflow Test"}, timeout=20).json()
    uid = reg["user"]["id"]

    r_list = requests.get(f"{API}/admin/users?approval_status=pending", headers=h, timeout=20)
    assert r_list.status_code == 200
    assert any(u["id"] == uid for u in r_list.json())

    r_approve = requests.post(f"{API}/admin/users/{uid}/approve", headers=h, timeout=20)
    assert r_approve.status_code == 200
    assert r_approve.json()["approval_status"] == "approved"

    r_role = requests.post(f"{API}/admin/users/{uid}/role", json={"role": "coordinator"}, headers=h, timeout=20)
    assert r_role.status_code == 200
    assert r_role.json()["role"] == "coordinator"

    projects = requests.get(f"{API}/projects", headers=h, timeout=20).json()
    if projects:
        proj_id = projects[0]["id"]
        r_proj = requests.post(f"{API}/admin/users/{uid}/projects", json={"project_ids": [proj_id]}, headers=h, timeout=20)
        assert r_proj.status_code == 200
        assert proj_id in r_proj.json()["assigned_project_ids"]

    r_deact = requests.post(f"{API}/admin/users/{uid}/active", json={"is_active": False}, headers=h, timeout=20)
    assert r_deact.status_code == 200
    assert r_deact.json()["is_active"] is False


def test_deactivated_account_hard_blocked(admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888855555", "name": "Deactivate Me"}, timeout=20).json()
    uid = reg["user"]["id"]
    user_headers = {"Authorization": f"Bearer {reg['token']}"}

    requests.post(f"{API}/admin/users/{uid}/active", json={"is_active": False}, headers=h, timeout=20)

    r = requests.get(f"{API}/me", headers=user_headers, timeout=20)
    assert r.status_code == 401


def test_reject_user(admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888866666", "name": "Reject Me"}, timeout=20).json()
    uid = reg["user"]["id"]
    r = requests.post(f"{API}/admin/users/{uid}/reject", headers=h, timeout=20)
    assert r.status_code == 200
    assert r.json()["approval_status"] == "rejected"


def test_admin_cannot_deactivate_self(admin):
    h = admin["headers"]
    me = requests.get(f"{API}/me", headers=h, timeout=20).json()
    r = requests.post(f"{API}/admin/users/{me['id']}/active", json={"is_active": False}, headers=h, timeout=20)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# Self-service name edit (PATCH /api/me)
# --------------------------------------------------------------------------
def test_update_own_name(supervisor):
    h = supervisor["headers"]
    r = requests.patch(f"{API}/me", json={"name": "Renamed Supervisor"}, headers=h, timeout=20)
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Supervisor"
    r2 = requests.get(f"{API}/me", headers=h, timeout=20)
    assert r2.json()["role"] == "supervisor"  # unaffected


def test_update_own_name_rejects_empty(supervisor):
    r = requests.patch(f"{API}/me", json={"name": ""}, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# Project lifecycle: DELETE with dependency guard
# --------------------------------------------------------------------------
def test_delete_empty_project(admin):
    h = admin["headers"]
    proj = requests.post(f"{API}/projects", json={"name": "V41 Delete Test", "code": "V41D"}, headers=h, timeout=20).json()
    r = requests.delete(f"{API}/projects/{proj['id']}", headers=h, timeout=20)
    assert r.status_code == 200
    assert r.json()["deleted"] is True


def test_delete_project_with_sites_blocked(admin):
    h = admin["headers"]
    proj = requests.post(f"{API}/projects", json={"name": "V41 Occupied", "code": "V41O"}, headers=h, timeout=20).json()
    requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"}, headers=h, timeout=20)
    r = requests.delete(f"{API}/projects/{proj['id']}", headers=h, timeout=20)
    assert r.status_code == 409


def test_delete_project_requires_admin(supervisor, admin):
    h = admin["headers"]
    proj = requests.post(f"{API}/projects", json={"name": "V41 Perm Test", "code": "V41P"}, headers=h, timeout=20).json()
    r = requests.delete(f"{API}/projects/{proj['id']}", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Knowledge Core stabilization: 404 vs 400 vs 409
# --------------------------------------------------------------------------
def test_knowledge_update_missing_item_is_404(admin):
    r = requests.patch(f"{API}/knowledge-items/does-not-exist-v41",
                       json={"name": "x"}, headers=admin["headers"], timeout=20)
    assert r.status_code == 404


def test_knowledge_bad_reference_is_400_not_404(admin):
    r = requests.post(f"{API}/knowledge-items",
                      json={"type": "activity", "name": "V41 Bad Ref", "category_id": "nope"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 400


def test_knowledge_list_still_correct_after_batching(admin):
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items", json={"type": "category", "name": "V41 Batch Cat"}, headers=h, timeout=20).json()
    requests.post(f"{API}/knowledge-items", json={"type": "activity", "name": "V41 Batch Act", "category_id": cat["id"]}, headers=h, timeout=20)
    r = requests.get(f"{API}/knowledge-items?type=activity&q=V41 Batch", headers=h, timeout=20)
    assert r.status_code == 200
    items = r.json()
    assert any(i["name"] == "V41 Batch Act" and i["category_name"] == "V41 Batch Cat" for i in items)


# --------------------------------------------------------------------------
# Regression: Sprint 1-4 endpoints unaffected
# --------------------------------------------------------------------------
def test_regression_sprint_1_4_endpoints(supervisor):
    h = supervisor["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/", timeout=20).status_code == 200
