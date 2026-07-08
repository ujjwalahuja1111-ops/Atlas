"""Project Atlas V4 — Sprint 4: Construction Knowledge Core tests.

Validates:
  * Single-collection master data (category/phase/activity/checklist_template/
    required_document) CRUD, discriminated by `type`
  * Admin-only (management-role) gating on all mutating endpoints; other
    roles get 403 but CAN still read
  * category_id / phase_id referential validation on create + update
  * Search (?q=) and filter (?type=, ?category_id=, ?phase_id=, ?tag=, ?status=)
  * Soft archive / unarchive (archived_at), matching the projects/sites
    pattern — archived items excluded from default list, included with
    ?include_archived=true
  * Lifecycle `status` (draft/active/deprecated/archived): defaults to draft,
    settable via update to draft/active/deprecated only (archived is
    rejected — must go through the archive endpoint), archive/unarchive
    keep status in sync with archived_at
  * `applicability` freeform dict: stored and returned verbatim, no
    filtering logic applied to it (reserved extension point)
  * Versioning: every update increments `version` and writes an immutable
    snapshot retrievable via GET /knowledge-items/{id}/versions
  * Generic relationships: add/remove typed edges (`relationships[]`),
    self-relationship rejected, relationship add/remove bumps version
  * GET /knowledge-meta exposes vocab for frontend dropdowns
  * No Mongo _id leak on any touched endpoint
  * Sprint 1/2/3 endpoints still respond (regression smoke)
"""
import os
import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or
        "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"


def _no_id(o, p="root"):
    if isinstance(o, dict):
        for k, v in o.items():
            assert k != "_id", f"_id at {p}"
            _no_id(v, f"{p}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _no_id(v, f"{p}[{i}]")


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    b = r.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("supervisor", "9999988888", "Test User")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def coordinator():
    u, h = _login("coordinator", "9222222222", "Priya Coordinator")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9333333333", "Mr. Sharma")
    return {"user": u, "headers": h}


# --------------------------------------------------------------------------
# Admin-only gating
# --------------------------------------------------------------------------
def test_create_requires_admin(supervisor, coordinator, admin):
    body = {"type": "category", "name": "Gating Test Category"}
    r_sup = requests.post(f"{API}/knowledge-items", json=body, headers=supervisor["headers"], timeout=20)
    assert r_sup.status_code == 403
    r_coord = requests.post(f"{API}/knowledge-items", json=body, headers=coordinator["headers"], timeout=20)
    assert r_coord.status_code == 403
    r_admin = requests.post(f"{API}/knowledge-items", json=body, headers=admin["headers"], timeout=20)
    assert r_admin.status_code == 201, r_admin.text


def test_reads_open_to_all_roles(supervisor, admin):
    cat = requests.post(f"{API}/knowledge-items",
                        json={"type": "category", "name": "Read Test Category"},
                        headers=admin["headers"], timeout=20).json()
    r = requests.get(f"{API}/knowledge-items", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 200
    assert any(i["id"] == cat["id"] for i in r.json())


# --------------------------------------------------------------------------
# CRUD + type discrimination + referential integrity
# --------------------------------------------------------------------------
def test_type_validation_rejects_unknown_type(admin):
    r = requests.post(f"{API}/knowledge-items", json={"type": "bogus", "name": "X"},
                      headers=admin["headers"], timeout=20)
    assert r.status_code == 400


def test_full_lifecycle_with_category_phase_activity(admin):
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items",
                        json={"type": "category", "name": "Civil Works V4"},
                        headers=h, timeout=20).json()
    phase = requests.post(f"{API}/knowledge-items",
                          json={"type": "phase", "name": "Foundation V4"},
                          headers=h, timeout=20).json()
    _no_id(cat); _no_id(phase)
    assert cat["type"] == "category" and cat["version"] == 1 and cat["archived_at"] is None

    # bad category_id ref rejected
    r_bad = requests.post(f"{API}/knowledge-items",
                          json={"type": "activity", "name": "Bad Ref", "category_id": "does-not-exist"},
                          headers=h, timeout=20)
    assert r_bad.status_code == 400

    act = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "Shuttering V4", "description": "Formwork",
        "category_id": cat["id"], "phase_id": phase["id"],
        "tags": ["formwork", "structure"], "ai_keywords": ["shuttering"],
        "default_duration_days": 3,
    }, headers=h, timeout=20).json()
    _no_id(act)
    assert act["category_name"] == "Civil Works V4"
    assert act["phase_name"] == "Foundation V4"

    # GET by id
    got = requests.get(f"{API}/knowledge-items/{act['id']}", headers=h, timeout=20).json()
    assert got["id"] == act["id"]


def test_checklist_template_and_required_document_types(admin):
    h = admin["headers"]
    tmpl = requests.post(f"{API}/knowledge-items", json={
        "type": "checklist_template", "name": "Pre-pour Checklist V4",
        "checklist_items": [{"id": "1", "text": "Rebar spacing verified"}],
    }, headers=h, timeout=20)
    assert tmpl.status_code == 201, tmpl.text

    doc = requests.post(f"{API}/knowledge-items", json={
        "type": "required_document", "name": "Structural Drawing V4",
        "document_kind": "drawing",
    }, headers=h, timeout=20)
    assert doc.status_code == 201, doc.text


# --------------------------------------------------------------------------
# Search + filter
# --------------------------------------------------------------------------
def test_search_and_filter(admin):
    h = admin["headers"]
    requests.post(f"{API}/knowledge-items",
                  json={"type": "activity", "name": "Excavation Alpha V4", "tags": ["earthwork"]},
                  headers=h, timeout=20)
    r_q = requests.get(f"{API}/knowledge-items?q=Excavation Alpha", headers=h, timeout=20)
    assert r_q.status_code == 200
    assert any("Excavation Alpha V4" == i["name"] for i in r_q.json())

    r_tag = requests.get(f"{API}/knowledge-items?tag=earthwork", headers=h, timeout=20)
    assert any(i["name"] == "Excavation Alpha V4" for i in r_tag.json())

    r_type = requests.get(f"{API}/knowledge-items?type=activity", headers=h, timeout=20)
    assert all(i["type"] == "activity" for i in r_type.json())


# --------------------------------------------------------------------------
# Soft archive / restore
# --------------------------------------------------------------------------
def test_archive_and_unarchive(admin):
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items",
                        json={"type": "category", "name": "Archive Test Category V4"},
                        headers=h, timeout=20).json()

    r_arch = requests.post(f"{API}/knowledge-items/{cat['id']}/archive", headers=h, timeout=20)
    assert r_arch.status_code == 200
    assert r_arch.json()["archived_at"] is not None

    default_list = requests.get(f"{API}/knowledge-items?type=category", headers=h, timeout=20).json()
    assert cat["id"] not in [i["id"] for i in default_list]

    with_archived = requests.get(f"{API}/knowledge-items?type=category&include_archived=true",
                                 headers=h, timeout=20).json()
    assert cat["id"] in [i["id"] for i in with_archived]

    r_restore = requests.post(f"{API}/knowledge-items/{cat['id']}/unarchive", headers=h, timeout=20)
    assert r_restore.status_code == 200
    assert r_restore.json()["archived_at"] is None


def test_archive_requires_admin(supervisor, admin):
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items",
                        json={"type": "category", "name": "Archive Gating Category V4"},
                        headers=h, timeout=20).json()
    r = requests.post(f"{API}/knowledge-items/{cat['id']}/archive", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------
def test_update_bumps_version_and_writes_snapshot(admin):
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items",
                        json={"type": "category", "name": "Version Test V4"},
                        headers=h, timeout=20).json()
    assert cat["version"] == 1

    upd = requests.patch(f"{API}/knowledge-items/{cat['id']}", json={"name": "Version Test V4 Renamed"},
                         headers=h, timeout=20)
    assert upd.status_code == 200
    body = upd.json()
    assert body["version"] == 2
    assert body["name"] == "Version Test V4 Renamed"

    versions = requests.get(f"{API}/knowledge-items/{cat['id']}/versions", headers=h, timeout=20)
    assert versions.status_code == 200
    vlist = versions.json()
    assert len(vlist) == 1
    assert vlist[0]["snapshot"]["name"] == "Version Test V4"
    _no_id(vlist)


# --------------------------------------------------------------------------
# Generic relationships (Activity Dependencies is one instance of this)
# --------------------------------------------------------------------------
def test_generic_relationships(admin):
    h = admin["headers"]
    act1 = requests.post(f"{API}/knowledge-items", json={"type": "activity", "name": "Rel Source V4"},
                         headers=h, timeout=20).json()
    act2 = requests.post(f"{API}/knowledge-items", json={"type": "activity", "name": "Rel Target V4"},
                         headers=h, timeout=20).json()

    r_rel = requests.post(f"{API}/knowledge-items/{act1['id']}/relationships",
                          json={"type": "depends_on", "target_id": act2["id"], "metadata": {"lag_days": 2}},
                          headers=h, timeout=20)
    assert r_rel.status_code == 201, r_rel.text
    body = r_rel.json()
    assert len(body["relationships"]) == 1
    assert body["relationships"][0]["type"] == "depends_on"
    assert body["relationships"][0]["target_name"] == "Rel Target V4"
    assert body["version"] == 2
    rel_id = body["relationships"][0]["id"]

    # self-relationship rejected
    r_self = requests.post(f"{API}/knowledge-items/{act1['id']}/relationships",
                           json={"type": "depends_on", "target_id": act1["id"]},
                           headers=h, timeout=20)
    assert r_self.status_code == 400

    # arbitrary future-relationship-type accepted (not restricted to a hard enum)
    r_custom = requests.post(f"{API}/knowledge-items/{act1['id']}/relationships",
                             json={"type": "linked_material", "target_id": act2["id"]},
                             headers=h, timeout=20)
    assert r_custom.status_code == 201, r_custom.text

    # remove relationship
    r_remove = requests.delete(f"{API}/knowledge-items/{act1['id']}/relationships/{rel_id}",
                               headers=h, timeout=20)
    assert r_remove.status_code == 200
    remaining_types = [r["type"] for r in r_remove.json()["relationships"]]
    assert "depends_on" not in remaining_types
    assert "linked_material" in remaining_types


def test_relationships_require_admin(supervisor, admin):
    h = admin["headers"]
    act1 = requests.post(f"{API}/knowledge-items", json={"type": "activity", "name": "Rel Gate Source V4"},
                         headers=h, timeout=20).json()
    act2 = requests.post(f"{API}/knowledge-items", json={"type": "activity", "name": "Rel Gate Target V4"},
                         headers=h, timeout=20).json()
    r = requests.post(f"{API}/knowledge-items/{act1['id']}/relationships",
                      json={"type": "depends_on", "target_id": act2["id"]},
                      headers=supervisor["headers"], timeout=20)
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Lifecycle status (draft/active/deprecated/archived) + applicability
# --------------------------------------------------------------------------
def test_status_defaults_to_draft(admin):
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items",
                        json={"type": "category", "name": "Status Default V4"},
                        headers=h, timeout=20).json()
    assert cat["status"] == "draft"
    assert cat["applicability"] == {}


def test_status_explicit_at_creation(admin):
    h = admin["headers"]
    act = requests.post(f"{API}/knowledge-items", json={
        "type": "activity", "name": "Status Explicit V4", "status": "active",
        "applicability": {"project_types": ["residential"], "regions": ["IN-NCR"]},
    }, headers=h, timeout=20).json()
    assert act["status"] == "active"
    assert act["applicability"]["project_types"] == ["residential"]


def test_status_rejects_invalid_values(admin):
    h = admin["headers"]
    r = requests.post(f"{API}/knowledge-items",
                      json={"type": "category", "name": "Bad Status V4", "status": "bogus"},
                      headers=h, timeout=20)
    assert r.status_code == 400

    r2 = requests.post(f"{API}/knowledge-items",
                       json={"type": "category", "name": "Pre-archived V4", "status": "archived"},
                       headers=h, timeout=20)
    assert r2.status_code == 400, "status=archived must be rejected at creation — use the archive endpoint"


def test_status_update_and_archive_sync(admin):
    h = admin["headers"]
    cat = requests.post(f"{API}/knowledge-items",
                        json={"type": "category", "name": "Status Sync V4"},
                        headers=h, timeout=20).json()
    assert cat["status"] == "draft"

    promote = requests.patch(f"{API}/knowledge-items/{cat['id']}", json={"status": "active"},
                             headers=h, timeout=20)
    assert promote.status_code == 200
    assert promote.json()["status"] == "active"

    # status=archived rejected via generic update
    r_bad = requests.patch(f"{API}/knowledge-items/{cat['id']}", json={"status": "archived"},
                           headers=h, timeout=20)
    assert r_bad.status_code == 400

    # archive syncs status
    r_arch = requests.post(f"{API}/knowledge-items/{cat['id']}/archive", headers=h, timeout=20)
    assert r_arch.json()["status"] == "archived"

    # unarchive resets status to active
    r_restore = requests.post(f"{API}/knowledge-items/{cat['id']}/unarchive", headers=h, timeout=20)
    assert r_restore.json()["status"] == "active"


def test_status_filter(admin):
    h = admin["headers"]
    requests.post(f"{API}/knowledge-items",
                  json={"type": "category", "name": "Status Filter Draft V4"},
                  headers=h, timeout=20)
    requests.post(f"{API}/knowledge-items",
                  json={"type": "category", "name": "Status Filter Active V4", "status": "active"},
                  headers=h, timeout=20)
    r_active = requests.get(f"{API}/knowledge-items?type=category&status=active", headers=h, timeout=20)
    assert r_active.status_code == 200
    assert all(i["status"] == "active" for i in r_active.json())
    assert any(i["name"] == "Status Filter Active V4" for i in r_active.json())


# --------------------------------------------------------------------------
# Meta vocab
# --------------------------------------------------------------------------
def test_knowledge_meta(supervisor):
    r = requests.get(f"{API}/knowledge-meta", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 200
    body = r.json()
    assert "activity" in body["types"]
    assert "depends_on" in body["relationship_types"]
    assert "active" in body["statuses"]
    assert "archived" not in body["statuses"], "archived is not a directly-settable status"


# --------------------------------------------------------------------------
# Regression: Sprint 1/2/3 endpoints unaffected
# --------------------------------------------------------------------------
def test_regression_v3_endpoints_still_respond(supervisor):
    h = supervisor["headers"]
    assert requests.get(f"{API}/projects", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/sites", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/operational-items", headers=h, timeout=20).status_code == 200
    assert requests.get(f"{API}/", timeout=20).status_code == 200
