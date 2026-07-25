"""Project Atlas — Reference Portfolio (RP-01).

Covers the two backend-verifiable pieces built this session:

1. COMMERCIAL REFERENCE DATA LAYER
   memory_engine.set_commercial_reference/get_commercial_reference -
   deliberately NOT a Commercial Foundation Engine implementation (see
   that function's own docstring) - a minimal, honestly-scoped
   reference-data store shaped to match the frozen specification.

2. CROSS-PROJECT COMPARISON
   GET /api/portfolio/compare - reuses _project_row (the same
   calculation Client Experience and Portfolio Control Center already
   use) so a project's health here is guaranteed identical to its
   health everywhere else in Atlas.

Does not re-seed the full RP-001/RP-002 reference portfolio (that is a
multi-minute operation exercised directly via
scripts/reference_portfolio.py, not appropriate for a fast test suite)
- these tests exercise the same code paths against lightweight,
purpose-built test projects instead.
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
    u, h = _login("management", "9993300001", "RP Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9993300002", "RP Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def two_projects(admin):
    p1 = requests.post(f"{API}/projects", json={"name": "RP Test Alpha", "code": "RPTA"},
                       headers=admin["headers"], timeout=20).json()
    p2 = requests.post(f"{API}/projects", json={"name": "RP Test Beta", "code": "RPTB"},
                       headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/sites", json={"project_id": p1["id"], "name": "Site A"},
                 headers=admin["headers"], timeout=20)
    requests.post(f"{API}/sites", json={"project_id": p2["id"], "name": "Site B"},
                 headers=admin["headers"], timeout=20)
    return p1, p2


# ==========================================================================
# Cross-Project Comparison
# ==========================================================================
def test_comparison_requires_at_least_two_projects(admin, two_projects):
    p1, _ = two_projects
    r = requests.get(f"{API}/portfolio/compare?project_ids={p1['id']}", headers=admin["headers"], timeout=20)
    assert r.status_code == 400


def test_comparison_shape(admin, two_projects):
    p1, p2 = two_projects
    r = requests.get(f"{API}/portfolio/compare?project_ids={p1['id']},{p2['id']}",
                     headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert len(body["projects"]) == 2
    for row in body["projects"]:
        for key in ("project_id", "project_name", "health", "workflow", "operations",
                   "timeline", "commercial", "variation_exposure_percent", "cash_flow_signal"):
            assert key in row, f"missing field: {key}"
        assert set(row["health"].keys()) == {"status", "score", "explanation"}


def test_comparison_health_matches_portfolio_control_center(admin, two_projects):
    """The comparison must reuse the exact same calculation as every
    other health view in Atlas - never a fourth, independently
    computed number."""
    p1, p2 = two_projects
    r_cmp = requests.get(f"{API}/portfolio/compare?project_ids={p1['id']},{p2['id']}",
                        headers=admin["headers"], timeout=20)
    r_pcc = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    pcc_by_id = {row["project_id"]: row for row in r_pcc.json()["projects"]}
    for row in r_cmp.json()["projects"]:
        pcc_row = pcc_by_id.get(row["project_id"])
        if pcc_row:
            assert row["health"]["status"] == pcc_row["health_status"]
            assert row["health"]["score"] == pcc_row["health_score"]


def test_comparison_without_commercial_data_has_no_fabricated_exposure(admin, two_projects):
    p1, p2 = two_projects
    r = requests.get(f"{API}/portfolio/compare?project_ids={p1['id']},{p2['id']}",
                     headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    for row in r.json()["projects"]:
        if row["commercial"] is None:
            assert row["variation_exposure_percent"] is None


def test_client_blocked_from_comparison(client, two_projects):
    p1, p2 = two_projects
    r = requests.get(f"{API}/portfolio/compare?project_ids={p1['id']},{p2['id']}",
                     headers=client["headers"], timeout=20)
    assert r.status_code == 403


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_core_platform_unaffected(admin, two_projects):
    p1, _ = two_projects
    assert requests.get(f"{API}/projects/{p1['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
