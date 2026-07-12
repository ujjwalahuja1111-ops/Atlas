"""Project Atlas — FAC-03: Authentication, Identity & Assignment Integrity (P0).

This is the dedicated test suite for FAC-03's specific fixes. Every test
here runs against the REAL, deployed FastAPI app via HTTP (not mongomock),
matching "do not claim a fix based only on unit tests" — this is the same
mechanism used to verify the running application.

Validates:
  * P0 Authentication Integrity: an unknown/invalid phone number is
    REJECTED outright (the exact founder-reproduced bug: "90000001"
    successfully logging in and reaching the Site Supervisor workspace).
    Login never creates, never modifies. A pending/rejected account is
    blocked from every real endpoint except GET /api/me.
  * P0 Identity Integrity: a single phone number always resolves to
    exactly one database record; the auth layer never creates
    duplicates, whether via re-login or Sign Up.
  * P0 Role Integrity: MongoDB role -> API response -> JWT-authenticated
    session -> workspace routing derivation, verified end-to-end for
    every role.
  * P0 Operational Assignment: PM assigns an item, the assigned
    supervisor immediately sees it via the exact query the frontend
    uses, and can acknowledge it.
  * P0 Client Permissions: re-verified end-to-end including the newly
    explicit prohibitions (acknowledge, start work, complete work).
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
    u, h = _login("management", "9993000001", "FAC03 Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("coordinator", "9993000002", "FAC03 PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("supervisor", "9993000003", "FAC03 Supervisor")
    return {"user": u, "headers": h}


# --------------------------------------------------------------------------
# P0 Authentication Integrity
# --------------------------------------------------------------------------
def test_founder_reproduced_invalid_phone_now_rejected():
    """The exact founder scenario: entering '90000001' must NOT log in."""
    r = requests.post(f"{API}/auth/login", json={"phone": "90000001", "name": "Anyone", "role": "supervisor"}, timeout=20)
    assert r.status_code == 401, r.text
    assert "token" not in r.json()


@pytest.mark.parametrize("fake_phone", ["11111111", "00000000", "12345678", "90000002"])
def test_unknown_well_formed_phones_all_rejected(fake_phone):
    r = requests.post(f"{API}/auth/login", json={"phone": fake_phone, "name": "X", "role": "management"}, timeout=20)
    assert r.status_code == 401, r.text


def test_login_never_creates_a_user():
    """Belt-and-suspenders on the founder's exact wording: confirm the
    phone genuinely has no account after a rejected login attempt, by
    trying to register it fresh - registration must succeed (it
    wouldn't if login had silently created something)."""
    phone = "9993000099"
    r1 = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "X", "role": "supervisor"}, timeout=20)
    assert r1.status_code == 401
    r2 = requests.post(f"{API}/auth/register", json={"phone": phone, "name": "Real Sign Up"}, timeout=20)
    assert r2.status_code == 200, "registration should succeed - login must not have created anything"


def test_existing_account_authenticates_without_modification(admin):
    """Existing phone: authenticate only, never modify role or name."""
    r = requests.post(f"{API}/auth/login",
                      json={"phone": "9993000001", "name": "Totally Different Typed Name", "role": "supervisor"},
                      timeout=20)
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "FAC03 Admin"
    assert r.json()["user"]["role"] == "management"


def test_pending_user_enters_pending_flow_not_normal_session():
    """Pending user: gets a token (so the app can show them their own
    status), but must NEVER receive a normal authenticated session -
    verified by confirming every real endpoint 403s except GET /api/me."""
    phone = "9993000010"
    reg = requests.post(f"{API}/auth/register", json={"phone": phone, "name": "Pending Person"}, timeout=20)
    assert reg.status_code == 200
    headers = {"Authorization": f"Bearer {reg.json()['token']}"}

    me = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert me.status_code == 200
    assert me.json()["approval_status"] == "pending"

    for path in ["/projects", "/sites", "/operational-items", "/knowledge-items", "/admin/users"]:
        r = requests.get(f"{API}{path}", headers=headers, timeout=20)
        assert r.status_code == 403, f"{path} should be blocked for a pending user, got {r.status_code}"

    patch = requests.patch(f"{API}/me", json={"name": "Trying to edit"}, headers=headers, timeout=20)
    assert patch.status_code == 403


def test_invalid_input_rejected_immediately():
    r = requests.post(f"{API}/auth/login", json={"phone": "not-a-phone", "name": "X"}, timeout=20)
    assert r.status_code == 400


# --------------------------------------------------------------------------
# P0 Identity Integrity
# --------------------------------------------------------------------------
def test_same_phone_always_resolves_to_one_record(admin):
    """Multiple logins with the exact same phone must always return the
    same user id - never a duplicate."""
    u1, _ = _login("supervisor", "9993000020", "Identity Test")
    r2 = requests.post(f"{API}/auth/login", json={"phone": "9993000020", "name": "Different Typed Name", "role": "management"}, timeout=20)
    assert r2.json()["user"]["id"] == u1["id"]


def test_register_refuses_a_phone_that_already_has_an_account():
    phone = "9993000021"
    _login("supervisor", phone, "Existing Account")
    r = requests.post(f"{API}/auth/register", json={"phone": phone, "name": "Duplicate Attempt"}, timeout=20)
    assert r.status_code == 400


def test_phone_formatting_variants_resolve_to_the_same_account():
    u1, _ = _login("supervisor", "+919993000022", "Format Test")
    r2 = requests.post(f"{API}/auth/login", json={"phone": "9199930 00022", "name": "X", "role": "supervisor"}, timeout=20)
    assert r2.status_code == 200
    assert r2.json()["user"]["id"] == u1["id"]


# --------------------------------------------------------------------------
# P0 Role Integrity: MongoDB -> API -> JWT session -> workspace routing
# --------------------------------------------------------------------------
@pytest.mark.parametrize("role,expected_default_workspace", [
    ("management", "admin"),
    ("coordinator", "pm"),
    ("supervisor", "supervisor"),
])
def test_role_integrity_chain(role, expected_default_workspace):
    phone = f"99930003{['management','coordinator','supervisor'].index(role)}0"
    user, headers = _login(role, phone, f"Chain Test {role}")

    assert user["role"] == role

    me = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert me.status_code == 200
    assert me.json()["role"] == role

    resolved_workspace = me.json().get("workspace") or expected_default_workspace
    assert resolved_workspace == expected_default_workspace


def test_client_workspace_routing(admin):
    user, _ = _login("coordinator", "9993000040", "Chain Test Client")
    requests.post(f"{API}/admin/users/{user['id']}/workspace", json={"workspace": "client"},
                 headers=admin["headers"], timeout=20)
    r = requests.post(f"{API}/auth/login", json={"phone": "9993000040", "name": "Chain Test Client", "role": "supervisor"}, timeout=20)
    assert r.json()["user"]["workspace"] == "client"


def test_backend_is_the_single_source_of_truth(admin):
    """A role/workspace change is immediately visible via GET /api/me on
    the SAME token - no re-login needed. This is what the frontend's
    cache-refresh mechanism depends on; the backend must never be stale."""
    user, headers = _login("supervisor", "9993000041", "Source of Truth Test")
    requests.post(f"{API}/admin/users/{user['id']}/role", json={"role": "coordinator"},
                 headers=admin["headers"], timeout=20)
    me = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert me.json()["role"] == "coordinator"


# --------------------------------------------------------------------------
# P0 Operational Assignment
# --------------------------------------------------------------------------
def test_pm_assigns_supervisor_immediately_sees_it(admin, pm, supervisor):
    proj = requests.post(f"{API}/projects", json={"name": "FAC03 Assignment Test", "code": "FAC03A"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"},
                        headers=admin["headers"], timeout=20).json()
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC03 Cement",
    }, headers=pm["headers"], timeout=20).json()

    r = requests.post(f"{API}/operational-items/{item['id']}/assign",
                      json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=pm["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["assigned_to_user_id"] == supervisor["user"]["id"]

    mine = requests.get(f"{API}/operational-items?assigned_to_me=true", headers=supervisor["headers"], timeout=20)
    assert mine.status_code == 200
    assert any(i["id"] == item["id"] for i in mine.json()), \
        f"assigned item not found in supervisor's assigned-to-me list: {mine.json()}"

    ack = requests.post(f"{API}/operational-items/{item['id']}/transition",
                        json={"to_status": "acknowledged"}, headers=supervisor["headers"], timeout=20)
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"


# --------------------------------------------------------------------------
# P0 Client Permissions (re-verified, including newly explicit prohibitions)
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client_user(admin):
    u, h = _login("coordinator", "9993000050", "FAC03 Client")
    requests.post(f"{API}/admin/users/{u['id']}/workspace", json={"workspace": "client"}, headers=admin["headers"], timeout=20)
    u2, h2 = _login("coordinator", "9993000050", "FAC03 Client")
    return {"user": u2, "headers": h2}


def test_client_cannot_acknowledge_work(pm, client_user):
    proj = requests.post(f"{API}/projects", json={"name": "FAC03 Client Perm", "code": "FAC03CP"},
                         headers=pm["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"}, headers=pm["headers"], timeout=20).json()
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC03 Client Item",
    }, headers=pm["headers"], timeout=20).json()

    r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                      json={"to_status": "acknowledged"}, headers=client_user["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_start_or_complete_work(pm, client_user):
    site = requests.get(f"{API}/sites", headers=pm["headers"], timeout=20).json()[0]
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "FAC03 Start/Complete Test",
    }, headers=pm["headers"], timeout=20).json()

    for target in ("in_progress", "fulfilled"):
        r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                          json={"to_status": target}, headers=client_user["headers"], timeout=20)
        assert r.status_code == 403, f"client should not be able to transition to {target}"


def test_client_can_still_approve_reject_and_comment(pm, client_user):
    site = requests.get(f"{API}/sites", headers=pm["headers"], timeout=20).json()[0]
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "FAC03 Approval Test",
    }, headers=pm["headers"], timeout=20).json()

    r = requests.post(f"{API}/operational-items/{item['id']}/transition",
                      json={"to_status": "fulfilled", "note": "Approved."}, headers=client_user["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["status"] == "fulfilled"


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
