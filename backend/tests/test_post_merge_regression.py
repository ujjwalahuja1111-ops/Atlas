"""Project Atlas — Post-merge regression: "Objects are not valid as a
React child" crash + a silent client-dashboard field-shape mismatch.

Root cause (both bugs): frontend/src/cre_api.ts's apiExecutiveAnswer
was typed Promise<any>, and engines/reasoning_engine.py's
client_dashboard_view (added in the same merge) mis-assumed one field's
shape from a function it called. Neither was caught by the type checker
(any bypasses it) or by the original tests (which checked key presence,
not value shape). Both are now precisely typed/tested.

Bug 1 — the reported crash: frontend/src/CreDashboard.tsx's
ManagementCreCards rendered `attention.summary || attention.answer` (a
whole object, when the string field it was assuming into existence,
`summary`, never existed) directly inside a <Text> child. Fixed in the
frontend only (rendering layer) - the backend's executive_answer
contract was already correct: {question, question_text, scope,
answer: {items, total_open_urgent}, explanation}. This file verifies
the backend contract precisely (so any future rendering fix has an
accurate contract to work from); the fix to CreDashboard.tsx itself is
a frontend-only change with no backend-testable surface for the
rendering fragment specifically, verified separately in
smoketest/test_founder_flows_post_merge.py by exercising the exact
fixed rendering logic against a real response.

Bug 2 — a silent failure, not a crash (found while investigating bug 1
alongside every other CRE dashboard field access): engines/
reasoning_engine.py's client_dashboard_view set "stage" from
compose_client_summary's own "stage" field, which is only ever the
plain string stage["current"] (see compose_client_summary's final
return statement, unmodified, still correct for its existing internal
-only consumer /client-summary). The client dashboard needs the full
{current, current_label} dict, which client_dashboard_view already
computes via project_lookahead and now correctly uses instead. This IS
a backend fix - the wrapper function this sprint added, not the
pre-existing compose_client_summary it calls.
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


@pytest.fixture(scope="session")
def admin():
    return {"headers": _seeded_admin_headers()}


@pytest.fixture()
def project(admin):
    return requests.post(f"{API}/projects", json={"name": "Post-Merge Regression", "code": "PMR"},
                         headers=admin["headers"], timeout=20).json()


# --------------------------------------------------------------------------
# Bug 1 — executive_answer's exact response contract (what the frontend
# fix now correctly relies on)
# --------------------------------------------------------------------------
def test_executive_answer_attention_today_exact_shape(admin):
    r = requests.get(f"{API}/reasoning/executive?question=attention_today", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"question", "question_text", "scope", "answer", "explanation"}
    assert set(body["answer"].keys()) == {"items", "total_open_urgent"}
    assert isinstance(body["answer"]["total_open_urgent"], int)
    assert isinstance(body["answer"]["items"], list)
    # The exact bug: neither "summary" nor "projects_needing_attention"
    # has ever existed on this response - a rendering fix that assumes
    # either must not silently pass by falling through to something else.
    assert "summary" not in body
    assert "projects_needing_attention" not in body


def test_executive_answer_attention_today_item_shape(admin, project):
    """Each item in answer.items is a PROJECTED subset of an insight
    (only 7 fields) - not a full insight document. A rendering fix must
    only rely on fields actually present here."""
    r = requests.get(f"{API}/reasoning/executive?question=attention_today", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    for item in r.json()["answer"]["items"]:
        assert set(item.keys()) == {"id", "project_id", "project_name", "severity",
                                    "observation", "recommendation", "suggested_due_date", "domain"}


# --------------------------------------------------------------------------
# Bug 2 — client_dashboard_view's stage field must be the full dict
# --------------------------------------------------------------------------
def test_client_dashboard_stage_is_the_full_dict_not_a_string(admin, project):
    r = requests.get(f"{API}/projects/{project['id']}/client-dashboard", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["stage"], dict), \
        f"client-dashboard's stage must be {{current, current_label}}, got {type(body['stage'])}: {body['stage']}"
    assert set(body["stage"].keys()) >= {"current", "current_label"}
    assert isinstance(body["stage"]["current_label"], str) and body["stage"]["current_label"]


def test_internal_client_summary_endpoint_unaffected(admin, project):
    """The pre-existing, internal-only /client-summary endpoint (which
    also calls compose_client_summary, untouched by the fix above) must
    be completely unaffected - its own "stage" field is correctly still
    the plain string, exactly as designed before this fix existed."""
    r = requests.get(f"{API}/projects/{project['id']}/client-summary", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["stage"], str)
    assert "sentences" in body and "summary_text" in body and "disclaimer" in body


def test_client_can_use_the_fixed_dashboard_view(admin, project):
    reg = requests.post(f"{API}/auth/register", json={"phone": "9994600001", "name": "PMR Client"}, timeout=20)
    uid = reg.json()["user"]["id"]
    requests.post(f"{API}/admin/users/{uid}/approve", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/admin/users/{uid}/role", json={"role": "client"}, headers=admin["headers"], timeout=20)
    login = requests.post(f"{API}/auth/login", json={"phone": "9994600001", "name": "PMR Client", "role": "client"}, timeout=20)
    client_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    r = requests.get(f"{API}/projects/{project['id']}/client-dashboard", headers=client_headers, timeout=20)
    assert r.status_code == 200
    assert isinstance(r.json()["stage"], dict)


# --------------------------------------------------------------------------
# Founder flows — regression sweep for the merge as a whole
# --------------------------------------------------------------------------
def test_founder_flow_login_dashboard_feed(admin, project):
    assert requests.get(f"{API}/projects", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=admin["headers"], timeout=20).status_code == 200
    site = requests.post(f"{API}/sites", json={"project_id": project["id"], "name": "Site"},
                         headers=admin["headers"], timeout=20).json()
    assert requests.get(f"{API}/timeline?site_id={site['id']}", headers=admin["headers"], timeout=20).status_code == 200


def test_founder_flow_event_capture_and_ai_proposals(admin, project):
    site = requests.post(f"{API}/sites", json={"project_id": project["id"], "name": "Site2"},
                         headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Regression sweep event"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    assert requests.get(f"{API}/ai-proposals", headers=admin["headers"], timeout=20).status_code == 200


def test_founder_flow_operational_items(admin, project):
    site = requests.post(f"{API}/sites", json={"project_id": project["id"], "name": "Site3"},
                         headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/operational-items", json={"site_id": site["id"], "category": "material_requirement", "title": "x"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200


def test_founder_flow_cre_endpoints_all_load(admin, project):
    for path in ["health", "insights", "lookahead", "forecast", "briefing"]:
        r = requests.get(f"{API}/projects/{project['id']}/{path}", headers=admin["headers"], timeout=20)
        assert r.status_code == 200, f"/{path}: {r.text}"
