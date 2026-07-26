"""Project Atlas — Atlas Visual Validation (VV-01).

Covers the one new backend piece this session: a visibility-checked,
read-only route for a project's Commercial reference data
(GET /projects/{id}/commercial-reference), consumed by the new
Screens 1-3 (Project Selector, Command Center, Compare Projects).

Also regression-guards the architecture fix made this session: the
route must call a public engine function, never an engine's private
helper directly - this is additionally enforced platform-wide by
tests/test_cre_architecture_guards.py's own static source check, but
verified here at the behavioral level too (a visibility violation must
still be caught correctly after the fix).
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
    u, h = _login("management", "9992200001", "VV Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9992200002", "VV Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project(admin):
    return requests.post(f"{API}/projects", json={"name": "VV Test", "code": "VVT"},
                         headers=admin["headers"], timeout=20).json()


def test_commercial_reference_null_when_not_set(admin, project):
    r = requests.get(f"{API}/projects/{project['id']}/commercial-reference",
                     headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json() is None


def test_client_blocked_from_commercial_reference(client, project):
    r = requests.get(f"{API}/projects/{project['id']}/commercial-reference",
                     headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_commercial_reference_requires_project_visibility(admin, project):
    """A supervisor NOT scoped to this project must be blocked - the
    engine-layer visibility check (moved there during this session's
    architecture fix) must actually run, not just exist in code."""
    sup, sup_h = _login("site_supervisor", "9992200003", "VV Supervisor")
    requests.post(f"{API}/admin/users/{sup['id']}/projects", json={"project_ids": []},
                 headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/projects/{project['id']}/commercial-reference", headers=sup_h, timeout=20)
    assert r.status_code in (403, 404), \
        "an out-of-scope supervisor must not see this project's commercial reference"


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_comparison_endpoint_unaffected(admin):
    p1 = requests.post(f"{API}/projects", json={"name": "VV Regr A", "code": "VVRA"},
                       headers=admin["headers"], timeout=20).json()
    p2 = requests.post(f"{API}/projects", json={"name": "VV Regr B", "code": "VVRB"},
                       headers=admin["headers"], timeout=20).json()
    r = requests.get(f"{API}/portfolio/compare?project_ids={p1['id']},{p2['id']}",
                     headers=admin["headers"], timeout=20)
    assert r.status_code == 200


def test_regression_core_platform_unaffected(admin, project):
    assert requests.get(f"{API}/projects/{project['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
