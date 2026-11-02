"""Launch-readiness patch 3 — the first operational workflow, end to end.

Real app (httpx.ASGITransport against server.app) on a genuinely blank,
in-memory database, via the real onboarding flow. The only simulated element
is generate_recommendation()'s network call (as in test_step4_blank_onboarding).
Capture is exercised with a text event, which is persisted immediately with
ai_status "pending" - no AI result is fabricated or required for these tests.

What this proves
 1. A business whose approved roles do NOT include both a project manager and
    a site supervisor (restaurant: management + supervisor; one-person shop:
    management only) can create a project and site and run the whole
    lifecycle: capture -> item -> assignment -> acknowledge/start/fulfil ->
    verification by a DIFFERENT person -> history with actors. The create-
    project wizard used to make a PM *and* a supervisor mandatory, so the
    frontend half of this (see frontend/scripts/check-project-wizard.test.mjs)
    blocked every such business at step 2.
 2. A project manager is project-scoped: a project they create is invisible
    to them until they are assigned - which is why the wizard now adds a
    non-management creator automatically.
 3. Separation of duties on verification is preserved.

Run from backend/: python -m pytest tests/test_first_operational_workflow.py -q
"""
from __future__ import annotations

import pytest

pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

from tests import test_step4_blank_onboarding as s4  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _onboard(http, rec_fn):
    from engines import business_setup_engine as bse
    _, token = await s4._register_and_approve_founding_admin(http)
    admin = {"Authorization": f"Bearer {token}"}
    original = bse.generate_recommendation

    async def _fake(desc):
        return dict(rec_fn(bse))

    bse.generate_recommendation = _fake
    try:
        r = await http.post("/api/business-setup/analyze", json={"description": "x business"}, headers=admin)
    finally:
        bse.generate_recommendation = original
    assert r.status_code == 200, r.text
    assert (await http.post("/api/business-setup/approve", json={}, headers=admin)).status_code == 200
    return admin


async def _provision(http, admin, phone, name, role):
    r = await http.post("/api/provisioning/users", json={"phone": phone, "name": name, "role": role}, headers=admin)
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    tok = (await http.post("/api/auth/login", json={"phone": phone})).json()["token"]
    return uid, {"Authorization": f"Bearer {tok}"}


async def _project_and_site(http, headers):
    """Exactly the two calls the create-project wizard makes first."""
    p = await http.post("/api/projects", json={"name": "First project"}, headers=headers)
    assert p.status_code == 200, p.text
    s = await http.post("/api/sites", json={"project_id": p.json()["id"], "name": "Main Site"}, headers=headers)
    assert s.status_code == 200, s.text
    return p.json(), s.json()


async def test_restaurant_without_a_project_manager_runs_the_whole_lifecycle():
    await s4._blank_instance()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s4._server_app()), base_url="http://t") as h:
        admin = await _onboard(h, s4.restaurant_rec)  # roles: management + site_supervisor, NO project_manager
        sup_id, sup = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
        project, site = await _project_and_site(h, admin)

        # Team step: only the supervisor exists, and that is enough.
        assert (await h.get("/api/users", params={"role": "project_manager"}, headers=admin)).json() == []
        r = await h.post(f"/api/admin/users/{sup_id}/projects", json={"project_ids": [project["id"]]}, headers=admin)
        assert r.status_code == 200, r.text

        # The supervisor can now reach the site and capture. Persisted immediately.
        sites = (await h.get("/api/sites", headers=sup)).json()
        assert [x["id"] for x in sites] == [site["id"]]
        ev = await h.post("/api/events", data={"site_id": site["id"], "text": "Need 20 kg tomatoes by Friday"}, headers=sup)
        assert ev.status_code == 201 and ev.json()["ai_status"] == "pending"
        assert (await h.get(f"/api/events/{ev.json()['id']}", headers=admin)).status_code == 200  # management can retrieve it

        # Item -> assign -> lifecycle by the assignee.
        item = (await h.post("/api/operational-items", headers=admin, json={
            "site_id": site["id"], "category": "material_requirement", "title": "20 kg tomatoes"})).json()
        assert item["status"] == "open"
        r = await h.post(f"/api/operational-items/{item['id']}/assign", json={"assigned_to_user_id": sup_id}, headers=admin)
        assert r.status_code == 200 and r.json()["assigned_to_user_id"] == sup_id
        assert (await h.get(f"/api/operational-items/{item['id']}", headers=sup)).status_code == 200
        for to in ("acknowledged", "in_progress", "fulfilled"):
            r = await h.post(f"/api/operational-items/{item['id']}/transition", json={"to_status": to}, headers=sup)
            assert r.status_code == 200 and r.json()["status"] == to, r.text

        # Separation of duties: the fulfiller cannot verify; management (a different person) can.
        r = await h.post(f"/api/operational-items/{item['id']}/transition", json={"to_status": "verified"}, headers=sup)
        assert r.status_code == 400
        r = await h.post(f"/api/operational-items/{item['id']}/transition", json={"to_status": "verified"}, headers=admin)
        assert r.status_code == 200 and r.json()["status"] == "verified"

        # Management retrieves the full provenance later.
        d = (await h.get(f"/api/operational-items/{item['id']}", headers=admin)).json()
        kinds = [x["kind"] for x in d["history"]]
        assert kinds == ["created", "assigned", "acknowledged", "started", "fulfilled", "verified"]
        assert d["item"]["status"] == "verified" and d["item"]["verified_by_user_id"]


async def test_one_person_business_can_create_capture_progress_and_close_without_any_team():
    await s4._blank_instance()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s4._server_app()), base_url="http://t") as h:
        admin = await _onboard(h, s4.small_shop_rec)  # roles: management only
        project, site = await _project_and_site(h, admin)  # no one to assign - must still work
        ev = await h.post("/api/events", data={"site_id": site["id"], "text": "Counter fridge stopped cooling"}, headers=admin)
        assert ev.status_code == 201
        item = (await h.post("/api/operational-items", headers=admin, json={
            "site_id": site["id"], "category": "site_issue", "title": "Fridge repair", "priority": "high"})).json()
        for to in ("in_progress", "fulfilled", "closed"):
            r = await h.post(f"/api/operational-items/{item['id']}/transition", json={"to_status": to}, headers=admin)
            assert r.status_code == 200 and r.json()["status"] == to, r.text
        d = (await h.get(f"/api/operational-items/{item['id']}", headers=admin)).json()
        assert [x["kind"] for x in d["history"]][-1] == "closed"
        # No demo data was injected along the way.
        assert len((await h.get("/api/projects", headers=admin)).json()) == 1


async def test_project_manager_does_not_see_a_project_they_created_until_assigned():
    await s4._blank_instance()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s4._server_app()), base_url="http://t") as h:
        admin = await _onboard(h, s4.construction_rec)
        pm_id, pm = await _provision(h, admin, "9200000001", "Rahul", "project_manager")
        project, _site = await _project_and_site(h, pm)  # a PM may create projects
        assert (await h.get("/api/projects", headers=pm)).json() == []  # scoped: sees nothing yet
        r = await h.post(f"/api/admin/users/{pm_id}/projects", json={"project_ids": [project["id"]]}, headers=pm)
        assert r.status_code == 200, r.text  # allowed: project has no members yet (the wizard's own case)
        assert [p["id"] for p in (await h.get("/api/projects", headers=pm)).json()] == [project["id"]]
