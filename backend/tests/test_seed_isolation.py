"""Step 4 follow-up — Separate Optional Demo Seed From Blank Onboarding.

Proves the four guarantees this fix establishes:
A. A blank database stays blank through the real onboarding flow - no
   project, site, or demo data appears as a side effect of registration,
   business setup, approval, or provisioning.
B. The explicit demo-seed route (POST /api/projects/seed) still works
   when deliberately invoked, is idempotent, and is now management-only.
C. Nothing in the backend invokes it automatically — confirmed by
   searching server.py's own startup path and by the fresh-onboarding
   proof in (A) never triggering it.
D. The existing Step 4 deterministic onboarding suite remains valid
   (re-run as part of the same regression pass, not duplicated here).

Follows the established mongomock_motor + ASGITransport pattern already
used throughout tests/test_step4_blank_onboarding.py and tests/
test_dev02_bootstrap_reliability.py's own commercial/CRE gate tests.

Run from backend/: python -m pytest tests/test_seed_isolation.py -q
"""
from __future__ import annotations

import os
import sys
import importlib
import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_seed_isolation_test")
os.environ.setdefault("JWT_SECRET", "seed-isolation-test-secret-key-at-least-32-bytes")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ENGINE_MODULE_NAMES = [
    "engines.memory_engine", "engines.operations_engine", "engines.intelligence_engine",
    "engines.commercial_engine", "engines.business_setup_engine", "engines.provisioning_engine",
    "engines.reasoning_engine", "engines.knowledge_graph_engine", "engines.workflow_engine",
    "engines.timeline_engine", "engines.notification_engine", "core.auth",
]


async def _blank_instance():
    """Same mechanism as test_step4_blank_onboarding.py's own
    _blank_instance(): a fresh AsyncMongoMockClient, reset through the
    repository's real scripts.db_reset.reset(), confirmed empty before
    any test logic runs."""
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()
    db = client["atlas_seed_isolation_blank"]

    import core.db as core_db
    core_db.db = db
    core_db.client = client
    for name in ENGINE_MODULE_NAMES:
        mod = importlib.import_module(name)
        if hasattr(mod, "db"):
            mod.db = db

    import scripts.db_reset as db_reset
    db_reset.db = db
    db_reset.client = client
    dropped = await db_reset.reset(verbose=False)
    assert dropped == []

    assert await db.business_configuration.count_documents({}) == 0
    assert await db.users.count_documents({}) == 0
    assert await db.projects.count_documents({}) == 0
    assert await db.sites.count_documents({}) == 0
    return client, db


def _server_app():
    import server
    return server.app


# ============================================================================
# A. Fresh onboarding stays genuinely blank through the real flow.
# ============================================================================

async def test_fresh_onboarding_creates_no_project_or_site_as_a_side_effect():
    client, db = await _blank_instance()
    app = _server_app()
    transport = httpx.ASGITransport(app=app)
    from engines import business_setup_engine as bse

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        # 1. First registration — the real path, not a direct db insert.
        r = await http.post("/api/auth/register", json={"phone": "9300000001", "name": "Founding Admin"})
        assert r.status_code == 200, r.text
        user, token = r.json()["user"], r.json()["token"]
        assert user["role"] == "management" and user["approval_status"] == "approved"
        headers = {"Authorization": f"Bearer {token}"}

        # No project/site exists purely from registering — this is the
        # exact guarantee the old apiSeedDemo() calls would have broken.
        assert await db.projects.count_documents({}) == 0
        assert await db.sites.count_documents({}) == 0

        # 2. Business configuration is genuinely absent until analyzed.
        r = await http.get("/api/business-setup", headers=headers)
        assert r.status_code == 200 and r.json()["status"] == "none"

        # 3. Business discovery (simulated AI call, same pattern as
        # test_step4_blank_onboarding.py's own module docstring explains).
        rec = {
            "business_profile": {"industry": "restaurant", "business_type": "restaurant", "org_size": None,
                                 "location_count": 1, "operating_model": "location-based"},
            "recommended_roles": ["management"],
            "capability_recommendations": {k: "not_required" for k in bse.CAPABILITIES},
            "client_access_required": False, "configuration_questions": [], "assumptions": [],
            "confidence": "high", "explanation": "x",
        }
        rec["capability_recommendations"].update({k: "required" for k in bse.ALWAYS_REQUIRED})
        original = bse.generate_recommendation
        async def _fake(desc): return dict(rec)
        bse.generate_recommendation = _fake
        try:
            r = await http.post("/api/business-setup/analyze",
                                json={"description": "We run a small restaurant."}, headers=headers)
        finally:
            bse.generate_recommendation = original
        assert r.status_code == 200

        # Still no project/site — analysis alone creates nothing.
        assert await db.projects.count_documents({}) == 0
        assert await db.sites.count_documents({}) == 0

        # 4. Human approval.
        r = await http.post("/api/business-setup/approve", json={}, headers=headers)
        assert r.status_code == 200

        # 5. Provisioning (no additional people in this test).
        r = await http.get("/api/provisioning/status", headers=headers)
        assert r.status_code == 200 and r.json()["configured"] is True

        # THE final, decisive assertion: after the complete, real
        # onboarding flow — register, discover, approve, reach the
        # provisioned/active state — still zero projects and zero sites.
        # A restaurant business must never have a construction demo
        # project silently appear in its workspace.
        assert await db.projects.count_documents({}) == 0
        assert await db.sites.count_documents({}) == 0


# ============================================================================
# B. The explicit demo-seed route still works, is idempotent, and is now
# management-only (Step 4 hardening found during this same trace).
# ============================================================================

async def test_explicit_seed_route_still_works_for_management():
    client, db = await _blank_instance()
    app = _server_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        r = await http.post("/api/auth/register", json={"phone": "9300000101", "name": "Admin"})
        token = r.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = await http.post("/api/projects/seed", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["seeded"] is True and body["sites"] == 3

        r2 = await http.post("/api/projects/seed", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["seeded"] is False  # idempotent — no second demo project


async def test_explicit_seed_route_is_management_only():
    client, db = await _blank_instance()
    app = _server_app()
    transport = httpx.ASGITransport(app=app)
    from engines import memory_engine as me
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        admin_r = await http.post("/api/auth/register", json={"phone": "9300000201", "name": "Admin"})
        admin_token = admin_r.json()["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # A second, non-founding account — approve it as project_manager
        # via the real admin route, matching how any ordinary user would
        # actually get a role in this product.
        pm_r = await http.post("/api/auth/register", json={"phone": "9300000202", "name": "PM"})
        pm_user_id = pm_r.json()["user"]["id"]
        r = await http.post(f"/api/admin/users/{pm_user_id}/approve", headers=admin_headers)
        assert r.status_code == 200
        r = await http.post(f"/api/admin/users/{pm_user_id}/role",
                            json={"role": "project_manager"}, headers=admin_headers)
        assert r.status_code == 200

        pm_login = await http.post("/api/auth/login", json={"phone": "9300000202"})
        pm_token = pm_login.json()["token"]

        r = await http.post("/api/projects/seed", headers={"Authorization": f"Bearer {pm_token}"})
        assert r.status_code == 403
        assert await db.projects.count_documents({}) == 0  # the rejected attempt created nothing


# ============================================================================
# C. Nothing invokes the seed route automatically.
# ============================================================================

def test_server_startup_never_imports_a_seed_script():
    """Static confirmation, mirroring routes/projects.py's own route
    (exercised live in (A)/(B) above): server.py has no import of
    scripts.bootstrap, scripts.db_seed, or scripts.seed_demo_project, and
    no startup event handler at all that could invoke one."""
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    server_src = open(os.path.join(backend_dir, "server.py"), encoding="utf-8").read()
    for forbidden in ("import bootstrap", "import db_seed", "import seed_demo_project", "on_event(\"startup\""):
        assert forbidden not in server_src, f"server.py must not reference {forbidden!r}"


def test_login_and_tabs_index_no_longer_reference_apiSeedDemo():
    """Backend-side mirror of frontend/scripts/check-entry-routing.js's
    own static guard (that script is the authoritative one; this is a
    second, independent confirmation from the Python test suite so the
    guarantee shows up in the same regression run as everything else)."""
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
    if not os.path.isdir(frontend_dir):
        pytest.skip("frontend directory not present in this checkout")
    login_src = open(os.path.join(frontend_dir, "app", "login.tsx"), encoding="utf-8").read()
    tabs_src = open(os.path.join(frontend_dir, "app", "(tabs)", "index.tsx"), encoding="utf-8").read()

    def _strip_comments(src: str) -> str:
        return "\n".join(line.split("//")[0] for line in src.splitlines())

    assert "apiSeedDemo" not in _strip_comments(login_src)
    assert "apiSeedDemo" not in _strip_comments(tabs_src)
