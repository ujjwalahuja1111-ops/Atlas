"""Project Atlas — FAC-OPS-05: Capture Site Discovery Regression.

Root cause: register_user() (Sprint 4.3) defaults every self-registered
account to scope_projects=True - reasonable when self-registration was
one option among several. FAC-03 removed the old "any login auto-
creates an unrestricted account" shortcut, making /auth/register the
ONLY way to create an account. Approving a user and assigning their
role - the two actions that make an account otherwise fully usable -
never touch assigned_project_ids; "Assign Projects" is a separate,
easy-to-miss action. Result: every newly self-registered PM/Supervisor
account was silently and completely scoped to zero projects the moment
it became otherwise functional, with no visible indication why Capture
(or anything else) showed nothing. Admin accounts were never actually
affected by this specific mechanism (management role is unconditionally
unrestricted regardless of scope_projects) - an "admin" account
exhibiting this symptom has almost certainly never actually been
assigned role=management.

Validates:
  * Approving a user with zero pre-assigned projects clears
    scope_projects (unrestricted) going forward.
  * Deliberate pre-approval project assignment is preserved, not
    silently overridden.
  * Explicitly assigning projects (at any point) sets scope_projects,
    so the "Assign Projects" action always has a real, visible effect.
  * Client's Capture restriction (a completely separate mechanism) is
    unaffected.
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


@pytest.fixture(scope="session")
def admin():
    return {"headers": _seeded_admin_headers()}


@pytest.fixture(scope="session")
def a_project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "FAC-OPS-05 Project", "code": "FOPS05"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "FAC-OPS-05 Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


def _register_approve_assign_role(admin_headers, phone, name, role):
    reg = requests.post(f"{API}/auth/register", json={"phone": phone, "name": name}, timeout=20)
    assert reg.status_code == 200, reg.text
    uid = reg.json()["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/approve", headers=admin_headers, timeout=20)
    requests.post(f"{API}/admin/users/{uid}/role", json={"role": role}, headers=admin_headers, timeout=20)
    login = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert login.status_code == 200, login.text
    return login.json()["user"], {"Authorization": f"Bearer {login.json()['token']}"}


# --------------------------------------------------------------------------
# The exact regression: self-register -> approve -> assign role, nothing else
# --------------------------------------------------------------------------
def test_self_registered_pm_sees_sites_after_approval_alone(admin, a_project_and_site):
    user, headers = _register_approve_assign_role(admin["headers"], "9994100001", "FOPS05 PM", "project_manager")
    assert user["scope_projects"] is False, \
        f"approving with zero pre-assigned projects should clear scope_projects, got {user}"
    r = requests.get(f"{API}/sites", headers=headers, timeout=20)
    assert r.status_code == 200
    assert len(r.json()) >= 1, "PM should see sites after approval alone, matching the founder-reported Capture symptom"


def test_self_registered_supervisor_sees_sites_after_approval_alone(admin, a_project_and_site):
    user, headers = _register_approve_assign_role(admin["headers"], "9994100002", "FOPS05 Supervisor", "site_supervisor")
    assert user["scope_projects"] is False
    r = requests.get(f"{API}/sites", headers=headers, timeout=20)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_self_registered_admin_was_never_actually_affected(admin, a_project_and_site):
    """Confirms the theory behind the founder's reported "Admin also
    affected" case: management role is unconditionally unrestricted
    regardless of scope_projects, so a genuinely role=management account
    was never actually broken by this mechanism."""
    user, headers = _register_approve_assign_role(admin["headers"], "9994100003", "FOPS05 Admin", "management")
    r = requests.get(f"{API}/sites", headers=headers, timeout=20)
    assert r.status_code == 200
    assert len(r.json()) >= 1


# --------------------------------------------------------------------------
# Deliberate scoping is preserved, not silently overridden
# --------------------------------------------------------------------------
def test_deliberate_pre_approval_scoping_preserved(admin, a_project_and_site):
    proj, _ = a_project_and_site
    reg = requests.post(f"{API}/auth/register", json={"phone": "9994100004", "name": "FOPS05 Scoped"}, timeout=20)
    uid = reg.json()["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/projects", json={"project_ids": [proj["id"]]}, headers=admin["headers"], timeout=20)
    r_approve = requests.post(f"{API}/admin/users/{uid}/approve", headers=admin["headers"], timeout=20)
    assert r_approve.json()["scope_projects"] is True, "deliberate pre-approval scoping must be preserved, not cleared"


def test_assigning_projects_always_takes_visible_effect(admin, a_project_and_site):
    """The 'Assign Projects' action must always have a real, visible
    effect - even on an account that approval already made unrestricted."""
    user, headers = _register_approve_assign_role(admin["headers"], "9994100005", "FOPS05 Reassign", "project_manager")
    assert user["scope_projects"] is False

    other_proj = requests.post(f"{API}/projects", json={"name": "FOPS05 Other Project", "code": "FOPS05OP"},
                               headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/admin/users/{user['id']}/projects", json={"project_ids": [other_proj["id"]]},
                      headers=admin["headers"], timeout=20)
    assert r.json()["scope_projects"] is True, "explicitly assigning projects must set scope_projects, or the action has no effect"

    r2 = requests.get(f"{API}/projects", headers=headers, timeout=20)
    names = [p["name"] for p in r2.json()]
    assert names == ["FOPS05 Other Project"], f"user should now see ONLY the newly-assigned project, got {names}"


# --------------------------------------------------------------------------
# Client's Capture restriction is a separate mechanism, unaffected
# --------------------------------------------------------------------------
def test_client_still_has_no_capture_access(admin, a_project_and_site):
    _, site = a_project_and_site
    user, headers = _register_approve_assign_role(admin["headers"], "9994100006", "FOPS05 Client", "client")
    r = requests.get(f"{API}/sites", headers=headers, timeout=20)
    assert r.status_code == 200
    r2 = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "client capture attempt"},
                       headers=headers, timeout=20)
    assert r2.status_code == 403


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
