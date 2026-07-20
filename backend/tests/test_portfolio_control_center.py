"""Project Atlas — Portfolio Control Center (Phase 1: schedule-based
portfolio monitoring only, no financial computation).

Validates that GET /api/portfolio/control-center:
  * Is management-only (PM, supervisor, client all correctly blocked).
  * Reuses existing CRE outputs exactly - health status/score match
    engines/reasoning_engine.compute_project_health precisely (never a
    second, independent health computation); planned/forecast
    completion and schedule variance match projections.delay_forecast
    precisely; next_milestone matches projections.project_lookahead's
    next_expected precisely.
  * Computes operational counts (open items, pending client approvals,
    critical items) correctly and keeps them live as items are decided.
  * Portfolio summary aggregates match a direct sum over the returned
    project rows.
  * Financial fields are always-null, disabled placeholders (Phase 1
    scope - no financial computation).
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
    u, h = _login("management", "9996600001", "PCC Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("project_manager", "9996600002", "PCC PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("site_supervisor", "9996600003", "PCC Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def client():
    u, h = _login("client", "9996600004", "PCC Client")
    return {"user": u, "headers": h}


@pytest.fixture()
def project_and_site(admin):
    proj = requests.post(f"{API}/projects", json={"name": "PCC Test Project", "code": "PCCT"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "PCC Test Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


# --------------------------------------------------------------------------
# Permissions
# --------------------------------------------------------------------------
def test_management_only_pm_blocked(pm):
    r = requests.get(f"{API}/portfolio/control-center", headers=pm["headers"], timeout=20)
    assert r.status_code == 403


def test_management_only_supervisor_blocked(supervisor):
    r = requests.get(f"{API}/portfolio/control-center", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_management_only_client_blocked(client):
    r = requests.get(f"{API}/portfolio/control-center", headers=client["headers"], timeout=20)
    assert r.status_code == 403


def test_management_can_access(admin):
    r = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"summary", "projects", "generated_at"}


# --------------------------------------------------------------------------
# Row shape and field correctness
# --------------------------------------------------------------------------
def test_project_row_shape(admin, project_and_site):
    proj, _ = project_and_site
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row = next(p for p in body["projects"] if p["project_id"] == proj["id"])
    expected_fields = {
        "project_id", "project_name", "progress_percent", "planned_completion",
        "forecast_completion", "schedule_variance_days", "health_status", "health_score",
        "health_explanation", "critical_issues_count", "open_operational_items",
        "pending_client_approvals", "critical_operational_items", "overdue_client_approvals",
        "next_milestone", "financials",
    }
    assert set(row.keys()) == expected_fields
    assert row["health_status"] in ("Healthy", "Attention", "Critical")


def test_financials_are_disabled_placeholders(admin, project_and_site):
    proj, _ = project_and_site
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row = next(p for p in body["projects"] if p["project_id"] == proj["id"])
    fin = row["financials"]
    assert fin["enabled"] is False
    assert fin["budget"] is None
    assert fin["forecast_cost"] is None
    assert fin["cost_variance"] is None
    assert fin["profitability"] is None
    assert fin["cash_flow"] is None


def test_operational_counts_are_live(admin, project_and_site):
    proj, site = project_and_site
    item = requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "safety_observation", "title": "Test hazard", "priority": "critical",
    }, headers=admin["headers"], timeout=20).json()

    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row = next(p for p in body["projects"] if p["project_id"] == proj["id"])
    assert row["open_operational_items"] >= 1
    assert row["critical_operational_items"] >= 1

    requests.post(f"{API}/operational-items/{item['id']}/transition",
                 json={"to_status": "closed"}, headers=admin["headers"], timeout=20)
    body2 = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row2 = next(p for p in body2["projects"] if p["project_id"] == proj["id"])
    assert row2["critical_operational_items"] == row["critical_operational_items"] - 1


def test_pending_client_approvals_reflect_real_decisions(admin, project_and_site):
    proj, site = project_and_site
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Approve fixture choice"},
                          headers=admin["headers"], timeout=20).json()
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json={},
                             headers=admin["headers"], timeout=20).json()

    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row = next(p for p in body["projects"] if p["project_id"] == proj["id"])
    assert row["pending_client_approvals"] >= 1

    requests.post(f"{API}/operational-items/{approval['id']}/transition",
                 json={"to_status": "fulfilled"}, headers=admin["headers"], timeout=20)
    body2 = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row2 = next(p for p in body2["projects"] if p["project_id"] == proj["id"])
    assert row2["pending_client_approvals"] == row["pending_client_approvals"] - 1


# --------------------------------------------------------------------------
# Health/forecast reuse (not reinvented)
# --------------------------------------------------------------------------
def test_health_matches_project_health_endpoint(admin, project_and_site):
    """Health status/score shown here must be exactly what
    GET /projects/{id}/health (compute_project_health, unmodified)
    already returns for the same project - proving this is presentation
    of an existing output, not a second, independent computation."""
    proj, _ = project_and_site
    portfolio_row = next(
        p for p in requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()["projects"]
        if p["project_id"] == proj["id"])
    health = requests.get(f"{API}/projects/{proj['id']}/health", headers=admin["headers"], timeout=20).json()
    label = {"green": "Healthy", "amber": "Attention", "red": "Critical"}[health["status"]]
    assert portfolio_row["health_status"] == label
    assert portfolio_row["health_score"] == health["score"]
    assert portfolio_row["progress_percent"] == health["progress"]["percent_complete"]


def test_forecast_fields_match_forecast_endpoint(admin, project_and_site):
    proj, _ = project_and_site
    portfolio_row = next(
        p for p in requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()["projects"]
        if p["project_id"] == proj["id"])
    forecast = requests.get(f"{API}/projects/{proj['id']}/forecast", headers=admin["headers"], timeout=20).json()
    assert portfolio_row["planned_completion"] == forecast["planned_completion"]
    assert portfolio_row["forecast_completion"] == forecast["forecast_completion"]
    assert portfolio_row["schedule_variance_days"] == forecast["forecast_slip_days"]


def test_next_milestone_matches_lookahead_endpoint(admin, project_and_site):
    proj, _ = project_and_site
    portfolio_row = next(
        p for p in requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()["projects"]
        if p["project_id"] == proj["id"])
    lookahead = requests.get(f"{API}/projects/{proj['id']}/lookahead", headers=admin["headers"], timeout=20).json()
    expected = lookahead["next_expected"]["name"] if lookahead.get("next_expected") else None
    assert portfolio_row["next_milestone"] == expected


# --------------------------------------------------------------------------
# Prioritization (worst-first, not alphabetical)
# --------------------------------------------------------------------------
def test_projects_sorted_worst_first_not_alphabetical(admin):
    """Create a project whose name would sort last alphabetically but
    has a critical operational item, and one that sorts first
    alphabetically with nothing wrong - the unhealthy one must appear
    first in the response regardless of name."""
    proj_bad = requests.post(f"{API}/projects", json={"name": "ZZZ Priority Test Bad", "code": "ZZPTB"},
                             headers=admin["headers"], timeout=20).json()
    site_bad = requests.post(f"{API}/sites", json={"project_id": proj_bad["id"], "name": "Site"},
                             headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/operational-items", json={
        "site_id": site_bad["id"], "category": "safety_observation", "title": "Hazard", "priority": "critical",
    }, headers=admin["headers"], timeout=20)

    proj_good = requests.post(f"{API}/projects", json={"name": "AAA Priority Test Good", "code": "AAPTG"},
                              headers=admin["headers"], timeout=20).json()

    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    names = [p["project_name"] for p in body["projects"]]
    idx_bad = names.index("ZZZ Priority Test Bad")
    idx_good = names.index("AAA Priority Test Good")
    assert idx_bad < idx_good, f"unhealthy project must sort before a healthy one regardless of name: {names}"


def test_health_tier_dominates_sort_order(admin):
    """A Healthy project must never sort ahead of a Critical/Attention
    one, even if the summary counts alone might suggest otherwise -
    health tier is the primary sort key, not a tiebreaker."""
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    rows = body["projects"]
    tier = {"Critical": 0, "Attention": 1, "Healthy": 2}
    tiers_seen = [tier[r["health_status"]] for r in rows]
    assert tiers_seen == sorted(tiers_seen), f"health tiers out of order: {[r['health_status'] for r in rows]}"


# --------------------------------------------------------------------------
# Health explanation
# --------------------------------------------------------------------------
def test_every_row_has_a_non_empty_explanation(admin):
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    for row in body["projects"]:
        assert isinstance(row["health_explanation"], list)
        assert len(row["health_explanation"]) > 0
        assert all(isinstance(b, str) and b for b in row["health_explanation"])


def test_explanation_mentions_critical_items_when_present(admin, project_and_site):
    proj, site = project_and_site
    requests.post(f"{API}/operational-items", json={
        "site_id": site["id"], "category": "safety_observation", "title": "Explanation test hazard", "priority": "critical",
    }, headers=admin["headers"], timeout=20)
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row = next(p for p in body["projects"] if p["project_id"] == proj["id"])
    assert row["critical_operational_items"] >= 1
    assert any("critical operational item" in b for b in row["health_explanation"]), row["health_explanation"]


def test_healthy_project_gets_generic_all_clear_explanation(admin):
    """A brand-new project with nothing wrong yet gets the exact generic
    all-clear explanation, not an empty list or a fabricated reason."""
    proj = requests.post(f"{API}/projects", json={"name": "PCC Fresh Clean Project", "code": "PCCFCP"},
                         headers=admin["headers"], timeout=20).json()
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row = next(p for p in body["projects"] if p["project_id"] == proj["id"])
    if row["health_status"] == "Healthy":
        assert row["health_explanation"] == ["No overdue milestones", "Operations on track"]


def test_overdue_client_approvals_field_present_and_consistent(admin, project_and_site):
    proj, _ = project_and_site
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    row = next(p for p in body["projects"] if p["project_id"] == proj["id"])
    assert "overdue_client_approvals" in row
    assert isinstance(row["overdue_client_approvals"], int)
    assert row["overdue_client_approvals"] <= row["pending_client_approvals"]


# --------------------------------------------------------------------------
# Summary aggregation
# --------------------------------------------------------------------------
def test_summary_matches_sum_of_rows(admin):
    body = requests.get(f"{API}/portfolio/control-center", headers=admin["headers"], timeout=20).json()
    rows = body["projects"]
    summary = body["summary"]
    assert summary["active_projects"] == len(rows)
    assert summary["healthy"] == sum(1 for r in rows if r["health_status"] == "Healthy")
    assert summary["attention"] == sum(1 for r in rows if r["health_status"] == "Attention")
    assert summary["critical"] == sum(1 for r in rows if r["health_status"] == "Critical")
    assert summary["pending_client_approvals"] == sum(r["pending_client_approvals"] for r in rows)
    assert summary["critical_operational_items"] == sum(r["critical_operational_items"] for r in rows)
    assert summary["projects_behind_schedule"] == sum(
        1 for r in rows if r["schedule_variance_days"] is not None and r["schedule_variance_days"] > 0)


# --------------------------------------------------------------------------
# Regression - other reasoning endpoints unaffected
# --------------------------------------------------------------------------
def test_regression_reasoning_endpoints_unaffected(admin, pm, supervisor, project_and_site):
    proj, _ = project_and_site
    for actor in (admin, pm, supervisor):
        for path in ("insights", "health", "lookahead", "forecast", "briefing"):
            r = requests.get(f"{API}/projects/{proj['id']}/{path}", headers=actor["headers"], timeout=20)
            assert r.status_code == 200, f"{actor['user']['role']} /{path}: {r.text}"


def test_regression_executive_reasoning_unaffected(admin):
    r = requests.get(f"{API}/reasoning/executive?question=attention_today", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
