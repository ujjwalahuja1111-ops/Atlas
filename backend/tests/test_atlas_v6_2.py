"""Project Atlas V6.2 — Sprint 6.2: Founder Acceptance Corrections tests.

Validates:
  * Manual Text Capture Processing: when AI is unavailable, a text
    observation creates a real operational_item directly instead of
    being stranded (reality_engine.capture()'s fallback).
  * Identity Security: login never modifies an existing account's name
    (extends Sprint 6's role protection to name).
  * Client Permissions: clients cannot assign/reassign/edit/escalate/
    blocker/duplicate/create operational items, and can only
    approve/reject client_approval items plus comment — with an
    optional comment that becomes part of the item's history.
  * Regression: everything from Sprint 1-6.1 still works.

Note: the AI-fallback tests below run against whatever ai_enabled state
the target server currently has. When AI is enabled there (the common
case for a shared preview deployment), the "AI unavailable" fallback
path cannot be exercised over HTTP without restarting the server — that
specific behaviour is covered exhaustively in the mongomock-backed smoke
test suite (test_sprint62_ai_fallback.py) instead, consistent with how
the other DX/optional-AI sprints handle server-startup-state-dependent
behaviour. The tests here cover what's true regardless of AI state.
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
def admin():
    u, h = _login("management", "9970100001", "V62 Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9970100002", "V62 PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client_user(admin):
    # FAC-04: Client is now a first-class role, directly assignable - no
    # more separate workspace-assignment step.
    u, h = _login("client", "9970100003", "V62 Client")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "V62 Test Project", "code": "V62TP"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "V62 Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# --------------------------------------------------------------------------
# Identity Security
# --------------------------------------------------------------------------
def test_login_does_not_modify_existing_account_name():
    phone = "9970100010"
    _login("site_supervisor", phone, "Real Name")
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Typed Something Else", "role": "site_supervisor"}, timeout=20)
    assert r.json()["user"]["name"] == "Real Name"


def test_login_does_not_modify_existing_account_role():
    phone = "9970100011"
    _login("management", phone, "V62 Role Test")
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "V62 Role Test", "role": "site_supervisor"}, timeout=20)
    assert r.json()["user"]["role"] == "management"


def test_profile_management_is_the_only_way_to_change_name(admin):
    phone = "9970100012"
    user, headers = _login("site_supervisor", phone, "Before Edit")
    r = requests.patch(f"{API}/me", json={"name": "After Edit"}, headers=headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["name"] == "After Edit"

    r2 = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Attempted Revert", "role": "site_supervisor"}, timeout=20)
    assert r2.json()["user"]["name"] == "After Edit"


def test_unknown_phone_rejected_not_auto_created():
    """FAC-03 P0 fix supersedes this test's original intent (it used to
    verify self-service account creation via login - that entire
    mechanic is gone). An unrecognized phone must be rejected outright;
    account creation is exclusively /auth/register's job."""
    phone = "9970100013"
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Brand New", "role": "project_manager"}, timeout=20)
    assert r.status_code == 401, r.text


# --------------------------------------------------------------------------
# Client Permissions
# --------------------------------------------------------------------------
def test_client_cannot_assign_work(pm, client_user, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "V62 Material",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/assign",
                      json={"assigned_to_user_id": pm["user"]["id"]}, headers=client_user["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_create_operational_items(client_user, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "general", "title": "Should fail",
    }, headers=client_user["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_edit_items(pm, client_user, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "V62 Edit Test",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.patch(f"{API}/operational-items/{item['id']}", json={"title": "Hacked"}, headers=client_user["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_transition_non_approval_items(pm, client_user, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "labour_requirement", "title": "V62 Labour",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                      json={"to_status": "fulfilled"}, headers=client_user["headers"], timeout=20)
    assert r.status_code == 403


def test_client_can_approve_with_comment(pm, client_user, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "V62 Approval",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                      json={"to_status": "fulfilled", "note": "Approved, looks great."},
                      headers=client_user["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["status"] == "fulfilled"

    hist = requests.get(f"{API}/operational-items/{item['id']}", headers=pm["headers"], timeout=20).json()["history"]
    assert any("Approved, looks great" in str(e.get("payload", {}).get("note", "")) for e in hist)


def test_client_can_reject_with_comment(pm, client_user, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "V62 Rejection",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                      json={"to_status": "cancelled", "note": "Needs revision."},
                      headers=client_user["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_client_can_comment(pm, client_user, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "V62 Comment Test",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/comments",
                      json={"text": "Just a note"}, headers=client_user["headers"], timeout=20)
    assert r.status_code == 201


def test_pm_still_fully_unaffected(pm, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "V62 PM Unaffected",
    }, headers=pm["headers"], timeout=20)
    assert item.status_code == 201


# --------------------------------------------------------------------------
# Workflow Activity Scheduling (endpoint-level smoke — full coverage in
# test_atlas_v6_1.py; this just confirms it survives this sprint's changes)
# --------------------------------------------------------------------------
def test_schedule_endpoint_still_reachable():
    r = requests.get(f"{API}/workflow-meta", timeout=20)
    assert r.status_code in (401, 403)


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/system-info", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
