"""Project Atlas — Construction Knowledge Base v2: Parametric Production
Models (Sprint 01).

Covers the complete production model feature:

1. An Activity may optionally define a production_model (additive field,
   None by default - every existing activity is completely unaffected).
2. The same activity template, applied to two different projects with
   different instance inputs, produces different, correct durations
   (the sprint's core demonstration: 1000 sqft house vs 3500 sqft villa).
3. Editable productivity: changing the template's default_value
   immediately affects duration for any activity that hasn't overridden
   it, with no separate "recalculate" step required beyond re-posting
   inputs (even empty ones).
4. Explainability: every calculated value returns its own worked
   calculation (formula, values, result) - never a black box.
5. Backward compatibility: an activity with no production_model
   continues to resolve its expected duration from the unmodified
   static default_duration_days, exactly as before this feature
   existed, and attempting to set production inputs on such an activity
   fails with an explicit, clear reason rather than silently doing
   nothing.
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


WALL_MASONRY_MODEL = {
    "calculation_method": "wall_area_productivity_v1",
    "inputs": [
        {"key": "wall_area", "label": "Wall Area", "category": "project", "unit": "sqm"},
        {"key": "crew_size", "label": "Crew Size", "category": "execution", "unit": "workers", "default_value": 4},
        {"key": "productivity", "label": "Productivity", "category": "execution",
         "unit": "sqm/day/worker", "default_value": 17.5},
    ],
    "outputs": ["duration_days", "crew_recommendation"],
}


def _make_wall_masonry_template(admin):
    activity = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "KBV2 Wall Masonry", "trade": "Masonry", "unit": "sqm",
        "default_duration_days": 7, "requires_inspection": False, "status": "active",
        "production_model": WALL_MASONRY_MODEL,
    }, headers=admin["headers"], timeout=20).json()
    template = requests.post(f"{API}/knowledge-items", json={
        "type": "workflow_template", "name": "KBV2 House Template", "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/knowledge-items/{template['id']}/relationships", json={
        "type": "includes_activity", "target_id": activity["id"],
    }, headers=admin["headers"], timeout=20)
    return activity, template


def _generate_workflow(admin, template, project_name, project_code):
    proj = requests.post(f"{API}/projects", json={"name": project_name, "code": project_code},
                         headers=admin["headers"], timeout=20).json()
    activities = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                               json={"template_id": template["id"]}, headers=admin["headers"], timeout=20).json()
    return proj, (activities[0] if activities else None)


# ==========================================================================
# Additive, backward-compatible schema
# ==========================================================================
def test_activity_without_production_model_is_unaffected(admin):
    activity = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "KBV2 Plain Activity", "trade": "Civil", "unit": "pt",
        "default_duration_days": 5, "requires_inspection": False, "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    assert activity["production_model"] is None


def test_activity_with_production_model_stores_it(admin):
    activity, _ = _make_wall_masonry_template(admin)
    assert activity["production_model"] is not None
    assert activity["production_model"]["calculation_method"] == "wall_area_productivity_v1"


def test_freshly_generated_activity_falls_back_to_static_duration(admin):
    _, template = _make_wall_masonry_template(admin)
    proj, activity = _generate_workflow(admin, template, "KBV2 Fresh Test", "KBV2FT")
    if not activity:
        pytest.skip("workflow generation returned no activities in this environment")
    assert activity.get("expected_duration_days") == 7


def test_plain_activity_falls_back_to_static_default(admin):
    activity = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "KBV2 Plain 2", "trade": "Civil", "unit": "pt",
        "default_duration_days": 9, "requires_inspection": False, "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    template = requests.post(f"{API}/knowledge-items", json={
        "type": "workflow_template", "name": "KBV2 Plain Template", "status": "active",
    }, headers=admin["headers"], timeout=20).json()
    requests.post(f"{API}/knowledge-items/{template['id']}/relationships", json={
        "type": "includes_activity", "target_id": activity["id"],
    }, headers=admin["headers"], timeout=20)
    proj, plain_activity = _generate_workflow(admin, template, "KBV2 Plain Project", "KBV2PP")
    if not plain_activity:
        pytest.skip("workflow generation returned no activities in this environment")
    assert plain_activity.get("expected_duration_days") == 9

    r = requests.post(f"{API}/workflow-activities/{plain_activity['id']}/production-inputs",
                      json={"inputs": {"x": 1}}, headers=admin["headers"], timeout=20)
    assert r.status_code == 400
    assert "no production model" in r.json()["detail"]


# ==========================================================================
# Core demonstration: same template, different projects, different durations
# ==========================================================================
def test_house_vs_villa_same_template_different_durations(admin):
    _, template = _make_wall_masonry_template(admin)
    house_proj, house_activity = _generate_workflow(admin, template, "KBV2 1000sqft House", "KBV2H1")
    villa_proj, villa_activity = _generate_workflow(admin, template, "KBV2 3500sqft Villa", "KBV2V1")
    if not house_activity or not villa_activity:
        pytest.skip("workflow generation returned no activities in this environment")

    r_house = requests.post(f"{API}/workflow-activities/{house_activity['id']}/production-inputs",
                            json={"inputs": {"wall_area": 150}}, headers=admin["headers"], timeout=20)
    r_villa = requests.post(f"{API}/workflow-activities/{villa_activity['id']}/production-inputs",
                            json={"inputs": {"wall_area": 420}}, headers=admin["headers"], timeout=20)
    assert r_house.status_code == 200 and r_villa.status_code == 200

    house_duration = r_house.json()["expected_duration_days"]
    villa_duration = r_villa.json()["expected_duration_days"]
    assert house_duration != villa_duration, "same template must produce different durations for different scale"
    assert house_duration == 3   # ceil(150 / (4*17.5)) = ceil(150/70) = 3
    assert villa_duration == 6   # ceil(420 / (4*17.5)) = ceil(420/70) = 6


# ==========================================================================
# Editable productivity
# ==========================================================================
def test_changing_default_productivity_immediately_affects_duration(admin):
    activity, template = _make_wall_masonry_template(admin)
    proj, wa = _generate_workflow(admin, template, "KBV2 Productivity Test", "KBV2PT")
    if not wa:
        pytest.skip("workflow generation returned no activities in this environment")

    r1 = requests.post(f"{API}/workflow-activities/{wa['id']}/production-inputs",
                       json={"inputs": {"wall_area": 420}}, headers=admin["headers"], timeout=20)
    duration_before = r1.json()["expected_duration_days"]

    higher_productivity_model = {**WALL_MASONRY_MODEL, "inputs": [
        {"key": "wall_area", "label": "Wall Area", "category": "project", "unit": "sqm"},
        {"key": "crew_size", "label": "Crew Size", "category": "execution", "unit": "workers", "default_value": 4},
        {"key": "productivity", "label": "Productivity", "category": "execution",
         "unit": "sqm/day/worker", "default_value": 30},
    ]}
    r_update = requests.patch(f"{API}/knowledge-items/{activity['id']}", json={
        "production_model": higher_productivity_model,
    }, headers=admin["headers"], timeout=20)
    assert r_update.status_code == 200

    r2 = requests.post(f"{API}/workflow-activities/{wa['id']}/production-inputs",
                       json={"inputs": {}}, headers=admin["headers"], timeout=20)
    duration_after = r2.json()["expected_duration_days"]
    assert duration_after < duration_before, "higher productivity must reduce expected duration"


# ==========================================================================
# Explainability
# ==========================================================================
def test_calculation_is_explainable(admin):
    _, template = _make_wall_masonry_template(admin)
    proj, wa = _generate_workflow(admin, template, "KBV2 Explain Test", "KBV2ET")
    if not wa:
        pytest.skip("workflow generation returned no activities in this environment")
    r = requests.post(f"{API}/workflow-activities/{wa['id']}/production-inputs",
                      json={"inputs": {"wall_area": 420}}, headers=admin["headers"], timeout=20)
    result = r.json()["production_model_result"]
    assert "explanation" in result
    explanation = result["explanation"]["duration_days"]
    assert "formula" in explanation
    assert "values" in explanation
    assert explanation["values"]["wall_area"] == 420
    assert explanation["result"] == result["outputs"]["duration_days"]


def test_instance_override_wins_over_template_default(admin):
    _, template = _make_wall_masonry_template(admin)
    proj, wa = _generate_workflow(admin, template, "KBV2 Override Test", "KBV2OT")
    if not wa:
        pytest.skip("workflow generation returned no activities in this environment")
    r = requests.post(f"{API}/workflow-activities/{wa['id']}/production-inputs",
                      json={"inputs": {"wall_area": 420, "crew_size": 8}}, headers=admin["headers"], timeout=20)
    assert r.json()["production_model_result"]["resolved_inputs"]["crew_size"] == 8


# ==========================================================================
# Regression
# ==========================================================================
def test_regression_acdp_workflow_unaffected(admin):
    projects = requests.get(f"{API}/projects", headers=admin["headers"], timeout=20).json()
    acdp = next((p for p in projects if p.get("code") == "ACDP-VILLA"), None)
    if not acdp:
        pytest.skip("ACDP not seeded in this environment")
    r = requests.get(f"{API}/projects/{acdp['id']}/workflow", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert len(r.json()) > 0
    for activity in r.json()[:5]:
        assert "expected_duration_days" in activity
