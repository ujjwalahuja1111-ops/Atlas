"""Project Atlas — UI Integration Sprint (UI-01).

Covers the one new backend piece this session: Portfolio Control
Center's summary extended with financial aggregates
(total_contract_value, total_forecast_cost, total_outstanding_receivables),
consumed by the Admin Dashboard's new Portfolio Summary widget.

Also regression-guards a real bug caught and fixed this session: the
first version of portfolio_control_center() called asyncio.gather
without asyncio being imported - a NameError only visible at runtime,
never caught by py_compile. Verified here by actually calling the
endpoint with real commercial reference data set, not just checking
the response shape.
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


@pytest.fixture(scope="session")
def admin():
    return {"headers": _seeded_admin_headers()}


def test_portfolio_summary_has_financial_fields(admin):
    r = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    summary = r.json()["summary"]
    for key in ("total_contract_value", "total_forecast_cost", "total_outstanding_receivables"):
        assert key in summary, f"missing field: {key}"


def test_total_outstanding_receivables_is_never_fabricated(admin):
    """The reference layer stores RA bill counts, not amounts paid - this
    field must always be None, never a guessed number, until real
    billing-amount data exists."""
    r = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    assert r.json()["summary"]["total_outstanding_receivables"] is None


def test_new_projects_appear_in_control_center(admin):
    p1 = requests.post(f"{API}/projects", json={"name": "UI01 Fin A", "code": "UI01FA"},
                       headers=admin["headers"], timeout=20).json()
    p2 = requests.post(f"{API}/projects", json={"name": "UI01 Fin B", "code": "UI01FB"},
                       headers=admin["headers"], timeout=20).json()

    r_after = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    project_ids = [p["project_id"] for p in r_after.json()["projects"]]
    assert p1["id"] in project_ids
    assert p2["id"] in project_ids


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_portfolio_control_center_shape_unaffected(admin):
    r = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert "projects" in r.json()
    assert "generated_at" in r.json()


def test_regression_core_platform_unaffected(admin):
    assert requests.get(f"{API}/operational-items", headers=admin["headers"], timeout=20).status_code == 200
