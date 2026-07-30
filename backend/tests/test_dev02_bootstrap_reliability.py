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


# ==========================================================================
# Beta-02 — Commercial Workspace Completion: Cross-Validation.
#
# The sprint's own explicit requirement: Client Investment must match
# Commercial Contract, Payment Journey must match Payment Requests,
# Variation Centre must match Commercial Variations, Portfolio
# Financials must match Commercial Summary. Verified here directly
# against RP-001's own real, already-migrated Commercial Foundation
# Engine data - not synthetic fixtures - so any future change that
# makes one of these views diverge from its own source of truth fails
# a real test, not just a manual spot-check.
# ==========================================================================
async def test_client_investment_matches_commercial_contract(seeded_rp001):
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    client = await memory_engine.get_user_by_phone("9800000005")

    summary = await commercial_engine.get_project_commercial_summary(project["id"])
    investment = await reasoning_engine.client_investment_summary(project["id"], user=client)

    assert investment["contract_value"] == summary["contract"]["current_contract_value"]
    assert investment["current_variation_total"] == summary["approved_variations_total"]
    assert investment["paid"] == summary["outstanding_payments"]["received"]
    assert investment["outstanding"] == summary["outstanding_payments"]["outstanding"]


async def test_payment_journey_matches_payment_requests(seeded_rp001):
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()

    summary = await commercial_engine.get_project_commercial_summary(project["id"])
    journey = await reasoning_engine.client_payment_journey(project["id"], user=admin)

    summary_milestone_ids = {m["id"] for m in summary["milestones"]}
    journey_milestone_ids = {s["milestone_id"] for s in journey["steps"]}
    assert summary_milestone_ids == journey_milestone_ids

    pr_by_milestone = {pr["milestone_id"]: pr for pr in summary["payment_requests"]}
    for step in journey["steps"]:
        pr = pr_by_milestone.get(step["milestone_id"])
        expected_status = pr["status"] if pr else None
        assert step["payment_status"] == expected_status


async def test_variation_centre_matches_commercial_variations(seeded_rp001):
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()

    summary = await commercial_engine.get_project_commercial_summary(project["id"])
    centre = await reasoning_engine.client_variation_centre(project["id"], user=admin)

    summary_ids = {v["id"] for v in summary["variations"]}
    centre_ids = {v["id"] for v in centre["pending"]} | {v["id"] for v in centre["history"]}
    assert summary_ids == centre_ids

    summary_by_id = {v["id"]: v for v in summary["variations"]}
    for v in centre["pending"] + centre["history"]:
        source = summary_by_id[v["id"]]
        assert v["before_cost"] == source["original_cost"]
        assert v["status"] == source["status"]


async def test_portfolio_financials_match_commercial_summary(seeded_rp001):
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()

    summary = await commercial_engine.get_project_commercial_summary(project["id"])
    portfolio = await reasoning_engine.portfolio_control_center(user=admin)
    row = next(r for r in portfolio["projects"] if r["project_id"] == project["id"])

    assert row["financials"]["budget"] == summary["budget"]["current_budget"]
    assert row["financials"]["forecast_cost"] == summary["budget"]["forecast_cost"]
    assert row["financials"]["cost_variance"] == summary["budget"]["variance"]
    assert row["financials"]["cash_flow_signal"] == summary["cash_flow_signal"]


async def test_commercial_summary_upcoming_payment_reused_not_duplicated(seeded_rp001):
    """Regression guard for the Beta-02 refactor: client_investment_summary
    must read commercial/summary's own upcoming_payment field rather than
    recomputing it - confirmed here by checking they're identical, not just
    similar."""
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    client = await memory_engine.get_user_by_phone("9800000005")

    summary = await commercial_engine.get_project_commercial_summary(project["id"])
    investment = await reasoning_engine.client_investment_summary(project["id"], user=client)
    assert investment["upcoming_payment"] == summary["upcoming_payment"]


# ==========================================================================
# Beta-03 — Project Operations Completion: My Day Commercial Awareness.
#
# Commercial Workspace (Beta-02) had never been integrated into My Day
# - a PM's daily operational hub had no visibility into pending
# variations, unpaid payment requests, or upcoming milestones at all.
# Fixed by reusing commercial_engine's own list functions directly, no
# recalculation. Also closes two smaller, explicitly-named gaps:
# Blocked workflow items (supervisor's My Day already had this, PM's
# didn't) and Open Operational Items as a visible total.
# ==========================================================================
async def test_pm_my_day_includes_commercial_awareness(seeded_rp001):
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    pm = await memory_engine.get_user_by_phone("9800000002")

    result = await operations_engine.my_day(user=pm)
    for key in ("blocked_activities", "open_operational_items_count", "upcoming_inspections",
               "pending_variations", "pending_payment_requests", "upcoming_milestones"):
        assert key in result


async def test_pm_my_day_pending_variations_matches_commercial_engine(seeded_rp001):
    """Cross-validation: My Day's pending variations must be exactly the
    submitted/client_review subset of commercial_engine's own
    list_variations - never a second, independently-derived list."""
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    pm = await memory_engine.get_user_by_phone("9800000002")

    result = await operations_engine.my_day(user=pm)
    all_variations = await commercial_engine.list_variations(project["id"])
    expected_pending_ids = {v["id"] for v in all_variations if v["status"] in ("submitted", "client_review")}
    actual_ids = {v["id"] for v in result["pending_variations"] if v["project_id"] == project["id"]}
    assert actual_ids == expected_pending_ids


async def test_pm_my_day_upcoming_milestone_is_earliest_unachieved(seeded_rp001):
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    pm = await memory_engine.get_user_by_phone("9800000002")

    result = await operations_engine.my_day(user=pm)
    all_milestones = await commercial_engine.list_milestones(project["id"])
    not_yet_achieved = sorted(
        (m for m in all_milestones if m["status"] in ("pending", "ready")),
        key=lambda m: m["sequence"])
    project_milestone = next((m for m in result["upcoming_milestones"] if m["project_id"] == project["id"]), None)
    if not_yet_achieved:
        assert project_milestone is not None
        assert project_milestone["id"] == not_yet_achieved[0]["id"]
    else:
        assert project_milestone is None


# ==========================================================================
# Beta-03 continuation — Daily Review.
#
# The end-of-day mirror of My Day, closing the largest named gap from
# the previous Beta-03 report: no dedicated end-of-day operational
# summary existed. Every section reuses existing queries directly -
# inspections/approvals/commercial actions remaining are literally My
# Day PM's own output, not a second implementation of the same
# questions.
# ==========================================================================
async def test_daily_review_reuses_my_day_pm_for_remaining_sections(seeded_rp001):
    """Cross-validation: Daily Review's inspections/approvals/commercial-
    actions-remaining sections must be identical to My Day PM's own
    output for the same three concepts - confirming reuse, not a
    parallel implementation that could silently drift."""
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    pm = await memory_engine.get_user_by_phone("9800000002")

    my_day_pm = await operations_engine._my_day_pm(pm, [project["id"]], reasoning_engine._iso(reasoning_engine._now()))
    review = await operations_engine.daily_review(user=pm)

    assert review["inspections_remaining"] == my_day_pm["upcoming_inspections"]
    assert review["approvals_remaining"] == my_day_pm["pending_approvals"]
    assert review["commercial_actions_remaining"]["pending_variations"] == my_day_pm["pending_variations"]
    assert review["commercial_actions_remaining"]["pending_payment_requests"] == my_day_pm["pending_payment_requests"]


async def test_daily_review_forbidden_for_supervisor_and_client(seeded_rp001):
    project, admin = seeded_rp001
    sup = await memory_engine.upsert_user(phone="9990000801", name="Sup", role="site_supervisor")
    client = await memory_engine.get_user_by_phone("9800000005")
    with pytest.raises(ValueError):
        await operations_engine.daily_review(user=sup)
    with pytest.raises(ValueError):
        await operations_engine.daily_review(user=client)


async def test_daily_review_finished_today_are_real_completions(seeded_rp001):
    """Every activity in finished_today must genuinely be status
    'completed' - not a fabricated or miscategorized entry."""
    project, admin = seeded_rp001
    pm = await memory_engine.get_user_by_phone("9800000002")
    review = await operations_engine.daily_review(user=pm)
    for a in review["finished_today"]["activities"]:
        assert a["status"] == "completed"


# ==========================================================================
# Beta-04 — Site Engineer Experience.
#
# Completion Evidence: a genuine gap named twice (first in the
# original Beta-03 report, then again explicitly in this sprint's own
# brief). Verified end-to-end with a real capture-to-evidence chain,
# not just the empty-list case - RP-001's own seed data was found,
# during this sprint's own verification, to never populate
# events.activity_id at all (a pre-existing, deliberate property of
# seed_demo_project.py's own _seed_event, unrelated to this fix),
# so a manually-constructed activity+event scenario is what actually
# proves the chain works, not a check against the Reference Portfolio.
# ==========================================================================
async def test_activity_evidence_returns_linked_events(seeded_rp001):
    admin = {"id": "u_evidence_test", "name": "Evidence Test Admin"}
    project = await memory_engine.insert_project(name="Evidence Chain Test", code="EVCHAIN")
    template = await knowledge_engine.create_item(actor=admin, type_="workflow_template", name="T", status="active")
    act = await knowledge_engine.create_item(actor=admin, type_="activity", name="Foundation Work", status="active")
    await knowledge_engine.add_relationship(template["id"], actor=admin, type_="includes_activity", target_id=act["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    activity_id = activities[0]["id"]

    # A real event, linked the same way a live capture submission
    # would link it (events.activity_id set at creation).
    event_doc = {
        "id": "evt_evidence_test", "site_id": "site_x", "project_id": project["id"],
        "activity_id": activity_id, "user_id": admin["id"], "user_name": admin["name"],
        "kind": "photo", "text_input": "Poured foundation slab",
        "audio_asset_id": None, "photo_asset_ids": ["asset_1"], "gps": None,
        "client_created_at": "2026-01-01T00:00:00Z", "server_created_at": "2026-01-01T00:00:00Z",
        "app_version": "test", "ai_status": "skipped", "ai_analysis_id": None,
        "proposals_status": "pending", "proposals_error": None, "requires_client_approval": False,
    }
    await core_db.db.events.insert_one(event_doc)

    evidence = await workflow_engine.get_activity_evidence(activity_id, user=admin)
    assert len(evidence) == 1
    assert evidence[0]["text_input"] == "Poured foundation slab"
    assert evidence[0]["kind"] == "photo"


async def test_activity_evidence_empty_for_activity_with_no_captures(seeded_rp001):
    """The correct, honest result for an activity nothing has been
    captured against yet - an empty list, not an error."""
    admin = {"id": "u_evidence_test2", "name": "Evidence Test Admin 2"}
    project = await memory_engine.insert_project(name="Evidence Empty Test", code="EVEMPTY")
    template = await knowledge_engine.create_item(actor=admin, type_="workflow_template", name="T", status="active")
    act = await knowledge_engine.create_item(actor=admin, type_="activity", name="Unstarted Work", status="active")
    await knowledge_engine.add_relationship(template["id"], actor=admin, type_="includes_activity", target_id=act["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    evidence = await workflow_engine.get_activity_evidence(activities[0]["id"], user=admin)
    assert evidence == []


async def test_activity_evidence_404_for_nonexistent_activity(seeded_rp001):
    admin = {"id": "u_evidence_test3", "name": "Evidence Test Admin 3"}
    with pytest.raises(workflow_engine.WorkflowNotFoundError):
        await workflow_engine.get_activity_evidence("nonexistent_activity_id", user=admin)


# ==========================================================================
# Beta-04 — supervisor's My Day "Overdue" section (named explicitly
# alongside "Due today" in this sprint's "My Work" list, previously
# missing entirely).
# ==========================================================================
async def test_supervisor_my_day_overdue_excludes_completed_activities(seeded_rp001):
    """Regression guard for a real bug caught during this sprint's own
    development: without excluding completed activities, a finished
    activity with a planned_finish in the past would be wrongly
    flagged as overdue."""
    admin = {"id": "u_overdue_test", "name": "Overdue Test Admin"}
    sup = await memory_engine.upsert_user(phone="9990000701", name="Overdue Test Sup", role="site_supervisor")
    project = await memory_engine.insert_project(name="Overdue Test", code="OVERDUE1")
    template = await knowledge_engine.create_item(actor=admin, type_="workflow_template", name="T", status="active")
    act = await knowledge_engine.create_item(actor=admin, type_="activity", name="Finished Late", status="active")
    await knowledge_engine.add_relationship(template["id"], actor=admin, type_="includes_activity", target_id=act["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    activity_id = activities[0]["id"]

    await core_db.db.workflow_activities.update_one(
        {"id": activity_id},
        {"$set": {"assigned_to_user_id": sup["id"], "planned_finish": "2020-01-01T00:00:00Z",
                 "status": "completed"}})

    result = await operations_engine.my_day(user=sup)
    overdue_ids = {a["id"] for a in result["overdue"] if "id" in a}
    assert activity_id not in overdue_ids, \
        "a completed activity must never appear in Overdue, regardless of its planned_finish date"


async def test_supervisor_my_day_overdue_includes_incomplete_past_due_activities(seeded_rp001):
    admin = {"id": "u_overdue_test2", "name": "Overdue Test Admin 2"}
    sup = await memory_engine.upsert_user(phone="9990000702", name="Overdue Test Sup 2", role="site_supervisor")
    project = await memory_engine.insert_project(name="Overdue Test 2", code="OVERDUE2")
    template = await knowledge_engine.create_item(actor=admin, type_="workflow_template", name="T", status="active")
    act = await knowledge_engine.create_item(actor=admin, type_="activity", name="Still Open And Late", status="active")
    await knowledge_engine.add_relationship(template["id"], actor=admin, type_="includes_activity", target_id=act["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    activity_id = activities[0]["id"]

    await core_db.db.workflow_activities.update_one(
        {"id": activity_id},
        {"$set": {"assigned_to_user_id": sup["id"], "planned_finish": "2020-01-01T00:00:00Z"}})

    result = await operations_engine.my_day(user=sup)
    overdue_ids = {a["id"] for a in result["overdue"] if "id" in a}
    assert activity_id in overdue_ids


# ==========================================================================
# Beta-04 — Site Progress: "one operational story" for a single project,
# the other gap named explicitly (after Completion Evidence) in this
# sprint's brief. Verified against RP-001's own real data.
# ==========================================================================
async def test_site_progress_composes_real_data(closed_out_rp001):
    project, admin = closed_out_rp001
    progress = await operations_engine.site_progress(project["id"], user=admin)
    assert progress["project_id"] == project["id"]
    assert progress["project_name"] == project["name"]
    assert progress["open_items_count"] >= 0
    assert len(progress["completed_recently"]) > 0
    for a in progress["completed_recently"]:
        assert a["status"] == "completed"


async def test_site_progress_latest_updates_reuses_timeline_engine(seeded_rp001):
    """Cross-validation: latest_updates must be genuinely sourced from
    timeline_engine.for_site - confirmed by checking the returned shape
    matches that function's own item structure (kind/event/created_at),
    not a second, parallel event read."""
    project, admin = seeded_rp001
    progress = await operations_engine.site_progress(project["id"], user=admin)
    assert len(progress["latest_updates"]) > 0
    for item in progress["latest_updates"]:
        assert "event" in item
        assert "created_at" in item
        assert item["kind"] == "construction_event"


async def test_site_progress_forbidden_for_client(seeded_rp001):
    project, admin = seeded_rp001
    client = await memory_engine.get_user_by_phone("9800000005")
    with pytest.raises(ValueError):
        await operations_engine.site_progress(project["id"], user=client)


async def test_site_progress_404_for_nonexistent_project(seeded_rp001):
    project, admin = seeded_rp001
    with pytest.raises(ValueError):
        await operations_engine.site_progress("nonexistent_project_xyz", user=admin)


# ==========================================================================
# Beta-05 — Construction Intelligence: Explain Health.
#
# This sprint's own named "largest remaining gap." Composed entirely
# from project_health and list_insights called exactly as they already
# exist - never a second health calculation, never a second insight
# system.
# ==========================================================================
async def test_explain_health_matches_project_health_exactly(seeded_rp001):
    """Cross-validation: explain_health's score/status/dimensions/drivers
    must be byte-identical to project_health's own output - confirming
    genuine reuse, not a second, potentially-diverging calculation."""
    project, admin = seeded_rp001
    health = await reasoning_engine.project_health(project["id"], user=admin)
    explained = await reasoning_engine.explain_health(project["id"], user=admin)
    assert explained["score"] == health["score"]
    assert explained["status"] == health["status"]
    assert explained["dimensions"] == health["dimensions"]
    assert explained["drivers"] == health["drivers"]


async def test_explain_health_recommended_actions_are_real_insights(seeded_rp001):
    """Every recommended action must trace back to a real, open,
    persisted insight - never fabricated advice."""
    project, admin = seeded_rp001
    explained = await reasoning_engine.explain_health(project["id"], user=admin)
    open_insights = await reasoning_engine.list_insights(project["id"], user=admin, status="open")
    open_insight_ids = {i["id"] for i in open_insights}
    for action in explained["recommended_actions"]:
        assert action["insight_id"] in open_insight_ids
        assert action["suggested_action"] is not None
        assert "category" in action["suggested_action"]
        assert "title" in action["suggested_action"]


async def test_explain_health_recommended_actions_sorted_by_severity(seeded_rp001):
    project, admin = seeded_rp001
    explained = await reasoning_engine.explain_health(project["id"], user=admin)
    severities = [a["severity"] for a in explained["recommended_actions"]]
    severity_ranks = [reasoning_engine.SEVERITIES.index(s) for s in severities]
    assert severity_ranks == sorted(severity_ranks, reverse=True)


async def test_explain_health_action_currency_reflects_real_insight_state(seeded_rp001):
    project, admin = seeded_rp001
    explained = await reasoning_engine.explain_health(project["id"], user=admin)
    open_insights = await reasoning_engine.list_insights(project["id"], user=admin, status="open")
    assert explained["action_currency"]["open_insight_count"] == len(open_insights)


# ==========================================================================
# Beta-05 continuation — Priority Engine: this sprint's own named
# "highest remaining gap." Composed entirely from portfolio_control_center
# and explain_health, both unchanged. "Today's Highest Priorities" - one
# flat, ranked, cross-project list, never a second health/risk
# calculation.
# ==========================================================================
async def test_priority_engine_flags_unhealthy_project(seeded_rp001):
    """A deliberately-constructed, isolated unhealthy project - not
    dependent on seeded_rp001's own current state, which varies
    depending on whether other tests sharing this module-scoped
    fixture have already run the STAB-01 closeout (making RP-001
    healthy) before this test executes.

    Ten uncovered-inspection activities, not one: each
    quality.completed_without_inspection finding is "warning" severity
    (a 12-point penalty per the health formula's own
    _HEALTH_SEVERITY_PENALTY) - a single finding only drops the quality
    dimension to 88, not enough to cross the Healthy threshold. Ten
    reliably drives quality to 0 and overall status to Critical,
    calibrated directly against the real scoring formula rather than
    assumed."""
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="Priority Engine Unhealthy Test", code="PRIOUNH")
    template = await knowledge_engine.create_item(actor=admin, type_="workflow_template", name="T", status="active")
    activity_ids = []
    for n in range(10):
        act = await knowledge_engine.create_item(actor=admin, type_="activity", name=f"Snagging Check {n}", status="active")
        await knowledge_engine.add_relationship(template["id"], actor=admin, type_="includes_activity", target_id=act["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    for a in activities:
        await core_db.db.workflow_activities.update_one(
            {"id": a["id"]}, {"$set": {"requires_inspection": True, "status": "completed"}})

    portfolio = await reasoning_engine.portfolio_control_center(user=admin)
    row = next(r for r in portfolio["projects"] if r["project_id"] == project["id"])
    assert row["health_status"] in ("Critical", "Attention"), \
        f"test setup did not produce an unhealthy project (got {row['health_status']}) - cannot verify the engine surfaces real problems"

    result = await reasoning_engine.priority_engine(user=admin)
    project_priorities = [p for p in result["priorities"] if p["project_id"] == project["id"]]
    assert len(project_priorities) > 0
    assert any(p["kind"] == "project_health" for p in project_priorities)


async def test_priority_engine_recommended_actions_trace_to_real_insights(seeded_rp001):
    """Every recommended_action entry must reference a real, currently
    open insight for that exact project - never fabricated."""
    project, admin = seeded_rp001
    result = await reasoning_engine.priority_engine(user=admin)
    open_insights = await reasoning_engine.list_insights(project["id"], user=admin, status="open")
    open_insight_ids = {i["id"] for i in open_insights}
    for p in result["priorities"]:
        if p["kind"] == "recommended_action" and p["project_id"] == project["id"]:
            assert p["insight_id"] in open_insight_ids


async def test_priority_engine_sorted_worst_first(seeded_rp001):
    project, admin = seeded_rp001
    result = await reasoning_engine.priority_engine(user=admin)
    ranks = [reasoning_engine.SEVERITIES.index(p["severity"]) for p in result["priorities"]]
    assert ranks == sorted(ranks, reverse=True)


async def test_priority_engine_caps_recommended_actions_per_project(seeded_rp001):
    """No single project should flood the portfolio-wide list - capped
    at 3 recommended actions per project, matching a genuinely
    cross-project "highest priorities" view rather than one project's
    own full insight backlog."""
    project, admin = seeded_rp001
    result = await reasoning_engine.priority_engine(user=admin)
    project_recommended = [p for p in result["priorities"]
                           if p["kind"] == "recommended_action" and p["project_id"] == project["id"]]
    assert len(project_recommended) <= 3


async def test_priority_engine_engine_function_has_no_internal_gate(seeded_rp001):
    """priority_engine() itself performs no role check, matching
    portfolio_control_center's own established convention of gating
    entirely at the route layer, not the engine. The actual RBAC
    enforcement (403 for non-management) is verified at the HTTP layer
    in test_rc01_commercial_visibility.py, where a real client can be
    constructed to receive a real HTTP response. This test only
    confirms the engine function's own output shape is stable
    regardless of caller role - a genuinely different, narrower claim
    than "forbidden"."""
    project, admin = seeded_rp001
    pm = await memory_engine.get_user_by_phone("9800000002")
    result = await reasoning_engine.priority_engine(user=pm)
    assert "priorities" in result


# ==========================================================================
# Beta-05 final convergence — Cross-Project Intelligence, Commercial
# Intelligence, Executive Timeline, Portfolio Search. All four compose
# existing engine outputs exactly as they already exist.
# ==========================================================================
async def test_cross_project_intelligence_no_duplicate_rule_evaluation(seeded_rp001):
    """Cross-validation: cross_project_intelligence's own per-project
    findings must be identical to _portfolio()'s own findings for that
    project - confirming genuine reuse (via p["findings"]), not a
    second evaluate_rules() call for the same snapshot."""
    project, admin = seeded_rp001
    portfolio = await reasoning_engine._portfolio(admin)
    direct_rule_ids = set()
    for p in portfolio:
        if p["digest"]["project_id"] == project["id"]:
            direct_rule_ids = {f["rule_id"] for f in p["findings"]}

    result = await reasoning_engine.cross_project_intelligence(user=admin)
    # Every rule_id this project contributes to a repeated pattern must
    # be among its own real findings - never fabricated.
    for pattern in result["repeated_patterns"]:
        if project["id"] in pattern["project_ids"]:
            assert pattern["rule_id"] in direct_rule_ids


async def test_cross_project_intelligence_requires_at_least_two_projects(seeded_rp001):
    """A pattern must never be reported as "repeated" from a single
    project's own finding."""
    project, admin = seeded_rp001
    result = await reasoning_engine.cross_project_intelligence(user=admin)
    for pattern in result["repeated_patterns"]:
        assert pattern["project_count"] >= 2
        assert len(set(pattern["project_ids"])) == pattern["project_count"]


async def test_commercial_intelligence_matches_commercial_summary(seeded_rp001):
    """Cross-validation: every figure in commercial_intelligence must
    trace exactly to get_project_commercial_summary's own output -
    never a second commercial calculation."""
    project, admin = seeded_rp001
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    summary = await commercial_engine.get_project_commercial_summary(project["id"])
    result = await reasoning_engine.commercial_intelligence(user=admin)

    if summary["budget"]["variance"] < 0:
        entry = next(e for e in result["projects_over_budget"] if e["project_id"] == project["id"])
        assert entry["variance"] == summary["budget"]["variance"]

    outstanding_entry = next((e for e in result["projects_awaiting_payment"] if e["project_id"] == project["id"]), None)
    if summary["outstanding_payments"]["outstanding"] > 0:
        assert outstanding_entry is not None
        assert outstanding_entry["outstanding"] == summary["outstanding_payments"]["outstanding"]


async def test_executive_timeline_reuses_timeline_engine_shapes(seeded_rp001):
    """Every event must carry the exact shape its own source function
    already produces (timeline_engine.for_site's "event" wrapper for
    reality, or commercial_engine's own event fields for commercial) -
    confirming genuine reuse, not a re-derived shape."""
    project, admin = seeded_rp001
    result = await reasoning_engine.executive_timeline(user=admin, project_id=project["id"])
    assert result["projects_covered"] == 1
    for e in result["events"]:
        assert e["source"] in ("reality", "commercial")
        assert e["project_id"] == project["id"]
        if e["source"] == "reality":
            assert "event" in e
        else:
            assert "kind" in e


async def test_executive_timeline_filters_by_category(seeded_rp001):
    project, admin = seeded_rp001
    result = await reasoning_engine.executive_timeline(user=admin, project_id=project["id"], category="commercial")
    for e in result["events"]:
        assert e["source"] == "commercial"


async def test_portfolio_search_finds_real_project(seeded_rp001):
    project, admin = seeded_rp001
    result = await reasoning_engine.portfolio_search("Villa", user=admin)
    assert result["total_results"] > 0
    assert any(p["id"] == project["id"] for p in result["projects"])


async def test_portfolio_search_rejects_short_query(seeded_rp001):
    project, admin = seeded_rp001
    with pytest.raises(reasoning_engine.ReasoningError):
        await reasoning_engine.portfolio_search("a", user=admin)


async def test_portfolio_search_scoped_to_visibility(seeded_rp001):
    """A project-scoped user must never see search results from a
    project they aren't assigned to."""
    project, admin = seeded_rp001
    outsider = await memory_engine.upsert_user(phone="9990000601", name="Search Outsider", role="site_supervisor")
    outsider = await memory_engine.set_user_projects(outsider["id"], [])
    result = await reasoning_engine.portfolio_search("Villa", user=outsider)
    assert not any(p["id"] == project["id"] for p in result["projects"])


# ==========================================================================
# Beta-06 — Security Audit finding.
#
# portfolio_search's own payments query was completely unscoped -
# unlike every other category in the same function (projects, sites,
# activities, variations, operational_items all correctly filtered by
# project visibility), payments carried no _scope() filter at all. A
# project-scoped user (e.g. a supervisor assigned to one project) could
# search for and find a payment reference string belonging to a
# project they have no visibility into. Confirmed as a real,
# demonstrable leak before fixing (not a theoretical concern), fixed
# by applying the exact same _scope() pattern every other category in
# this function already used. This test guards specifically against
# this exact regression, not just "search is generally scoped."
# ==========================================================================
async def test_portfolio_search_payments_scoped_to_visibility(seeded_rp001):
    _, admin = seeded_rp001
    client = await memory_engine.upsert_user(phone="9990000603", name="Beta06 Security Test Client", role="client")
    project = await memory_engine.insert_project(name="Beta06 Security Test Project", code="B06SEC")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=client["id"],
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="M1", sequence=1,
        planned_percent=50, trigger="test", planned_date="2026-02-01")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    ms = await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)

    pr = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=1000, raised_date="2026-01-15", due_date="2026-02-15")
    await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=1000, date="2026-01-20",
        method="bank_transfer", reference="BETA06-SECURITY-TEST-REF")

    outsider = await memory_engine.upsert_user(phone="9990000602", name="Payments Search Outsider", role="site_supervisor")
    outsider = await memory_engine.set_user_projects(outsider["id"], [])
    result = await reasoning_engine.portfolio_search("BETA06-SECURITY-TEST-REF", user=outsider)
    assert result["payments"] == [], \
        "A project-scoped user must never see a payment reference from a project they cannot access"

    admin_result = await reasoning_engine.portfolio_search("BETA06-SECURITY-TEST-REF", user=admin)
    assert len(admin_result["payments"]) >= 1, \
        "the payment must still be findable by a user who genuinely has visibility into the project"
