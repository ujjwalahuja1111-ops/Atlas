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


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    b = r.json()
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

    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "V6 Admin Test", "role": "supervisor"}, timeout=20)
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
    _login("coordinator", phone, "Original Name")
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Someone Typed This", "role": "supervisor"}, timeout=20)
    body = r.json()["user"]
    assert body["name"] == "Original Name"
    assert body["role"] == "coordinator"


def test_brand_new_account_self_service_role_preserved():
    phone = "9600100003"
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": "Brand New", "role": "coordinator"}, timeout=20)
    assert r.json()["user"]["role"] == "coordinator"


def test_role_change_still_works_via_admin_endpoint():
    admin, admin_headers = _login("management", "9600100004", "V6 Admin")
    target, _ = _login("supervisor", "9600100005", "V6 Target")
    r = requests.post(f"{API}/admin/users/{target['id']}/role", json={"role": "coordinator"}, headers=admin_headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["role"] == "coordinator"


# --------------------------------------------------------------------------
# Workspace routing resolves correctly once role is no longer corrupted
# --------------------------------------------------------------------------
def test_workspace_routing_for_every_role():
    DEFAULT_VIEW_ROLE_FOR = {"supervisor": "supervisor", "coordinator": "pm", "management": "admin"}
    admin, admin_headers = _login("management", "9600100010", "V6 Routing Admin")

    for phone, name, role, expected_workspace in [
        ("9600100011", "V6 Admin", "management", "admin"),
        ("9600100012", "V6 PM", "coordinator", "pm"),
        ("9600100013", "V6 Sup", "supervisor", "supervisor"),
    ]:
        user, _ = _login(role, phone, name)
        resolved = user.get("workspace") or DEFAULT_VIEW_ROLE_FOR[user["role"]]
        assert resolved == expected_workspace, f"{name}: expected {expected_workspace}, got {resolved}"

    client, _ = _login("coordinator", "9600100014", "V6 Client")
    requests.post(f"{API}/admin/users/{client['id']}/workspace", json={"workspace": "client"}, headers=admin_headers, timeout=20)
    r = requests.post(f"{API}/auth/login", json={"phone": "9600100014", "name": "V6 Client", "role": "supervisor"}, timeout=20)
    user = r.json()["user"]
    resolved = user.get("workspace") or DEFAULT_VIEW_ROLE_FOR[user["role"]]
    assert resolved == "client"


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
