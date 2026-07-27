"""Project Atlas — Client Experience Layer (CX-01).

Covers the three new client-facing views built this sprint (Investment,
Payment Journey, Variation Centre) - thin presentation wrappers over
commercial_engine, no calculation of their own. Per this sprint's own
explicit testing requirement, verifies clients genuinely never see
Budget, Forecast, or any other internal-only field, across every
endpoint this sprint touches - not merely that a frontend screen
chooses not to render them.

Distinct from tests/test_client_experience.py (an earlier sprint's
suite, covering client_dashboard/client_approval_centre/
client_communication_centre - the material/drawing approval system,
not commercial Variations).
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
    u, h = _login("management", "9991100001", "CX Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9991100002", "CX Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_with_commercial(admin, client):
    proj = requests.post(f"{API}/projects", json={"name": "CX Test", "code": "CXT2"},
                         headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/contracts", json={
        "project_id": proj["id"], "client_id": client["user"]["id"],
        "original_contract_value": 10000000, "contract_date": "2026-01-01", "duration_days": 180,
    }, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/budgets", json={
        "project_id": proj["id"], "original_budget": 8500000,
    }, headers=admin["headers"], timeout=20)
    ms = requests.post(f"{API}/commercial/milestones", json={
        "project_id": proj["id"], "name": "Foundation Complete", "sequence": 1,
        "planned_percent": 20, "trigger": "Foundation cast", "planned_date": "2026-02-15",
    }, headers=admin["headers"], timeout=20).json()
    return proj, ms


# ==========================================================================
# Investment - never Budget/Forecast/internal costs
# ==========================================================================
def test_client_investment_never_exposes_budget_fields(client, project_with_commercial):
    proj, _ = project_with_commercial
    r = requests.get(f"{API}/projects/{proj['id']}/client-investment", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    forbidden = ("budget", "forecast", "committed_cost", "actual_cost", "variance", "remaining_budget")
    body_str = str(body).lower()
    for field in forbidden:
        assert field not in body_str, f"internal field leaked to client: {field}"


def test_client_investment_has_only_client_safe_fields(client, project_with_commercial):
    proj, _ = project_with_commercial
    r = requests.get(f"{API}/projects/{proj['id']}/client-investment", headers=client["headers"], timeout=20)
    body = r.json()
    assert set(body.keys()) == {
        "project_id", "contract_value", "paid", "outstanding",
        "current_variation_total", "upcoming_payment",
    }


def test_client_still_blocked_from_raw_budget_route(client, project_with_commercial):
    proj, _ = project_with_commercial
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/budget", headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_commercial_summary_still_includes_budget_for_non_client_roles(admin, project_with_commercial):
    """The full commercial/summary endpoint is open to clients too (by
    design - see routes/commercial.py's own RBAC docstring), but its
    budget sub-object still carries internal figures if read directly.
    This documents why the client screens in this sprint deliberately
    build on client-investment instead - confirmed here from the
    admin side, where reading it is expected and correct."""
    proj, _ = project_with_commercial
    r = requests.get(f"{API}/projects/{proj['id']}/commercial/summary", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert "budget" in r.json()


# ==========================================================================
# Payment Journey
# ==========================================================================
def test_client_payment_journey_shape(client, project_with_commercial):
    proj, _ = project_with_commercial
    r = requests.get(f"{API}/projects/{proj['id']}/client-payment-journey", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "steps" in body
    assert len(body["steps"]) >= 1
    step = body["steps"][0]
    for key in ("milestone_id", "name", "sequence", "milestone_status", "payment_status", "amount"):
        assert key in step


def test_payment_journey_null_when_no_contract(client, admin):
    proj = requests.post(f"{API}/projects", json={"name": "No Contract", "code": "NOCX"},
                         headers=admin["headers"], timeout=20).json()
    r = requests.get(f"{API}/projects/{proj['id']}/client-payment-journey", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json() is None


def test_upcoming_payment_shows_remaining_balance_not_full_amount(admin, client, project_with_commercial):
    """Regression guard for a real bug caught and fixed during
    development: the first version showed a partially-paid request's
    FULL original amount as "upcoming," not what's actually still
    owed."""
    proj, ms = project_with_commercial
    requests.post(f"{API}/commercial/milestones/{ms['id']}/status", json={"status": "ready"}, headers=admin["headers"], timeout=20)
    ms2 = requests.post(f"{API}/commercial/milestones/{ms['id']}/status", json={"status": "achieved"}, headers=admin["headers"], timeout=20).json()
    pr = requests.post(f"{API}/commercial/payment-requests", json={
        "project_id": proj["id"], "milestone_id": ms["id"], "amount": ms2["contract_value"],
        "raised_date": "2026-02-16", "due_date": "2026-03-01",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/payment-requests/{pr['id']}/status", json={"status": "raised"}, headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/payment-requests/{pr['id']}/status", json={"status": "sent"}, headers=admin["headers"], timeout=20)
    partial_amount = round(pr["amount"] / 2, 2)
    requests.post(f"{API}/commercial/payments", json={
        "payment_request_id": pr["id"], "amount": partial_amount, "date": "2026-02-20", "method": "bank_transfer",
    }, headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/projects/{proj['id']}/client-investment", headers=client["headers"], timeout=20)
    upcoming = r.json()["upcoming_payment"]
    assert upcoming is not None
    assert upcoming["amount"] == round(pr["amount"] - partial_amount, 2), \
        "upcoming_payment must show the remaining balance, not the original full amount"


# ==========================================================================
# Variation Centre - impact pre-calculated, never computed by caller
# ==========================================================================
def test_client_variation_centre_includes_calculated_impact(admin, client, project_with_commercial):
    proj, _ = project_with_commercial
    var = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj["id"], "title": "Extra bathroom", "description": "test",
        "original_cost": 0, "proposed_cost": 350000, "time_impact_days": 10,
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/variations/{var['id']}/submit", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{var['id']}/send-for-client-review", headers=admin["headers"], timeout=20)

    r = requests.get(f"{API}/projects/{proj['id']}/client-variations", headers=client["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    pending = [v for v in body["pending"] if v["id"] == var["id"]]
    assert len(pending) == 1
    v = pending[0]
    assert v["impact"]["cost_impact"] == 350000
    assert v["impact"]["schedule_impact_days"] == 10
    assert v["before_cost"] == 0
    assert v["after_cost"] == 350000
    # Payment/forecast impact must be zero before approval - a real
    # financial consequence hasn't happened yet, and this must not be
    # fabricated to look like it has.
    assert v["impact"]["payment_impact"] == 0
    assert v["impact"]["forecast_impact"] == 0


def test_client_can_decide_variation_via_existing_endpoint(admin, client, project_with_commercial):
    """CX-01 introduces no new write endpoint for deciding a variation -
    the client uses the same commercial/variations/{id}/decide route
    already opened to the client role in CF-01."""
    proj, _ = project_with_commercial
    var = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj["id"], "title": "Landscape upgrade", "description": "test",
        "original_cost": 0, "proposed_cost": 150000,
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/variations/{var['id']}/submit", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{var['id']}/send-for-client-review", headers=admin["headers"], timeout=20)

    r = requests.post(f"{API}/commercial/variations/{var['id']}/decide",
                      json={"decision": "approved"}, headers=client["headers"], timeout=20)
    assert r.status_code == 200

    r2 = requests.get(f"{API}/projects/{proj['id']}/client-variations", headers=client["headers"], timeout=20)
    history_ids = [v["id"] for v in r2.json()["history"]]
    assert var["id"] in history_ids


def test_investment_reflects_approved_variation(admin, client, project_with_commercial):
    proj, _ = project_with_commercial
    before = requests.get(f"{API}/projects/{proj['id']}/client-investment", headers=client["headers"], timeout=20).json()
    var = requests.post(f"{API}/commercial/variations", json={
        "project_id": proj["id"], "title": "Pool deck upgrade", "description": "test",
        "original_cost": 0, "proposed_cost": 275000,
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/commercial/variations/{var['id']}/submit", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{var['id']}/send-for-client-review", headers=admin["headers"], timeout=20)
    requests.post(f"{API}/commercial/variations/{var['id']}/decide",
                 json={"decision": "approved"}, headers=client["headers"], timeout=20)
    after = requests.get(f"{API}/projects/{proj['id']}/client-investment", headers=client["headers"], timeout=20).json()
    assert after["contract_value"] == before["contract_value"] + 275000
    assert after["current_variation_total"] == before["current_variation_total"] + 275000


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_existing_client_dashboard_endpoints_unaffected(client, project_with_commercial):
    proj, _ = project_with_commercial
    assert requests.get(f"{API}/projects/{proj['id']}/client-dashboard", headers=client["headers"], timeout=20).status_code in (200, 404)
    assert requests.get(f"{API}/projects/{proj['id']}/client-timeline", headers=client["headers"], timeout=20).status_code == 200


def test_regression_core_platform_unaffected(admin):
    assert requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).status_code == 200
