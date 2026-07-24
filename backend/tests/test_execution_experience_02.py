"""Project Atlas — Execution Experience Sprint 02.

Covers the two backend-verifiable pieces delivered in this pass:

1. ACTIVITY OWNERSHIP MODEL (item 1, highest priority)
   Workflow activities now support explicit assignment - a new
   /workflow-activities/{id}/assign endpoint mirroring operational
   items' existing assign pattern exactly (same RBAC allowlist, same
   eligibility check reused rather than reimplemented). Assignment
   history is retained on the activity document itself
   (assignment_history), and reassignment is supported (just calling
   assign again with a different assignee).

2. "MY DAY" DASHBOARD (item 6)
   GET /api/my-day - the full role-based execution dashboard replacing
   Sprint 01's /work-queue. Supervisor gets six sections (Ready To
   Start, In Progress, Due Today, Blocked, Waiting For Material,
   Recently Assigned); PM gets five (Projects Requiring Attention,
   Delayed Activities, Pending Approvals, High Priority Work,
   Escalations); Admin reuses Portfolio Control Center's own summary
   directly rather than recomputing portfolio health a second way.
"""
import os
import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or
        "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

_SEEDED_ADMIN_PHONE = "9000000001"
_seeded_admin_cache: dict = {}


def _seeded_admin_headers():
    if "headers" not in _seeded_admin_cache:
        r = requests.post(f"{API}/auth/login",
                          json={"phone": _SEEDED_ADMIN_PHONE, "role": "management"}, timeout=20)
        assert r.status_code == 200, f"Seeded admin not found - has the environment been seeded? {r.text}"
        _seeded_admin_cache["headers"] = {"Authorization": f"Bearer {r.json()['token']}"}
    return _seeded_admin_cache["headers"]


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "role": role}, timeout=20)
    if r.status_code == 200:
        b = r.json()
        return b["user"], {"Authorization": f"Bearer {b['token']}"}
    reg = requests.post(f"{API}/auth/register", json={"phone": phone, "name": name}, timeout=20)
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["user"]["id"]
    admin_headers = _seeded_admin_headers()
    requests.post(f"{API}/admin/users/{user_id}/approve", headers=admin_headers, timeout=20)
    requests.post(f"{API}/admin/users/{user_id}/role", json={"role": role}, headers=admin_headers, timeout=20)
    r2 = requests.post(f"{API}/auth/login", json={"phone": phone, "role": role}, timeout=20)
    assert r2.status_code == 200, r2.text
    b = r2.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9994400001", "EES2 Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9994400002", "EES2 Supervisor A")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor_b():
    u, h = _login("site_supervisor", "9994400003", "EES2 Supervisor B")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9994400004", "EES2 PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9994400005", "EES2 Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_and_site(admin, supervisor, supervisor_b, pm):
    proj = requests.post(f"{API}/projects", json={"name": "EES2 Test", "code": "EES2"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"},
                        headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/admin/users/{supervisor['user']['id']}/projects",
                 json={"project_ids": [proj["id"]]}, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{supervisor_b['user']['id']}/projects",
                 json={"project_ids": [proj["id"]]}, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{pm['user']['id']}/projects",
                 json={"project_ids": [proj["id"]]}, headers=admin["headers"], timeout=20)
    return proj, site


def _make_activity(admin, proj, name="EES2 Activity"):
    template = requests.post(f"{API}/knowledge-items", json={
        "type": "workflow_template", "name": f"{name} Template", "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    act = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": name, "trade": "Civil", "unit": "cum",
        "default_duration_days": 3, "requires_inspection": False, "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/knowledge-items/{template['id']}/relationships", json={
        "type": "includes_activity", "target_id": act["id"],
    }, headers=admin["headers"], timeout=20)
    activities = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                               json={"template_id": template["id"]}, headers=admin["headers"], timeout=20).json()
    return activities[0] if activities else None


# ==========================================================================
# Activity Ownership Model (item 1)
# ==========================================================================
def test_activity_created_unassigned(admin, project_and_site):
    proj, _ = project_and_site
    activity = _make_activity(admin, proj, "Unassigned Test")
    if not activity:
        pytest.skip("workflow generation returned no activities in this environment")
    assert activity["assigned_to_user_id"] is None
    assert activity["assignment_history"] == []


def test_assign_activity_to_supervisor(admin, supervisor, project_and_site):
    proj, _ = project_and_site
    activity = _make_activity(admin, proj, "Electrical Work")
    if not activity:
        pytest.skip("workflow generation returned no activities in this environment")
    r = requests.post(f"{API}/workflow-activities/{activity['id']}/assign",
                      json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["assigned_to_user_id"] == supervisor["user"]["id"]
    assert r.json()["assigned_at"] is not None


def test_reassignment_retains_history(admin, supervisor, supervisor_b, project_and_site):
    proj, _ = project_and_site
    activity = _make_activity(admin, proj, "Painting Work")
    if not activity:
        pytest.skip("workflow generation returned no activities in this environment")
    requests.post(f"{API}/workflow-activities/{activity['id']}/assign",
                 json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=admin["headers"], timeout=20)
    r = requests.post(f"{API}/workflow-activities/{activity['id']}/assign",
                      json={"assigned_to_user_id": supervisor_b["user"]["id"]}, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["assigned_to_user_id"] == supervisor_b["user"]["id"]
    assert len(body["assignment_history"]) == 2
    assert body["assignment_history"][0]["assigned_to_user_id"] == supervisor["user"]["id"]
    assert body["assignment_history"][1]["previous_assignee_id"] == supervisor["user"]["id"]


def test_unassign_activity(admin, supervisor, project_and_site):
    proj, _ = project_and_site
    activity = _make_activity(admin, proj, "Plumbing Work")
    if not activity:
        pytest.skip("workflow generation returned no activities in this environment")
    requests.post(f"{API}/workflow-activities/{activity['id']}/assign",
                 json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=admin["headers"], timeout=20)
    r = requests.post(f"{API}/workflow-activities/{activity['id']}/assign", json={}, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["assigned_to_user_id"] is None


def test_supervisor_cannot_assign_activities(supervisor, supervisor_b, project_and_site):
    proj, _ = project_and_site
    r = requests.post(f"{API}/workflow-activities/fake_id/assign",
                      json={"assigned_to_user_id": supervisor_b["user"]["id"]}, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_assign_activities(client):
    r = requests.post(f"{API}/workflow-activities/fake_id/assign", json={}, headers=client["headers"], timeout=20)
    assert r.status_code == 403


# ==========================================================================
# "My Day" Dashboard (item 6)
# ==========================================================================
def test_supervisor_my_day_shape(supervisor):
    r = requests.get(f"{API}/my-day", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "site_supervisor"
    for key in ("ready_to_start", "in_progress", "due_today", "blocked",
               "waiting_for_material", "recently_assigned"):
        assert key in body, f"missing section: {key}"


def test_pm_my_day_shape(pm):
    r = requests.get(f"{API}/my-day", headers=pm["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    for key in ("projects_requiring_attention", "delayed_activities",
               "pending_approvals", "high_priority_work", "escalations"):
        assert key in body, f"missing section: {key}"


def test_admin_my_day_reuses_portfolio_control_center(admin):
    r_myday = requests.get(f"{API}/my-day", headers=admin["headers"], timeout=20)
    r_pcc = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    assert r_myday.status_code == 200 and r_pcc.status_code == 200
    myday_health = r_myday.json()["portfolio_health"]
    pcc_summary = r_pcc.json()["summary"]
    assert myday_health == pcc_summary, "My Day must reuse Portfolio Control Center's summary exactly, not recompute it"


def test_client_blocked_from_my_day(client):
    r = requests.get(f"{API}/my-day", headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_assigned_activity_appears_in_supervisor_ready_to_start(admin, supervisor, project_and_site):
    proj, _ = project_and_site
    activity = _make_activity(admin, proj, "Ready Test Activity")
    if not activity:
        pytest.skip("workflow generation returned no activities in this environment")
    requests.post(f"{API}/workflow-activities/{activity['id']}/assign",
                 json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/my-day", headers=supervisor["headers"], timeout=20)
    ids = [a["id"] for a in r.json()["ready_to_start"]]
    assert activity["id"] in ids


def test_material_item_appears_in_waiting_for_material(admin, supervisor, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "EES2 Steel",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{item['id']}/assign",
                 json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/my-day", headers=supervisor["headers"], timeout=20)
    ids = [i["id"] for i in r.json()["waiting_for_material"]]
    assert item["id"] in ids


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_core_platform_unaffected(admin, project_and_site):
    proj, _ = project_and_site
    assert requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/projects/{proj['id']}/workflow", headers=admin["headers"], timeout=20).status_code == 200
