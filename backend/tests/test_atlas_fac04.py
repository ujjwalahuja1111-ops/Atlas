"""Project Atlas — FAC-04: Final Authorization Model Freeze.

Validates:
  * Four first-class backend roles: management, project_manager,
    site_supervisor, client - with zero permission inheritance between
    project_manager and client (the root problem this sprint exists to
    fix - they used to share the generic "coordinator" role).
  * Role assignment automatically derives the one correct workspace -
    there is no longer a separate, independent "assign workspace" action
    (the endpoint is removed entirely).
  * Client permission enforcement, backend AND frontend-facing contract:
    a client can never assign/reassign/edit/escalate/acknowledge/start/
    complete work or capture events: only approve/reject/comment on
    client_approval items and view.
  * Project Manager can manage assigned projects and operational work,
    but not administer users or manage system configuration.
  * Site Supervisor can execute assigned work but not assign work or
    manage/approve users.
  * Admin retains full administrative access.
  * Workspace routing for all four roles.
  * Regression: existing projects/workflows continue functioning.
"""
import os
import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or
        "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

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
    u, h = _login("management", "9995000001", "FAC04 Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9995000002", "FAC04 PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9995000003", "FAC04 Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9995000004", "FAC04 Client")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "FAC04 Test Project", "code": "FAC04TP"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "FAC04 Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# --------------------------------------------------------------------------
# Four first-class roles, zero inheritance between project_manager and client
# --------------------------------------------------------------------------
def test_client_is_directly_assignable_as_a_role(admin):
    """The root fix: Client is a first-class role, not a workspace layered
    on top of 'coordinator'."""
    user, _ = _login("project_manager", "9995000010", "FAC04 Role Test")
    r = requests.post(f"{API}/admin/users/{user['id']}/role", json={"role": "client"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["role"] == "client"
    assert r.json()["workspace"] == "client"


def test_role_assignment_rejects_the_removed_generic_role(admin):
    user, _ = _login("client", "9995000011", "FAC04 Reject Test")
    r = requests.post(f"{API}/admin/users/{user['id']}/role", json={"role": "coordinator"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code in (400, 422)


def test_workspace_assignment_endpoint_no_longer_exists(admin):
    user, _ = _login("client", "9995000012", "FAC04 Endpoint Test")
    r = requests.post(f"{API}/admin/users/{user['id']}/workspace", json={"workspace": "pm"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Routing: each role reflects its correct workspace
# --------------------------------------------------------------------------
@pytest.mark.parametrize("role,expected_workspace", [
    ("management", "admin"),
    ("project_manager", "pm"),
    ("site_supervisor", "supervisor"),
    ("client", "client"),
])
def test_role_routes_to_correct_workspace(role, expected_workspace):
    phone = f"999500002{['management','project_manager','site_supervisor','client'].index(role)}"
    user, headers = _login(role, phone, f"FAC04 Routing {role}")
    assert user["role"] == role
    assert user["workspace"] == expected_workspace
    me = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert me.json()["workspace"] == expected_workspace


# --------------------------------------------------------------------------
# Client: may only view/approve/reject/comment; never anything operational
# --------------------------------------------------------------------------
def test_client_cannot_capture_events(client, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Client trying to capture"},
                      headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_assign_or_reassign_work(pm, client, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC04 Assign Test",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/assign",
                      json={"assigned_to_user_id": pm["user"]["id"]}, headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_edit_operational_items(pm, client, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC04 Edit Test",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.patch(f"{API}/operational-items/{item['id']}", json={"title": "Hacked"}, headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_acknowledge_start_or_complete_work(pm, client, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC04 Lifecycle Test",
    }, headers=pm["headers"], timeout=20).json()
    for target in ("acknowledged", "in_progress", "fulfilled"):
        r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                          json={"to_status": target}, headers=client["headers"], timeout=20)
        assert r.status_code == 403, f"client should not reach {target}"


def test_client_cannot_escalate_work(pm, client, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC04 Escalate Test",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/escalate", json={"reason": "test"}, headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_client_can_approve_reject_and_comment(pm, client, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "FAC04 Approval Test",
    }, headers=pm["headers"], timeout=20).json()
    r1 = requests.post(f"{API}/operational-items/{item['id']}/transition",
                       json={"to_status": "fulfilled", "note": "Looks good."}, headers=client["headers"], timeout=20)
    assert r1.status_code == 200

    item2 = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "FAC04 Rejection Test",
    }, headers=pm["headers"], timeout=20).json()
    r2 = requests.post(f"{API}/operational-items/{item2['id']}/transition",
                       json={"to_status": "cancelled", "note": "Needs revision."}, headers=client["headers"], timeout=20)
    assert r2.status_code == 200

    r3 = requests.post(f"{API}/operational-items/{item2['id']}/comments", json={"text": "extra note"}, headers=client["headers"], timeout=20)
    assert r3.status_code == 201


def test_client_can_view_project_progress(client, project_and_site):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects", headers=client["headers"], timeout=20)
    assert r.status_code == 200


# --------------------------------------------------------------------------
# Project Manager: may manage assigned projects, assign work, review
# proposals; must not administer users or manage system config
# --------------------------------------------------------------------------
def test_pm_can_assign_operational_work(pm, supervisor, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC04 PM Assign Test",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/assign",
                      json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=pm["headers"], timeout=20)
    assert r.status_code == 200


def test_pm_can_manage_projects(pm):
    r = requests.post(f"{API}/projects", json={"name": "FAC04 PM-Managed Project", "code": "FAC04PMP"},
                      headers=pm["headers"], timeout=20)
    assert r.status_code == 200


def test_pm_cannot_administer_users(pm):
    r = requests.get(f"{API}/admin/users", headers=pm["headers"], timeout=20)
    assert r.status_code == 403


def test_pm_cannot_manage_system_configuration(pm):
    r = requests.get(f"{API}/admin/system-info", headers=pm["headers"], timeout=20)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Site Supervisor: may execute assigned work; must not assign/manage/approve users
# --------------------------------------------------------------------------
def test_supervisor_can_execute_assigned_work(pm, supervisor, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC04 Execute Test",
    }, headers=pm["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{item['id']}/assign",
                 json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=pm["headers"], timeout=20)
    r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                      json={"to_status": "acknowledged"}, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 200


def test_supervisor_can_capture_events(supervisor, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Supervisor capture"},
                      headers=supervisor["headers"], timeout=20)
    assert r.status_code == 201


def test_supervisor_cannot_assign_work(supervisor, pm, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC04 Sup Assign Test",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/assign",
                      json={"assigned_to_user_id": pm["user"]["id"]}, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_supervisor_cannot_manage_users(supervisor):
    r = requests.get(f"{API}/admin/users", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_supervisor_cannot_approve_users(supervisor):
    fresh = requests.post(f"{API}/auth/register", json={"phone": "9995000099", "name": "Approve Target"}, timeout=20)
    target_id = fresh.json()["user"]["id"]
    r = requests.post(f"{API}/admin/users/{target_id}/approve", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Admin retains full administrative access
# --------------------------------------------------------------------------
def test_admin_retains_full_administration(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/admin/users", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/system-info", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert requests.post(f"{API}/projects", json={"name": "FAC04 Admin Project", "code": "FAC04AP"},
                         headers=h, timeout=20).status_code == 200


# --------------------------------------------------------------------------
# Regression: existing workflows and seeded data continue functioning
# --------------------------------------------------------------------------
def test_seeded_users_have_correct_roles_and_can_login():
    """Verifies the exact founder-required distribution: 2 Management,
    2 Project Managers, 2 Site Supervisors, 2 Clients."""
    seeded = [
        ("9000000001", "management", "admin"), ("9000000002", "management", "admin"),
        ("9000000011", "project_manager", "pm"), ("9000000012", "project_manager", "pm"),
        ("9000000021", "site_supervisor", "supervisor"), ("9000000022", "site_supervisor", "supervisor"),
        ("9000000031", "client", "client"), ("9000000032", "client", "client"),
    ]
    for phone, expected_role, expected_workspace in seeded:
        r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "x", "role": "site_supervisor"}, timeout=20)
        assert r.status_code == 200, f"seeded user {phone} failed to log in: {r.text}"
        assert r.json()["user"]["role"] == expected_role, f"{phone}: expected role {expected_role}, got {r.json()['user']['role']}"
        assert r.json()["user"]["workspace"] == expected_workspace


def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
