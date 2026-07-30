"""Project Atlas — RC-01 Production Readiness Validation.

Covers a genuine, serious defect found and fixed during RC-01
validation: 7 of 8 GET routes in routes/commercial.py had no
project-visibility check at all. Any authenticated user - regardless
of their own project scoping - could read another project's complete
commercial data (contract value, milestones, payment requests,
payments, variations, commercial events) simply by knowing or guessing
its project_id. Confirmed reproducible before the fix: a site
supervisor scoped only to Project B successfully read Project A's full
commercial summary via GET /projects/{project_a_id}/commercial/summary.

Fixed by adding commercial_engine.assert_project_visible - a public
function (not a private one called directly from a route, which would
violate the same architecture guard test_cre_architecture_guards.py
already enforces platform-wide) mirroring the exact convention
workflow_engine._assert_project_visible and
reasoning_engine._assert_project_visible already establish elsewhere:
out-of-scope projects behave as 404, not 403.
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
    u, h = _login("management", "9990000101", "RC01 Admin")
    return {"user": u, "headers": h}


@pytest.fixture()
def two_projects_one_scoped_out(admin):
    """Project A (has a Contract + Milestone) and Project B, plus an
    outsider supervisor scoped ONLY to Project B and an insider
    supervisor scoped ONLY to Project A."""
    proj_a = requests.post(f"{API}/projects", json={"name": "RC01 Project A", "code": "RC01A"},
                           headers=admin["headers"], timeout=20).json()
    proj_b = requests.post(f"{API}/projects", json={"name": "RC01 Project B", "code": "RC01B"},
                           headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/contracts", json={
        "project_id": proj_a["id"], "original_contract_value": 1000000,
        "contract_date": "2026-01-01", "duration_days": 90,
    }, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/milestones", json={
        "project_id": proj_a["id"], "name": "MS1", "sequence": 1,
        "planned_percent": 10, "trigger": "test",
    }, headers=admin["headers"], timeout=20)

    outsider, outsider_h = _login("site_supervisor", "9990000102", "RC01 Outsider")
    insider, insider_h = _login("site_supervisor", "9990000103", "RC01 Insider")
    requests.post(f"{API}/admin/users/{outsider['id']}/projects", json={"project_ids": [proj_b["id"]]},
                 headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{insider['id']}/projects", json={"project_ids": [proj_a["id"]]},
                 headers=admin["headers"], timeout=20)

    return proj_a, outsider_h, insider_h


COMMERCIAL_READ_PATHS = [
    "commercial/summary",
    "commercial/contract",
    "commercial/milestones",
    "commercial/payment-requests",
    "commercial/payments",
    "commercial/variations",
    "commercial/events",
]


@pytest.mark.parametrize("path", COMMERCIAL_READ_PATHS)
def test_outsider_cannot_read_another_projects_commercial_data(path, two_projects_one_scoped_out):
    proj_a, outsider_h, _ = two_projects_one_scoped_out
    r = requests.get(f"{API}/projects/{proj_a['id']}/{path}", headers=outsider_h, timeout=20)
    assert r.status_code == 404, \
        f"{path}: an out-of-scope user must never see another project's commercial data (got {r.status_code})"


@pytest.mark.parametrize("path", COMMERCIAL_READ_PATHS)
def test_insider_can_still_read_their_own_projects_commercial_data(path, two_projects_one_scoped_out):
    proj_a, _, insider_h = two_projects_one_scoped_out
    r = requests.get(f"{API}/projects/{proj_a['id']}/{path}", headers=insider_h, timeout=20)
    assert r.status_code == 200, \
        f"{path}: a legitimately-scoped user must still see their own project's data (got {r.status_code})"


def test_budget_still_requires_management_or_pm_role_in_addition_to_visibility(admin, two_projects_one_scoped_out):
    """Budget has two layers: role (management/PM only) AND visibility
    (must be scoped to this project). Confirms the visibility fix did
    not accidentally weaken the pre-existing role restriction."""
    proj_a, _, insider_h = two_projects_one_scoped_out
    r = requests.get(f"{API}/projects/{proj_a['id']}/commercial/budget", headers=insider_h, timeout=20)
    assert r.status_code == 403, "a site_supervisor must still be blocked from Budget regardless of project scope"


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_commercial_summary_available_for_reference_portfolio(admin):
    """RP-001 must still be readable by management after this fix -
    confirms the fix didn't break the unscoped (broad-visibility)
    management role's own legitimate access."""
    r = requests.get(f"{API}/projects", headers=admin["headers"], timeout=20)
    rp001 = next((p for p in r.json() if p["code"] == "ACDP-VILLA"), None)
    if rp001:
        r2 = requests.get(f"{API}/projects/{rp001['id']}/commercial/summary", headers=admin["headers"], timeout=20)
        assert r2.status_code == 200


def test_regression_core_platform_unaffected(admin):
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200


# ==========================================================================
# STAB-01 Issue 2 — Commercial Summary Consistency.
#
# RC-01 found: GET /commercial/summary returned 200 null for a
# genuinely nonexistent project, indistinguishable from a real project
# with no Contract yet. Verified here to already be resolved as a
# direct, correct side effect of RC-01's own visibility fix
# (commercial_engine.assert_project_visible calls memory_engine.get_project
# first and raises CommercialNotFoundError -> 404 if the project truly
# doesn't exist, before ever reaching the "does it have a contract"
# question) - no additional code change was needed, only verification
# that the fix already in place actually closes this specific finding
# too, across every commercial route, not just /summary.
# ==========================================================================
COMMERCIAL_NULL_CAPABLE_PATHS = ["commercial/summary", "commercial/contract"]
COMMERCIAL_LIST_PATHS = ["commercial/milestones", "commercial/payment-requests",
                        "commercial/payments", "commercial/variations", "commercial/events"]


@pytest.mark.parametrize("path", COMMERCIAL_NULL_CAPABLE_PATHS + COMMERCIAL_LIST_PATHS + ["commercial/budget"])
def test_nonexistent_project_returns_404_not_200(path, admin):
    r = requests.get(f"{API}/projects/nonexistent_stab01_check/{path}", headers=admin["headers"], timeout=20)
    assert r.status_code == 404, f"{path}: a genuinely nonexistent project must 404, got {r.status_code}"


@pytest.mark.parametrize("path", COMMERCIAL_NULL_CAPABLE_PATHS)
def test_real_project_without_contract_returns_200_null(path, admin):
    """A real project that simply has no Contract yet is a genuinely
    different case from one that doesn't exist - this must remain 200
    null, not be over-corrected into a 404 too."""
    proj = requests.post(f"{API}/projects", json={"name": "STAB01 No Contract", "code": "STAB01NC"},
                         headers=admin["headers"], timeout=20).json()
    r = requests.get(f"{API}/projects/{proj['id']}/{path}", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.parametrize("path", COMMERCIAL_LIST_PATHS)
def test_real_project_without_data_returns_200_empty_list(path, admin):
    proj = requests.post(f"{API}/projects", json={"name": "STAB01 No Data", "code": "STAB01ND"},
                         headers=admin["headers"], timeout=20).json()
    r = requests.get(f"{API}/projects/{proj['id']}/{path}", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json() == []


# ==========================================================================
# Beta-02 — Commercial Workspace Completion.
#
# Verifying RBAC while building the new admin/PM Commercial Workspace
# surfaced a real gap: GET /commercial/summary returned the full budget
# object to any role with project visibility - management, project
# manager, and site_supervisor alike - contradicting "Budget
# (management only)" as documented throughout Atlas (CF-01's own
# frozen spec §6, this sprint's own RBAC section). The new workspace
# screen already gated the Budget section's DISPLAY to management, but
# the underlying API data was never actually restricted - "never
# calculate/expose in the frontend" only works if the backend itself
# doesn't over-share first. Fixed at the route level (not the engine,
# which stays role-agnostic and correct for its other internal
# callers - client_investment_summary never reads budget from this
# summary at all, so it was never affected).
# ==========================================================================
@pytest.fixture()
def project_with_budget(admin):
    client, client_h = _login("client", "9990000201", "Beta02 Client")
    pm, pm_h = _login("project_manager", "9990000202", "Beta02 PM")
    sup, sup_h = _login("site_supervisor", "9990000203", "Beta02 Supervisor")
    proj = requests.post(f"{API}/projects", json={"name": "Beta02 Budget Test", "code": "B02BUD"},
                         headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/contracts", json={
        "project_id": proj["id"], "client_id": client["id"],
        "original_contract_value": 5000000, "contract_date": "2026-01-01", "duration_days": 100,
    }, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/budgets", json={
        "project_id": proj["id"], "original_budget": 4000000,
    }, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{pm['id']}/projects", json={"project_ids": [proj["id"]]},
                 headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{sup['id']}/projects", json={"project_ids": [proj["id"]]},
                 headers=admin["headers"], timeout=20)
    return proj, pm_h, sup_h, client_h


def test_commercial_summary_budget_visible_to_management(admin, project_with_budget):
    proj, _, _, _ = project_with_budget
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/summary", headers=admin["headers"], timeout=20)
    assert r.json()["budget"] is not None


@pytest.mark.parametrize("role_headers_index", [1, 2, 3])  # pm, supervisor, client
def test_commercial_summary_budget_hidden_from_non_management(role_headers_index, project_with_budget):
    proj = project_with_budget[0]
    headers = project_with_budget[role_headers_index]
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/summary", headers=headers, timeout=20)
    assert r.status_code == 200
    assert r.json()["budget"] is None, \
        "Budget must never be exposed via commercial/summary to any role other than management"


def test_commercial_summary_other_fields_still_visible_to_pm(project_with_budget):
    """Confirms the fix is scoped to budget only - PM's own 'operational
    commercial visibility' (contract, milestones, variations, payments)
    must remain intact."""
    proj, pm_h, _, _ = project_with_budget
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/summary", headers=pm_h, timeout=20)
    body = r.json()
    assert body["contract"] is not None
    assert body["contract"]["current_contract_value"] == 5000000
    assert "cash_flow_signal" in body


# ==========================================================================
# Beta-05 continuation — Priority Engine RBAC (the actual HTTP-layer
# enforcement, matching Portfolio Control Center's own established
# management-only gate exactly).
# ==========================================================================
def test_priority_engine_management_only(admin, project_with_budget):
    _, pm_h, sup_h, client_h = project_with_budget
    r_admin = requests.get(f"{API}/portfolio/priorities", headers=admin["headers"], timeout=20)
    assert r_admin.status_code == 200
    assert "priorities" in r_admin.json()

    for role_headers in (pm_h, sup_h, client_h):
        r = requests.get(f"{API}/portfolio/priorities", headers=role_headers, timeout=20)
        assert r.status_code == 403, "Priority Engine must be management-only, matching Portfolio Control Center"
