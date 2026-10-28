"""Launch-readiness regression: the management landing screen (Executive
Hub) must stay usable for a business whose approved configuration does not
include the construction-reasoning capability.

Backend half (proved here, through the real app and the real onboarding
flow): for a restaurant, the capability-gated hub endpoints correctly
return 403 while the universal ones (projects, management digest) still
return 200 - so "some hub sections are unavailable" is a normal, permanent
state for non-construction businesses, not an error.

Frontend half (static guard, frontend/scripts/check-entry-routing.js): the
hub must load its sections independently (Promise.allSettled), not with
Promise.all, where one 403 blanked the entire screen.

The only simulated element is generate_recommendation()'s network call,
exactly as in test_step4_blank_onboarding.py.

Run from backend/: python -m pytest tests/test_hub_partial_availability.py -q
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


async def test_restaurant_hub_endpoints_gated_sections_403_universal_sections_200():
    from engines import business_setup_engine as bse
    client, db = await s4._blank_instance()
    app = s4._server_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        _, token = await s4._register_and_approve_founding_admin(http)
        headers = {"Authorization": f"Bearer {token}"}

        original = bse.generate_recommendation

        async def _fake(desc):
            return dict(s4.restaurant_rec(bse))

        bse.generate_recommendation = _fake
        try:
            r = await http.post("/api/business-setup/analyze", json={"description": s4.RESTAURANT_DESC}, headers=headers)
        finally:
            bse.generate_recommendation = original
        assert r.status_code == 200, r.text
        r = await http.post("/api/business-setup/approve", json={}, headers=headers)
        assert r.status_code == 200, r.text

        gated = await http.get("/api/portfolio/priorities", headers=headers)
        assert gated.status_code == 403
        gated = await http.get("/api/portfolio/cross-project-intelligence", headers=headers)
        assert gated.status_code == 403

        assert (await http.get("/api/inbox/management-digest", headers=headers)).status_code == 200
        r = await http.get("/api/projects", headers=headers)
        assert r.status_code == 200 and r.json() == []  # blank business: zero projects, no demo data
