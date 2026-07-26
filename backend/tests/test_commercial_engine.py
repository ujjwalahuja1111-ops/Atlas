"""Project Atlas — Commercial Foundation Engine (CF-01).

Comprehensive coverage of the real, state-machine-governed Commercial
Foundation Engine — Contract, Milestone, Payment Request, Payment,
Variation, Budget — replacing the lightweight commercial_reference
placeholder.

Every scenario here was first verified manually against a live
instance before being written as a permanent test, per Atlas
Engineering Standards v1 §10's own regression discipline: a real bug
fix or a real verified behavior becomes a permanent test, not a
one-off manual check.
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
    u, h = _login("management", "9996600001", "CF Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9996600002", "CF Client")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9996600003", "CF Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_with_contract(admin):
    proj = requests.post(f"{API}/projects", json={"name": "CF Test", "code": "CFT"},
                         headers=admin["headers"], timeout=20).json()
    contract = requests.post(f"{API}/commercial/contracts", json={
        "project_id": proj["id"], "original_contract_value": 10000000,
        "contract_date": "2026-01-01", "duration_days": 180,
    }, headers=admin["headers"], timeout=20).json()
    return proj, contract


# ==========================================================================
# Contract
# ==========================================================================
def test_contract_current_value_equals_original_when_no_variations(admin, project_with_contract):
    _, contract = project_with_contract
    assert contract["current_contract_value"] == 10000000


def test_second_contract_for_same_project_rejected(admin, project_with_contract):
    proj, _ = project_with_contract
    r = requests.post(f"{API}/commercial/contracts", json={
        "project_id": proj["id"], "original_contract_value": 5000000,
        "contract_date": "2026-01-01", "duration_days": 90,
    }, headers=admin["headers"], timeout=20)
    assert r.status_code == 400


def test_supervisor_cannot_create_contract(supervisor):
    proj_id = "prj_fake_for_rbac_test"
    r = requests.post(f"{API}/commercial/contracts", json={
        "project_id": proj_id, "original_contract_value": 1000000,
        "contract_date": "2026-01-01", "duration_days": 90,
    }, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_client_can_read_contract(client, project_with_contract):
    proj, _ = project_with_contract
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/contract", headers=client["headers"], timeout=20)
    assert r.status_code == 200


# ==========================================================================
# Milestone lifecycle and derived contract_value
# ==========================================================================
def test_milestone_contract_value_derived_from_percent(admin, project_with_contract):
    proj, _ = project_with_contract
    r = requests.post(f"{API}/commercial/milestones", json={
        "project_id": proj["id"], "name": "Foundation Complete", "sequence": 1,
        "planned_percent": 15, "trigger": "Foundation cast", "planned_date": "2026-02-15",
    }, headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    assert r.json()["contract_value"] == 1500000  # 15% of 1cr


def test_milestone_illegal_transition_rejected(admin, project_with_contract):
    proj, _ = project_with_contract
    ms = requests.post(f"{API}/commercial/milestones", json={
        "project_id": proj["id"], "name": "Roof", "sequence": 2,
        "planned_percent": 10, "trigger": "Roof cast",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/commercial/milestones/{ms['id']}/status",
                      json={"status": "paid"}, headers=admin["headers"], timeout=20)
    assert r.status_code == 400


def test_payment_request_rejected_against_non_achieved_milestone(admin, project_with_contract):
    proj, _ = project_with_contract
    ms = requests.post(f"{API}/commercial/milestones", json={
        "project_id": proj["id"], "name": "Structure", "sequence": 3,
        "planned_percent": 20, "trigger": "Structure complete",
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/commercial/payment-requests", json={
        "project_id": proj["id"], "milestone_id": ms["id"], "amount": 100000,
        "raised_date": "2026-03-01", "due_date": "2026-03-15",
    }, headers=admin["headers"], timeout=20)
    assert r.status_code == 400
    assert "achieved" in r.json()["detail"]


# ==========================================================================
# Payment lifecycle - partial, multiple, milestone auto-transitions
# ==========================================================================
def test_payment_lifecycle_partial_then_full(admin, client, project_with_contract):
    proj, _ = project_with_contract
    ms = requests.post(f"{API}/commercial/milestones", json={
        "project_id": proj["id"], "name": "Brickwork", "sequence": 4,
        "planned_percent": 10, "trigger": "Brickwork complete",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/milestones/{ms['id']}/status", json={"status": "ready"}, headers=admin["headers"], timeout=20)
    ms = requests.post(f"{API}/commercial/milestones/{ms['id']}/status", json={"status": "achieved"}, headers=admin["headers"], timeout=20).json()
    assert ms["actual_date"] is not None

    pr = requests.post(f"{API}/commercial/payment-requests", json={
        "project_id": proj["id"], "milestone_id": ms["id"], "amount": 1000000,
        "raised_date": "2026-03-01", "due_date": "2026-03-15",
    }, headers=admin["headers"], timeout=20).json()

    ms_after = requests.get(f"{API}/projects/{proj['id']}/commercial/milestones", headers=admin["headers"], timeout=20).json()
    this_ms = next(m for m in ms_after if m["id"] == ms["id"])
    assert this_ms["status"] == "payment_requested"

    requests.post(f"{API}/commercial/payment-requests/{pr['id']}/status", json={"status": "raised"}, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/payment-requests/{pr['id']}/status", json={"status": "sent"}, headers=admin["headers"], timeout=20)

    r1 = requests.post(f"{API}/commercial/payments", json={
        "payment_request_id": pr["id"], "amount": 600000, "date": "2026-03-10", "method": "bank_transfer",
    }, headers=admin["headers"], timeout=20)
    assert r1.status_code == 201

    prs = requests.get(f"{API}/projects/{proj['id']}/commercial/payment-requests", headers=admin["headers"], timeout=20).json()
    this_pr = next(p for p in prs if p["id"] == pr["id"])
    assert this_pr["status"] == "partially_paid"

    r2 = requests.post(f"{API}/commercial/payments", json={
        "payment_request_id": pr["id"], "amount": 400000, "date": "2026-03-15", "method": "bank_transfer",
    }, headers=admin["headers"], timeout=20)
    assert r2.status_code == 201

    prs2 = requests.get(f"{API}/projects/{proj['id']}/commercial/payment-requests", headers=admin["headers"], timeout=20).json()
    this_pr2 = next(p for p in prs2 if p["id"] == pr["id"])
    assert this_pr2["status"] == "paid"

    ms_final = requests.get(f"{API}/projects/{proj['id']}/commercial/milestones", headers=admin["headers"], timeout=20).json()
    this_ms_final = next(m for m in ms_final if m["id"] == ms["id"])
    assert this_ms_final["status"] == "paid", "milestone must auto-transition to paid once its payment request is fully paid"


# ==========================================================================
# Variation approval - the Client Impact Engine + automatic Contract update
# ==========================================================================
def test_approved_variation_updates_contract_value_automatically(admin, client, project_with_contract):
    proj, _ = project_with_contract
    var = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj["id"], "title": "Extra bathroom", "description": "test",
        "original_cost": 0, "proposed_cost": 350000, "time_impact_days": 10,
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/variations/{var['id']}/submit", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{var['id']}/send-for-client-review", headers=admin["headers"], timeout=20)

    r = requests.post(f"{API}/commercial/variations/{var['id']}/decide",
                      json={"decision": "approved"}, headers=client["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["impact"]["cost_impact"] == 350000
    assert r.json()["impact"]["schedule_impact_days"] == 10

    contract = requests.get(f"{API}/projects/{proj['id']}/commercial/contract", headers=admin["headers"], timeout=20).json()
    assert contract["current_contract_value"] == 10350000


def test_rejected_variation_does_not_affect_contract(admin, client, project_with_contract):
    proj, contract_before = project_with_contract
    before_value = requests.get(f"{API}/projects/{proj['id']}/commercial/contract",
                                headers=admin["headers"], timeout=20).json()["current_contract_value"]

    var = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj["id"], "title": "Rejected item", "description": "test",
        "original_cost": 0, "proposed_cost": 999999,
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/variations/{var['id']}/submit", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{var['id']}/send-for-client-review", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{var['id']}/decide",
                 json={"decision": "rejected"}, headers=client["headers"], timeout=20)

    after_value = requests.get(f"{API}/projects/{proj['id']}/commercial/contract",
                               headers=admin["headers"], timeout=20).json()["current_contract_value"]
    assert after_value == before_value


def test_variation_cannot_be_decided_before_client_review(admin, project_with_contract):
    proj, _ = project_with_contract
    var = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj["id"], "title": "Draft item", "description": "test",
        "original_cost": 0, "proposed_cost": 50000,
    }, headers=admin["headers"], timeout=20).json()
    r = requests.post(f"{API}/commercial/variations/{var['id']}/decide",
                      json={"decision": "approved"}, headers=admin["headers"], timeout=20)
    assert r.status_code == 400


# ==========================================================================
# Budget calculations
# ==========================================================================
def test_budget_forecast_variance_remaining(admin, project_with_contract):
    proj, _ = project_with_contract
    requests.post(f"{API}/commercial/budgets", json={
        "project_id": proj["id"], "original_budget": 8500000,
    }, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/projects/{proj['id']}/commercial/budget/commit-cost",
                 json={"amount_delta": 5000000, "reason": "Steel committed"}, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/projects/{proj['id']}/commercial/budget/record-actual-cost",
                 json={"amount_delta": 3200000, "reason": "Spend to date"}, headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/projects/{proj['id']}/commercial/budget", headers=admin["headers"], timeout=20)
    b = r.json()
    assert b["forecast_cost"] == 5000000  # max(committed, actual)
    assert b["variance"] == 3500000       # 8.5M - 5M
    assert b["remaining_budget"] == 5300000  # 8.5M - 3.2M


def test_budget_is_never_client_visible(client, admin, project_with_contract):
    proj, _ = project_with_contract
    requests.post(f"{API}/commercial/budgets", json={
        "project_id": proj["id"], "original_budget": 1000000,
    }, headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/budget", headers=client["headers"], timeout=20)
    assert r.status_code == 403


# ==========================================================================
# Commercial Timeline integration
# ==========================================================================
def test_commercial_events_appear_in_commercial_timeline(admin, project_with_contract):
    proj, _ = project_with_contract
    r = requests.get(f"{API}/projects/{proj['id']}/commercial-timeline", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 1
    assert any(e["kind"] == "contract_created" for e in events)
    assert all("title" in e and "created_at" in e for e in events)


# ==========================================================================
# Commercial summary composition
# ==========================================================================
def test_commercial_summary_composes_everything(admin, project_with_contract):
    proj, _ = project_with_contract
    requests.post(f"{API}/commercial/budgets", json={
        "project_id": proj["id"], "original_budget": 8000000,
    }, headers=admin["headers"], timeout=20)
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/summary", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    summary = r.json()
    for key in ("contract", "budget", "milestones", "milestone_completion_percent",
               "payment_requests", "payments", "outstanding_payments", "cash_flow_signal",
               "variations", "approved_variations_total", "pending_variations_total"):
        assert key in summary, f"missing field: {key}"


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_reference_portfolio_endpoints_unaffected(admin):
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200


def test_regression_core_platform_unaffected(admin, project_with_contract):
    proj, _ = project_with_contract
    assert requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
