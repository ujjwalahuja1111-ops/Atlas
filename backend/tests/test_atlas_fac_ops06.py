"""Project Atlas — FAC-OPS-06: Assignee role display, assignment
visibility, voice/text updates, and assignment eligibility.

Validates:
  * GET /api/users returns the CURRENT backend role for every user
    (freshness was a frontend-caching bug, not a backend one - see
    frontend/app/(tabs)/ops.tsx and app/op/[id].tsx's loadUsers/
    openAssign fixes; this file confirms the backend always served
    fresh data, which the fix depends on).
  * Items assigned to Management, Project Manager, or Supervisor all
    appear in that user's assigned_to_me query.
  * Text updates on operational items reuse the exact same
    voice_update_item ledger entry and response shape as voice updates
    (no second, separate mechanism).
  * Assignment eligibility: only active, correctly-roled, same-project
    users can be listed as candidates or actually assigned - enforced
    identically by the picker listing and the assign action.
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


def _register_approve_assign_role(admin_headers, phone, name, role):
    reg = requests.post(f"{API}/auth/register", json={"phone": phone, "name": name}, timeout=20)
    assert reg.status_code == 200, reg.text
    uid = reg.json()["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/approve", headers=admin_headers, timeout=20)
    requests.post(f"{API}/admin/users/{uid}/role", json={"role": role}, headers=admin_headers, timeout=20)
    login = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert login.status_code == 200, login.text
    return login.json()["user"], {"Authorization": f"Bearer {login.json()['token']}"}


@pytest.fixture(scope="session")
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "FAC-OPS-06 Project", "code": "FOPS06P"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "FAC-OPS-06 Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# --------------------------------------------------------------------------
# 1. Assignee role is always current (backend freshness)
# --------------------------------------------------------------------------
def test_users_endpoint_reflects_role_change_immediately(admin):
    user, _ = _register_approve_assign_role(admin["headers"], "9993200001", "FOPS06 Role Test", "site_supervisor")
    requests.post(f"{API}/admin/users/{user['id']}/role", json={"role": "management"},
                 headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/users", headers=admin["headers"], timeout=20)
    match = next((u for u in r.json() if u["id"] == user["id"]), None)
    assert match is not None
    assert match["role"] == "management", f"GET /api/users must always reflect the current role, got {match}"


# --------------------------------------------------------------------------
# 2. Assignment visibility for every operational role
# --------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["management", "project_manager", "site_supervisor"])
def test_assigned_item_appears_in_assigned_to_me(admin, project_and_site, role):
    _, site = project_and_site
    assignee, assignee_headers = _register_approve_assign_role(
        admin["headers"], f"999320{['management','project_manager','site_supervisor'].index(role)}002", f"FOPS06 {role}", role)
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": f"For {role}",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{item['id']}/assign",
                 json={"assigned_to_user_id": assignee["id"]}, headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/operational-items?assigned_to_me=true", headers=assignee_headers, timeout=20)
    assert any(i["id"] == item["id"] for i in r.json())


# --------------------------------------------------------------------------
# 3. Text updates reuse the exact same mechanism as voice
# --------------------------------------------------------------------------
def test_text_update_creates_the_same_ledger_shape_as_voice(admin, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC-OPS-06 Update Test",
    }, headers=admin["headers"], timeout=20).json()

    r = requests.post(f"{API}/operational-items/{item['id']}/voice-update",
                      data={"text": "Delivered 20 bags"}, headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    assert r.json()["transcript"] == "Delivered 20 bags"
    assert r.json()["audio_asset_id"] is None

    detail = requests.get(f"{API}/operational-items/{item['id']}", headers=admin["headers"], timeout=20).json()
    assert any(e.get("kind") == "voice_update" and e.get("payload", {}).get("transcript") == "Delivered 20 bags"
              for e in detail["history"])


def test_voice_update_still_requires_audio_or_text(admin, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC-OPS-06 Empty Update Test",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/voice-update", data={}, headers=admin["headers"], timeout=20)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# 4. Assignment eligibility
# --------------------------------------------------------------------------
def test_ineligible_client_never_listed_or_assignable(admin, project_and_site):
    proj, site = project_and_site
    client_user, _ = _register_approve_assign_role(admin["headers"], "9993200010", "FOPS06 Client", "client")

    r = requests.get(f"{API}/users?project_id={proj['id']}", headers=admin["headers"], timeout=20)
    assert not any(u["id"] == client_user["id"] for u in r.json()), "client must never be listed as an eligible assignee"

    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC-OPS-06 Client Assign Test",
    }, headers=admin["headers"], timeout=20).json()
    r2 = requests.post(f"{API}/operational-items/{item['id']}/assign",
                       json={"assigned_to_user_id": client_user["id"]}, headers=admin["headers"], timeout=20)
    assert r2.status_code == 400


def test_inactive_user_never_listed_or_assignable(admin, project_and_site):
    proj, site = project_and_site
    user, _ = _register_approve_assign_role(admin["headers"], "9993200011", "FOPS06 Inactive", "site_supervisor")
    requests.post(f"{API}/admin/users/{user['id']}/active", json={"is_active": False},
                 headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/users?project_id={proj['id']}", headers=admin["headers"], timeout=20)
    assert not any(u["id"] == user["id"] for u in r.json())

    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC-OPS-06 Inactive Assign Test",
    }, headers=admin["headers"], timeout=20).json()
    r2 = requests.post(f"{API}/operational-items/{item['id']}/assign",
                       json={"assigned_to_user_id": user["id"]}, headers=admin["headers"], timeout=20)
    assert r2.status_code == 400


def test_cross_project_assignment_impossible(admin):
    proj_a = requests.post(f"{API}/projects", json={"name": "FAC-OPS-06 Cross A", "code": "FOPS06CA"},
                           headers=admin["headers"], timeout=20).json()
    proj_b = requests.post(f"{API}/projects", json={"name": "FAC-OPS-06 Cross B", "code": "FOPS06CB"},
                           headers=admin["headers"], timeout=20).json()
    site_a = requests.post(f"{API}/sites", json={"project_id": proj_a["id"], "name": "Site A"},
                           headers=admin["headers"], timeout=20).json()

    user, _ = _register_approve_assign_role(admin["headers"], "9993200012", "FOPS06 Cross Project", "site_supervisor")
    requests.post(f"{API}/admin/users/{user['id']}/projects", json={"project_ids": [proj_b["id"]]},
                 headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/users?project_id={proj_a['id']}", headers=admin["headers"], timeout=20)
    assert not any(u["id"] == user["id"] for u in r.json()), "a user scoped to Project B must not appear for Project A"

    item = requests.post(f"{API}/operational-items", json={
        "site_id": site_a["id"], "category": "material_requirement", "title": "FAC-OPS-06 Cross Assign Test",
    }, headers=admin["headers"], timeout=20).json()
    r2 = requests.post(f"{API}/operational-items/{item['id']}/assign",
                       json={"assigned_to_user_id": user["id"]}, headers=admin["headers"], timeout=20)
    assert r2.status_code == 400, "cross-project assignment must be impossible"


def test_eligible_user_still_assignable(admin, project_and_site):
    proj, site = project_and_site
    user, _ = _register_approve_assign_role(admin["headers"], "9993200013", "FOPS06 Eligible", "project_manager")
    r = requests.get(f"{API}/users?project_id={proj['id']}", headers=admin["headers"], timeout=20)
    assert any(u["id"] == user["id"] for u in r.json())

    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC-OPS-06 Eligible Assign Test",
    }, headers=admin["headers"], timeout=20).json()
    r2 = requests.post(f"{API}/operational-items/{item['id']}/assign",
                       json={"assigned_to_user_id": user["id"]}, headers=admin["headers"], timeout=20)
    assert r2.status_code == 200


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/users", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
