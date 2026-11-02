"""Launch-readiness patch 4 - additive project assignment.

Root cause: POST /api/admin/users/{id}/projects always REPLACED the user's
assigned_project_ids (memory_engine.set_user_projects -> $set). The
create-project wizard sends only the new project's id, so assigning the same
person to a second project silently removed their access to the first.

Fix under test: the route accepts mode="add" (atomic $addToSet, idempotent,
validated against existing projects). mode defaults to "replace", which is
exactly the old behaviour, because the User Management screen sends the full
desired list (that is how it removes a project) and depends on it.

Real app, blank in-memory DB, real onboarding. Only generate_recommendation()'s
network call is simulated (as in test_step4_blank_onboarding.py).

Run from backend/: python -m pytest tests/test_additive_project_assignment.py -q
"""
from __future__ import annotations

import pytest

pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

from tests import test_step4_blank_onboarding as s4  # noqa: E402
from tests.test_first_operational_workflow import _onboard, _provision, _project_and_site  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _assign(h, headers, uid, ids, mode=None):
    body = {"project_ids": ids}
    if mode:
        body["mode"] = mode
    return await h.post(f"/api/admin/users/{uid}/projects", json=body, headers=headers)


async def _visible(h, headers):
    return sorted(p["id"] for p in (await h.get("/api/projects", headers=headers)).json())


async def _visible_sites(h, headers):
    return sorted(s["project_id"] for s in (await h.get("/api/sites", headers=headers)).json())


def _client():
    # routes.admin_users does `from core.db import db`, so (like every engine in
    # ENGINE_MODULE_NAMES) its own binding must follow the per-test blank DB.
    import core.db as core_db
    import routes.admin_users as admin_users
    admin_users.db = core_db.db
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=s4._server_app()), base_url="http://t")


async def test_defect_reproduced_wizard_style_calls_replace_by_default():
    """Documents the legacy default: omitting mode still means replace."""
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        uid, sup = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
        a, _ = await _project_and_site(h, admin)
        b, _ = await _project_and_site(h, admin)
        await _assign(h, admin, uid, [a["id"]])
        await _assign(h, admin, uid, [b["id"]])  # no mode == legacy replace
        assert await _visible(h, sup) == [b["id"]]  # A was lost - the reported defect, unchanged for legacy callers


async def test_restaurant_multi_outlet_additive_assignment_keeps_both_outlets():
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        s1, sup1 = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
        a, site_a = await _project_and_site(h, admin)
        b, site_b = await _project_and_site(h, admin)

        assert (await _assign(h, admin, s1, [a["id"]], "add")).status_code == 200
        assert (await _assign(h, admin, s1, [b["id"]], "add")).status_code == 200
        assert await _visible(h, sup1) == sorted([a["id"], b["id"]])
        assert await _visible_sites(h, sup1) == sorted([a["id"], b["id"]])

        # Repeating is idempotent: no duplicate entries.
        for _ in range(2):
            assert (await _assign(h, admin, s1, [a["id"]], "add")).status_code == 200
        stored = (await s4_db().users.find_one({"id": s1}))["assigned_project_ids"]
        assert sorted(stored) == sorted([a["id"], b["id"]]) and len(stored) == 2

        # Capture still works at both outlets for the same person.
        for site in (site_a, site_b):
            r = await h.post("/api/events", data={"site_id": site["id"], "text": "Delivery received"}, headers=sup1)
            assert r.status_code == 201


async def test_two_supervisors_keep_independent_assignments():
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        s1, sup1 = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
        s2, sup2 = await _provision(h, admin, "9200000102", "Amit", "site_supervisor")
        a, _ = await _project_and_site(h, admin)
        b, _ = await _project_and_site(h, admin)
        c, _ = await _project_and_site(h, admin)
        await _assign(h, admin, s1, [a["id"]], "add")
        await _assign(h, admin, s2, [b["id"]], "add")
        await _assign(h, admin, s1, [c["id"]], "add")
        assert await _visible(h, sup1) == sorted([a["id"], c["id"]])
        assert await _visible(h, sup2) == [b["id"]]  # untouched by s1's assignments


async def test_removal_via_replace_removes_only_that_project():
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        s1, sup1 = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
        a, _ = await _project_and_site(h, admin)
        b, _ = await _project_and_site(h, admin)
        await _assign(h, admin, s1, [a["id"]], "add")
        await _assign(h, admin, s1, [b["id"]], "add")
        # What the User Management screen does to un-assign A: send the full desired list.
        assert (await _assign(h, admin, s1, [b["id"]])).status_code == 200
        assert await _visible(h, sup1) == [b["id"]]


async def test_add_rejects_unknown_project_and_grants_nothing():
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        s1, sup1 = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
        a, _ = await _project_and_site(h, admin)
        await _assign(h, admin, s1, [a["id"]], "add")
        r = await _assign(h, admin, s1, ["prj_does_not_exist"], "add")
        assert r.status_code == 404
        assert await _visible(h, sup1) == [a["id"]]
        r = await h.post(f"/api/admin/users/{s1}/projects", json={"project_ids": [a["id"]], "mode": "bogus"}, headers=admin)
        assert r.status_code == 422


async def test_unauthorized_callers_cannot_grant_access():
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.construction_rec)
        s1, sup1 = await _provision(h, admin, "9200000201", "Sup", "site_supervisor")
        pm_id, pm = await _provision(h, admin, "9200000001", "Rahul", "project_manager")
        a, _ = await _project_and_site(h, admin)
        # A supervisor cannot assign anyone (including themselves) to anything.
        assert (await _assign(h, sup1, s1, [a["id"]], "add")).status_code == 403
        assert await _visible(h, sup1) == []
        # A PM who is not a member of a project that already has members cannot add people to it.
        await _assign(h, admin, s1, [a["id"]], "add")
        assert (await _assign(h, pm, pm_id, [a["id"]], "add")).status_code == 403
        assert await _visible(h, pm) == []


async def test_pm_and_supervisor_visibility_stays_scoped_across_two_construction_projects():
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.construction_rec)
        pm_id, pm = await _provision(h, admin, "9200000001", "Rahul", "project_manager")
        sup_id, sup = await _provision(h, admin, "9200000201", "Sup", "site_supervisor")
        a, _ = await _project_and_site(h, admin)
        b, _ = await _project_and_site(h, admin)
        c, _ = await _project_and_site(h, admin)  # nobody is assigned here
        await _assign(h, admin, pm_id, [a["id"]], "add")
        await _assign(h, admin, pm_id, [b["id"]], "add")
        await _assign(h, admin, sup_id, [b["id"]], "add")
        assert await _visible(h, pm) == sorted([a["id"], b["id"]])
        assert await _visible(h, sup) == [b["id"]]
        assert c["id"] not in await _visible(h, pm) and c["id"] not in await _visible(h, sup)
        assert len(await _visible(h, admin)) == 3  # management is unscoped


async def test_single_project_behaviour_unchanged_in_both_modes():
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        s1, sup1 = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
        s2, sup2 = await _provision(h, admin, "9200000102", "Amit", "site_supervisor")
        a, _ = await _project_and_site(h, admin)
        await _assign(h, admin, s1, [a["id"]], "add")
        await _assign(h, admin, s2, [a["id"]])  # legacy replace form
        assert await _visible(h, sup1) == [a["id"]] and await _visible(h, sup2) == [a["id"]]


def s4_db():
    import core.db as core_db
    return core_db.db
