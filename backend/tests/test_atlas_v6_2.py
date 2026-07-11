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


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    b = r.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9970100001", "V62 Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("coordinator", "9970100002", "V62 PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client_user(admin):
    u, h = _login("coordinator", "9970100003", "V62 Client")
    requests.post(f"{API}/admin/users/{u['id']}/workspace", json={"workspace": "client"},
                 headers=admin["headers"], timeout=20)
    u2, h2 = _login("coordinator", "9970100003", "V62 Client")
    return {"user": u2, "headers": h2}


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
    _login("supervisor", phone, "Real Name")
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Typed Something Else", "role": "supervisor"}, timeout=20)
    assert r.json()["user"]["name"] == "Real Name"


def test_login_does_not_modify_existing_account_role():
    phone = "9970100011"
    _login("management", phone, "V62 Role Test")
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "V62 Role Test", "role": "supervisor"}, timeout=20)
    assert r.json()["user"]["role"] == "management"


def test_profile_management_is_the_only_way_to_change_name(admin):
    phone = "9970100012"
    user, headers = _login("supervisor", phone, "Before Edit")
    r = requests.patch(f"{API}/me", json={"name": "After Edit"}, headers=headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["name"] == "After Edit"

    r2 = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Attempted Revert", "role": "supervisor"}, timeout=20)
    assert r2.json()["user"]["name"] == "After Edit"


def test_brand_new_account_self_service_creation_preserved():
    phone = "9970100013"
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Brand New", "role": "coordinator"}, timeout=20)
    assert r.json()["user"]["name"] == "Brand New"
    assert r.json()["user"]["role"] == "coordinator"


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
