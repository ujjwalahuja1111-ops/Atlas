"""Project Atlas V5 — Sprint 5: Construction Workflow Engine tests.

Validates:
  * Activity Library: Knowledge Core activities gain trade/unit/
    requires_inspection fields with zero change to CRUD/search/versioning
  * Activity relationships: depends_on, linked_document, linked_material,
    linked_equipment, linked_labour (new), uses (checklist), and the
    computed (never stored) "Unlocks" reverse-lookup
  * Workflow Templates are plain knowledge_items (type=workflow_template)
    served entirely by the existing Knowledge endpoints — zero new
    endpoints needed for template CRUD
  * Project Creation -> Generate Workflow: activities + dependency links +
    initial status, "reference Activity Library items only"
  * Activity Status: not_started/ready/in_progress/blocked/completed,
    dependency-respecting transitions, completion cascade
  * Workflow Viewer data: GET /api/projects/{id}/workflow enriched with
    dependency names+status
  * Sprint 4.3 project-scoping foundation reused (not duplicated) for
    workflow visibility
  * Regression: Sprint 1-4.3 endpoints and existing Knowledge Core
    behaviour unchanged
"""
import os
import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or
        "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    b = r.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9400000001", "V5 Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("supervisor", "9400000002", "V5 Supervisor")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def library(admin):
    """A small, reusable Activity Library: Excavation -> Shuttering -> Concrete Pour,
    plus a Villa template referencing all three in order."""
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items", json={"type": "category", "name": "V5 Structural " + os.urandom(4).hex()},
                        headers=h, timeout=20).json()
    phase = requests.post(f"{API}/knowledge-items", json={"type": "phase", "name": "V5 Foundation " + os.urandom(4).hex()},
                          headers=h, timeout=20).json()

    exc = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "V5 Excavation " + os.urandom(4).hex(),
        "category_id": cat["id"], "phase_id": phase["id"],
        "trade": "Civil", "unit": "cum", "default_duration_days": 2,
        "requires_inspection": False, "status": "active",
    }, headers=h, timeout=20).json()

    sh = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "V5 Shuttering " + os.urandom(4).hex(),
        "category_id": cat["id"], "phase_id": phase["id"],
        "trade": "Civil", "unit": "sqm", "requires_inspection": True, "status": "active",
    }, headers=h, timeout=20).json()

    cp = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "V5 Concrete Pour " + os.urandom(4).hex(),
        "category_id": cat["id"], "phase_id": phase["id"],
        "trade": "Civil", "unit": "cum", "requires_inspection": True, "status": "active",
    }, headers=h, timeout=20).json()

    requests.post(f"{API}/knowledge-items/{sh['id']}/relationships",
                  json={"type": "depends_on", "target_id": exc["id"]}, headers=h, timeout=20)
    requests.post(f"{API}/knowledge-items/{cp['id']}/relationships",
                  json={"type": "depends_on", "target_id": sh["id"]}, headers=h, timeout=20)

    template = requests.post(f"{API}/knowledge-items", json={
        "type": "workflow_template", "name": "V5 Villa " + os.urandom(4).hex(), "status": "active",
    }, headers=h, timeout=20).json()
    for order, act in enumerate([exc, sh, cp]):
        requests.post(f"{API}/knowledge-items/{template['id']}/relationships",
                      json={"type": "includes_activity", "target_id": act["id"], "metadata": {"order": order}},
                      headers=h, timeout=20)

    return {"category": cat, "phase": phase, "excavation": exc, "shuttering": sh, "concrete": cp, "template": template}


# --------------------------------------------------------------------------
# Activity Library fields
# --------------------------------------------------------------------------
def test_activity_has_sprint5_fields(library):
    exc = library["excavation"]
    assert exc["trade"] == "Civil"
    assert exc["unit"] == "cum"
    assert exc["requires_inspection"] is False
    assert library["shuttering"]["requires_inspection"] is True


def test_activity_active_flag_reuses_status(admin):
    """'Active' is not a new field — it's status == 'active', reusing the
    existing Knowledge Core lifecycle (no duplicated logic)."""
    r = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "V5 Draft Activity " + os.urandom(4).hex(), "status": "draft",
    }, headers=admin["headers"], timeout=20)
    assert r.status_code == 201
    assert r.json()["status"] == "draft"


# --------------------------------------------------------------------------
# Relationships: Unlocks (computed), new types
# --------------------------------------------------------------------------
def test_unlocks_is_computed_not_stored(library, admin):
    r = requests.get(f"{API}/knowledge-items/{library['excavation']['id']}", headers=admin["headers"], timeout=20)
    body = r.json()
    assert "unlocks" in body
    assert any(u["id"] == library["shuttering"]["id"] for u in body["unlocks"])


def test_knowledge_meta_includes_new_relationship_types(admin):
    r = requests.get(f"{API}/knowledge-meta", headers=admin["headers"], timeout=20)
    body = r.json()
    assert "linked_labour" in body["relationship_types"]
    assert "includes_activity" in body["relationship_types"]
    assert "workflow_template" in body["types"]


def test_placeholder_relationship_types_reused_from_sprint4(library, admin):
    """Materials/Equipment/Documents were already reserved in Sprint 4 —
    Sprint 5 needed zero schema change for them."""
    h = admin["headers"]
    doc = requests.post(f"{API}/knowledge-items", json={"type": "required_document", "name": "V5 Permit " + os.urandom(4).hex()},
                        headers=h, timeout=20).json()
    r = requests.post(f"{API}/knowledge-items/{library['excavation']['id']}/relationships",
                      json={"type": "linked_document", "target_id": doc["id"]}, headers=h, timeout=20)
    assert r.status_code == 201


# --------------------------------------------------------------------------
# Workflow Templates are plain knowledge_items
# --------------------------------------------------------------------------
def test_workflow_template_served_by_existing_knowledge_endpoint(library, admin):
    r = requests.get(f"{API}/knowledge-items?type=workflow_template", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert any(t["id"] == library["template"]["id"] for t in r.json())


def test_seed_default_templates_idempotent(admin):
    h = admin["headers"]
    r1 = requests.post(f"{API}/workflow-templates/seed-defaults", headers=h, timeout=20)
    assert r1.status_code == 200
    body1 = r1.json()
    assert set(body1["created"]) | set(body1["already_existed"]) == {
        "Villa", "Residential", "Commercial", "Interior", "Renovation",
    }
    r2 = requests.post(f"{API}/workflow-templates/seed-defaults", headers=h, timeout=20)
    assert r2.json()["created"] == []


def test_seed_default_templates_requires_admin(supervisor):
    r = requests.post(f"{API}/workflow-templates/seed-defaults", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Project Creation -> Generate Workflow
# --------------------------------------------------------------------------
def test_generate_workflow_requires_admin_or_coordinator(library, admin, supervisor):
    h = admin["headers"]
    proj = requests.post(f"{API}/projects", json={"name": "V5 Perm Test " + os.urandom(4).hex(), "code": "V5PT"},
                         headers=h, timeout=20).json()
    r = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                      json={"template_id": library["template"]["id"]}, headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


def test_generate_workflow_end_to_end(library, admin, supervisor):
    h = admin["headers"]
    proj = requests.post(f"{API}/projects", json={"name": "V5 Gen Test " + os.urandom(4).hex(), "code": "V5GT"},
                         headers=h, timeout=20).json()

    r = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                      json={"template_id": library["template"]["id"]}, headers=h, timeout=20)
    assert r.status_code == 201, r.text
    generated = r.json()
    assert len(generated) == 3

    by_name = {g["name"]: g for g in generated}
    exc_gen = by_name[library["excavation"]["name"]]
    sh_gen = by_name[library["shuttering"]["name"]]
    assert exc_gen["status"] == "ready"        # no dependencies
    assert sh_gen["status"] == "not_started"    # depends on excavation
    assert sh_gen["depends_on_activity_ids"] == [exc_gen["id"]]
    assert sh_gen["trade"] == "Civil" and sh_gen["requires_inspection"] is True  # denormalized

    # regeneration blocked
    r2 = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                       json={"template_id": library["template"]["id"]}, headers=h, timeout=20)
    assert r2.status_code == 400

    # supervisor can VIEW the workflow even though they can't generate it
    r3 = requests.get(f"{API}/projects/{proj['id']}/workflow", headers=supervisor["headers"], timeout=20)
    assert r3.status_code == 200
    assert len(r3.json()) == 3


# --------------------------------------------------------------------------
# Activity Status: respects dependencies, cascades on completion
# --------------------------------------------------------------------------
def test_status_respects_dependencies_and_cascades(library, admin, supervisor):
    h = admin["headers"]
    proj = requests.post(f"{API}/projects", json={"name": "V5 Status Test " + os.urandom(4).hex(), "code": "V5ST"},
                         headers=h, timeout=20).json()
    gen = requests.post(f"{API}/projects/{proj['id']}/workflow/generate",
                        json={"template_id": library["template"]["id"]}, headers=h, timeout=20).json()
    by_name = {g["name"]: g for g in gen}
    exc = by_name[library["excavation"]["name"]]
    sh = by_name[library["shuttering"]["name"]]
    cp = by_name[library["concrete"]["name"]]

    # blocked: can't start shuttering while excavation isn't completed
    r1 = requests.post(f"{API}/workflow-activities/{sh['id']}/status", json={"status": "in_progress"},
                       headers=supervisor["headers"], timeout=20)
    assert r1.status_code == 409

    # allowed: excavation has no deps
    r2 = requests.post(f"{API}/workflow-activities/{exc['id']}/status", json={"status": "in_progress"},
                       headers=supervisor["headers"], timeout=20)
    assert r2.status_code == 200

    r3 = requests.post(f"{API}/workflow-activities/{exc['id']}/status", json={"status": "completed"},
                       headers=supervisor["headers"], timeout=20)
    assert r3.status_code == 200

    # cascade: shuttering auto-promoted to ready
    r4 = requests.get(f"{API}/projects/{proj['id']}/workflow", headers=supervisor["headers"], timeout=20)
    sh_after = next(x for x in r4.json() if x["id"] == sh["id"])
    assert sh_after["status"] == "ready"

    # concrete still not_started (shuttering not completed yet)
    cp_after = next(x for x in r4.json() if x["id"] == cp["id"])
    assert cp_after["status"] == "not_started"

    # blocked is always allowed, from any status
    r5 = requests.post(f"{API}/workflow-activities/{cp['id']}/status", json={"status": "blocked"},
                       headers=supervisor["headers"], timeout=20)
    assert r5.status_code == 200
    assert r5.json()["status"] == "blocked"

    # invalid status rejected
    r6 = requests.post(f"{API}/workflow-activities/{exc['id']}/status", json={"status": "not-a-status"},
                       headers=supervisor["headers"], timeout=20)
    assert r6.status_code == 400


def test_workflow_meta_status_vocabulary(admin):
    r = requests.get(f"{API}/workflow-meta", headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert set(r.json()["statuses"]) == {"not_started", "ready", "in_progress", "blocked", "completed"}


# --------------------------------------------------------------------------
# Regression: Sprint 1-4.3 endpoints and Knowledge Core unaffected
# --------------------------------------------------------------------------
def test_regression_sprint_1_4_3_endpoints(supervisor, admin):
    h = supervisor["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/knowledge-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/", timeout=20).status_code == 200

    ah = admin["headers"]
    assert requests.get(f"{API}/admin/users", headers=ah, timeout=20).status_code == 200
    assert requests.get(f"{API}/admin/system-info", headers=ah, timeout=20).status_code == 200


def test_regression_existing_knowledge_crud_unaffected(admin):
    """A category (unaffected by any Sprint 5 field) still works exactly
    as it did in Sprint 4."""
    h = admin["headers"]
    r = requests.post(f"{API}/knowledge-items", json={"type": "category", "name": "V5 Regression Cat " + os.urandom(4).hex()},
                      headers=h, timeout=20)
    assert r.status_code == 201
    assert r.json()["version"] == 1
    assert "trade" not in r.json() or r.json()["trade"] is None
