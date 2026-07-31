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
# Beta-06C — Authorization Boundary Validation. Three more resources
# found with the exact same "zero visibility check" pattern already
# fixed once for operational items in Beta-06B: events, raw assets
# (photo/audio binary data), and site requirements. Each demonstrated
# exploitable before fixing, each fixed by reusing
# commercial_engine.assert_project_visible directly (already public,
# already generic despite its module name).
# ==========================================================================
@pytest.fixture()
def event_with_photo(admin):
    outsider_user, outsider_h = _login("site_supervisor", "9990000301", "Beta06C Event Outsider")
    proj_a = requests.post(f"{API}/projects", json={"name": "Beta06C Event Secret", "code": "B06CEVT1"},
                           headers=admin["headers"], timeout=20).json()
    proj_b = requests.post(f"{API}/projects", json={"name": "Beta06C Event Visible", "code": "B06CEVT2"},
                           headers=admin["headers"], timeout=20).json()
    site_a = requests.post(f"{API}/sites", json={"project_id": proj_a["id"], "name": "Secret Site"},
                           headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/admin/users/{outsider_user['id']}/projects", json={"project_ids": [proj_b["id"]]},
                 headers=admin["headers"], timeout=20)

    files = {"photos": ("secret.jpg", b"fakejpegdata", "image/jpeg")}
    data = {"site_id": site_a["id"], "text": "Confidential", "kind": "photo"}
    event = requests.post(f"{API}/events", data=data, files=files, headers=admin["headers"], timeout=20).json()
    return event, site_a, outsider_h


def test_event_detail_blocks_outsider(event_with_photo, admin):
    event, _, outsider_h = event_with_photo
    r = requests.get(f"{API}/events/{event['id']}", headers=outsider_h, timeout=20)
    assert r.status_code == 404
    r2 = requests.get(f"{API}/events/{event['id']}", headers=admin["headers"], timeout=20)
    assert r2.status_code == 200


def test_site_requirements_blocks_outsider(event_with_photo, admin):
    _, site, outsider_h = event_with_photo
    r = requests.get(f"{API}/sites/{site['id']}/requirements", headers=outsider_h, timeout=20)
    assert r.status_code == 404
    r2 = requests.get(f"{API}/sites/{site['id']}/requirements", headers=admin["headers"], timeout=20)
    assert r2.status_code == 200


def test_raw_asset_blocks_outsider(event_with_photo, admin):
    event, _, outsider_h = event_with_photo
    asset_id = event["photo_asset_ids"][0]
    r = requests.get(f"{API}/raw-assets/{asset_id}", headers=outsider_h, timeout=20)
    assert r.status_code == 404
    r2 = requests.get(f"{API}/raw-assets/{asset_id}", headers=admin["headers"], timeout=20)
    assert r2.status_code == 200


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


# ==========================================================================
# Beta-06D — State Mutation & Authorization Validation.
#
# Beta-06B/C proved read endpoints must independently enforce
# visibility. This pass proved the same must hold for every mutation:
# systematically found that essentially every write endpoint on
# operational items (transition, assign, comment, request-clarification,
# blocker set/clear, edit, voice-update, duplicate) and six commercial
# mutation functions (milestone status, payment request status, variation
# decide/submit/send-for-client-review, record_payment) had zero
# visibility enforcement - demonstrated as exploitable (an outsider
# transitioned an item's real status; an unrelated client approved a
# real Rs 5L variation) before fixing.
# ==========================================================================
@pytest.fixture()
def cross_project_item_and_variation(admin):
    outsider_user, outsider_h = _login("site_supervisor", "9990000401", "Beta06D Item Outsider")
    client_user, client_h = _login("client", "9990000402", "Beta06D Client A")
    outsider_client_user, outsider_client_h = _login("client", "9990000403", "Beta06D Outsider Client")

    proj_a = requests.post(f"{API}/projects", json={"name": "Beta06D Secret", "code": "B06DSEC1"},
                           headers=admin["headers"], timeout=20).json()
    proj_b = requests.post(f"{API}/projects", json={"name": "Beta06D Visible", "code": "B06DVIS1"},
                           headers=admin["headers"], timeout=20).json()
    site_a = requests.post(f"{API}/sites", json={"project_id": proj_a["id"], "name": "Secret Site"},
                           headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/admin/users/{outsider_user['id']}/projects", json={"project_ids": [proj_b["id"]]},
                 headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{outsider_client_user['id']}/projects", json={"project_ids": [proj_b["id"]]},
                 headers=admin["headers"], timeout=20)

    item = requests.post(f"{API}/operational-items", json={
        "site_id": site_a["id"], "category": "site_issue", "title": "Beta06D secret item", "priority": "high",
    }, headers=admin["headers"], timeout=20).json()

    requests.post(f"{API}/commercial/contracts", json={
        "project_id": proj_a["id"], "client_id": client_user["id"],
        "original_contract_value": 1000000, "contract_date": "2026-01-01", "duration_days": 100,
    }, headers=admin["headers"], timeout=20)
    variation = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj_a["id"], "title": "Beta06D secret variation", "description": "d",
        "original_cost": 0, "proposed_cost": 500000,
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/variations/{variation['id']}/submit", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{variation['id']}/send-for-client-review",
                 headers=admin["headers"], timeout=20)

    return item, variation, proj_a, outsider_h, outsider_client_h


def test_item_transition_blocks_outsider(cross_project_item_and_variation, admin):
    item, _, _, outsider_h, _ = cross_project_item_and_variation
    r = requests.post(f"{API}/operational-items/{item['id']}/transition", json={"to_status": "in_progress"},
                      headers=outsider_h, timeout=20)
    assert r.status_code == 404
    r2 = requests.get(f"{API}/operational-items/{item['id']}", headers=admin["headers"], timeout=20)
    assert r2.json()["item"]["status"] != "in_progress", "the outsider's blocked attempt must not have mutated state"


def test_item_comment_blocks_outsider(cross_project_item_and_variation):
    item, _, _, outsider_h, _ = cross_project_item_and_variation
    r = requests.post(f"{API}/operational-items/{item['id']}/comments", json={"text": "unauthorized"},
                      headers=outsider_h, timeout=20)
    assert r.status_code == 404


def test_item_edit_blocks_outsider(cross_project_item_and_variation, admin):
    item, _, _, outsider_h, _ = cross_project_item_and_variation
    r = requests.patch(f"{API}/operational-items/{item['id']}", json={"title": "hacked"},
                       headers=outsider_h, timeout=20)
    assert r.status_code == 404
    r2 = requests.get(f"{API}/operational-items/{item['id']}", headers=admin["headers"], timeout=20)
    assert r2.json()["item"]["title"] == "Beta06D secret item", "the outsider's blocked edit must not have mutated state"


def test_item_blocker_set_and_clear_block_outsider(cross_project_item_and_variation):
    item, _, _, outsider_h, _ = cross_project_item_and_variation
    r1 = requests.post(f"{API}/operational-items/{item['id']}/blocker", json={"category": "material"},
                       headers=outsider_h, timeout=20)
    assert r1.status_code == 404
    r2 = requests.delete(f"{API}/operational-items/{item['id']}/blocker", headers=outsider_h, timeout=20)
    assert r2.status_code == 404


def test_item_voice_update_blocks_outsider(cross_project_item_and_variation):
    item, _, _, outsider_h, _ = cross_project_item_and_variation
    r = requests.post(f"{API}/operational-items/{item['id']}/voice-update", data={"text": "unauthorized"},
                      headers=outsider_h, timeout=20)
    assert r.status_code == 404


def test_variation_decide_blocks_outsider_client(cross_project_item_and_variation, admin):
    _, variation, proj_a, _, outsider_client_h = cross_project_item_and_variation
    r = requests.post(f"{API}/commercial/variations/{variation['id']}/decide", json={"decision": "approved"},
                      headers=outsider_client_h, timeout=20)
    assert r.status_code == 404
    r2 = requests.get(f"{API}/projects/{proj_a['id']}/commercial/variations",
                      headers=admin["headers"], timeout=20)
    decided = [v for v in r2.json() if v["id"] == variation["id"] and v["status"] == "approved"]
    assert not decided, "the outsider client's blocked approval must not have mutated the variation's real state"


def test_variation_submit_blocks_wrong_project_pm(cross_project_item_and_variation, admin):
    """A fresh variation, not yet submitted, so submit is still a legal
    transition for someone with the right role - confirming the block
    is genuinely about project visibility, not merely an already-illegal
    state transition or a role restriction. Uses a project_manager (the
    role /submit actually permits) scoped to a different project, not
    site_supervisor (who /submit's own _require_write_access would
    already reject regardless of visibility, and so would not actually
    exercise this fix)."""
    _, _, proj_a, _, _ = cross_project_item_and_variation
    pm_user, pm_h = _login("project_manager", "9990000404", "Beta06D Wrong-Project PM")
    proj_b_2 = requests.post(f"{API}/projects", json={"name": "Beta06D Visible 2", "code": "B06DVIS2"},
                             headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/admin/users/{pm_user['id']}/projects", json={"project_ids": [proj_b_2["id"]]},
                 headers=admin["headers"], timeout=20)

    fresh_var = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj_a["id"], "title": "Beta06D fresh variation", "description": "d",
        "original_cost": 0, "proposed_cost": 100000,
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/commercial/variations/{fresh_var['id']}/submit", headers=pm_h, timeout=20)
    assert r.status_code == 404
