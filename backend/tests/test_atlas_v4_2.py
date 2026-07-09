"""Project Atlas V4.2 — Sprint 4.2: Admin Experience tests.

Validates:
  * GET /api/admin/system-info — admin-gated, returns every required field
    (version, git_commit, build_date, backend_status, database_status,
    total_users, total_projects, total_sites, pending_approvals), reflects
    live counts as data changes
  * No existing Sprint 1-4.1 endpoint's contract changed — this sprint adds
    exactly one new backend endpoint and zero frontend-visible backend
    behaviour changes to anything else

This file only covers what's new in Sprint 4.2. User Management CRUD
(approve/reject/assign role/assign projects/activate-deactivate) already
has full coverage in test_atlas_v4_1.py and is unchanged by this sprint —
Search, View Details, and CSV export are frontend-only additions with no
new backend surface, so they have no corresponding backend test here.
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
def supervisor():
    u, h = _login("supervisor", "9999955555", "V42 Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9999944444", "V42 Admin")
    return {"user": u, "headers": h}


# --------------------------------------------------------------------------
# System Information — admin gating
# --------------------------------------------------------------------------
def test_system_info_requires_admin(supervisor):
    r = requests.get(f"{API}/admin/system-info", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_system_info_requires_auth():
    r = requests.get(f"{API}/admin/system-info", timeout=20)
    assert r.status_code == 401


# --------------------------------------------------------------------------
# System Information — response shape
# --------------------------------------------------------------------------
def test_system_info_returns_all_required_fields(admin):
    r = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    required_fields = [
        "project_name", "version", "git_commit", "build_date",
        "server_started_at", "uptime_seconds", "backend_status",
        "database_status", "total_users", "total_projects",
        "total_sites", "pending_approvals",
    ]
    for field in required_fields:
        assert field in body, f"missing field: {field}"


def test_system_info_backend_and_database_status(admin):
    r = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20)
    body = r.json()
    assert body["backend_status"] == "healthy"
    assert body["database_status"] == "connected"


def test_system_info_counts_are_non_negative_integers(admin):
    r = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20)
    body = r.json()
    for field in ["total_users", "total_projects", "total_sites", "pending_approvals", "uptime_seconds"]:
        assert isinstance(body[field], int), f"{field} should be an int, got {type(body[field])}"
        assert body[field] >= 0


def test_system_info_version_matches_app_version(admin):
    r = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20)
    body = r.json()
    assert body["version"] == "2.0.0"
    assert body["project_name"] == "Project Atlas"


# --------------------------------------------------------------------------
# System Information — counts reflect live data
# --------------------------------------------------------------------------
def test_pending_approvals_reflects_new_signups(admin):
    before = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/auth/register", json={"phone": "9888800001", "name": "V42 Signup"}, timeout=20)
    after = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20).json()
    assert after["pending_approvals"] >= before["pending_approvals"] + 1


def test_total_users_reflects_new_accounts(admin):
    before = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/auth/login", json={"phone": "9888800002", "name": "V42 New Login", "role": "supervisor"}, timeout=20)
    after = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20).json()
    assert after["total_users"] >= before["total_users"] + 1


def test_total_projects_reflects_new_project(admin):
    before = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/projects", json={"name": "V42 Project", "code": "V42P"}, headers=admin["headers"], timeout=20)
    after = requests.get(f"{API}/admin/system-info", headers=admin["headers"], timeout=20).json()
    assert after["total_projects"] >= before["total_projects"] + 1


# --------------------------------------------------------------------------
# Regression: Sprint 1-4.1 endpoints and User Management unaffected
# --------------------------------------------------------------------------
def test_regression_sprint_1_4_1_endpoints(supervisor, admin):
    h = supervisor["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/", timeout=20).status_code == 200

    ah = admin["headers"]
    assert requests.get(f"{API}/admin/users", headers=ah, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users?approval_status=pending", headers=ah, timeout=20).status_code == 200


def test_regression_existing_user_management_endpoints_unchanged(admin):
    h = admin["headers"]
    reg = requests.post(f"{API}/auth/register", json={"phone": "9888800003", "name": "V42 Regression"}, timeout=20).json()
    uid = reg["user"]["id"]
    assert requests.post(f"{API}/admin/users/{uid}/approve", headers=h, timeout=20).status_code == 200
    assert requests.post(f"{API}/admin/users/{uid}/role", json={"role": "coordinator"}, headers=h, timeout=20).status_code == 200
    assert requests.post(f"{API}/admin/users/{uid}/active", json={"is_active": False}, headers=h, timeout=20).status_code == 200
