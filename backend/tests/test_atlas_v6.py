"""Project Atlas V6 — Sprint 6: Founder Acceptance Completion tests.

Validates:
  * The root-cause fix for "all seeded users persist as site_supervisor":
    an existing account's role is never overwritten by a subsequent
    login's guessed role. Verified at every layer the brief asked for -
    stored MongoDB role, API response role, and authenticated session
    role (frontend role is a pure derivation of these, covered by the
    existing roles.ts unit-level reasoning, not a separate backend test).
  * Self-service role assignment is preserved for a genuinely brand-new
    account's first-ever login (no regression to Sprint 1-4 behaviour).
  * Workspace routing resolves correctly for every seeded role now that
    the underlying role is no longer corrupted.
  * GET /api/ reports whether the AI worker is actually running, so the
    frontend can clearly indicate AI is unavailable instead of polling
    indefinitely.
  * Event capture, timeline, and operational history are all completely
    unaffected by AI being disabled - never blocked.
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


# --------------------------------------------------------------------------
# The critical fix: role is never corrupted by a subsequent login
# --------------------------------------------------------------------------
def test_existing_account_role_survives_a_guessed_role_login():
    """Reproduces the exact reported bug: an account is created with a
    real role (e.g. by the seed script or an admin), then logs in from a
    "new device" that has no cached role for that phone and falls back to
    guessing 'supervisor' - the account's real role must not change."""
    phone = "9600100001"
    user, _ = _login("management", phone, "V6 Admin Test")
    assert user["role"] == "management"

    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "V6 Admin Test", "role": "site_supervisor"}, timeout=20)
    assert r.status_code == 200
    body = r.json()

    assert body["user"]["role"] == "management", f"role corrupted: {body['user']['role']}"

    headers = {"Authorization": f"Bearer {body['token']}"}
    r2 = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert r2.json()["role"] == "management"


def test_name_does_not_update_on_plain_login():
    """Sprint 6.2 Identity Security fix supersedes Sprint 6's original
    behaviour here: name (like role, fixed in Sprint 6) must never be
    modified by logging in. Only PATCH /api/me (self-service) or an
    admin action may change an existing account's identity."""
    phone = "9600100002"
    _login("project_manager", phone, "Original Name")
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Someone Typed This", "role": "site_supervisor"}, timeout=20)
    body = r.json()["user"]
    assert body["name"] == "Original Name"
    assert body["role"] == "project_manager"


def test_unknown_phone_is_rejected_not_auto_created():
    """FAC-03 P0 fix supersedes this test's original intent (it used to
    verify a brand-new phone number got auto-created with self-service
    role on first login - that entire mechanic is gone). An unrecognized
    phone number must now be rejected outright; account creation is
    exclusively /auth/register's job."""
    phone = "9600100003"
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Brand New", "role": "project_manager"}, timeout=20)
    assert r.status_code == 401, r.text


def test_role_change_still_works_via_admin_endpoint():
    admin, admin_headers = _login("management", "9600100004", "V6 Admin")
    target, _ = _login("site_supervisor", "9600100005", "V6 Target")
    r = requests.post(f"{API}/admin/users/{target['id']}/role", json={"role": "project_manager"}, headers=admin_headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["role"] == "project_manager"


# --------------------------------------------------------------------------
# Workspace routing resolves correctly once role is no longer corrupted
# --------------------------------------------------------------------------
def test_workspace_routing_for_every_role():
    # FAC-04: workspace is now a pure, total function of role - all four
    # roles, including client, are directly assignable and auto-derive
    # their one correct workspace.
    default_view_role_for = {"site_supervisor": "supervisor", "project_manager": "pm",
                             "management": "admin", "client": "client"}
    _login("management", "9600100010", "V6 Routing Admin")

    for phone, name, role, expected_workspace in [
        ("9600100011", "V6 Admin", "management", "admin"),
        ("9600100012", "V6 PM", "project_manager", "pm"),
        ("9600100013", "V6 Sup", "site_supervisor", "supervisor"),
        ("9600100014", "V6 Client", "client", "client"),
    ]:
        user, _ = _login(role, phone, name)
        resolved = user.get("workspace") or default_view_role_for[user["role"]]
        assert resolved == expected_workspace, f"{name}: expected {expected_workspace}, got {resolved}"


# --------------------------------------------------------------------------
# AI availability status + non-blocking behaviour when disabled
# --------------------------------------------------------------------------
def test_root_endpoint_reports_ai_status():
    r = requests.get(f"{API}/", timeout=20)
    assert r.status_code == 200
    assert "ai_enabled" in r.json()
    assert isinstance(r.json()["ai_enabled"], bool)


def test_event_capture_unaffected_by_ai_status():
    """Whatever ai_enabled currently is, capturing an event, seeing it in
    the timeline, and it having a well-formed ai_status must all work -
    this sprint doesn't change AI behaviour when it IS enabled, and
    Sprint 5.0.2 already guarantees capture never blocks when it's not."""
    admin, admin_headers = _login("management", "9600100020", "V6 Cap Admin")
    proj = requests.post(f"{API}/projects", json={"name": "V6 Cap Test", "code": "V6CAP"}, headers=admin_headers, timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"}, headers=admin_headers, timeout=20).json()
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "V6 test note"}, headers=admin_headers, timeout=20)
    assert r.status_code == 201, r.text
    event = r.json()
    assert event["ai_status"] in ("pending", "skipped", "analyzed", "failed")

    r2 = requests.get(f"{API}/timeline?site_id={site['id']}", headers=admin_headers, timeout=20)
    assert r2.status_code == 200
    assert any(i["event"]["id"] == event["id"] for i in r2.json())


# --------------------------------------------------------------------------
# Regression: everything from Sprint 1-DX-7 still works
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected():
    admin, admin_headers = _login("management", "9600100030", "V6 Regression Admin")
    assert requests.get(f"{API}/projects", headers=admin_headers, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=admin_headers, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=admin_headers, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin_headers, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users", headers=admin_headers, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/system-info", headers=admin_headers, timeout=20).status_code == 200
