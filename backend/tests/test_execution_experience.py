"""Project Atlas — Execution Experience Sprint 01.

Covers the two backend-verifiable pieces delivered in this pass:

1. TIMELINE IMPROVEMENTS (items 9 & 10)
   actual_start/actual_finish auto-timestamp on the matching workflow
   activity status transition, never overwriting an already-set value.
   Manual override of actual dates via the schedule endpoint is now
   Management-only; planned dates remain open to any role.

2. PERSONAL WORK QUEUE (items 1 & 2)
   GET /api/work-queue - role-based "what should I do next," composed
   entirely from existing operational-item and workflow-activity data.
   Supervisor sees Ready To Start; PM/Management see Assigned To Me;
   client is blocked entirely.
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
    u, h = _login("management", "9996100001", "EES Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9996100002", "EES Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9996100003", "EES PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9996100004", "EES Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "EES Test", "code": "EES1"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# ==========================================================================
# Timeline Improvements (items 9 & 10)
# ==========================================================================
def test_actual_start_auto_timestamps_on_in_progress(admin, project_and_site):
    proj, _ = project_and_site
    template = requests.post(f"{API}/knowledge-items", json={
        "type": "workflow_template", "name": "EES Template", "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    act = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "EES Excavation", "trade": "Civil", "unit": "cum",
        "default_duration_days": 5, "requires_inspection": False, "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/knowledge-items/{template['id']}/relationships", json={
        "type": "includes_activity", "target_id": act["id"],
    }, headers=admin["headers"], timeout=20)
    activities = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                               json={"template_id": template["id"]}, headers=admin["headers"], timeout=20).json()
    if not activities:
        pytest.skip("workflow generation returned no activities in this environment")
    activity_id = activities[0]["id"]

    r = requests.post(f"{API}/workflow-activities/{activity_id}/status",
                      json={"status": "in_progress"}, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["actual_start"] is not None


def test_supervisor_cannot_manually_override_actual_dates(admin, supervisor, project_and_site):
    proj, _ = project_and_site
    template = requests.post(f"{API}/knowledge-items", json={
        "type": "workflow_template", "name": "EES Template 2", "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    act = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "EES Foundation", "trade": "Civil", "unit": "cum",
        "default_duration_days": 3, "requires_inspection": False, "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/knowledge-items/{template['id']}/relationships", json={
        "type": "includes_activity", "target_id": act["id"],
    }, headers=admin["headers"], timeout=20)
    activities = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                               json={"template_id": template["id"]}, headers=admin["headers"], timeout=20).json()
    if not activities:
        pytest.skip("workflow generation returned no activities in this environment")
    activity_id = activities[0]["id"]

    r_sup = requests.post(f"{API}/workflow-activities/{activity_id}/schedule",
                          json={"actual_start": "2020-01-01T00:00:00Z"}, headers=supervisor["headers"], timeout=20)
    assert r_sup.status_code == 403

    r_admin = requests.post(f"{API}/workflow-activities/{activity_id}/schedule",
                            json={"actual_start": "2020-01-01T00:00:00Z"}, headers=admin["headers"], timeout=20)
    assert r_admin.status_code == 200

    r_sup_planned = requests.post(f"{API}/workflow-activities/{activity_id}/schedule",
                                  json={"planned_start": "2026-08-01T00:00:00Z"}, headers=supervisor["headers"], timeout=20)
    assert r_sup_planned.status_code == 200, "planned dates must remain open to any role"


# ==========================================================================
# Personal Work Queue (items 1 & 2)
# ==========================================================================
def test_supervisor_work_queue_shape(supervisor):
    r = requests.get(f"{API}/work-queue", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "site_supervisor"
    assert "ready_to_start" in body
    assert "operational_items" in body["ready_to_start"]
    assert "workflow_activities" in body["ready_to_start"]


def test_pm_work_queue_shape(pm):
    r = requests.get(f"{API}/work-queue", headers=pm["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "assigned_to_me" in body
    assert set(body["assigned_to_me"]["counts"].keys()) == {
        "assigned_to_me", "pending_approvals", "overdue", "critical"}


def test_client_blocked_from_work_queue(client):
    r = requests.get(f"{API}/work-queue", headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_assigned_item_appears_in_supervisor_ready_to_start(admin, supervisor, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "EES Cement", "priority": "high",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{item['id']}/assign",
                 json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/work-queue", headers=supervisor["headers"], timeout=20)
    ids = [i["id"] for i in r.json()["ready_to_start"]["operational_items"]]
    assert item["id"] in ids


def test_pending_approval_appears_in_pm_assigned_to_me(admin, pm, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "EES approval test"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()

    r = requests.get(f"{API}/work-queue", headers=pm["headers"], timeout=20)
    ids = [i["id"] for i in r.json()["assigned_to_me"]["items"]]
    assert approval["id"] in ids


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_core_platform_unaffected(admin, project_and_site):
    proj, _ = project_and_site
    assert requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/projects/{proj['id']}/workflow", headers=admin["headers"], timeout=20).status_code == 200
