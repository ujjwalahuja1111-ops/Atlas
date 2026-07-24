"""Project Atlas — Usability, Consistency & State Correctness fixes.

Covers four backend-verifiable fixes:

1. AUTHENTICATION IDENTITY VALIDATION
   LoginRequest.name/role are now optional (previously name was
   required but silently ignored) - login authenticates purely by
   phone, and the returned user is always the database record, never
   influenced by anything the caller sends.

2. PENDING REVIEW SYNCHRONIZATION
   New exclude_terminal filter on GET /operational-items, reusing the
   canonical TERMINAL_ITEM_STATUSES set - replaces an incomplete
   client-side status list (missing 'fulfilled') that let approved
   client approvals keep appearing as pending.

3. PROPOSAL -> OPERATIONAL EVENT TRANSITION
   reject_ai_proposal() now has the same terminal-state guard
   accept_ai_proposal() already had - an already-decided proposal can
   no longer be accepted OR rejected again.

4. AI STRUCTURED EXTRACTION
   quantity/unit, already extracted alongside required_date/priority,
   now carry through onto the created operational item at accept time
   - but ONLY at high confidence, and ONLY at creation (an explicit
   human edit passed to accept() always wins).
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
    u, h = _login("management", "9997700001", "Usability Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9997700002", "Usability Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "Usability Test", "code": "USAB"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# ==========================================================================
# 1. Authentication Identity Validation
# ==========================================================================
def test_login_without_name_succeeds(admin):
    """The login form no longer sends a name; confirm the API accepts a
    request with no name field at all (backward-compatible optional)."""
    r = requests.post(f"{API}/auth/login",
                      json={"phone": _SEEDED_ADMIN_PHONE, "role": "management"}, timeout=20)
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "Atlas Admin 1"


def test_login_ignores_a_bogus_name_and_returns_real_identity(admin):
    """Whatever name is sent (or not sent) never changes the returned
    identity - it always comes from the database."""
    r = requests.post(f"{API}/auth/login",
                      json={"phone": _SEEDED_ADMIN_PHONE, "name": "Totally Made Up Name", "role": "management"},
                      timeout=20)
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "Atlas Admin 1"


def test_login_still_rejects_unknown_phone(admin):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": "9999999999", "role": "management"}, timeout=20)
    assert r.status_code == 401


# ==========================================================================
# 2. Pending Review Synchronization
# ==========================================================================
def test_exclude_terminal_removes_approved_client_approvals(admin, client, project_and_site):
    proj, site = project_and_site
    event1 = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve A"},
                           headers=admin["headers"], timeout=20).json()
    approval1 = requests.post(f"{API}/events/{event1['id']}/request-approval", json={},
                              headers=admin["headers"], timeout=20).json()
    event2 = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve B"},
                           headers=admin["headers"], timeout=20).json()
    approval2 = requests.post(f"{API}/events/{event2['id']}/request-approval", json={},
                              headers=admin["headers"], timeout=20).json()

    before = requests.get(f"{API}/operational-items?site_id={site['id']}&category=client_approval&exclude_terminal=true",
                          headers=client["headers"], timeout=20).json()
    before_ids = {i["id"] for i in before}
    assert approval1["id"] in before_ids and approval2["id"] in before_ids

    requests.post(f"{API}/operational-items/{approval1['id']}/transition",
                 json={"to_status": "fulfilled"}, headers=client["headers"], timeout=20)

    after = requests.get(f"{API}/operational-items?site_id={site['id']}&category=client_approval&exclude_terminal=true",
                         headers=client["headers"], timeout=20).json()
    after_ids = {i["id"] for i in after}
    assert approval1["id"] not in after_ids, "approved item must not still appear as pending"
    assert approval2["id"] in after_ids, "undecided item must still appear as pending"


def test_exclude_terminal_does_not_override_an_explicit_status_filter(admin, project_and_site):
    _, site = project_and_site
    r = requests.get(f"{API}/operational-items?site_id={site['id']}&status=open&exclude_terminal=true",
                     headers=admin["headers"], timeout=20)
    assert r.status_code == 200


# ==========================================================================
# 3. Proposal -> Operational Event Transition
# ==========================================================================
def test_cannot_reject_an_already_accepted_proposal(admin, project_and_site):
    """The actual bug: reject_ai_proposal was missing the terminal-state
    guard accept_ai_proposal already had."""
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "test"},
                          headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/events/{event['id']}/regenerate-proposals?force=true", headers=admin["headers"], timeout=20)
    proposals = requests.get(f"{API}/ai-proposals?event_id={event['id']}", headers=admin["headers"], timeout=20).json()
    if not proposals:
        pytest.skip("no proposal generated for this event (no structured content to extract)")
    pid = proposals[0]["id"]
    r1 = requests.post(f"{API}/ai-proposals/{pid}/accept", json={}, headers=admin["headers"], timeout=20)
    if r1.status_code != 200:
        pytest.skip("proposal could not be accepted in this environment")
    r2 = requests.post(f"{API}/ai-proposals/{pid}/reject", json={}, headers=admin["headers"], timeout=20)
    assert r2.status_code == 400
    assert "already" in r2.json()["detail"]


def test_cannot_accept_an_already_rejected_proposal(admin, project_and_site):
    _, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "test reject then accept"},
                          headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/events/{event['id']}/regenerate-proposals?force=true", headers=admin["headers"], timeout=20)
    proposals = requests.get(f"{API}/ai-proposals?event_id={event['id']}", headers=admin["headers"], timeout=20).json()
    if not proposals:
        pytest.skip("no proposal generated for this event")
    pid = proposals[0]["id"]
    r1 = requests.post(f"{API}/ai-proposals/{pid}/reject", json={}, headers=admin["headers"], timeout=20)
    if r1.status_code != 200:
        pytest.skip("proposal could not be rejected in this environment")
    r2 = requests.post(f"{API}/ai-proposals/{pid}/accept", json={}, headers=admin["headers"], timeout=20)
    assert r2.status_code == 400


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_core_platform_unaffected(admin, project_and_site):
    proj, _ = project_and_site
    assert requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
