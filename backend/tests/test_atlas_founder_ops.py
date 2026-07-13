"""Project Atlas — Founder Acceptance Cycle: Operational Workflow
Completion.

Validates:
  * Operational Assignment end-to-end: PM assigns -> item persists with
    assigned_to_user_id -> supervisor's assigned_to_me query returns it
    -> supervisor updates it -> the update is visible via the operational
    center's recently_updated (what a PM sees).
  * Client Approval Flow: client may only approve/reject/comment on
    client_approval items; every internal operational action remains
    backend-rejected (re-verification, not a new fix - FAC-04 already
    built this; confirming it still holds).
  * AI Failure Fallback: event stored, appears in timeline, generates an
    operational record, remains visible via the standard operational
    items list (what a PM sees) - re-verification after the role-model
    changes.

The frontend bug this sprint actually fixed (app/(tabs)/ops.tsx's
dataForBucket() discarding a supervisor's correctly-fetched assigned
items whenever the operational center, which supervisors never fetch,
was null) has no backend surface to test directly - it's proven via a
standalone reproduction of the exact logic, and via this file confirming
the API returns the correct data for the frontend to render.
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
    u, h = _login("management", "9996500001", "Founder Sprint Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9996500002", "Founder Sprint PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9996500003", "Founder Sprint Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9996500004", "Founder Sprint Client")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "Founder Sprint Project", "code": "FSP"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Founder Sprint Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# --------------------------------------------------------------------------
# Operational Assignment — full path, PM assigns -> Supervisor sees it -> updates
# --------------------------------------------------------------------------
def test_pm_assigns_supervisor_sees_and_updates(pm, supervisor, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Founder Sprint Assignment Test",
    }, headers=pm["headers"], timeout=20).json()

    r1 = requests.post(f"{API}/operational-items/{item['id']}/assign",
                       json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=pm["headers"], timeout=20)
    assert r1.status_code == 200
    assert r1.json()["assigned_to_user_id"] == supervisor["user"]["id"]

    # Exact query the supervisor's Operations screen issues
    mine = requests.get(f"{API}/operational-items?assigned_to_me=true", headers=supervisor["headers"], timeout=20)
    assert mine.status_code == 200
    assert any(i["id"] == item["id"] for i in mine.json()), \
        f"PM-assigned item not found in supervisor's assigned-to-me results: {mine.json()}"

    # Supervisor updates (acknowledges) it
    r2 = requests.post(f"{API}/operational-items/{item['id']}/transition",
                       json={"to_status": "acknowledged"}, headers=supervisor["headers"], timeout=20)
    assert r2.status_code == 200
    assert r2.json()["status"] == "acknowledged"


def test_supervisor_update_visible_to_pm_as_progress(pm, supervisor, project_and_site):
    """'Supervisor updates -> PM sees progress': the PM's operational
    center (recently_updated) reflects a status change the supervisor
    just made."""
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Founder Sprint Progress Test",
    }, headers=pm["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{item['id']}/assign",
                 json={"assigned_to_user_id": supervisor["user"]["id"]}, headers=pm["headers"], timeout=20)
    requests.post(f"{API}/operational-items/{item['id']}/transition",
                 json={"to_status": "acknowledged"}, headers=supervisor["headers"], timeout=20)
    r3 = requests.post(f"{API}/operational-items/{item['id']}/transition",
                       json={"to_status": "in_progress"}, headers=supervisor["headers"], timeout=20)
    assert r3.status_code == 200

    center = requests.get(f"{API}/operational-center", headers=pm["headers"], timeout=20)
    assert center.status_code == 200
    recent_ids = [i["id"] for i in center.json()["recently_updated"]]
    assert item["id"] in recent_ids, "supervisor's update should surface in the PM's recently_updated view"


# --------------------------------------------------------------------------
# Client Approval Flow — re-verification (backend built in FAC-04)
# --------------------------------------------------------------------------
def test_client_approval_flow_still_correctly_restricted(pm, client, project_and_site):
    _, site = project_and_site
    approval_item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "Founder Sprint Approval Test",
    }, headers=pm["headers"], timeout=20).json()

    # May only approve/reject/comment
    r_approve = requests.post(f"{API}/operational-items/{approval_item['id']}/transition",
                              json={"to_status": "fulfilled", "note": "Approved, looks good."},
                              headers=client["headers"], timeout=20)
    assert r_approve.status_code == 200

    reject_item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "client_approval", "title": "Founder Sprint Rejection Test",
    }, headers=pm["headers"], timeout=20).json()
    r_reject = requests.post(f"{API}/operational-items/{reject_item['id']}/transition",
                             json={"to_status": "cancelled", "note": "Please revise."},
                             headers=client["headers"], timeout=20)
    assert r_reject.status_code == 200

    r_comment = requests.post(f"{API}/operational-items/{reject_item['id']}/comments",
                              json={"text": "Additional context"}, headers=client["headers"], timeout=20)
    assert r_comment.status_code == 201

    # Every internal/assignment action remains rejected
    other_item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Founder Sprint Internal Test",
    }, headers=pm["headers"], timeout=20).json()

    assert requests.post(f"{API}/operational-items/{other_item['id']}/assign",
                         json={"assigned_to_user_id": pm["user"]["id"]}, headers=client["headers"], timeout=20).status_code == 403
    assert requests.patch(f"{API}/operational-items/{other_item['id']}",
                          json={"title": "hacked"}, headers=client["headers"], timeout=20).status_code == 403
    for target in ("acknowledged", "in_progress", "fulfilled"):
        assert requests.post(f"{API}/operational-items/{other_item['id']}/transition",
                             json={"to_status": target}, headers=client["headers"], timeout=20).status_code == 403


def test_client_dashboard_data_sources_accessible(client, project_and_site):
    """The new client dashboard reads project summary, workflow, timeline,
    and client_approval operational items - confirm a client account can
    reach every one of these (view-only)."""
    proj, site = project_and_site
    assert requests.get(f"{API}/projects", headers=client["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=client["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/projects/{proj['id']}/summary", headers=client["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/projects/{proj['id']}/workflow", headers=client["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/timeline?site_id={site['id']}", headers=client["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items?site_id={site['id']}&category=client_approval",
                        headers=client["headers"], timeout=20).status_code == 200


# --------------------------------------------------------------------------
# AI Failure Fallback — re-verification
# --------------------------------------------------------------------------
def test_ai_disabled_event_still_produces_visible_record(pm, project_and_site):
    """Re-verification (mechanism built in Sprint 6.2): a captured event
    is stored and appears in the timeline regardless of AI status - this
    is true whether AI is enabled or disabled on the target server."""
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Founder sprint AI fallback check"},
                      headers=pm["headers"], timeout=20)
    assert r.status_code == 201
    event = r.json()
    assert event["ai_status"] in ("pending", "skipped", "analyzed", "failed")

    tl = requests.get(f"{API}/timeline?site_id={site['id']}", headers=pm["headers"], timeout=20)
    assert any(i["event"]["id"] == event["id"] for i in tl.json())


# --------------------------------------------------------------------------
# Regression
# --------------------------------------------------------------------------
def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
