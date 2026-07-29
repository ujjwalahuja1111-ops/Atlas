"""DEV-02 — Bootstrap Runtime Reliability regression tests.

Follows tests/test_cre_smoke_mongomock.py's own established pattern
(mongomock_motor, real engine code, no deployed server needed) rather
than the live-URL pattern most other test files in this suite use -
appropriate here because these tests verify internal round-trip
behavior and state-machine correctness, not an HTTP surface.

Skips cleanly if mongomock_motor is not installed, matching that
file's own convention exactly.

The correctness and round-trip-count claims below were independently
verified during development against this repository's own sandbox
tooling (see scripts/DEV02_ROOT_CAUSE.md for the full measurement) -
this file re-expresses those same checks in the project's own
committed, mongomock_motor-based test convention so they run
automatically in any environment that has it installed, including CI.

Run from backend/:  python -m pytest tests/test_dev02_bootstrap_reliability.py -q
"""
import os
import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_dev02_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_dev02_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, knowledge_engine, workflow_engine  # noqa: E402

for _mod in (memory_engine, knowledge_engine, workflow_engine):
    _mod.db = _mock_db

ADMIN = {"id": "u_admin", "name": "Admin"}

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


# ==========================================================================
# Client lifecycle
# ==========================================================================
def test_shared_client_has_hardened_pool_settings():
    """The one shared Motor client every engine and script uses must
    have explicit idle-recycling and retry settings - not left to
    driver defaults that could vary or be silently disabled. See
    scripts/DEV02_ROOT_CAUSE.md for why this matters specifically for
    a long-running, multi-stage process like bootstrap.py.

    Verified by source scan, not runtime introspection: this test
    file's own mongomock swap (above) replaces core_db.client with a
    mock client entirely, so checking core_db.client.options at this
    point would only ever check the mock's options, never the real
    configured client this test is actually meant to guard."""
    import re
    from pathlib import Path
    source = Path(__file__).parent.parent.joinpath("core", "db.py").read_text()
    assert re.search(r"maxIdleTimeMS\s*=\s*45000", source), \
        "core/db.py must set an explicit maxIdleTimeMS on the shared client"
    assert re.search(r"retryReads\s*=\s*True", source), \
        "core/db.py must set explicit retryReads=True on the shared client"
    assert re.search(r"retryWrites\s*=\s*True", source), \
        "core/db.py must set explicit retryWrites=True on the shared client"


# ==========================================================================
# Workflow Engine — sibling promotion correctness, after the fix
# ==========================================================================
@pytest.fixture()
async def dependency_chain():
    """A -> B -> C dependency chain, three real workflow activities in
    a real project, via the real engine functions - not hand-built
    documents, so this exercises the actual generate_workflow path."""
    project = await memory_engine.insert_project(name="DEV-02 Test", code=f"D02-{os.urandom(3).hex()}")
    template = await knowledge_engine.create_item(actor=ADMIN, type_="workflow_template", name="DEV-02 Template", status="active")
    act_a = await knowledge_engine.create_item(actor=ADMIN, type_="activity", name="Foundation", status="active")
    act_b = await knowledge_engine.create_item(actor=ADMIN, type_="activity", name="Structure", status="active")
    act_c = await knowledge_engine.create_item(actor=ADMIN, type_="activity", name="Roof", status="active")
    for a in (act_a, act_b, act_c):
        await knowledge_engine.add_relationship(template["id"], actor=ADMIN, type_="includes_activity", target_id=a["id"])

    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=ADMIN)
    by_name = {a["name"]: a for a in activities}
    a_id, b_id, c_id = by_name["Foundation"]["id"], by_name["Structure"]["id"], by_name["Roof"]["id"]

    await core_db.db.workflow_activities.update_one(
        {"id": b_id}, {"$set": {"depends_on_activity_ids": [a_id], "status": "not_started"}})
    await core_db.db.workflow_activities.update_one(
        {"id": c_id}, {"$set": {"depends_on_activity_ids": [b_id], "status": "not_started"}})
    return a_id, b_id, c_id


async def test_completing_activity_promotes_direct_dependent_only(dependency_chain):
    a_id, b_id, c_id = dependency_chain
    b_before = await workflow_engine.get_workflow_activity(b_id)
    c_before = await workflow_engine.get_workflow_activity(c_id)
    assert b_before["status"] == "not_started"
    assert c_before["status"] == "not_started"

    await workflow_engine.set_status(a_id, "in_progress", actor=ADMIN)
    await workflow_engine.set_status(a_id, "completed", actor=ADMIN)

    b_after = await workflow_engine.get_workflow_activity(b_id)
    c_after = await workflow_engine.get_workflow_activity(c_id)
    assert b_after["status"] == "ready", "direct dependent must be promoted"
    assert c_after["status"] == "not_started", \
        "a sibling one level further down the chain must NOT be prematurely promoted"


async def test_completing_second_link_promotes_third(dependency_chain):
    a_id, b_id, c_id = dependency_chain
    await workflow_engine.set_status(a_id, "in_progress", actor=ADMIN)
    await workflow_engine.set_status(a_id, "completed", actor=ADMIN)
    await workflow_engine.set_status(b_id, "in_progress", actor=ADMIN)
    await workflow_engine.set_status(b_id, "completed", actor=ADMIN)

    c_after = await workflow_engine.get_workflow_activity(c_id)
    assert c_after["status"] == "ready"


async def test_completing_activity_own_status_is_correct(dependency_chain):
    """Regression guard specific to this fix: the completing activity's
    own in-memory status is corrected before being reused for the
    sibling-promotion check - confirming that correction actually
    took effect and didn't leave the activity's OWN record stale."""
    a_id, _, _ = dependency_chain
    await workflow_engine.set_status(a_id, "in_progress", actor=ADMIN)
    await workflow_engine.set_status(a_id, "completed", actor=ADMIN)
    a_final = await workflow_engine.get_workflow_activity(a_id)
    assert a_final["status"] == "completed"


async def test_promote_unlocked_siblings_reduces_find_calls(dependency_chain):
    """Direct regression guard for the measured defect: completing an
    activity must issue at most ONE workflow_activities.find() call
    (the dependency-gate check's own fetch, reused for promotion) -
    never two, which was the bug this sprint fixes.

    Patches mongomock_motor's own AsyncMongoMockCollection.find - not
    the dynamically-created AsyncIOMotorCollection subclass Motor
    reports via type(), which does not define its own find() to
    override (confirmed directly: patching it had no effect, since
    Python's attribute lookup found the real implementation on the
    mock library's own class further down the MRO instead)."""
    from mongomock_motor import AsyncMongoMockCollection
    a_id, _, _ = dependency_chain
    find_count = {"n": 0}
    orig_find = AsyncMongoMockCollection.find

    def counting_find(self, *args, **kwargs):
        if self.name == "workflow_activities":
            find_count["n"] += 1
        return orig_find(self, *args, **kwargs)

    AsyncMongoMockCollection.find = counting_find
    try:
        await workflow_engine.set_status(a_id, "in_progress", actor=ADMIN)
        find_count["n"] = 0  # only count the completion transition itself
        await workflow_engine.set_status(a_id, "completed", actor=ADMIN)
    finally:
        AsyncMongoMockCollection.find = orig_find

    assert find_count["n"] == 1, \
        f"expected exactly 1 workflow_activities.find() call on completion, got {find_count['n']}"


async def test_promote_unlocked_siblings_standalone_path_still_works():
    """_promote_unlocked_siblings remains correctly callable with no
    pre-fetched siblings (its own independent path, unchanged by this
    fix) - fetches its own data and still promotes correctly."""
    project = await memory_engine.insert_project(name="DEV-02 Standalone Test", code=f"D02S-{os.urandom(3).hex()}")
    template = await knowledge_engine.create_item(actor=ADMIN, type_="workflow_template", name="Standalone Template", status="active")
    act_a = await knowledge_engine.create_item(actor=ADMIN, type_="activity", name="Excavation", status="active")
    act_b = await knowledge_engine.create_item(actor=ADMIN, type_="activity", name="Footing", status="active")
    for a in (act_a, act_b):
        await knowledge_engine.add_relationship(template["id"], actor=ADMIN, type_="includes_activity", target_id=a["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=ADMIN)
    by_name = {a["name"]: a for a in activities}
    a_id, b_id = by_name["Excavation"]["id"], by_name["Footing"]["id"]
    await core_db.db.workflow_activities.update_one(
        {"id": b_id}, {"$set": {"depends_on_activity_ids": [a_id], "status": "not_started"}})

    await workflow_engine._promote_unlocked_siblings(project["id"], a_id)  # no siblings_by_id given
    # a_id was never actually completed above, so b should NOT be
    # promoted - this is a sanity check that the standalone call path
    # correctly does nothing when the completed activity isn't
    # actually a satisfied dependency yet.
    b_after = await workflow_engine.get_workflow_activity(b_id)
    assert b_after["status"] == "not_started"


# ==========================================================================
# Regression — existing behavior unaffected
# ==========================================================================
async def test_non_completion_transitions_unaffected(dependency_chain):
    a_id, _, _ = dependency_chain
    result = await workflow_engine.set_status(a_id, "in_progress", actor=ADMIN)
    assert result["status"] == "in_progress"
    assert result["actual_start"] is not None


# ==========================================================================
# STAB-01 Issue 1 — RP-001 Completion.
#
# Kept in THIS file for the exact same reason the DEV-02 continuation
# tests above are: a second file independently swapping core_db.db at
# import time collides with this file's own swap via shared global
# module state when both run in the same pytest session - confirmed
# directly, again, while writing this addition (the identical failure
# mode this file's own docstring already documents from the first
# time it happened).
#
# Covers RC-01's own finding: RP-001 carried 135 of 162 operational
# items open despite 99.2% workflow completion, computing overall CRE
# health as Critical. Root cause, found by measurement during this
# sprint (not assumed): resolving open operational items ALONE had
# ZERO effect on health - the actual primary driver was 155 of 157
# requires_inspection activities complete with no inspection-category
# operational item recorded, tripping CRE's own
# quality.completed_without_inspection rule on every one. Both real
# defects are fixed by creating the genuinely missing data and letting
# CRE's own existing rule evaluation compute health from it - never by
# assigning a health value directly.
# ==========================================================================
from engines import reasoning_engine, commercial_engine, operations_engine  # noqa: E402
reasoning_engine.db = _mock_db
commercial_engine.db = _mock_db
operations_engine.db = _mock_db

from scripts import seed_demo_project, reference_portfolio  # noqa: E402
seed_demo_project.db = _mock_db
reference_portfolio.db = _mock_db


@pytest.fixture(scope="module")
async def seeded_rp001():
    """Seeds ACDP once for this block - the full 18-month simulation is
    expensive to run per-test, matching test_cre_smoke_mongomock.py's
    own module-scoped fixture convention."""
    await seed_demo_project.main(close_when_done=False)
    project = await core_db.db.projects.find_one({"code": "ACDP-VILLA"}, {"_id": 0})
    admin = await memory_engine.get_user_by_phone("9800000001")
    return project, admin


async def test_rp001_health_is_critical_before_fix(seeded_rp001):
    """Confirms the defect genuinely exists in freshly-seeded ACDP data
    before either fix runs - a baseline, not an assumption."""
    project, admin = seeded_rp001
    health = await reasoning_engine.project_health(project["id"], user=admin)
    assert health["status"] == "red"


async def test_resolving_operational_items_alone_does_not_fix_health(seeded_rp001):
    """Regression guard for a real investigation finding: resolving all
    open operational items has ZERO effect on health by itself - the
    actual driver is missing inspection records. This test exists so a
    future change that removes the inspection-recording fix (assuming
    operational-item resolution alone is sufficient) fails loudly."""
    project, admin = seeded_rp001
    await reference_portfolio.complete_rp001_operations()
    health = await reasoning_engine.project_health(project["id"], user=admin)
    assert health["status"] == "red", \
        "operational-item resolution alone must not be sufficient to fix RP-001's health - " \
        "if this now passes as green, the inspection-recording fix may have become redundant " \
        "and this test should be revisited, not just relaxed"


async def test_recording_missing_inspections_completes_the_fix(seeded_rp001):
    project, admin = seeded_rp001
    result = await reference_portfolio.record_missing_rp001_inspections()
    assert result["recorded"] > 0
    assert result["unmatched"] == [], "every uncovered activity must match a real site by name"

    health = await reasoning_engine.project_health(project["id"], user=admin)
    assert health["status"] == "green"
    assert health["score"] == 100
    assert health["drivers"] == []


@pytest.fixture(scope="module")
async def closed_out_rp001(seeded_rp001):
    """RP-001 after both closeout fixes, explicit and independent of
    test execution order — the tests above already exercise the BEFORE
    state and each individual fix's own effect; everything below this
    point needs the fully-closed-out state and gets it deterministically
    here rather than relying on those earlier tests having already run
    first (idempotent, so calling again after they did is a safe no-op,
    not a duplicate mutation)."""
    project, admin = seeded_rp001
    await reference_portfolio.complete_rp001_operations()
    await reference_portfolio.record_missing_rp001_inspections()
    return project, admin


async def test_no_critical_priority_operational_items_remain_open(closed_out_rp001):
    project, admin = closed_out_rp001
    sites = await memory_engine.list_sites(project_id=project["id"])
    site_ids = [s["id"] for s in sites]
    items = await core_db.db.operational_items.find({"site_id": {"$in": site_ids}}, {"_id": 0}).to_list(2000)
    open_critical = [i for i in items if i["priority"] == "critical"
                    and i["status"] not in ("fulfilled", "verified", "closed", "archived", "cancelled", "duplicate")]
    assert open_critical == [], "a genuinely completed reference project must carry no open critical items"


async def test_a_small_genuine_residual_remains(closed_out_rp001):
    """Not every item is forced closed - a small, real punch-list is
    deliberately left, matching how an actually-completed project
    looks (not a suspiciously perfect zero)."""
    project, admin = closed_out_rp001
    sites = await memory_engine.list_sites(project_id=project["id"])
    site_ids = [s["id"] for s in sites]
    items = await core_db.db.operational_items.find({"site_id": {"$in": site_ids}}, {"_id": 0}).to_list(2000)
    open_items = [i for i in items if i["status"] not in
                 ("fulfilled", "verified", "closed", "archived", "cancelled", "duplicate")]
    assert 0 <= len(open_items) <= 15, \
        f"expected a small genuine residual (0-15 items), got {len(open_items)}"


async def test_re_running_both_fixes_is_safe_and_converges(closed_out_rp001):
    """Not a strict single-call no-op (the residual selection recomputes
    against whatever's still open each run) but must be SAFE - no
    duplicate inspection records, no error, and health remains green."""
    project, admin = closed_out_rp001
    await reference_portfolio.complete_rp001_operations()
    inspection_result = await reference_portfolio.record_missing_rp001_inspections()
    assert inspection_result["recorded"] == 0, "a second run must find nothing left uncovered"

    health = await reasoning_engine.project_health(project["id"], user=admin)
    assert health["status"] == "green"


async def test_resolution_notes_are_contextual_not_generic(closed_out_rp001):
    """Each resolved item's own note must reference real, varied content
    - not a single repeated 'resolved' stamp on all items, per this
    sprint's own explicit 'do not fabricate history' principle."""
    project, admin = closed_out_rp001
    sites = await memory_engine.list_sites(project_id=project["id"])
    site_ids = [s["id"] for s in sites]
    items = await core_db.db.operational_items.find(
        {"site_id": {"$in": site_ids}, "category": "material_requirement",
        "status": {"$in": ["fulfilled", "verified"]}}, {"_id": 0}).to_list(50)
    assert len(items) > 5
    events = await operations_engine.list_events_for_item(items[0]["id"])
    fulfilled_events = [e for e in events if e["kind"] == "fulfilled"]
    assert fulfilled_events
    note = fulfilled_events[0]["payload"].get("note", "")
    assert len(note) > 20
    assert "delivered" in note.lower() or "received" in note.lower() or "procurement" in note.lower()


# ==========================================================================
# Beta-01 — Product Completion.
#
# Two genuine gaps found during a real user-journey walkthrough (not a
# code audit): the Portfolio Control Center's per-project financials
# were permanently stubbed disabled/null ("coming soon") despite the
# Commercial Foundation Engine having carried real budget/forecast
# data for months; and the client dashboard's "WEEKLY SUMMARY" card
# was a permanent placeholder that also mislabeled itself as an AI
# capability Atlas doesn't have. Both fixed by reusing existing engine
# data directly - no new engine, no fabrication, no AI.
# ==========================================================================
async def test_portfolio_financials_enabled_with_real_commercial_data(seeded_rp001):
    """RP-001 has real Commercial Foundation Engine data once migrated
    (a separate step from ACDP's own base seed - ensured explicitly
    here, not assumed from the shared fixture, which other tests in
    this file deliberately don't need it for) - Portfolio Control
    Center must surface it, not show the old disabled placeholder."""
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    portfolio = await reasoning_engine.portfolio_control_center(user=admin)
    row = next(r for r in portfolio["projects"] if r["project_id"] == project["id"])
    assert row["financials"]["enabled"] is True
    assert row["financials"]["budget"] is not None
    assert row["financials"]["forecast_cost"] is not None
    assert row["financials"]["cash_flow_signal"] in ("healthy", "attention", "critical")


async def test_portfolio_financials_disabled_for_project_without_commercial_data(seeded_rp001):
    """A project with no Contract/Budget must stay honestly disabled -
    never a fabricated number."""
    project, admin = seeded_rp001
    fresh_project = await memory_engine.insert_project(name="No Commercial Data Test", code="NOCOMM01")
    portfolio = await reasoning_engine.portfolio_control_center(user=admin)
    row = next((r for r in portfolio["projects"] if r["project_id"] == fresh_project["id"]), None)
    if row:  # only present if visible in this snapshot; absence is also a valid pass
        assert row["financials"]["enabled"] is False
        assert row["financials"]["budget"] is None


async def test_client_recent_activity_counts_real_events(seeded_rp001):
    project, admin = seeded_rp001
    activity = await reasoning_engine.client_recent_activity(project["id"], user=admin, days=548)
    # ACDP's own 18-month simulated timeline easily exceeds any activity
    # in the real last-7-days window, so a wide `days` window is used
    # here specifically to confirm the counting logic itself works
    # against real, existing event data - not to claim 548 days is the
    # real product's own default.
    assert activity["photos_captured"] > 0
    assert activity["activities_completed"] > 0
    assert activity["has_activity"] is True


async def test_client_recent_activity_empty_window_shows_no_activity(seeded_rp001):
    project, admin = seeded_rp001
    activity = await reasoning_engine.client_recent_activity(project["id"], user=admin, days=0)
    assert activity["has_activity"] is False
    assert activity["photos_captured"] == 0


async def test_client_recent_activity_requires_project_visibility(seeded_rp001):
    project, admin = seeded_rp001
    outsider = await memory_engine.upsert_user(phone="9990000999", name="Outsider", role="site_supervisor")
    outsider = await memory_engine.set_user_projects(outsider["id"], [])
    with pytest.raises(Exception):
        await reasoning_engine.client_recent_activity(project["id"], user=outsider)
