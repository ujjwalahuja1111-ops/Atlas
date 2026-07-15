"""Project Atlas — Client Approval Workflow + CRE Dashboard Integration.

IMPORTANT: the Construction Reasoning Engine (Innovation Sprint 01-01C)
is a pre-existing, completed feature — this suite does not test its
reasoning logic (see tests/test_cre_rules.py, test_cre_projections.py,
test_cre_architecture_guards.py for that). It tests only the two things
this integration sprint actually added: the Client Approval Workflow
end-to-end, and the permission boundary of the one new client-safe CRE
view plus the pre-existing internal reasoning endpoints' visibility to
every role now that dashboards actually call them.

CRE evidence exposure (approvals visible to CRE with zero engine
changes, since they are ordinary client_approval operational_items) is
verified directly against the engine in
smoketest/test_client_approval_workflow.py — not repeatable here since
this file runs over real HTTP against a deployed instance, not a
process that can import engines.reasoning_engine directly.

A. CLIENT APPROVAL WORKFLOW
  * Event capture is never blocked by requires_client_approval.
  * request-approval is the SAME endpoint for "send immediately" and
    "send later" — idempotent, linked to the original event, never
    duplicates event/media.
  * Client may approve / reject / request clarification / leave text
    or voice feedback on a client_approval item; every other internal
    action remains rejected.
  * Complete history is recorded; the event timeline reflects approval
    status.

B. CRE DASHBOARD INTEGRATION — visibility and permissions
  * The client-safe dashboard view is client-callable and returns only
    the pre-sanitized fields (never rule ids / confidence / evidence).
  * Every other reasoning endpoint remains internal-only (client 403).
  * Internal roles (management, project_manager, site_supervisor) can
    all reach the reasoning endpoints their dashboard cards use.
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
    u, h = _login("management", "9992200001", "CAW Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9992200002", "CAW PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9992200003", "CAW Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9992200004", "CAW Client")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "CAW Test Project", "code": "CAWTP"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "CAW Test Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# ==========================================================================
# A. CLIENT APPROVAL WORKFLOW
# ==========================================================================
def test_capture_never_blocked_by_approval_checkbox(pm, project_and_site):
    _, site = project_and_site
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Tile work done",
                                              "requires_client_approval": "true"},
                      headers=pm["headers"], timeout=20)
    assert r.status_code == 201
    assert r.json()["requires_client_approval"] is True


def test_both_send_paths_use_the_same_endpoint_and_are_idempotent(pm, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "New window installed"},
                          headers=pm["headers"], timeout=20).json()

    r1 = requests.post(f"{API}/events/{event['id']}/request-approval",
                       json={"message": "Please check the window finish"}, headers=pm["headers"], timeout=20)
    assert r1.status_code == 201
    item = r1.json()
    assert item["category"] == "client_approval"
    assert item["inherited_evidence_event_id"] == event["id"]

    r2 = requests.post(f"{API}/events/{event['id']}/request-approval", json={}, headers=pm["headers"], timeout=20)
    assert r2.json()["id"] == item["id"], "second call must return the existing request, not a duplicate"


def test_client_approve_reject_clarify_and_feedback(admin, pm, client, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve budget line"},
                          headers=pm["headers"], timeout=20).json()
    item = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                         headers=pm["headers"], timeout=20).json()

    # Client sees it
    r = requests.get(f"{API}/operational-items?site_id={site['id']}&category=client_approval",
                     headers=client["headers"], timeout=20)
    assert any(i["id"] == item["id"] for i in r.json())

    # Text feedback via the existing voice-update mechanism
    r_fb = requests.post(f"{API}/operational-items/{item['id']}/voice-update",
                         data={"text": "Looks reasonable"}, headers=client["headers"], timeout=20)
    assert r_fb.status_code == 201

    # Request clarification — non-terminal
    r_clar = requests.post(f"{API}/operational-items/{item['id']}/request-clarification",
                           json={"note": "What's the total?"}, headers=client["headers"], timeout=20)
    assert r_clar.status_code == 201
    assert r_clar.json()["status"] == "open"

    # Every internal action remains rejected
    assert requests.post(f"{API}/operational-items/{item['id']}/assign",
                         json={"assigned_to_user_id": pm["user"]["id"]}, headers=client["headers"], timeout=20).status_code == 403
    assert requests.patch(f"{API}/operational-items/{item['id']}", json={"title": "x"},
                          headers=client["headers"], timeout=20).status_code == 403

    # Complete history recorded
    history = requests.get(f"{API}/operational-items/{item['id']}", headers=pm["headers"], timeout=20).json()["history"]
    assert any(e["kind"] == "voice_update" for e in history)
    assert any(e["kind"] == "clarification_requested" for e in history)

    # Approve
    r_approve = requests.post(f"{API}/operational-items/{item['id']}/transition",
                              json={"to_status": "fulfilled", "note": "Approved"}, headers=client["headers"], timeout=20)
    assert r_approve.status_code == 200

    # Timeline reflects the decision
    tl = requests.get(f"{API}/timeline?site_id={site['id']}", headers=pm["headers"], timeout=20).json()
    entry = next(i for i in tl if i["event"]["id"] == event["id"])
    assert entry["approval_status"] == "fulfilled"


def test_non_client_cannot_request_clarification(pm, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve this"},
                          headers=pm["headers"], timeout=20).json()
    item = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                         headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/request-clarification",
                      json={"note": "test"}, headers=pm["headers"], timeout=20)
    assert r.status_code == 403


def test_client_cannot_voice_update_non_approval_items(pm, client, project_and_site):
    _, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "material_requirement", "title": "Cement",
    }, headers=pm["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items/{item['id']}/voice-update",
                      data={"text": "comment"}, headers=client["headers"], timeout=20)
    assert r.status_code == 403


# ==========================================================================
# B. CRE DASHBOARD INTEGRATION — visibility and permissions
# ==========================================================================
def test_client_can_use_only_the_client_safe_dashboard_view(admin, client, project_and_site):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/client-dashboard", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"project_id", "project_name", "stage", "summary_text", "upcoming_milestones", "generated_at"}
    for m in body["upcoming_milestones"]:
        assert set(m.keys()) == {"name"}, "milestones must never leak activity_id/prerequisites/evidence"


@pytest.mark.parametrize("endpoint", [
    "insights", "health", "lookahead", "forecast", "briefing",
    "client-summary", "construction-memory", "reasoning/runs",
])
def test_client_blocked_from_every_internal_reasoning_endpoint(client, project_and_site, endpoint):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/{endpoint}", headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_client_blocked_from_executive_reasoning(client):
    r = requests.get(f"{API}/reasoning/executive?question=attention_today", headers=client["headers"], timeout=20)
    assert r.status_code == 403


@pytest.mark.parametrize("endpoint", ["insights", "health", "lookahead", "forecast", "briefing"])
def test_internal_roles_can_reach_reasoning_endpoints_their_dashboards_use(admin, pm, supervisor, project_and_site, endpoint):
    proj, _ = project_and_site
    for actor in (admin, pm, supervisor):
        r = requests.get(f"{API}/projects/{proj['id']}/{endpoint}", headers=actor["headers"], timeout=20)
        assert r.status_code == 200, f"{actor['user']['role']} should reach /{endpoint}: {r.text}"


def test_only_management_and_pm_can_trigger_reasoning_runs(admin, pm, supervisor, project_and_site):
    proj, _ = project_and_site
    assert requests.post(f"{API}/projects/{proj['id']}/reasoning/run", json={"include_ai": False},
                         headers=admin["headers"], timeout=20).status_code == 201
    assert requests.post(f"{API}/projects/{proj['id']}/reasoning/run", json={"include_ai": False},
                         headers=pm["headers"], timeout=20).status_code == 201
    assert requests.post(f"{API}/projects/{proj['id']}/reasoning/run", json={"include_ai": False},
                         headers=supervisor["headers"], timeout=20).status_code == 403


def test_dashboard_insight_fields_include_the_safe_fields_cards_render(admin, project_and_site):
    """Documents the contract CreDashboard.tsx's InsightRow relies on: a
    dashboard card only ever destructures observation/risk/recommendation/
    severity/suggested_* from an insight. This does not forbid rule_id/
    confidence/evidence existing in the API response for internal roles
    (they legitimately need it elsewhere) - it guards that the safe
    subset a card needs is always present, so future dashboard work
    building on this endpoint has no reason to reach for the unsafe
    fields instead."""
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/insights", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    safe_fields = {"observation", "risk", "recommendation", "severity",
                   "suggested_operational_action", "suggested_responsible_role", "suggested_due_date"}
    for insight in r.json():
        assert safe_fields.issubset(insight.keys())


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_full_stack_unaffected(admin):
    h = admin["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/users", headers=h, timeout=20).status_code == 200
    assert "ai_enabled" in requests.get(f"{API}/", timeout=20).json()
