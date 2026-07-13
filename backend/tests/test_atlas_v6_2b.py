"""Project Atlas V6.2b — Sprint 6.2 Founder Verification Failure fixes.

Covers the two backend-verifiable fixes from the founder verification
pass that are NOT already covered by test_atlas_v6_2.py:

  * Phone normalization consistency (Identity Security root cause #2):
    the same phone number typed with/without a '+' prefix or with
    different spacing must resolve to the SAME account, not silently
    create a second one.
  * GET /api/me reflects an admin-assigned workspace/role change
    immediately, on the SAME token, with no re-login required — the
    backend guarantee the frontend's self-healing cache refresh
    (app/(tabs)/_layout.tsx) depends on.

The AI-failure-path fallback (the other major finding — a configured
but broken AI key previously still stranded manual observations) is
covered in the mongomock-backed smoke suite
(test_sprint62v2_ai_failure_fallback.py) rather than here, since
reproducing a genuine AI runtime failure over HTTP against a live
preview server isn't reliable/repeatable the way monkeypatching
_structure() directly is - consistent with how AI-worker-state-
dependent behaviour is handled elsewhere in this test suite.
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


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9990100001", "V62b Admin")
    return {"user": u, "headers": h}


# --------------------------------------------------------------------------
# Phone normalization consistency
# --------------------------------------------------------------------------
def test_plus_prefix_and_bare_digits_resolve_to_the_same_account():
    """The exact bug found: '+919990100010' and '9199901 00010' (same
    digits, formatted differently) used to normalize to two different
    stored phone keys, so the second login silently created a brand-new
    account rather than matching the first — which looked exactly like
    "my identity got overwritten" from the outside, even though no
    document was actually mutated."""
    u1, _ = _login("site_supervisor", "+919990100010", "First Login")
    u2, _ = _login("site_supervisor", "9199901 00010", "Second Login Attempt")
    assert u1["id"] == u2["id"], "same phone number in different formats must resolve to the same account"
    assert u2["name"] == "First Login"


def test_spacing_and_dashes_are_normalized_consistently():
    u1, _ = _login("site_supervisor", "999-010-0011", "Dash Format")
    u2, _ = _login("site_supervisor", "999 010 0011", "Space Format")
    assert u1["id"] == u2["id"]


# --------------------------------------------------------------------------
# GET /api/me reflects server-side changes immediately (no re-login)
# --------------------------------------------------------------------------
def test_get_me_reflects_role_and_workspace_change_on_same_token(admin):
    """FAC-04: role is now the single action that changes both role AND
    workspace (auto-derived) - no more separate workspace-assignment step."""
    user, headers = _login("project_manager", "9990100020", "V62b Workspace Test")
    r1 = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert r1.json()["workspace"] == "pm"

    requests.post(f"{API}/admin/users/{user['id']}/role", json={"role": "client"},
                 headers=admin["headers"], timeout=20)

    r2 = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert r2.json()["role"] == "client"
    assert r2.json()["workspace"] == "client"


def test_get_me_reflects_role_change_on_same_token(admin):
    user, headers = _login("site_supervisor", "9990100021", "V62b Role Test")
    requests.post(f"{API}/admin/users/{user['id']}/role", json={"role": "project_manager"},
                 headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/me", headers=headers, timeout=20)
    assert r.json()["role"] == "project_manager"


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
