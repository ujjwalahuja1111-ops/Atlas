"""Project Atlas — Canonical Event UX Patch: Timeline Planning
(Events) and Assignment Timeline (Operational Items).

Covers the two backend additions this patch made:

1. PATCH /events/{id}/timeline — planned/actual start/finish on
   events. Record Time (client_created_at/server_created_at) is
   untouched by this feature entirely. Workflow-aware: an event
   linked to a workflow activity redirects to the existing, unmodified
   workflow_engine.set_schedule() instead of storing a duplicate copy
   - "Workflow remains the scheduling source of truth."

2. POST /operational-items/{id}/assign (extended) and the new
   POST /operational-items/{id}/target-timeline — Target Start +
   Target Finish (reusing the pre-existing required_by field) with
   Start+Finish / Start+Duration / Finish+Duration auto-derivation.
   Deliberately does not re-test that required_by feeds existing CRE
   reasoning (material lead-time, frontier-gap rules) - that reasoning
   is untouched and already covered by tests/test_cre_rules.py; this
   file only confirms the new write path populates the same field
   those rules already read.

Both endpoints are gated to management/project_manager only, matching
the brief's RBAC table (Site Supervisor and Client both "cannot
modify planning").
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
                          json={"phone": _SEEDED_ADMIN_PHONE, "name": "Atlas Admin 1", "role": "management"},
                          timeout=20)
        assert r.status_code == 200, f"Seeded admin not found - has the environment been seeded? {r.text}"
        _seeded_admin_cache["headers"] = {"Authorization": f"Bearer {r.json()['token']}"}
    return _seeded_admin_cache["headers"]


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    if r.status_code == 200:
        b = r.json()
        return b["user"], {"Authorization": f"Bearer {b['token']}"}
    reg = requests.post(f"{API}/auth/register", json={"phone": phone, "name": name}, timeout=20)
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["user"]["id"]
    admin_headers = _seeded_admin_headers()
    requests.post(f"{API}/admin/users/{user_id}/approve", headers=admin_headers, timeout=20)
    requests.post(f"{API}/admin/users/{user_id}/role", json={"role": role}, headers=admin_headers, timeout=20)
    r2 = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r2.status_code == 200, r2.text
    b = r2.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9998800001", "CEUX Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9998800002", "CEUX PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9998800003", "CEUX Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9998800004", "CEUX Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "CEUX Test Project", "code": "CEUXTP"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "CEUX Test Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# ==========================================================================
# Event Timeline Planning
# ==========================================================================
def test_event_created_with_null_timeline_fields(admin, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Timeline test event"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    event = r.json()
    assert event["planned_start"] is None
    assert event["planned_finish"] is None
    assert event["actual_start"] is None
    assert event["actual_finish"] is None


def test_get_event_includes_resolved_timeline(admin, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "x"},
                          headers=admin["headers"], timeout=20).json()
    r = requests.get(f"{API}/events/{event['id']}", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["timeline"]["source"] == "event"


def test_pm_can_set_standalone_event_timeline(admin, pm, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "x"},
                          headers=admin["headers"], timeout=20).json()
    r = requests.patch(f"{API}/events/{event['id']}/timeline",
                       json={"planned_start": "2026-09-01T00:00:00+00:00", "planned_finish": "2026-09-05T00:00:00+00:00"},
                       headers=pm["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["planned_start"] == "2026-09-01T00:00:00+00:00"
    assert r.json()["planned_finish"] == "2026-09-05T00:00:00+00:00"


@pytest.mark.parametrize("role_fixture", ["supervisor", "client"])
def test_non_pm_roles_cannot_edit_event_timeline(request, project_and_site, role_fixture):
    _, site = project_and_site
    admin_h = request.getfixturevalue("admin")["headers"]
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "x"},
                          headers=admin_h, timeout=20).json()
    actor = request.getfixturevalue(role_fixture)
    r = requests.patch(f"{API}/events/{event['id']}/timeline",
                       json={"planned_start": "2026-01-01T00:00:00Z"}, headers=actor["headers"], timeout=20)
    assert r.status_code == 403


def test_timeline_update_requires_at_least_one_field(admin, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "x"},
                          headers=admin["headers"], timeout=20).json()
    r = requests.patch(f"{API}/events/{event['id']}/timeline", json={}, headers=admin["headers"], timeout=20)
    assert r.status_code == 400


# ==========================================================================
# Assignment Timeline
# ==========================================================================
def test_item_created_with_null_target_start(admin, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Cement",
    }, headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    assert r.json()["target_start"] is None


def test_assign_with_start_and_duration_derives_finish(admin, pm, project_and_site):
    proj, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Steel",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/assign", json={
        "assigned_to_user_id": pm["user"]["id"],
        "target_start": "2026-09-01T00:00:00+00:00",
        "duration_days": 4,
    }, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["target_start"] == "2026-09-01T00:00:00+00:00"
    assert body["required_by"].startswith("2026-09-05")


def test_assign_with_finish_and_duration_derives_start(admin, pm, project_and_site):
    proj, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Bricks",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/assign", json={
        "assigned_to_user_id": pm["user"]["id"],
        "target_finish": "2026-09-20T00:00:00+00:00",
        "duration_days": 2,
    }, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["required_by"] == "2026-09-20T00:00:00+00:00"
    assert body["target_start"].startswith("2026-09-18")


def test_standalone_target_timeline_partial_update_preserves_other_field(admin, pm, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Sand",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{item['id']}/assign", json={
        "assigned_to_user_id": pm["user"]["id"], "target_start": "2026-09-01T00:00:00+00:00", "duration_days": 3,
    }, headers=admin["headers"], timeout=20)

    r = requests.post(f"{API}/operational-items/{item['id']}/target-timeline",
                      json={"target_finish": "2026-09-15T00:00:00+00:00"}, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["required_by"] == "2026-09-15T00:00:00+00:00"
    assert body["target_start"] == "2026-09-01T00:00:00+00:00", \
        "a partial update (finish only) must not clear the already-set target_start"


def test_target_timeline_requires_at_least_one_field(admin, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Paint",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/target-timeline", json={},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 400


def test_supervisor_cannot_set_target_timeline(admin, supervisor, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Tiles",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/target-timeline",
                      json={"target_finish": "2026-01-01T00:00:00Z"}, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_assign_without_timeline_fields_unaffected(admin, pm, project_and_site):
    """Backward compatibility: assigning without any timeline fields
    behaves exactly as before this patch."""
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "safety_observation", "title": "Hazard",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/assign",
                      json={"assigned_to_user_id": pm["user"]["id"]}, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert body["assigned_to_user_id"] == pm["user"]["id"]
    assert body["target_start"] is None
    assert body["required_by"] is None


# ==========================================================================
# Regression - preserved systems
# ==========================================================================
def test_regression_workflow_and_cre_unaffected(admin, project_and_site):
    proj, _ = project_and_site
    assert requests.get(f"{API}/projects/{proj['id']}/workflow", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).status_code == 200


def test_regression_portfolio_control_center_unaffected(admin):
    r = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert set(r.json().keys()) == {"summary", "projects", "generated_at"}


def test_regression_client_approval_workflow_unaffected(admin, client, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve this"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()
    assert approval["category"] == "client_approval"
    r = requests.get(f"{API}/operational-items?category=client_approval&site_id={site['id']}",
                     headers=client["headers"], timeout=20)
    assert r.status_code == 200
    assert any(i["id"] == approval["id"] for i in r.json())
