"""Project Atlas V6.1 — Sprint 6.1: Founder Acceptance Fixes & Communication
Foundation tests.

Validates:
  * Workflow Activity Scheduling: Planned/Actual Start/Finish can be set,
    read back, and partial updates don't clear other fields.
  * Foundation for AI Client Communication: captured events store
    project_id (denormalized) and accept an optional activity_id, and
    both survive through GET /api/timeline and GET /api/events/{id}.
  * Manual text capture (Add as Text) creates the same event structure
    as voice capture wherever applicable, through the same backend path.
  * AI-disabled behaviour remains graceful (still true after this
    sprint's changes).
  * Regression: everything from Sprint 1-6 still works.
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
    u, h = _login("management", "9800100001", "V61 Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("supervisor", "9800100002", "V61 Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "V61 Test Project", "code": "V61TP"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "V61 Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


@pytest.fixture(scope="session")
def workflow_activity(admin, project_and_site):
    proj, _ = project_and_site
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items", json={"type": "category", "name": "V61 Category"}, headers=h, timeout=20).json()
    act = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "V61 Activity", "category_id": cat["id"], "status": "active",
    }, headers=h, timeout=20).json()
    tmpl = requests.post(f"{API}/knowledge-items", json={"type": "workflow_template", "name": "V61 Template", "status": "active"}, headers=h, timeout=20).json()
    requests.post(f"{API}/knowledge-items/{tmpl['id']}/relationships",
                 json={"type": "includes_activity", "target_id": act["id"], "metadata": {"order": 0}}, headers=h, timeout=20)
    generated = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                              json={"template_id": tmpl["id"]}, headers=h, timeout=20).json()
    return generated[0]


# --------------------------------------------------------------------------
# Workflow Activity Scheduling
# --------------------------------------------------------------------------
def test_new_activity_has_null_schedule_fields(workflow_activity):
    for field in ["planned_start", "planned_finish", "actual_start", "actual_finish"]:
        assert workflow_activity[field] is None


def test_set_planned_dates(supervisor, workflow_activity):
    r = requests.post(f"{API}/workflow-activities/{workflow_activity['id']}/schedule",
                      json={"planned_start": "2026-09-01", "planned_finish": "2026-09-10"},
                      headers=supervisor["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["planned_start"] == "2026-09-01"
    assert r.json()["planned_finish"] == "2026-09-10"


def test_partial_schedule_update_preserves_other_fields(supervisor, workflow_activity):
    requests.post(f"{API}/workflow-activities/{workflow_activity['id']}/schedule",
                 json={"planned_start": "2026-09-01"}, headers=supervisor["headers"], timeout=20)
    r = requests.post(f"{API}/workflow-activities/{workflow_activity['id']}/schedule",
                      json={"actual_start": "2026-09-02"}, headers=supervisor["headers"], timeout=20)
    assert r.json()["planned_start"] == "2026-09-01"
    assert r.json()["actual_start"] == "2026-09-02"


def test_schedule_visible_via_workflow_listing(admin, project_and_site, workflow_activity):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/workflow", headers=admin["headers"], timeout=20)
    listed = next(a for a in r.json() if a["id"] == workflow_activity["id"])
    assert "planned_start" in listed and "actual_start" in listed


# --------------------------------------------------------------------------
# Foundation for AI Client Communication
# --------------------------------------------------------------------------
def test_event_stores_project_id(admin, project_and_site):
    proj, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "V61 project_id test"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    assert r.json()["project_id"] == proj["id"]


def test_event_has_reserved_activity_id_field(admin, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "V61 activity_id test"},
                      headers=admin["headers"], timeout=20)
    body = r.json()
    assert "activity_id" in body
    assert body["activity_id"] is None


def test_event_accepts_optional_activity_id(admin, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "V61 with activity",
                                              "activity_id": "wfa_manual_test"},
                      headers=admin["headers"], timeout=20)
    assert r.json()["activity_id"] == "wfa_manual_test"


def test_project_id_survives_timeline_and_event_detail(admin, project_and_site):
    proj, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "V61 retrieval test"},
                      headers=admin["headers"], timeout=20)
    event_id = r.json()["id"]

    r2 = requests.get(f"{API}/timeline?site_id={site['id']}", headers=admin["headers"], timeout=20)
    listed = next(i["event"] for i in r2.json() if i["event"]["id"] == event_id)
    assert listed["project_id"] == proj["id"]

    r3 = requests.get(f"{API}/events/{event_id}", headers=admin["headers"], timeout=20)
    assert r3.json()["event"]["project_id"] == proj["id"]


# --------------------------------------------------------------------------
# Manual text capture creates the same event structure as voice capture
# --------------------------------------------------------------------------
def test_manual_text_capture_creates_operational_event(admin, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Manual text capture"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "text"
    assert body["text_input"] == "Manual text capture"
    assert body["ai_status"] == "pending"
    for field in ["id", "site_id", "project_id", "user_id", "user_name", "server_created_at", "ai_analysis_id"]:
        assert field in body


# --------------------------------------------------------------------------
# AI-disabled behaviour remains graceful
# --------------------------------------------------------------------------
def test_root_endpoint_still_reports_ai_status():
    r = requests.get(f"{API}/", timeout=20)
    assert r.status_code == 200
    assert "ai_enabled" in r.json()


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected(admin, supervisor):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/system-info", headers=h, timeout=20).status_code == 200

    r = requests.post(f"{API}/auth/login", json={"phone": "9800100001", "name": "V61 Admin", "role": "supervisor"}, timeout=20)
    assert r.json()["user"]["role"] == "management"
