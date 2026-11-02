"""Launch-readiness patch 2 — reopening business setup and team provisioning.

The patch only adds navigation to screens whose backend already exists, so
the backend guarantees the new entry points rely on are proven here against
the real app and the real onboarding flow (only generate_recommendation()'s
network call is simulated, exactly as in test_step4_blank_onboarding.py):

 1. Management can reopen the business configuration and team provisioning.
 2. Non-management users are refused (403) on every management-only control.
 3. Revisiting does not change the approved configuration; re-analysing or
    re-approving cannot silently overwrite it.
 4. Revisiting does not reprovision existing users (duplicate phone refused,
    user count unchanged).

Run from backend/: python -m pytest tests/test_reopen_setup_access.py -q
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


async def _onboarded_restaurant(http):
    """Founding admin -> approved restaurant configuration -> one supervisor."""
    from engines import business_setup_engine as bse
    _, token = await s4._register_and_approve_founding_admin(http)
    admin = {"Authorization": f"Bearer {token}"}
    original = bse.generate_recommendation

    async def _fake(desc):
        return dict(s4.restaurant_rec(bse))

    bse.generate_recommendation = _fake
    try:
        r = await http.post("/api/business-setup/analyze", json={"description": s4.RESTAURANT_DESC}, headers=admin)
    finally:
        bse.generate_recommendation = original
    assert r.status_code == 200, r.text
    assert (await http.post("/api/business-setup/approve", json={}, headers=admin)).status_code == 200
    r = await http.post("/api/provisioning/users",
                        json={"phone": "9200000101", "name": "Priya", "role": "site_supervisor"}, headers=admin)
    assert r.status_code == 200, r.text
    r = await http.post("/api/auth/login", json={"phone": "9200000101"})
    assert r.status_code == 200, r.text
    sup = {"Authorization": f"Bearer {r.json()['token']}"}
    return admin, sup


async def test_management_can_reopen_setup_and_provisioning_and_non_management_cannot():
    client, db = await s4._blank_instance()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s4._server_app()), base_url="http://test") as http:
        admin, sup = await _onboarded_restaurant(http)

        # 1. management reopens both
        r = await http.get("/api/business-setup", headers=admin)
        assert r.status_code == 200 and r.json()["status"] == "approved"
        assert (await http.get("/api/provisioning/status", headers=admin)).status_code == 200
        assert (await http.get("/api/provisioning/role-slots", headers=admin)).status_code == 200

        # 2. a supervisor is refused on every management-only control
        for method, url, body in [
            ("GET", "/api/business-setup", None),
            ("POST", "/api/business-setup/analyze", {"description": "anything"}),
            ("POST", "/api/business-setup/approve", {}),
            ("GET", "/api/provisioning/status", None),
            ("GET", "/api/provisioning/role-slots", None),
            ("POST", "/api/provisioning/users", {"phone": "9200000999", "name": "X", "role": "site_supervisor"}),
        ]:
            r = await http.request(method, url, json=body, headers=sup)
            assert r.status_code == 403, f"{method} {url} -> {r.status_code}"
        assert await db.users.count_documents({"phone": "9200000999"}) == 0


async def test_revisiting_leaves_approved_configuration_and_existing_users_intact():
    client, db = await s4._blank_instance()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=s4._server_app()), base_url="http://test") as http:
        admin, _ = await _onboarded_restaurant(http)
        before = (await http.get("/api/business-setup", headers=admin)).json()
        users_before = await db.users.count_documents({})

        # Viewing again changes nothing.
        again = (await http.get("/api/business-setup", headers=admin)).json()
        assert again == before

        # Re-analysing cannot overwrite an approved configuration (409), even though the
        # description is different; nothing is persisted.
        from engines import business_setup_engine as bse
        original = bse.generate_recommendation

        async def _other(desc):  # a valid recommendation, so the request reaches the overwrite guard
            return dict(s4.restaurant_rec(bse))

        bse.generate_recommendation = _other
        try:
            r = await http.post("/api/business-setup/analyze",
                                json={"description": "A totally different business"}, headers=admin)
        finally:
            bse.generate_recommendation = original
        assert r.status_code == 409, r.text
        # Re-approving must not alter the approved fields.
        await http.post("/api/business-setup/approve", json={"capability_overrides": {"commercial": "required"}},
                        headers=admin)
        after = (await http.get("/api/business-setup", headers=admin)).json()
        for k in ("status", "raw_description", "approved_capabilities", "approved_roles", "approved_client_access",
                  "approved_by_user_id"):
            assert after[k] == before[k], k

        # Existing users are not reprovisioned: same phone is refused, count unchanged.
        r = await http.post("/api/provisioning/users",
                            json={"phone": "9200000101", "name": "Someone Else", "role": "site_supervisor"},
                            headers=admin)
        assert r.status_code == 400
        assert await db.users.count_documents({}) == users_before
        assert (await db.users.find_one({"phone": "9200000101"}))["name"] == "Priya"
