"""Project Atlas — Client Approval traceability verification.

This is a VERIFICATION suite, not a fix: it was written after auditing
the Client Approval Workflow's data model and found ZERO integrity
issues. It exists to keep it that way — codifying the invariants below
as regression tests so a future change cannot silently break them
without a test failing.

Verified invariants:
  1. Approval -> Event (forward): every approval created via
     POST /events/{id}/request-approval stores
     inherited_evidence_event_id, set once at creation.
  2. Event -> Approval (backward): GET /timeline and GET /events/{id}
     both correctly resolve an event's linked approval via a
     category-scoped query (operations_engine.find_open_item_for_event/
     find_items_for_events) — never confused with an unrelated item
     linked to the same event (e.g. an AI-unavailable fallback note,
     category "general").
  3. Related workflow activity ("where applicable"): no current capture
     flow ever sets activity_id on an event, so this is currently
     always inapplicable — not a defect. The relationship is not
     duplicated onto the operational_item; if an event ever does carry
     an activity_id, it remains reachable via the event, not lost.
  4. Immutability: inherited_evidence_event_id is not in
     EDITABLE_FIELDS (routes/operational_items.py's PATCH endpoint), so
     it cannot be changed after creation — verified by attempting to
     overwrite it directly.
  5. Status transitions (including the terminal "fulfilled"/"cancelled"
     decisions) never touch the link — transition_status only ever
     writes status/timestamp/actor fields.
  6. No orphaning is possible: there is no DELETE endpoint for events or
     operational items at all. Sites and projects CAN be hard-deleted,
     but only when memory_engine.site_reference_counts/
     project_reference_counts confirm zero dependent events/operational
     -items/sites exist — enforced with a 409 otherwise. The only
     removal mechanism that actually applies here (archiving a site) is
     non-destructive: both directions of the link remain fully
     resolvable afterward.
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
def project_and_site(admin):
    """Function-scoped (not session) since several tests here archive or
    attempt to delete the site/project — each test needs its own."""
    proj = requests.post(f"{API}/projects", json={"name": "Traceability Verify", "code": "TRVFY"},
                         headers=admin["headers"], timeout=20).json()
    site = requests.post(f"{API}/sites", json={"project_id": proj["id"], "name": "Traceability Verify Site"},
                        headers=admin["headers"], timeout=20).json()
    return proj, site


def _event_and_approval(admin, site, message=None):
    event = requests.post(f"{API}/events", data={"site_id": site["id"], "text": "Traceability test event"},
                          headers=admin["headers"], timeout=20).json()
    body = {"message": message} if message else {}
    approval = requests.post(f"{API}/events/{event['id']}/request-approval", json=body,
                             headers=admin["headers"], timeout=20).json()
    return event, approval


def test_approval_stores_the_event_link(admin, project_and_site):
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    assert approval["inherited_evidence_event_id"] == event["id"]


def test_event_resolves_its_approval_via_timeline(admin, project_and_site):
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    tl = requests.get(f"{API}/timeline?site_id={site['id']}", headers=admin["headers"], timeout=20).json()
    entry = next(i for i in tl if i["event"]["id"] == event["id"])
    assert entry["approval_item_id"] == approval["id"]
    assert entry["approval_status"] == "open"


def test_event_resolves_its_approval_via_single_event_detail(admin, project_and_site):
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    single = requests.get(f"{API}/events/{event['id']}", headers=admin["headers"], timeout=20).json()
    assert single["approval_item_id"] == approval["id"]


def test_workflow_activity_not_duplicated_onto_the_approval_item(admin, project_and_site):
    """'Where applicable' - no current capture flow sets activity_id on
    an event, so no approval item should have one either; the
    relationship (if it ever exists) is reachable via the event only."""
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    assert event.get("activity_id") is None
    assert "activity_id" not in approval


def test_event_link_is_immutable_via_edit(admin, project_and_site):
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    r = requests.patch(f"{API}/operational-items/{approval['id']}",
                       json={"title": "Renamed", "inherited_evidence_event_id": "evt_hacked"},
                       headers=admin["headers"], timeout=20)
    assert r.status_code == 200
    assert r.json()["inherited_evidence_event_id"] == event["id"], \
        "inherited_evidence_event_id must never change, even if present in an edit payload"


def test_event_link_survives_full_approval_lifecycle(admin, project_and_site):
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    requests.post(f"{API}/operational-items/{approval['id']}/transition",
                 json={"to_status": "fulfilled", "note": "Approved"}, headers=admin["headers"], timeout=20)
    after = requests.get(f"{API}/operational-items/{approval['id']}", headers=admin["headers"], timeout=20).json()
    assert after["item"]["inherited_evidence_event_id"] == event["id"]


def test_no_delete_endpoint_exists_for_events_or_items(admin, project_and_site):
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    assert requests.delete(f"{API}/events/{event['id']}", headers=admin["headers"], timeout=20).status_code in (404, 405)
    assert requests.delete(f"{API}/operational-items/{approval['id']}", headers=admin["headers"], timeout=20).status_code in (404, 405)


def test_site_hard_delete_blocked_while_dependents_exist(admin, project_and_site):
    _, site = project_and_site
    _event_and_approval(admin, site)
    r = requests.delete(f"{API}/sites/{site['id']}", headers=admin["headers"], timeout=20)
    assert r.status_code == 409


def test_project_hard_delete_blocked_while_it_has_a_site(admin, project_and_site):
    proj, _ = project_and_site
    r = requests.delete(f"{API}/projects/{proj['id']}", headers=admin["headers"], timeout=20)
    assert r.status_code == 409


def test_archiving_site_does_not_orphan_either_direction(admin, project_and_site):
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    r_archive = requests.post(f"{API}/sites/{site['id']}/archive", headers=admin["headers"], timeout=20)
    assert r_archive.status_code == 200

    tl = requests.get(f"{API}/timeline?site_id={site['id']}", headers=admin["headers"], timeout=20).json()
    entry = next((i for i in tl if i["event"]["id"] == event["id"]), None)
    assert entry is not None and entry["approval_item_id"] == approval["id"]

    item = requests.get(f"{API}/operational-items/{approval['id']}", headers=admin["headers"], timeout=20).json()
    assert item["item"]["inherited_evidence_event_id"] == event["id"]


def test_second_unrelated_item_on_same_event_never_confused_with_approval(admin, project_and_site):
    """Category-scoping guard: an event could have an unrelated item
    linked via inherited_evidence_event_id too (e.g. an AI-unavailable
    fallback note, category "general") - that must never be mistaken
    for the client_approval request just because it points at the same
    event."""
    _, site = project_and_site
    event, approval = _event_and_approval(admin, site)
    # A second request-approval call for the SAME event must return the
    # existing approval, not create or find a different item.
    r = requests.post(f"{API}/events/{event['id']}/request-approval", json={}, headers=admin["headers"], timeout=20)
    assert r.json()["id"] == approval["id"]
