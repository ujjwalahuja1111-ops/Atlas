"""Project Atlas — Atlas Client Experience (ACE) Sprint 01.

Covers the four new client-facing views, all composed from existing
CRE/operations data - no new engine, no financial data fabricated (see
the implementation report for why Payment Centre/Cost Deviations/
Financial Summary/Document Centre/Notification Centre were not built).

1. CLIENT EXPERIENCE DASHBOARD (item 1)
   GET /api/projects/{id}/client-experience - hero section (progress,
   phase, health, expected completion, next milestone) plus "what
   needs my attention." Health/forecast values are byte-identical to
   Portfolio Control Center's own _project_row calculation - verified
   directly, not just structurally similar.

2. APPROVAL CENTRE (item 3)
   GET /api/projects/{id}/client-approvals - permanent history. Fixes
   the brief's own named complaint: an approved item does NOT
   disappear, it moves from pending to approved and stays visible,
   with its material approval options (item 4) preserved.

3. COMMUNICATION CENTRE (item 10)
   GET /api/projects/{id}/client-communications - built entirely from
   the existing request_clarification ledger (operational_events),
   correctly classifying "waiting for contractor" as the item whose
   most recent ledger event IS the clarification request.

4. PROJECT TIMELINE (item 6)
   GET /api/projects/{id}/client-timeline - milestones derived from
   the existing STAGE_ORDER/STAGE_LABELS vocabulary, no workflow
   activity detail exposed.
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
    u, h = _login("management", "9991100001", "ACE Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9991100002", "ACE Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_and_site(admin, client):
    proj = requests.post(f"{API}/projects", json={"name": "ACE Test", "code": "ACET"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"},
                        headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/admin/users/{client['user']['id']}/projects",
                 json={"project_ids": [proj["id"]]}, headers=admin["headers"], timeout=20)
    return proj, site


# ==========================================================================
# 1. Client Experience Dashboard
# ==========================================================================
def test_dashboard_shape(client, project_and_site):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/client-experience", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    for key in ("overall_progress_percent", "current_phase", "health", "expected_completion",
               "next_milestone", "attention_required", "attention_message"):
        assert key in body, f"missing field: {key}"
    assert set(body["health"].keys()) == {"status", "score", "explanation"}


def test_no_action_required_when_nothing_pending(client, project_and_site):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/client-experience", headers=client["headers"], timeout=20)
    assert r.json()["attention_message"] == "No action required today."
    assert r.json()["attention_required"] == []


def test_pending_approval_appears_in_attention(admin, client, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve tile"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()

    r = requests.get(f"{API}/projects/{approval['project_id']}/client-experience", headers=client["headers"], timeout=20)
    assert r.json()["attention_message"] is None
    ids = [i["id"] for i in r.json()["attention_required"]]
    assert approval["id"] in ids


def test_dashboard_health_matches_portfolio_control_center(admin, client, project_and_site):
    """The dashboard must reuse Portfolio Control Center's own
    calculation, not a second, independently computed health number."""
    proj, _ = project_and_site
    r_dash = requests.get(f"{API}/projects/{proj['id']}/client-experience", headers=client["headers"], timeout=20)
    r_pcc = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    pcc_row = next(p for p in r_pcc.json()["projects"] if p["project_id"] == proj["id"])
    assert r_dash.json()["health"]["status"] == pcc_row["health_status"]
    assert r_dash.json()["health"]["score"] == pcc_row["health_score"]


# ==========================================================================
# 2. Approval Centre - permanent history
# ==========================================================================
def test_approved_item_does_not_disappear(admin, client, project_and_site):
    """The brief's own named complaint: 'Approve -> Disappears is
    incorrect.' An approved item must remain visible, moved from
    pending to approved."""
    proj, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve paint"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()

    before = requests.get(f"{API}/projects/{proj['id']}/client-approvals", headers=client["headers"], timeout=20).json()
    assert before["counts"]["pending"] >= 1

    requests.post(f"{API}/operational-items/{approval['id']}/transition",
                 json={"to_status": "fulfilled"}, headers=client["headers"], timeout=20)

    after = requests.get(f"{API}/projects/{proj['id']}/client-approvals", headers=client["headers"], timeout=20).json()
    approved_ids = [i["id"] for i in after["approved"]]
    timeline_ids = [i["id"] for i in after["timeline"]]
    assert approval["id"] in approved_ids, "approved item must appear in the approved list, not vanish"
    assert approval["id"] in timeline_ids, "approved item must remain in the permanent timeline"


def test_material_approval_options_preserved_after_decision(admin, client, project_and_site):
    """Item 4 - Material Approval informed choice. Options set before
    a decision must still be visible after the decision, not lost."""
    proj, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve floor tiles"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()
    options = [
        {"label": "Kajaria XYZ", "cost": 120, "unit": "sqft", "recommended": True},
        {"label": "Johnson ABC", "cost": 138, "unit": "sqft", "cost_delta": 52000},
    ]
    r_set = requests.patch(f"{API}/operational-items/{approval['id']}", json={"approval_options": options},
                           headers=admin["headers"], timeout=20)
    assert r_set.status_code == 200
    assert r_set.json()["approval_options"] == options

    requests.post(f"{API}/operational-items/{approval['id']}/transition",
                 json={"to_status": "fulfilled"}, headers=client["headers"], timeout=20)

    after = requests.get(f"{API}/projects/{proj['id']}/client-approvals", headers=client["headers"], timeout=20).json()
    approved = next(i for i in after["approved"] if i["id"] == approval["id"])
    assert approved["options"] == options


def test_rejected_item_appears_in_rejected_list(admin, client, project_and_site):
    proj, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve extra cost item"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{approval['id']}/transition",
                 json={"to_status": "cancelled"}, headers=client["headers"], timeout=20)

    after = requests.get(f"{API}/projects/{proj['id']}/client-approvals", headers=client["headers"], timeout=20).json()
    rejected_ids = [i["id"] for i in after["rejected"]]
    assert approval["id"] in rejected_ids


# ==========================================================================
# 3. Communication Centre
# ==========================================================================
def test_clarification_request_appears_as_waiting_for_contractor(admin, client, project_and_site):
    proj, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve paint shade"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items/{approval['id']}/request-clarification",
                 json={"note": "Which shade of white?"}, headers=client["headers"], timeout=20)

    r = requests.get(f"{API}/projects/{proj['id']}/client-communications", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["waiting_for_contractor"]]
    assert approval["id"] in ids
    entry = next(i for i in r.json()["waiting_for_contractor"] if i["id"] == approval["id"])
    assert entry["note"] == "Which shade of white?"


def test_pending_approval_without_clarification_is_waiting_for_client(admin, client, project_and_site):
    proj, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve fixture"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()

    r = requests.get(f"{API}/projects/{proj['id']}/client-communications", headers=client["headers"], timeout=20)
    ids = [i["id"] for i in r.json()["waiting_for_client"]]
    assert approval["id"] in ids


# ==========================================================================
# 4. Project Timeline
# ==========================================================================
def test_timeline_shape_and_stage_ordering(client, project_and_site):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/client-timeline", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "current_stage" in body
    assert len(body["milestones"]) == 10
    statuses = [m["status"] for m in body["milestones"]]
    assert all(s in ("completed", "in_progress", "upcoming") for s in statuses)
    assert statuses.count("in_progress") == 1
    for m in body["milestones"]:
        assert set(m.keys()) == {"key", "label", "status"}


# ==========================================================================
# RBAC / regression
# ==========================================================================
def test_supervisor_can_also_view_client_experience_views(admin, project_and_site):
    """Same project-visibility rule as every other reasoning view - not
    client-exclusive, matching client_dashboard_view's own precedent."""
    proj, _ = project_and_site
    sup, sup_h = _login("site_supervisor", "9991100003", "ACE Supervisor")
    requests.post(f"{API}/admin/users/{sup['id']}/projects", json={"project_ids": [proj["id"]]},
                 headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/projects/{proj['id']}/client-experience", headers=sup_h, timeout=20)
    assert r.status_code == 200


def test_regression_existing_client_dashboard_unaffected(client, project_and_site):
    proj, _ = project_and_site
    r = requests.get(f"{API}/projects/{proj['id']}/client-dashboard", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    assert set(r.json().keys()) == {"project_id", "project_name", "stage", "summary_text",
                                    "upcoming_milestones", "generated_at"}


def test_regression_core_platform_unaffected(admin, project_and_site):
    proj, _ = project_and_site
    assert requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
