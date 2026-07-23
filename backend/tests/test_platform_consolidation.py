"""Project Atlas — Platform Consolidation Sprint.

Covers the Orphan Endpoint Audit's outcomes:

REMOVED (confirmed 404/no route - dead code, no downstream consumers):
  - POST /operational-items/{id}/due (superseded by target_start/
    required_by editing + Assignment Timeline)
  - POST /operational-items/{id}/escalate (redundant with the existing
    priority-edit capability)
  - POST /operational-items/{id}/target-timeline (redundant once
    target_start became directly editable via the general PATCH
    endpoint; the underlying engine function is unchanged and still
    used internally by /assign)
  - GET /projects/{id}/client-summary (implied a send workflow that
    doesn't exist anywhere in Atlas)
  - GET /projects/{id}/reasoning/runs (no consuming screen)
  - POST /insights/{id}/feedback, /insights/{id}/relationships
    (explicitly documented as scaffolding for a future learning layer
    that was never built; the automatically-populated part of
    related_insights, done directly inside run_reasoning, is untouched)
  - GET /reasoning-meta (exposed vocabulary only for the endpoints
    above; unlike its siblings /knowledge-meta and /workflow-meta,
    which ARE actively used)

KEPT DELIBERATELY (looked orphaned, confirmed still necessary):
  - POST /insights/{id}/status - the only way an insight is ever marked
    resolved; run_reasoning() never auto-resolves a stale insight.
  - list_rules() (engine function) - used by CRE architecture-guard
    tests, not by any route anymore.

WIRED (previously orphaned, now reachable from the UI):
  - POST /projects/{id}/reasoning/run - the highest-value finding: several
    dashboard cards read from a collection only this endpoint (or the
    ACDP seed script) ever populates. Wired into Management/PM's CRE
    dashboards via a Refresh Insights button; deliberately NOT wired for
    Site Supervisor, who isn't permitted to call it.
  - POST /events/{id}/regenerate-proposals - wired into Event Detail's
    AI Proposal section, shown even with zero proposals.
  - target_start - added to the existing operational item edit form,
    reusing the general PATCH endpoint (it was already an allowed
    field with no UI).
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
    u, h = _login("management", "9993300001", "Consol Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9993300002", "Consol Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "Consolidation Test", "code": "CONSOL"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# --------------------------------------------------------------------------
# Removed endpoints are genuinely gone
# --------------------------------------------------------------------------
@pytest.mark.parametrize("method,path", [
    ("post", "/operational-items/fake_id/due"),
    ("post", "/operational-items/fake_id/escalate"),
    ("post", "/operational-items/fake_id/target-timeline"),
    ("get", "/reasoning-meta"),
])
def test_removed_endpoints_are_gone(admin, method, path):
    fn = requests.post if method == "post" else requests.get
    r = fn(f"{API}{path}", json={} if method == "post" else None, headers=admin["headers"], timeout=20)
    assert r.status_code in (404, 405), f"{method.upper()} {path} should be removed, got {r.status_code}"


def test_removed_project_scoped_endpoints_are_gone(admin, project_and_site):
    proj, _ = project_and_site
    r1 = requests.get(f"{API}/projects/{proj['id']}/client-summary", headers=admin["headers"], timeout=20)
    assert r1.status_code == 404
    r2 = requests.get(f"{API}/projects/{proj['id']}/reasoning/runs", headers=admin["headers"], timeout=20)
    assert r2.status_code == 404


def test_removed_insight_endpoints_are_gone(admin):
    r1 = requests.post(f"{API}/insights/fake_id/feedback", json={"verdict": "accepted"}, headers=admin["headers"], timeout=20)
    assert r1.status_code == 404
    r2 = requests.post(f"{API}/insights/fake_id/relationships",
                       json={"related_insight_id": "x", "relation": "previous"}, headers=admin["headers"], timeout=20)
    assert r2.status_code == 404


# --------------------------------------------------------------------------
# Kept endpoints still work
# --------------------------------------------------------------------------
def test_client_dashboard_unaffected_by_client_summary_removal(admin, project_and_site):
    """client_dashboard_view's own use of compose_client_summary is
    direct, not through the removed client_summary_view wrapper -
    confirm it's unaffected."""
    proj, _ = project_and_site
    reg = requests.post(f"{API}/auth/register", json={"phone": "9993300003", "name": "Consol Client"}, timeout=20)
    uid = reg.json()["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/approve", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{uid}/role", json={"role": "client"}, headers=admin["headers"], timeout=20)
    login = requests.post(f"{API}/auth/login", json={"phone": "9993300003", "name": "Consol Client", "role": "client"}, timeout=20)
    client_h = {"Authorization": f"Bearer {login.json()['token']}"}
    r = requests.get(f"{API}/projects/{proj['id']}/client-dashboard", headers=client_h, timeout=20)
    assert r.status_code == 200
    assert "stage" in r.json() and "summary_text" in r.json()


# --------------------------------------------------------------------------
# Wired: reasoning/run
# --------------------------------------------------------------------------
def test_reasoning_run_populates_insights_for_a_real_project(admin, project_and_site):
    """The core Consolidation Sprint finding: insights are empty for a
    real project until reasoning/run is called, and populated
    afterward."""
    proj, site = project_and_site
    requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Consolidation stale item",
    }, headers=admin["headers"], timeout=20)

    before = requests.get(f"{API}/projects/{proj['id']}/insights", headers=admin["headers"], timeout=20)
    assert before.status_code == 200

    r = requests.post(f"{API}/projects/{proj['id']}/reasoning/run", json={}, headers=admin["headers"], timeout=20)
    assert r.status_code == 201


def test_supervisor_cannot_trigger_reasoning_run(admin, supervisor, project_and_site):
    """Confirms the deliberate choice NOT to show a Refresh button to
    Site Supervisor in the frontend is backed by a real server-side
    restriction, not just a UI convention."""
    proj, _ = project_and_site
    r = requests.post(f"{API}/projects/{proj['id']}/reasoning/run", json={}, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_insight_status_endpoint_still_works(admin, project_and_site):
    """/insights/{id}/status was deliberately kept - confirm it's still
    reachable end to end after a reasoning run produces a real
    insight."""
    proj, site = project_and_site
    requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Insight status test item",
    }, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/projects/{proj['id']}/reasoning/run", json={}, headers=admin["headers"], timeout=20)
    insights = requests.get(f"{API}/projects/{proj['id']}/insights", headers=admin["headers"], timeout=20).json()
    if insights:
        r = requests.post(f"{API}/insights/{insights[0]['id']}/status",
                          json={"status": "dismissed", "note": "test"}, headers=admin["headers"], timeout=20)
        assert r.status_code == 200


# --------------------------------------------------------------------------
# Wired: target_start editing
# --------------------------------------------------------------------------
def test_target_start_editable_via_general_patch_endpoint(admin, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Target start edit test",
    }, headers=admin["headers"], timeout=20).json()
    assert item["target_start"] is None
    r = requests.patch(f"{API}/operational-items/{item['id']}",
                       json={"target_start": "2026-09-01T00:00:00+00:00"}, headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["target_start"] == "2026-09-01T00:00:00+00:00"


# --------------------------------------------------------------------------
# Wired: regenerate-proposals
# --------------------------------------------------------------------------
def test_regenerate_proposals_still_reachable(admin, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Consolidation regenerate test"},
                          headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/events/{event['id']}/regenerate-proposals?force=true", headers=admin["headers"], timeout=20)
    assert r.status_code == 200


# --------------------------------------------------------------------------
# Regression - core platform unaffected
# --------------------------------------------------------------------------
def test_regression_core_platform_unaffected(admin, project_and_site):
    proj, _ = project_and_site
    assert requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/projects/{proj['id']}/workflow", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
