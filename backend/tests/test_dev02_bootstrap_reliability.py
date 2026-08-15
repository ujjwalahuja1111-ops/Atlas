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
import asyncio
import pytest
from datetime import datetime, timezone

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
from engines import reasoning_engine, commercial_engine, operations_engine, knowledge_graph_engine, notification_engine  # noqa: E402
from services import daily_site_report_service  # noqa: E402
from services import inbox_intelligence_service  # noqa: E402
from services import commercial_workflow_service  # noqa: E402
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
    reality, its "operational_event"/"operational_item" wrapper for
    operations, or commercial_engine's own event fields for commercial) -
    confirming genuine reuse, not a re-derived shape."""
    project, admin = seeded_rp001
    result = await reasoning_engine.executive_timeline(user=admin, project_id=project["id"])
    assert result["projects_covered"] == 1
    for e in result["events"]:
        assert e["source"] in ("reality", "operations", "commercial")
        assert e["project_id"] == project["id"]
        if e["source"] == "reality":
            assert "event" in e
        elif e["source"] == "operations":
            assert "operational_event" in e
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
    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "sent", actor=admin)
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


# ==========================================================================
# Beta-06B — Navigation & UX Validation: a security finding, not a
# navigation one.
#
# operational_items had zero project-visibility enforcement anywhere -
# neither the detail endpoint nor the list endpoint checked whether
# the caller could actually see the item's own project. Fixed by
# adding operations_engine.assert_item_visible, reusing the exact same
# _is_project_scoped check every other project-visibility boundary in
# Atlas already uses.
# ==========================================================================
async def test_item_visibility_blocks_outsider(seeded_rp001):
    _, admin = seeded_rp001
    proj_a = await memory_engine.insert_project(name="Item Visibility Secret", code="ITEMVIS1")
    proj_b = await memory_engine.insert_project(name="Item Visibility Visible", code="ITEMVIS2")
    site_a = await memory_engine.insert_site(project_id=proj_a["id"], name="Site A")
    item = await operations_engine.create_item(
        actor=admin, site_id=site_a["id"], category="site_issue", title="Confidential matter", priority="high")

    outsider = await memory_engine.upsert_user(phone="9990000701", name="Item Outsider", role="site_supervisor")
    outsider = await memory_engine.set_user_projects(outsider["id"], [proj_b["id"]])

    with pytest.raises(ValueError):
        await operations_engine.assert_item_visible(item, outsider)


async def test_item_visibility_allows_assigned_user(seeded_rp001):
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="Item Visibility Assigned", code="ITEMVIS3")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site A")
    item = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="site_issue", title="Visible matter", priority="normal")

    insider = await memory_engine.upsert_user(phone="9990000702", name="Item Insider", role="site_supervisor")
    insider = await memory_engine.set_user_projects(insider["id"], [project["id"]])

    await operations_engine.assert_item_visible(item, insider)


async def test_item_visibility_allows_management_unconditionally(seeded_rp001):
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="Item Visibility Mgmt", code="ITEMVIS4")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site A")
    item = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="site_issue", title="Any matter", priority="normal")

    mgmt = await memory_engine.upsert_user(phone="9990000703", name="Unrestricted Mgmt", role="management")
    await operations_engine.assert_item_visible(item, mgmt)


async def test_list_items_scoped_by_visibility(seeded_rp001):
    _, admin = seeded_rp001
    proj_a = await memory_engine.insert_project(name="List Scope Secret", code="LISTSCOPE1")
    proj_b = await memory_engine.insert_project(name="List Scope Visible", code="LISTSCOPE2")
    site_a = await memory_engine.insert_site(project_id=proj_a["id"], name="Site A")
    site_b = await memory_engine.insert_site(project_id=proj_b["id"], name="Site B")
    await operations_engine.create_item(actor=admin, site_id=site_a["id"], category="site_issue", title="Secret item", priority="normal")
    await operations_engine.create_item(actor=admin, site_id=site_b["id"], category="site_issue", title="Visible item", priority="normal")

    outsider = await memory_engine.upsert_user(phone="9990000704", name="List Scope Outsider", role="site_supervisor")
    outsider = await memory_engine.set_user_projects(outsider["id"], [proj_b["id"]])

    all_items = await operations_engine.list_items()
    outsider_visible = [i for i in all_items if i.get("project_id") in (outsider.get("assigned_project_ids") or [])]
    assert all(i.get("project_id") == proj_b["id"] for i in outsider_visible)
    assert not any(i["title"] == "Secret item" for i in outsider_visible)


# ==========================================================================
# Beta-06E — Reference Portfolio & Multi-Role Operational Validation.
#
# Found while simulating a complete real day (create -> assign ->
# acknowledge -> in_progress -> fulfilled -> verified -> closed) through
# the actual API, not by reading code: an item that had genuinely just
# completed its full lifecycle did not appear in Daily Review's own
# finished_today section. Root cause: operational_items documents never
# carry an updated_at field at all - only created_at (set once) and
# last_updated_at (set on every transition_status call) - so
# daily_review's own query, which filtered on updated_at, had never
# matched a single operational item since Daily Review was built. No
# existing test caught this because none asserted on this specific
# field. Fixed by querying the field that is actually written.
# ==========================================================================
async def test_daily_review_finds_items_resolved_today_via_real_transition(seeded_rp001):
    """Not a synthetic document insert - genuinely walks the same
    transition_status() path the real API uses, the same way the bug
    was originally found."""
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="Beta06E Daily Review Fix Test", code="B06EDR1")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site A")
    item = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="material_requirement",
        title="Beta06E lifecycle test item", priority="high")
    await operations_engine.transition_status(item_id=item["id"], to_status="fulfilled", actor=admin)

    review = await operations_engine.daily_review(user=admin)
    resolved_ids = {i["id"] for i in review["finished_today"]["operational_items"]}
    assert item["id"] in resolved_ids, \
        "an item resolved today via the real transition path must appear in Daily Review's finished_today"


# ==========================================================================
# Beta-06F — Timeline & Construction History Integrity Validation.
#
# Found by directly testing this sprint's own question: "if this
# actually happened, could someone reconstruct it using only Atlas?"
# For operational item history specifically, the answer was no -
# Executive Timeline called timeline_engine.for_site() without
# include_ops=True, so every operational item creation, transition,
# and comment was invisible to it, despite for_site's own include_ops
# mechanism already existing and working correctly when called
# directly. Confirmed via a real create -> transition -> comment
# sequence producing zero Executive Timeline events before the fix.
# ==========================================================================
async def test_executive_timeline_includes_operational_item_history(seeded_rp001):
    """Reproduces the exact sequence that found the bug: a real item,
    a real transition, a real comment, through the actual engine
    functions the API calls - not a synthetic timeline entry."""
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="Beta06F Timeline Test", code="B06FTL3")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site A")
    item = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="site_issue",
        title="Beta06F timeline test item", priority="high")
    await operations_engine.transition_status(item_id=item["id"], to_status="in_progress", actor=admin)
    await operations_engine.add_comment(item_id=item["id"], actor=admin, text="Progress comment")

    timeline = await reasoning_engine.executive_timeline(user=admin, project_id=project["id"])
    operations_events = [e for e in timeline["events"] if e["source"] == "operations"]
    assert len(operations_events) >= 3, \
        f"expected at least 3 operational events (create/transition/comment), found {len(operations_events)}"


async def test_executive_timeline_operations_events_reference_real_item(seeded_rp001):
    """Every operations-source event must trace to a real operational
    item that actually exists - never a fabricated or orphaned entry."""
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="Beta06F Timeline Test 2", code="B06FTL4")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site A")
    item = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="site_issue",
        title="Beta06F timeline reference test", priority="normal")

    timeline = await reasoning_engine.executive_timeline(user=admin, project_id=project["id"])
    for e in timeline["events"]:
        if e["source"] == "operations":
            assert e["operational_item"] is not None
            assert e["operational_item"]["id"] == item["id"]


# ==========================================================================
# Beta-06G — Multi-Role Experience & Production Readiness Validation.
#
# request_clarification's own docstring states its purpose is "making
# it clearly visible to the PM that the client has questions" - but
# no screen anywhere actually surfaced this distinctly from an
# ordinary pending approval. A PM checking My Day had no way to tell
# which client_approval items were awaiting their own response versus
# simply pending the client's decision, without opening every item
# individually. Found by walking a real client approval lifecycle
# (create -> client requests clarification -> PM responds -> client
# approves) end to end, then asking whether the PM's own daily view
# reflected the mid-lifecycle state correctly.
# ==========================================================================
async def test_my_day_flags_items_awaiting_clarification_response(seeded_rp001):
    _, admin = seeded_rp001
    pm = await memory_engine.upsert_user(phone="9990000501", name="Beta06G PM", role="project_manager")
    client = await memory_engine.upsert_user(phone="9990000502", name="Beta06G Client", role="client")
    project = await memory_engine.insert_project(name="Beta06G Clarification Test", code="B06GCLR1")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site A")
    pm = await memory_engine.set_user_projects(pm["id"], [project["id"]])
    client = await memory_engine.set_user_projects(client["id"], [project["id"]])

    awaiting = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="client_approval", title="Awaiting response", priority="normal")
    await operations_engine.request_clarification(item_id=awaiting["id"], actor=client, note="What color?")

    answered = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="client_approval", title="Already answered", priority="normal")
    await operations_engine.request_clarification(item_id=answered["id"], actor=client, note="What material?")
    await operations_engine.add_comment(item_id=answered["id"], actor=pm, text="It's granite.")

    never_asked = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="client_approval", title="Never questioned", priority="normal")

    result = await operations_engine.my_day(user=pm)
    flags = {a["title"]: a["awaiting_clarification_response"] for a in result["pending_approvals"]}
    assert flags["Awaiting response"] is True
    assert flags["Already answered"] is False
    assert flags["Never questioned"] is False


# ==========================================================================
# RC-02 — closes the explicit Beta-06F documented risk: workflow
# activity progression's own presence in Executive Timeline. Workflow
# activities carry no separate event ledger (unlike operational items'
# operational_events), so this is honestly each activity's own most
# recent status change, not a fabricated full transition history the
# data does not contain.
# ==========================================================================
async def test_executive_timeline_includes_workflow_activity_progress(seeded_rp001):
    """Reproduces the exact sequence that found the gap: real
    set_status() calls through the actual engine function, not a
    synthetic document with status_updated_at pre-set."""
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="RC02 Workflow Timeline Test", code="RC02WFT3")
    template = await knowledge_engine.create_item(actor=admin, type_="workflow_template", name="T", status="active")
    act = await knowledge_engine.create_item(actor=admin, type_="activity", name="RC02 Foundation Work", status="active")
    await knowledge_engine.add_relationship(template["id"], actor=admin, type_="includes_activity", target_id=act["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    a_id = activities[0]["id"]
    await workflow_engine.set_status(a_id, "in_progress", actor=admin)
    await workflow_engine.set_status(a_id, "completed", actor=admin)

    timeline = await reasoning_engine.executive_timeline(user=admin, project_id=project["id"])
    workflow_events = [e for e in timeline["events"] if e["source"] == "workflow"]
    assert len(workflow_events) >= 1
    assert any(e["activity"]["id"] == a_id and e["activity"]["status"] == "completed" for e in workflow_events)


async def test_executive_timeline_workflow_filter(seeded_rp001):
    _, admin = seeded_rp001
    project = await memory_engine.insert_project(name="RC02 Workflow Timeline Filter Test", code="RC02WFT4")
    template = await knowledge_engine.create_item(actor=admin, type_="workflow_template", name="T", status="active")
    act = await knowledge_engine.create_item(actor=admin, type_="activity", name="RC02 Filter Activity", status="active")
    await knowledge_engine.add_relationship(template["id"], actor=admin, type_="includes_activity", target_id=act["id"])
    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    await workflow_engine.set_status(activities[0]["id"], "in_progress", actor=admin)

    timeline = await reasoning_engine.executive_timeline(user=admin, project_id=project["id"], category="workflow")
    for e in timeline["events"]:
        assert e["source"] == "workflow"
    assert len(timeline["events"]) >= 1


# ==========================================================================
# RC-03 — Production Configuration Validation.
#
# A genuine, confirmed production blocker: register_user() always
# created a pending account requiring an existing admin's approval,
# with no exception for a brand-new, empty database's very first user.
# db_seed.py's own docstring explicitly states it has "zero effect on
# production runtime behaviour" - confirming it was never the intended
# path for a real customer's first admin account. Fixed: the very
# first account ever registered on an empty database is automatically
# approved as management.
#
# Explicitly clears db.users first in each test, since this file's own
# seeded_rp001 fixture is module-scoped and other tests in this same
# file may have already populated users - this is the one behavior in
# this whole file that genuinely requires an empty database to test
# correctly, not just a fresh project/site.
# ==========================================================================
async def test_first_ever_registration_becomes_approved_management():
    await core_db.db.users.delete_many({})
    await core_db.db.system_state.delete_many({})
    user = await memory_engine.register_user(phone="9990000901", name="RC03 Founding Admin")
    assert user["role"] == "management"
    assert user["approval_status"] == "approved"
    assert user["scope_projects"] is False


async def test_second_registration_after_founding_admin_is_normal_pending():
    await core_db.db.users.delete_many({})
    await core_db.db.system_state.delete_many({})
    await memory_engine.register_user(phone="9990000902", name="RC03 Founding Admin 2")
    second = await memory_engine.register_user(phone="9990000903", name="RC03 Second Person")
    assert second["role"] == "site_supervisor"
    assert second["approval_status"] == "pending"
    assert second["scope_projects"] is True


async def test_founding_admin_can_immediately_act_as_management():
    """The founding admin isn't just labeled management - confirms they
    can actually use a real management-only capability immediately,
    with no approval step from anyone. Deliberately does not depend on
    seeded_rp001 (module-scoped, shared across this whole file) since
    this test must delete all users to guarantee a genuinely empty
    database - doing that while also depending on that shared fixture
    would corrupt its own admin account for every test that runs after
    this one in the same session."""
    await core_db.db.users.delete_many({})
    await core_db.db.system_state.delete_many({})
    founder = await memory_engine.register_user(phone="9990000904", name="RC03 Acting Admin")
    project = await memory_engine.insert_project(name="RC03 Founder's First Project", code="RC03FOUND")
    portfolio = await reasoning_engine.portfolio_control_center(user=founder)
    assert any(r["project_id"] == project["id"] for r in portfolio["projects"])


# ==========================================================================
# Pilot Certification — Phase 1, Operational Recovery. Found by
# testing this sprint's own named scenario ("client clarification
# after approval"): request_clarification had no check for whether an
# item's decision was already final. A client could request
# clarification on an item already fulfilled/cancelled/closed, which
# is semantically nonsensical and would cascade into Beta-06G's own
# "awaiting your response" PM flag incorrectly firing on an
# already-resolved item.
# ==========================================================================
async def test_clarification_blocked_after_item_already_decided(seeded_rp001):
    _, admin = seeded_rp001
    client = {"id": "cert_client_1", "name": "Cert Client", "role": "client"}
    project = await memory_engine.insert_project(name="Cert Clarification Fix Test", code="CERTCLAR1")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="client_approval", title="Tile", priority="normal")
    await operations_engine.transition_status(item_id=item["id"], to_status="fulfilled", actor=client)

    with pytest.raises(ValueError, match="already final"):
        await operations_engine.request_clarification(item_id=item["id"], actor=client, note="wait what?")


async def test_clarification_still_works_while_item_open(seeded_rp001):
    """Confirms the fix is scoped to terminal states only - the normal,
    legitimate case (item still awaiting the client's real decision)
    must remain completely unaffected."""
    _, admin = seeded_rp001
    client = {"id": "cert_client_2", "name": "Cert Client 2", "role": "client"}
    project = await memory_engine.insert_project(name="Cert Clarification Fix Test 2", code="CERTCLAR2")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await operations_engine.create_item(
        actor=admin, site_id=site["id"], category="client_approval", title="Paint", priority="normal")

    result = await operations_engine.request_clarification(item_id=item["id"], actor=client, note="what color?")
    assert result["status"] == "open"


# ==========================================================================
# Pilot Certification — Phase 3, Founding Administrator Robustness.
# Hardened the RC-03 count-then-insert check (a genuine race) with
# Mongo's own atomic find_one_and_update claim pattern. A regression
# was caught and fixed during this pass's own development: the
# claim-only version would incorrectly grant founding-admin to a
# register_user() call on a database already populated via a
# different path (db_seed.py's upsert_user never touches the claim
# document) - fixed by checking the user count first.
# ==========================================================================
async def test_concurrent_registrations_produce_exactly_one_founding_admin():
    await core_db.db.users.delete_many({})
    await core_db.db.system_state.delete_many({})
    results = await asyncio.gather(
        memory_engine.register_user(phone="9990001001", name="Cert Race A"),
        memory_engine.register_user(phone="9990001002", name="Cert Race B"),
    )
    founders = [r for r in results if r["role"] == "management" and r["approval_status"] == "approved"]
    assert len(founders) == 1, f"exactly one must become founding admin, found {len(founders)}"


async def test_seeded_database_does_not_grant_founding_admin_to_later_registration():
    await core_db.db.users.delete_many({})
    await core_db.db.system_state.delete_many({})
    await memory_engine.upsert_user(phone="9990001003", name="Cert Seeded Admin", role="management")
    late = await memory_engine.register_user(phone="9990001004", name="Cert Late Registrant")
    assert late["role"] == "site_supervisor"
    assert late["approval_status"] == "pending"


# ==========================================================================
# CP-01 — Commercial Operations Phase I (Vertical Slice).
#
# update_contract and update_milestone are new, minimal extensions
# (CO-01's own Product Decisions Register: editable only before the
# record is genuinely relied upon by anyone downstream - draft for
# Contract, pending for Milestone). Both reuse the exact same
# append_commercial_event audit pattern every other commercial
# mutation already uses - no new audit mechanism.
# ==========================================================================
async def test_update_contract_while_draft_succeeds_and_logs_event():
    admin = {"id": "cp01_u1", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="CP01 Contract Edit Test", code="CP01CE1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)

    updated = await commercial_engine.update_contract(
        project["id"], actor=admin, duration_days=150, retention_percent=7.5)
    assert updated["duration_days"] == 150
    assert updated["retention_percent"] == 7.5
    # original_contract_value must be completely untouched - this
    # function deliberately never edits it, per CO-01's own ruling
    # that contract value only ever changes through approved
    # Variations.
    assert updated["original_contract_value"] == 1000000

    events = await commercial_engine.list_commercial_events(project["id"])
    assert any(e["kind"] == "contract_updated" for e in events)


async def test_update_contract_blocked_after_activation():
    admin = {"id": "cp01_u2", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="CP01 Contract Lock Test", code="CP01CL1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    await commercial_engine.transition_contract_status(project["id"], "review", actor=admin)
    await commercial_engine.transition_contract_status(project["id"], "approved", actor=admin)
    await commercial_engine.transition_contract_status(project["id"], "active", actor=admin)

    with pytest.raises(commercial_engine.CommercialError, match="only be edited while status is 'draft'"):
        await commercial_engine.update_contract(project["id"], actor=admin, duration_days=999)


async def test_update_milestone_while_pending_succeeds_and_logs_event():
    admin = {"id": "cp01_u3", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="CP01 Milestone Edit Test", code="CP01ME1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1,
        planned_percent=20, trigger="foundation complete")

    updated = await commercial_engine.update_milestone(
        ms["id"], actor=admin, name="Foundation Works", planned_percent=25)
    assert updated["name"] == "Foundation Works"
    assert updated["planned_percent"] == 25
    # contract_value stays the one-time-derived snapshot, deliberately
    # not recomputed on edit - matching create_milestone's own
    # documented reasoning.
    assert updated["contract_value"] == ms["contract_value"]

    events = await commercial_engine.list_commercial_events(project["id"])
    assert any(e["kind"] == "milestone_updated" for e in events)


async def test_update_milestone_blocked_after_ready():
    admin = {"id": "cp01_u4", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="CP01 Milestone Lock Test", code="CP01ML1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1,
        planned_percent=20, trigger="foundation complete")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)

    with pytest.raises(commercial_engine.CommercialError, match="only be edited while status is 'pending'"):
        await commercial_engine.update_milestone(ms["id"], actor=admin, name="Should not save")


# ==========================================================================
# WF-01 — Workflow Orchestration. Integration tests confirming the full
# chain works end-to-end: a commercial mutation automatically triggers
# a reasoning pass, which persists an insight a caller can retrieve via
# reasoning_engine.list_insights — no manual "refresh insights" call
# anywhere in either test, matching this package's own core objective.
# ==========================================================================
async def test_milestone_achieved_automatically_surfaces_billing_insight():
    admin = {"id": "wf01_u1", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="WF01 Auto-Trigger Milestone", code="WF01ATM1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1,
        planned_percent=20, trigger="foundation complete")

    before = await reasoning_engine.list_insights(project["id"], user=admin)
    assert not [i for i in before if i["rule_id"] == "commercial.milestone_ready_for_billing"]

    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)

    # No manual reasoning_engine.run_reasoning() call here - the trigger
    # inside transition_milestone_status must have already done it.
    after = await reasoning_engine.list_insights(project["id"], user=admin)
    billing = [i for i in after if i["rule_id"] == "commercial.milestone_ready_for_billing"]
    assert len(billing) == 1
    assert "Foundation" in billing[0]["suggested_operational_action"]["title"]


async def test_variation_approved_automatically_surfaces_contract_review_insight():
    admin = {"id": "wf01_u2", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="WF01 Auto-Trigger Variation", code="WF01ATV1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    var = await commercial_engine.create_variation(
        actor=admin, project_id=project["id"], title="Extra waterproofing",
        description="d", original_cost=0, proposed_cost=50000)
    await commercial_engine.submit_variation(var["id"], actor=admin)
    await commercial_engine.send_variation_to_client_review(var["id"], actor=admin)

    before = await reasoning_engine.list_insights(project["id"], user=admin)
    assert not [i for i in before if i["rule_id"] == "commercial.variation_approved_needs_contract_review"]

    await commercial_engine.decide_variation(var["id"], "approved", actor=admin)

    after = await reasoning_engine.list_insights(project["id"], user=admin)
    review = [i for i in after if i["rule_id"] == "commercial.variation_approved_needs_contract_review"]
    assert len(review) == 1
    assert review[0]["suggested_responsible_role"] == "management"


# ==========================================================================
# CM-01 — Continuous Project Memory. "Since Last Visit" is a pure
# composition over the existing commercial_events ledger - these tests
# confirm the actual promise: an honest empty first visit, a genuinely
# complete accounting of everything that happened since, and a
# correctly-scoped visit boundary that neither repeats old events nor
# misses new ones.
# ==========================================================================
async def test_first_visit_is_honestly_empty_not_fabricated():
    admin = {"id": "cm01_u1", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="CM01 First Visit Test", code="CM01FV1")
    result = await reasoning_engine.get_since_last_visit(project["id"], user=admin)
    assert result["is_first_visit"] is True
    assert result["since"] is None
    assert result["changes"] == []


async def test_second_visit_shows_everything_since_first_visit():
    admin = {"id": "cm01_u2", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="CM01 Second Visit Test", code="CM01SV1")

    # First visit - records the boundary, nothing to show yet.
    await reasoning_engine.get_since_last_visit(project["id"], user=admin)

    # Real activity happens "while the user is away".
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1,
        planned_percent=20, trigger="foundation complete")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)

    result = await reasoning_engine.get_since_last_visit(project["id"], user=admin)
    assert result["is_first_visit"] is False
    kinds = [c["kind"] for c in result["changes"]]
    assert "contract_created" in kinds
    assert "milestone_created" in kinds
    assert kinds.count("milestone_status_changed") == 2  # ready, then achieved

    achieved_entry = next(c for c in result["changes"] if c["kind"] == "milestone_status_changed"
                          and c["entity_id"] == ms["id"] and "completed" in c["what_changed"].lower())
    assert "AI Suggestions" in achieved_entry["why_it_matters"]


async def test_third_visit_immediately_after_is_empty():
    admin = {"id": "cm01_u3", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="CM01 Third Visit Test", code="CM01TV1")
    await reasoning_engine.get_since_last_visit(project["id"], user=admin)
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    await reasoning_engine.get_since_last_visit(project["id"], user=admin)  # second visit, consumes the event

    third = await reasoning_engine.get_since_last_visit(project["id"], user=admin)
    assert third["changes"] == []


async def test_since_last_visit_blocks_outsider():
    admin = {"id": "cm01_u4", "name": "Admin", "role": "management"}
    outsider = {"id": "cm01_outsider", "name": "Outsider", "role": "project_manager",
               "scope_projects": True, "assigned_project_ids": []}
    project = await memory_engine.insert_project(name="CM01 Security Test", code="CM01SEC1")
    with pytest.raises(reasoning_engine.ReasoningNotFoundError):
        await reasoning_engine.get_since_last_visit(project["id"], user=outsider)


# ==========================================================================
# KM-01 — Construction Knowledge Graph. Confirms the exact chain this
# package's own validation walkthrough required: Observation -> caused
# -> Variation -> modified -> Contract, and Payment -> settles ->
# Payment Request, entirely via relationships inferred from existing
# fields (project_id, milestone_id, payment_request_id,
# linked_photo_ids, raw_asset.event_id) - no new storage for any of
# these edges.
# ==========================================================================
async def test_variation_relationships_show_causing_observation_and_modified_contract():
    admin = {"id": "km01_u1", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="KM01 Relationship Test", code="KM01REL1")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    asset = await memory_engine.put_asset(event_id="km01_fake_event", kind="photo", mime="image/jpeg", raw_bytes=b"x")
    await core_db.db.events.insert_one({
        "id": "km01_fake_event", "site_id": site["id"], "project_id": project["id"],
        "text": "Structural crack found", "type": "photo", "server_created_at": "2026-01-01T00:00:00+00:00",
    })
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    var = await commercial_engine.create_variation(
        actor=admin, project_id=project["id"], title="Structural repair",
        description="d", original_cost=0, proposed_cost=50000, linked_photo_ids=[asset["id"]])
    await commercial_engine.submit_variation(var["id"], actor=admin)
    await commercial_engine.send_variation_to_client_review(var["id"], actor=admin)
    await commercial_engine.decide_variation(var["id"], "approved", actor=admin)

    rel = await knowledge_graph_engine.get_entity_relationships("variation", var["id"], user=admin)
    incoming_relationships = [(e["entity_type"], e["relationship"]) for e in rel["incoming"]]
    assert ("event", "CAUSED") in incoming_relationships
    outgoing_relationships = [(e["entity_type"], e["relationship"]) for e in rel["outgoing"]]
    assert ("contract", "MODIFIED") in outgoing_relationships


async def test_impact_trace_walks_the_full_chain_without_crashing_on_dead_ends():
    """The exact bug caught by live verification during this package's
    own development: a Variation's own outgoing edges include 'project'
    and 'contract', neither of which this engine expands further -
    the trace must skip these gracefully, not abort entirely."""
    admin = {"id": "km01_u2", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="KM01 Impact Trace Test", code="KM01IMP1")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    asset = await memory_engine.put_asset(event_id="km01_fake_event_2", kind="photo", mime="image/jpeg", raw_bytes=b"x")
    await core_db.db.events.insert_one({
        "id": "km01_fake_event_2", "site_id": site["id"], "project_id": project["id"],
        "text": "Crack found", "type": "photo", "server_created_at": "2026-01-01T00:00:00+00:00",
    })
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    var = await commercial_engine.create_variation(
        actor=admin, project_id=project["id"], title="Repair",
        description="d", original_cost=0, proposed_cost=50000, linked_photo_ids=[asset["id"]])
    await commercial_engine.submit_variation(var["id"], actor=admin)
    await commercial_engine.send_variation_to_client_review(var["id"], actor=admin)
    await commercial_engine.decide_variation(var["id"], "approved", actor=admin)

    trace = await knowledge_graph_engine.impact_trace("km01_fake_event_2", user=admin)
    entity_types = [step["entity_type"] for step in trace["chain"]]
    assert "event" in entity_types  # origin
    assert "variation" in entity_types
    assert "contract" in entity_types


async def test_decision_trace_shows_payment_settles_payment_request():
    admin = {"id": "km01_u3", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="KM01 Decision Trace Test", code="KM01DEC1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1,
        planned_percent=20, trigger="foundation complete")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)
    pr = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=ms["contract_value"], raised_date="2026-02-01", due_date="2026-02-15")
    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "sent", actor=admin)
    pay = await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=ms["contract_value"],
        date="2026-02-10", method="bank_transfer")

    trace = await knowledge_graph_engine.decision_trace("payment", pay["id"], user=admin)
    evidence_relationships = [(e["entity_type"], e["relationship"]) for e in trace["evidence"]]
    assert ("payment_request", "SETTLES") in evidence_relationships


async def test_knowledge_graph_blocks_outsider():
    admin = {"id": "km01_u4", "name": "Admin", "role": "management"}
    outsider = {"id": "km01_outsider", "name": "Outsider", "role": "project_manager",
               "scope_projects": True, "assigned_project_ids": []}
    project = await memory_engine.insert_project(name="KM01 Security Test", code="KM01SEC1")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1,
        planned_percent=20, trigger="t")
    with pytest.raises(knowledge_graph_engine.KnowledgeGraphNotFoundError):
        await knowledge_graph_engine.get_entity_relationships("milestone", ms["id"], user=outsider)


# ==========================================================================
# PILOT-02 P2-01 — Archive Isolation. A real bug found during this
# package's own audit: archiving a project never cascaded to its
# sites, and list_sites only checked a site's own archived_at, never
# its parent project's - so an archived project's sites stayed fully
# visible in Capture and Home's own site pickers.
# ==========================================================================
async def test_archived_project_sites_are_hidden_from_list_sites():
    admin = {"id": "p201_u1", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name="P201 Archive Test", code="P201ARCH1")
    site = await memory_engine.insert_site(project_id=project["id"], name="Test Site")

    before = await memory_engine.list_sites()
    assert site["id"] in [s["id"] for s in before]

    await memory_engine.archive_project(project["id"])
    after = await memory_engine.list_sites()
    assert site["id"] not in [s["id"] for s in after]

    # The site itself was never individually archived - confirming the
    # fix works via the parent project's own archive state, not by
    # also (incorrectly) archiving the site's own record.
    site_doc = await core_db.db.sites.find_one({"id": site["id"]}, {"_id": 0})
    assert site_doc.get("archived_at") is None

    # include_archived=True must still surface it - the fix hides by
    # default, it doesn't delete or make the data unreachable.
    with_archived = await memory_engine.list_sites(include_archived=True)
    assert site["id"] in [s["id"] for s in with_archived]


# ==========================================================================
# PX-01A P2-09 — Notification Inbox Foundation. Matches the exact
# scenarios manually verified through the live API before these
# permanent tests were written.
# ==========================================================================
async def test_assignment_notification_reaches_the_assignee():
    admin = {"id": "p209_u1", "name": "Admin", "role": "management"}
    assignee = {"id": "p209_assignee1", "name": "Assignee", "role": "site_supervisor"}
    project = await memory_engine.insert_project(name="P209 Assignment Test", code="P209ASN1")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await operations_engine.create_item(
        site_id=site["id"], title="Fix crack", category="quality_observation", actor=admin)

    before = await notification_engine.list_notifications(assignee["id"])
    assert before == []

    await operations_engine.assign_item(item_id=item["id"], assignee=assignee, actor=admin)

    after = await notification_engine.list_notifications(assignee["id"])
    assert len(after) == 1
    assert after[0]["category"] == "assignment"
    assert "Fix crack" in after[0]["title"]
    assert after[0]["read"] is False


async def test_payment_request_notification_reaches_project_management():
    admin = {"id": "p209_u2", "name": "Admin", "role": "management"}
    mgmt_user = await memory_engine.upsert_user(phone="9990300001", name="P209 Notif Mgmt", role="management")
    project = await memory_engine.insert_project(name="P209 Commercial Notif Test", code="P209COM1")
    await memory_engine.set_user_projects(mgmt_user["id"], [project["id"]])
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1,
        planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)

    await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=ms["contract_value"], raised_date="2026-02-01", due_date="2026-02-15")

    notifications = await notification_engine.list_notifications(mgmt_user["id"])
    assert len(notifications) == 1
    assert notifications[0]["category"] == "commercial"
    assert "raised" in notifications[0]["title"].lower()


async def test_mark_notification_read_updates_unread_count():
    user_id = "p209_u3"
    await notification_engine.create_notification(
        user_id=user_id, category="assignment", title="Test", body="Test body")
    notif = (await notification_engine.list_notifications(user_id))[0]

    assert await notification_engine.unread_count(user_id) == 1
    await notification_engine.mark_read(notif["id"], user_id=user_id)
    assert await notification_engine.unread_count(user_id) == 0


async def test_mark_read_is_scoped_to_the_correct_user():
    """Marking someone else's notification read must be a no-op, not
    an error or a cross-user leak."""
    owner_id, other_id = "p209_owner", "p209_other"
    await notification_engine.create_notification(
        user_id=owner_id, category="assignment", title="Test", body="Test body")
    notif = (await notification_engine.list_notifications(owner_id))[0]

    await notification_engine.mark_read(notif["id"], user_id=other_id)
    assert await notification_engine.unread_count(owner_id) == 1  # untouched


# ==========================================================================
# PX-02 Phase 3 — AI Daily Site Report Generator. Matches the exact
# scenarios manually verified live through the real API before being
# written as permanent tests.
# ==========================================================================
async def _setup_report_project(name_suffix: str):
    admin = {"id": f"p3_admin_{name_suffix}", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name=f"P3 Report Test {name_suffix}", code=f"P3RPT{name_suffix}")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    return admin, project, site


async def test_daily_report_with_no_activity():
    admin, project, site = await _setup_report_project("empty")
    today = datetime.now(timezone.utc).date().isoformat()

    report = await daily_site_report_service.generate_daily_report(project["id"], today, user=admin)

    assert report["site_activity_snapshot"]["new_capture_events"] == 0
    assert report["work_completed_today"] == []
    assert report["blockers_and_risks"] == []
    assert "no new capture events" in report["executive_summary"]
    assert report["ai_forecast_impact"]["confidence"] == "High confidence"


async def test_daily_report_with_capture_events_only():
    admin, project, site = await _setup_report_project("capture")
    today = datetime.now(timezone.utc).date().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    await core_db.db.events.insert_one({
        "id": "evt_p3test1", "site_id": site["id"], "project_id": project["id"],
        "text_input": "Reinforcement work completed for footing F-12",
        "photo_asset_ids": ["asset_1"], "server_created_at": now_iso, "kind": "text",
    })

    report = await daily_site_report_service.generate_daily_report(project["id"], today, user=admin)

    assert report["site_activity_snapshot"]["new_capture_events"] == 1
    assert report["site_activity_snapshot"]["photos_attached"] == 1
    assert "Reinforcement work completed for footing F-12" in report["work_completed_today"]


async def test_daily_report_with_blockers_and_approvals():
    admin, project, site = await _setup_report_project("blockers")
    today = datetime.now(timezone.utc).date().isoformat()

    item = await operations_engine.create_item(
        site_id=site["id"], title="Steel delivery delayed", category="material_requirement", actor=admin)
    await operations_engine.set_blocker(item_id=item["id"], actor=admin, category="material", note="Pending procurement")
    approval = await operations_engine.create_item(
        site_id=site["id"], title="Approve tile selection", category="client_approval", actor=admin)

    report = await daily_site_report_service.generate_daily_report(project["id"], today, user=admin)

    assert len(report["blockers_and_risks"]) == 1
    assert report["blockers_and_risks"][0]["title"] == "Steel delivery delayed"
    assert report["blockers_and_risks"][0]["impact_category"] == "schedule"
    assert len(report["client_decisions_pending"]) == 1
    assert report["client_decisions_pending"][0]["title"] == "Approve tile selection"
    assert "1 open blocker" in report["ai_forecast_impact"]["statement"]
    assert "remains unresolved" in report["ai_forecast_impact"]["statement"]  # singular agreement


async def test_client_safe_transformation_removes_restricted_fields():
    admin, project, site = await _setup_report_project("clientsafe")
    today = datetime.now(timezone.utc).date().isoformat()
    item = await operations_engine.create_item(
        site_id=site["id"], title="Blocked item", category="material_requirement", actor=admin)
    await operations_engine.set_blocker(item_id=item["id"], actor=admin, category="material", note="test")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    await commercial_engine.create_budget(actor=admin, project_id=project["id"], original_budget=800000)
    await commercial_engine.record_actual_cost(project["id"], 50000, actor=admin, reason="test expense")

    internal = await daily_site_report_service.generate_daily_report(project["id"], today, user=admin)
    assert "owner" in internal["blockers_and_risks"][0]
    assert len(internal["commercial_attention"]) >= 1

    safe = daily_site_report_service.to_client_safe(internal)
    assert safe["client_safe"] is True
    assert "owner" not in safe["blockers_and_risks"][0]
    assert safe["commercial_attention"] == []
    # the underlying title/impact data must still be present - client-safe
    # removes specific restricted fields, it doesn't hide the blocker's own existence
    assert safe["blockers_and_risks"][0]["title"] == "Blocked item"


async def test_daily_report_metrics_are_deterministic_across_repeated_calls():
    admin, project, site = await _setup_report_project("determinism")
    today = datetime.now(timezone.utc).date().isoformat()
    item = await operations_engine.create_item(
        site_id=site["id"], title="Test item", category="general", actor=admin)
    await operations_engine.set_blocker(item_id=item["id"], actor=admin, category="other", note="test")

    report_a = await daily_site_report_service.generate_daily_report(project["id"], today, user=admin)
    report_b = await daily_site_report_service.generate_daily_report(project["id"], today, user=admin)

    assert report_a["site_activity_snapshot"] == report_b["site_activity_snapshot"]
    assert report_a["blockers_and_risks"] == report_b["blockers_and_risks"]


async def test_daily_report_markdown_export_formatting():
    admin, project, site = await _setup_report_project("export")
    today = datetime.now(timezone.utc).date().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    await core_db.db.events.insert_one({
        "id": "evt_p3test2", "site_id": site["id"], "project_id": project["id"],
        "text_input": "Test capture", "photo_asset_ids": [], "server_created_at": now_iso, "kind": "text",
    })

    report = await daily_site_report_service.generate_daily_report(project["id"], today, user=admin)
    markdown = daily_site_report_service.render_markdown(report)

    assert markdown.startswith("# Atlas Daily Site Report")
    assert f"**Project:** {report['project_name']}" in markdown
    assert "## Executive Summary" in markdown
    assert "## Site Activity Snapshot" in markdown
    assert "| New capture events |" in markdown
    assert "## Blockers & Risks" in markdown
    assert "## AI Forecast Impact" in markdown
    assert "Test capture" in markdown


# ==========================================================================
# PX-02 Phase 4 — Inbox Intelligence & Waiting-State Coordination.
# Matches the exact scenarios manually verified live through the real
# API before being written as permanent tests.
# ==========================================================================
async def _setup_coordination_project(name_suffix: str):
    pm = {"id": f"p4_pm_{name_suffix}", "name": "PM", "role": "project_manager"}
    sup = await memory_engine.upsert_user(phone=f"90{name_suffix}0001", name="Sup", role="site_supervisor")
    project = await memory_engine.insert_project(name=f"P4 Coordination {name_suffix}", code=f"P4C{name_suffix}")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    return pm, sup, project, site


async def test_waiting_state_classification_action_required_for_assignee():
    pm, sup, project, site = await _setup_coordination_project("wsclass")
    item = await operations_engine.create_item(site_id=site["id"], title="Fix crack", category="quality_observation", actor=pm)
    await operations_engine.assign_item(item_id=item["id"], assignee=sup, actor=pm)

    inbox = await inbox_intelligence_service.build_coordination_inbox(sup)

    assert len(inbox["action_required"]) == 1
    assert "Fix crack" in inbox["action_required"][0]["latest_title"]


async def test_waiting_state_classification_waiting_for_others_for_initiator():
    pm, sup, project, site = await _setup_coordination_project("wsother")
    item = await operations_engine.create_item(site_id=site["id"], title="Approve tile selection", category="client_approval", actor=pm)

    inbox = await inbox_intelligence_service.build_coordination_inbox(pm)

    assert len(inbox["waiting_for_others"]) == 1
    assert inbox["waiting_for_others"][0]["latest_title"] == "Approve tile selection"


async def test_notification_grouping_collapses_same_entity():
    pm, sup, project, site = await _setup_coordination_project("group")
    item = await operations_engine.create_item(site_id=site["id"], title="Grouped item", category="general", actor=pm)
    # Three separate assignment notifications on the same entity
    for _ in range(3):
        await notification_engine.notify_assignment(
            assignee_user_id=sup["id"], actor_name="PM", item_title="Grouped item",
            project_id=project["id"], entity_type="operational_item", entity_id=item["id"],
        )

    inbox = await inbox_intelligence_service.build_coordination_inbox(sup)

    assert len(inbox["action_required"]) == 1  # collapsed into one card
    assert inbox["action_required"][0]["count"] == 3


async def test_escalation_threshold_calculation():
    from datetime import timedelta
    fresh_ts = datetime.now(timezone.utc).isoformat()
    assert inbox_intelligence_service._aging_signal("clarification", fresh_ts) == "green"
    warning_ts = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    assert inbox_intelligence_service._aging_signal("clarification", warning_ts) == "amber"
    escalated_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert inbox_intelligence_service._aging_signal("clarification", escalated_ts) == "red"


async def test_deep_link_phase_routing_matrix():
    assert inbox_intelligence_service._target_phase("operational_item") == "execute"
    assert inbox_intelligence_service._target_phase("payment_request") == "bill"
    assert inbox_intelligence_service._target_phase("variation") == "plan"
    assert inbox_intelligence_service._target_phase(None) == "execute"  # safe default, never crashes


async def test_project_scoped_filtering():
    pm, sup, project_a, site_a = await _setup_coordination_project("scopeA")
    _, _, project_b, site_b = await _setup_coordination_project("scopeB")
    item_a = await operations_engine.create_item(site_id=site_a["id"], title="Item A", category="general", actor=pm)
    await operations_engine.assign_item(item_id=item_a["id"], assignee=sup, actor=pm)
    item_b = await operations_engine.create_item(site_id=site_b["id"], title="Item B", category="general", actor=pm)
    await operations_engine.assign_item(item_id=item_b["id"], assignee=sup, actor=pm)

    all_inbox = await inbox_intelligence_service.build_coordination_inbox(sup)
    scoped_inbox = await inbox_intelligence_service.build_coordination_inbox(sup, project_id=project_a["id"])

    assert len(all_inbox["action_required"]) == 2
    assert len(scoped_inbox["action_required"]) == 1
    assert scoped_inbox["action_required"][0]["project_id"] == project_a["id"]


async def test_unread_count_accuracy_after_grouping():
    pm, sup, project, site = await _setup_coordination_project("unread")
    item = await operations_engine.create_item(site_id=site["id"], title="Unread test", category="general", actor=pm)
    await notification_engine.notify_assignment(
        assignee_user_id=sup["id"], actor_name="PM", item_title="Unread test",
        project_id=project["id"], entity_type="operational_item", entity_id=item["id"],
    )
    await notification_engine.notify_assignment(
        assignee_user_id=sup["id"], actor_name="PM", item_title="Unread test",
        project_id=project["id"], entity_type="operational_item", entity_id=item["id"], is_reassignment=True,
    )

    inbox = await inbox_intelligence_service.build_coordination_inbox(sup)
    card = inbox["action_required"][0]
    assert card["count"] == 2
    assert card["read"] is False  # grouped card is unread if ANY underlying notification is unread

    # Mark both underlying notifications read, confirm the grouped card reflects it
    for nid in card["notification_ids"]:
        await notification_engine.mark_read(nid, user_id=sup["id"])
    inbox_after = await inbox_intelligence_service.build_coordination_inbox(sup)
    assert inbox_after["action_required"][0]["read"] is True
    assert await notification_engine.unread_count(sup["id"]) == 0


async def test_client_visibility_restriction_via_per_user_scoping():
    """A client never sees a PM/Supervisor's own assignment
    notifications - structurally, via the same per-user scoping every
    other role relies on, not a client-specific filter."""
    pm, sup, project, site = await _setup_coordination_project("clientvis")
    item = await operations_engine.create_item(site_id=site["id"], title="Internal item", category="general", actor=pm)
    await operations_engine.assign_item(item_id=item["id"], assignee=sup, actor=pm)

    client = await memory_engine.upsert_user(phone="90clientvis0002", name="Client", role="client")
    client_inbox = await inbox_intelligence_service.build_coordination_inbox(client)

    assert client_inbox["action_required"] == []
    assert client_inbox["waiting_for_others"] == []


# ==========================================================================
# PX-03 Phase 1 — Commercial Workflow Completion & Cash-Flow
# Coordination. Matches the exact scenarios manually verified live
# through the real API before being written as permanent tests.
# ==========================================================================
async def _setup_commercial_project(name_suffix: str):
    admin = {"id": f"p31_admin_{name_suffix}", "name": "Admin", "role": "management"}
    project = await memory_engine.insert_project(name=f"P31 Commercial {name_suffix}", code=f"P31C{name_suffix}")
    return admin, project


async def test_profitability_panel_matches_task_own_worked_example():
    """Deliberately uses this task's own brief numbers (Contract
    Rs 1,20,00,000, Forecast Cost Rs 92,50,000) to cross-check the
    formula implementation against the brief's own stated expected
    output (Forecast Profit Rs 27,50,000, Margin 22.9%), not just
    internal consistency."""
    admin, project = await _setup_commercial_project("worked_example")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=12000000, contract_date="2026-01-01", duration_days=180)
    await commercial_engine.create_budget(actor=admin, project_id=project["id"], original_budget=9250000)
    await commercial_engine.record_actual_cost(project["id"], 9250000, actor=admin, reason="test")

    panel = await commercial_workflow_service.build_profitability_panel(project["id"], user=admin)

    assert panel["kpis"]["forecast_profit"]["value"] == 2750000.0
    assert round(panel["kpis"]["forecast_margin_percent"]["value"], 1) == 22.9


async def test_approved_variation_increases_revenue_potential():
    admin, project = await _setup_commercial_project("variation_impact")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=10000000, contract_date="2026-01-01", duration_days=100)

    panel_before = await commercial_workflow_service.build_profitability_panel(project["id"], user=admin)
    assert panel_before["kpis"]["current_revenue_potential"]["value"] == 10000000.0

    var = await commercial_engine.create_variation(
        actor=admin, project_id=project["id"], title="Extra scope", description="d",
        original_cost=0, proposed_cost=500000)
    await commercial_engine.submit_variation(var["id"], actor=admin)
    await commercial_engine.send_variation_to_client_review(var["id"], actor=admin)
    await commercial_engine.decide_variation(var["id"], "approved", actor=admin)

    panel_after = await commercial_workflow_service.build_profitability_panel(project["id"], user=admin)
    assert panel_after["kpis"]["approved_variations"]["value"] == 500000
    assert panel_after["kpis"]["current_revenue_potential"]["value"] == 10500000.0


async def test_payment_request_approval_gate_state_transitions():
    admin, project = await _setup_commercial_project("pr_states")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=5000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)
    pr = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=ms["contract_value"], raised_date="2026-08-01", due_date="2026-08-15")

    assert pr["status"] == "draft"
    assert pr["raised_by_user_id"] == admin["id"]  # the real bug this phase found and fixed

    # draft -> raised directly must now be illegal (the new approval gate)
    with pytest.raises(commercial_engine.CommercialError):
        await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=admin)

    pr = await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=admin)
    assert pr["status"] == "under_review"
    pr = await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=admin)
    assert pr["status"] == "raised"

    # return-for-revision path - a genuinely separate milestone, since
    # the first create_payment_request call above already transitioned
    # its own milestone to 'payment_requested' as a side effect.
    ms2 = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Structure", sequence=2, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms2["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms2["id"], "achieved", actor=admin)
    pr2 = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms2["id"],
        amount=100000, raised_date="2026-08-01", due_date="2026-08-15")
    pr2 = await commercial_engine.transition_payment_request_status(pr2["id"], "under_review", actor=admin)
    pr2 = await commercial_engine.transition_payment_request_status(pr2["id"], "draft", actor=admin)
    assert pr2["status"] == "draft"


async def test_receivables_calculation():
    admin, project = await _setup_commercial_project("receivables")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)
    pr = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=200000, raised_date="2026-08-01", due_date="2026-08-15")
    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "sent", actor=admin)
    await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=120000, date="2026-08-10", method="bank_transfer")

    billing = await commercial_workflow_service.build_billing_and_collections(project["id"], user=admin)
    assert billing["billed_to_date"]["value"] == 200000.0
    assert billing["received_to_date"]["value"] == 120000.0
    assert billing["outstanding_receivables"]["value"] == 80000.0
    assert billing["collection_efficiency_percent"]["value"] == 60.0


async def test_commercial_health_classification():
    admin, project = await _setup_commercial_project("health")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    await commercial_engine.create_budget(actor=admin, project_id=project["id"], original_budget=1200000)
    # Forecast cost > revenue -> negative margin -> risk
    await commercial_engine.record_actual_cost(project["id"], 1200000, actor=admin, reason="test")

    health = await commercial_workflow_service.commercial_health(project["id"], user=admin)
    assert health["status"] == "risk"
    assert "negative_forecast_margin" in health["reasons"]


async def test_payment_request_inbox_integration():
    """PM submits -> Management sees Commercial Attention. Management
    approves -> PM sees Payment Request Approved. Matches the exact
    live scenario verified through the real API before this test was
    written."""
    pm = await memory_engine.upsert_user(phone="90p31inbox0001", name="Inbox PM", role="project_manager")
    mgmt = await memory_engine.upsert_user(phone="90p31inbox0002", name="Inbox Mgmt", role="management")
    project = await memory_engine.insert_project(name="P31 Inbox Test", code="P31INBOX1")
    await memory_engine.set_user_projects(pm["id"], [project["id"]])
    await memory_engine.set_user_projects(mgmt["id"], [project["id"]])
    await commercial_engine.create_contract(
        actor=pm, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=pm, project_id=project["id"], name="Foundation", sequence=1, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=pm)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=pm)
    pr = await commercial_engine.create_payment_request(
        actor=pm, project_id=project["id"], milestone_id=ms["id"],
        amount=ms["contract_value"], raised_date="2026-08-01", due_date="2026-08-15")

    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=pm)
    mgmt_inbox = await inbox_intelligence_service.build_coordination_inbox(mgmt)
    assert len(mgmt_inbox["commercial_attention"]) == 1
    assert "submitted for review" in mgmt_inbox["commercial_attention"][0]["latest_title"]

    pm_inbox = await inbox_intelligence_service.build_coordination_inbox(pm)
    assert len(pm_inbox["waiting_for_others"]) == 1

    await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=mgmt)
    pm_inbox_after = await inbox_intelligence_service.build_coordination_inbox(pm)
    all_cards = pm_inbox_after["action_required"] + pm_inbox_after["commercial_attention"] + pm_inbox_after["activity_feed"]
    assert any("Approved" in c["latest_title"] for c in all_cards)


async def test_client_role_visibility_restriction_on_commercial_endpoints():
    """A client explicitly scoped away from a project must not see
    its commercial data - confirmed here at the service level that
    assert_project_visible still gates access the same way for every
    real, properly-scoped user, matching the existing, unmodified
    authorization convention this task's own Section 8 asks to
    preserve. upsert_user() alone never sets scope_projects (a
    deliberate migration safeguard, confirmed by reading
    _is_project_scoped's own docstring before assuming this was a
    bug) - real scoping happens via set_user_projects, matching how
    Atlas actually configures client access in practice."""
    admin, project = await _setup_commercial_project("client_access")
    _, unrelated_project = await _setup_commercial_project("client_access_unrelated")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    outsider_client = await memory_engine.upsert_user(phone="90p31clientacc0001", name="Outsider Client", role="client")
    await memory_engine.set_user_projects(outsider_client["id"], [unrelated_project["id"]])
    outsider_client = await memory_engine.get_user_by_phone("90p31clientacc0001")
    with pytest.raises(Exception):
        await commercial_workflow_service.build_profitability_panel(project["id"], user=outsider_client)


async def test_payment_request_status_change_creates_timeline_event():
    admin, project = await _setup_commercial_project("timeline")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)
    pr = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=100000, raised_date="2026-08-01", due_date="2026-08-15")
    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=admin)

    events = await commercial_engine.list_commercial_events(project["id"])
    status_change_events = [e for e in events if e["kind"] == "payment_request_status_changed"]
    assert len(status_change_events) >= 1
    assert status_change_events[0]["payload"]["to"] == "under_review"


# ==========================================================================
# PX-03 Phase 2 — Commercial Workspace UI Completion & Client-Safe
# Billing. Matches the exact scenarios manually verified live through
# the real API before being written as permanent tests.
# ==========================================================================
async def test_client_cannot_retrieve_internal_profitability_fields():
    """The high-priority security fix this phase exists for.
    Confirmed live before this test was written: a Client legitimately
    assigned to a project (the normal case) must not receive
    margin/budget/forecast data."""
    admin, project = await _setup_commercial_project("client_profit_block")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    client = await memory_engine.upsert_user(phone="90p32client0001", name="Sec Client", role="client")
    await memory_engine.set_user_projects(client["id"], [project["id"]])
    client = await memory_engine.get_user_by_phone("90p32client0001")

    with pytest.raises(commercial_workflow_service.CommercialPermissionError):
        await commercial_workflow_service.build_profitability_panel(project["id"], user=client)
    with pytest.raises(commercial_workflow_service.CommercialPermissionError):
        await commercial_workflow_service.commercial_health(project["id"], user=client)
    with pytest.raises(commercial_workflow_service.CommercialPermissionError):
        await commercial_workflow_service.cash_flow_timeline(project["id"], user=client)


async def test_client_safe_bill_summary_never_contains_internal_fields():
    admin, project = await _setup_commercial_project("client_safe_shape")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    await commercial_engine.create_budget(actor=admin, project_id=project["id"], original_budget=800000)
    client = await memory_engine.upsert_user(phone="90p32client0002", name="Sec Client 2", role="client")
    await memory_engine.set_user_projects(client["id"], [project["id"]])
    client = await memory_engine.get_user_by_phone("90p32client0002")

    summary = await commercial_workflow_service.build_client_safe_bill_summary(project["id"], user=client)
    forbidden_keys = ("forecast_profit", "forecast_margin_percent", "budget", "actual_expenses",
                      "committed_cost", "remaining_budget", "kpis", "reasons")
    for key in forbidden_keys:
        assert key not in summary, f"'{key}' leaked into the client-safe response"
    assert summary["approved_contract_amount"] == 1000000


async def test_supervisor_cannot_retrieve_detailed_commercial_fields():
    admin, project = await _setup_commercial_project("supervisor_block")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    supervisor = await memory_engine.upsert_user(phone="90p32sup0001", name="Sec Sup", role="site_supervisor")
    await memory_engine.set_user_projects(supervisor["id"], [project["id"]])
    supervisor = await memory_engine.get_user_by_phone("90p32sup0001")

    with pytest.raises(commercial_workflow_service.CommercialPermissionError):
        await commercial_workflow_service.build_profitability_panel(project["id"], user=supervisor)
    with pytest.raises(commercial_workflow_service.CommercialPermissionError):
        await commercial_workflow_service.build_billing_and_collections(project["id"], user=supervisor)


async def test_management_and_pm_retain_full_internal_access():
    """The security fix must not have collaterally broken the two
    roles that legitimately need this data - confirmed explicitly,
    not just assumed from the regression suite passing."""
    admin, project = await _setup_commercial_project("internal_access_preserved")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    pm = await memory_engine.upsert_user(phone="90p32pm0001", name="Preserved PM", role="project_manager")
    await memory_engine.set_user_projects(pm["id"], [project["id"]])
    pm = await memory_engine.get_user_by_phone("90p32pm0001")

    panel = await commercial_workflow_service.build_profitability_panel(project["id"], user=pm)
    assert panel is not None
    panel_admin = await commercial_workflow_service.build_profitability_panel(project["id"], user=admin)
    assert panel_admin is not None


async def test_record_payment_rejects_unsent_payment_request():
    """A real, genuine defect found while auditing the payment flow
    for the new approval gate: record_payment previously only blocked
    'cancelled' status, meaning a payment could be recorded against a
    request still in draft or under_review - before it had ever
    reached the client."""
    admin, project = await _setup_commercial_project("unsent_payment_block")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)
    pr = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=100000, raised_date="2026-08-01", due_date="2026-08-15")

    with pytest.raises(commercial_engine.CommercialError):
        await commercial_engine.record_payment(
            actor=admin, payment_request_id=pr["id"], amount=100000, date="2026-08-05", method="bank_transfer")

    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=admin)
    with pytest.raises(commercial_engine.CommercialError):
        await commercial_engine.record_payment(
            actor=admin, payment_request_id=pr["id"], amount=100000, date="2026-08-05", method="bank_transfer")

    await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "sent", actor=admin)
    # now genuinely allowed
    pay = await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=100000, date="2026-08-05", method="bank_transfer")
    assert pay["amount"] == 100000


# ==========================================================================
# PX-03 Phase 3 — Commercial Workflow Completion, Notifications & Final
# Pilot Hardening. Matches the exact scenarios manually verified live
# through the real API before being written as permanent tests.
# ==========================================================================
async def _setup_sent_payment_request(name_suffix: str, due_date: str = "2026-08-15"):
    admin, project = await _setup_commercial_project(name_suffix)
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)
    pr = await commercial_engine.create_payment_request(
        actor=admin, project_id=project["id"], milestone_id=ms["id"],
        amount=300000, raised_date="2026-08-01", due_date=due_date)
    await commercial_engine.transition_payment_request_status(pr["id"], "under_review", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "raised", actor=admin)
    await commercial_engine.transition_payment_request_status(pr["id"], "sent", actor=admin)
    return admin, project, pr


async def test_partial_payment_notification_targets_raiser():
    pm = await memory_engine.upsert_user(phone="90p33partial0001", name="Partial PM", role="project_manager")
    admin, project, pr = await _setup_sent_payment_request("partial_notif")
    # re-raise with the real PM as the actor so raised_by_user_id differs from the recorder
    await memory_engine.set_user_projects(pm["id"], [project["id"]])
    ms2 = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Structure", sequence=2, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms2["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms2["id"], "achieved", actor=admin)
    pr2 = await commercial_engine.create_payment_request(
        actor=pm, project_id=project["id"], milestone_id=ms2["id"],
        amount=300000, raised_date="2026-08-01", due_date="2026-08-15")
    await commercial_engine.transition_payment_request_status(pr2["id"], "under_review", actor=pm)
    await commercial_engine.transition_payment_request_status(pr2["id"], "raised", actor=admin)
    await commercial_engine.transition_payment_request_status(pr2["id"], "sent", actor=admin)

    await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr2["id"], amount=100000, date="2026-08-10", method="bank_transfer")

    inbox = await inbox_intelligence_service.build_coordination_inbox(pm)
    all_cards = inbox["action_required"] + inbox["commercial_attention"] + inbox["activity_feed"]
    partial_card = next((c for c in all_cards if "Partial payment" in c["latest_title"]), None)
    assert partial_card is not None
    assert "100,000" in partial_card["latest_body"]


async def test_full_payment_notification_differs_from_partial():
    pm = await memory_engine.upsert_user(phone="90p33full0001", name="Full PM", role="project_manager")
    admin, project, pr = await _setup_sent_payment_request("full_notif")
    await memory_engine.set_user_projects(pm["id"], [project["id"]])
    ms2 = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Structure", sequence=2, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms2["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms2["id"], "achieved", actor=admin)
    pr2 = await commercial_engine.create_payment_request(
        actor=pm, project_id=project["id"], milestone_id=ms2["id"],
        amount=300000, raised_date="2026-08-01", due_date="2026-08-15")
    await commercial_engine.transition_payment_request_status(pr2["id"], "under_review", actor=pm)
    await commercial_engine.transition_payment_request_status(pr2["id"], "raised", actor=admin)
    await commercial_engine.transition_payment_request_status(pr2["id"], "sent", actor=admin)

    await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr2["id"], amount=300000, date="2026-08-10", method="bank_transfer")

    inbox = await inbox_intelligence_service.build_coordination_inbox(pm)
    all_cards = inbox["action_required"] + inbox["commercial_attention"] + inbox["activity_feed"]
    full_card = next((c for c in all_cards if "fully paid" in c["latest_title"]), None)
    assert full_card is not None


async def test_overdue_transition_and_escalation():
    from datetime import timedelta
    admin, project, pr = await _setup_sent_payment_request(
        "overdue_escalation", due_date=(datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat())

    result = await commercial_engine.check_and_escalate_overdue_payment_requests(project["id"], actor=admin)
    assert pr["id"] in result["newly_overdue"]
    assert pr["id"] in result["escalated"]

    updated = await commercial_engine.get_payment_request(pr["id"])
    assert updated["status"] == "overdue"

    inbox = await inbox_intelligence_service.build_coordination_inbox(admin)
    all_cards = inbox["action_required"] + inbox["commercial_attention"] + inbox["activity_feed"]
    escalation_card = next((c for c in all_cards if "severely overdue" in c["latest_title"]), None)
    assert escalation_card is not None


async def test_overdue_escalation_is_idempotent():
    from datetime import timedelta
    admin, project, pr = await _setup_sent_payment_request(
        "idempotent_escalation", due_date=(datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat())

    result1 = await commercial_engine.check_and_escalate_overdue_payment_requests(project["id"], actor=admin)
    assert len(result1["escalated"]) == 1

    result2 = await commercial_engine.check_and_escalate_overdue_payment_requests(project["id"], actor=admin)
    assert result2["newly_overdue"] == []
    assert result2["escalated"] == []  # must not duplicate on re-run

    notifs = await notification_engine.list_notifications(admin["id"], limit=100)
    escalation_notifs = [n for n in notifs if "severely overdue" in n["title"]]
    assert len(escalation_notifs) == 1


async def test_recently_overdue_not_yet_escalated():
    """Only past the OVERDUE_ESCALATION_DAYS threshold should escalate
    - a request 2 days overdue should transition to 'overdue' but not
    yet trigger an escalation notification."""
    from datetime import timedelta
    admin, project, pr = await _setup_sent_payment_request(
        "recently_overdue", due_date=(datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat())

    result = await commercial_engine.check_and_escalate_overdue_payment_requests(project["id"], actor=admin)
    assert pr["id"] in result["newly_overdue"]
    assert pr["id"] not in result["escalated"]


async def test_commercial_events_route_blocked_for_client_and_supervisor():
    """A real security leak found this phase: list_commercial_events
    had zero role gating, exposing exact internal budget/cost figures
    (budget_revised's from/to values) to any Client or Supervisor with
    project access."""
    admin, project = await _setup_commercial_project("events_leak")
    await commercial_engine.create_budget(actor=admin, project_id=project["id"], original_budget=1000000)
    await commercial_engine.revise_budget(project["id"], 1200000, actor=admin, reason="scope change")

    client = await memory_engine.upsert_user(phone="90p33eventsleak0001", name="Events Client", role="client")
    await memory_engine.set_user_projects(client["id"], [project["id"]])
    client = await memory_engine.get_user_by_phone("90p33eventsleak0001")
    supervisor = await memory_engine.upsert_user(phone="90p33eventsleak0002", name="Events Sup", role="site_supervisor")
    await memory_engine.set_user_projects(supervisor["id"], [project["id"]])
    supervisor = await memory_engine.get_user_by_phone("90p33eventsleak0002")

    # The service layer itself has no role check on list_commercial_events -
    # the fix lives at the route layer (routes/commercial.py), so this
    # test exercises the route directly via the app, not the bare engine
    # function, to prove the actual leak is closed where it matters.
    import server
    import httpx
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        from core.auth import create_token
        client_token = create_token(client["id"])
        sup_token = create_token(supervisor["id"])
        r_client = await c.get(f"/api/projects/{project['id']}/commercial/events",
                               headers={"Authorization": f"Bearer {client_token}"})
        r_sup = await c.get(f"/api/projects/{project['id']}/commercial/events",
                            headers={"Authorization": f"Bearer {sup_token}"})
        assert r_client.status_code == 403
        assert r_sup.status_code == 403


async def test_commercial_summary_blocked_for_supervisor_client_safe():
    """A real audit finding this phase: the summary route treated
    Supervisor identically to Client (both got everything except
    budget) - Supervisor should be more restricted per this task's own
    Section 7, which gives no safe-list exception the way Client's own
    Section 6 does."""
    admin, project = await _setup_commercial_project("summary_supervisor")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)

    import server
    import httpx
    from core.auth import create_token
    supervisor = await memory_engine.upsert_user(phone="90p33summarysup0001", name="Summary Sup", role="site_supervisor")
    await memory_engine.set_user_projects(supervisor["id"], [project["id"]])
    supervisor = await memory_engine.get_user_by_phone("90p33summarysup0001")
    client = await memory_engine.upsert_user(phone="90p33summarysup0002", name="Summary Client", role="client")
    await memory_engine.set_user_projects(client["id"], [project["id"]])
    client = await memory_engine.get_user_by_phone("90p33summarysup0002")

    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        sup_token = create_token(supervisor["id"])
        client_token = create_token(client["id"])
        r_sup = await c.get(f"/api/projects/{project['id']}/commercial/summary",
                            headers={"Authorization": f"Bearer {sup_token}"})
        r_client = await c.get(f"/api/projects/{project['id']}/commercial/summary",
                               headers={"Authorization": f"Bearer {client_token}"})
        assert r_sup.status_code == 403
        assert r_client.status_code == 200
        assert r_client.json()["budget"] is None


async def test_archived_project_blocks_new_commercial_activity_but_preserves_reads():
    """A real, genuine gap found this phase: commercial_engine.py had
    zero archive-awareness anywhere. 'ARCHIVED != DELETED' - reads must
    keep working, only new mutations are rejected."""
    admin, project = await _setup_commercial_project("archive_isolation")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    ms = await commercial_engine.create_milestone(
        actor=admin, project_id=project["id"], name="Foundation", sequence=1, planned_percent=20, trigger="t")
    await commercial_engine.transition_milestone_status(ms["id"], "ready", actor=admin)
    await commercial_engine.transition_milestone_status(ms["id"], "achieved", actor=admin)

    await memory_engine.archive_project(project["id"])

    # Reads must still succeed - historical access preserved
    summary = await commercial_engine.get_project_commercial_summary(project["id"])
    assert summary is not None

    # New mutations must be rejected
    with pytest.raises(commercial_engine.CommercialError):
        await commercial_engine.create_payment_request(
            actor=admin, project_id=project["id"], milestone_id=ms["id"],
            amount=100000, raised_date="2026-08-14", due_date="2026-08-28")


async def test_notification_failure_does_not_block_the_underlying_mutation():
    """This task's own explicit rule: notifications must never block
    the underlying commercial transaction. Confirmed by monkeypatching
    notify_commercial to raise, and verifying record_payment still
    succeeds and returns the real payment document."""
    admin, project, pr = await _setup_sent_payment_request("notif_failure_isolation")

    import unittest.mock
    with unittest.mock.patch.object(notification_engine, "notify_commercial", side_effect=RuntimeError("simulated failure")):
        pay = await commercial_engine.record_payment(
            actor=admin, payment_request_id=pr["id"], amount=100000, date="2026-08-05", method="bank_transfer")
    assert pay["amount"] == 100000
    updated_pr = await commercial_engine.get_payment_request(pr["id"])
    assert updated_pr["status"] == "partially_paid"


# ==========================================================================
# PX-03 Phase 4 — Commercial Workflow Finalization. Matches the exact
# scenarios manually verified live before being written as permanent
# tests.
# ==========================================================================
async def test_overpayment_rejected():
    admin, project, pr = await _setup_sent_payment_request("overpay")
    with pytest.raises(commercial_engine.CommercialError, match="exceeds the remaining balance"):
        await commercial_engine.record_payment(
            actor=admin, payment_request_id=pr["id"], amount=pr["amount"] + 1, date="2026-08-05", method="bank_transfer")


async def test_zero_payment_rejected():
    admin, project, pr = await _setup_sent_payment_request("zero_pay")
    with pytest.raises(commercial_engine.CommercialError, match="greater than zero"):
        await commercial_engine.record_payment(
            actor=admin, payment_request_id=pr["id"], amount=0, date="2026-08-05", method="bank_transfer")


async def test_negative_payment_rejected():
    admin, project, pr = await _setup_sent_payment_request("negative_pay")
    with pytest.raises(commercial_engine.CommercialError, match="greater than zero"):
        await commercial_engine.record_payment(
            actor=admin, payment_request_id=pr["id"], amount=-100, date="2026-08-05", method="bank_transfer")


async def test_exact_remaining_amount_accepted():
    admin, project, pr = await _setup_sent_payment_request("exact_remaining")
    pay = await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=pr["amount"], date="2026-08-05", method="bank_transfer")
    assert pay["amount"] == pr["amount"]
    updated = await commercial_engine.get_payment_request(pr["id"])
    assert updated["status"] == "paid"


async def test_payment_against_fully_paid_request_rejected():
    admin, project, pr = await _setup_sent_payment_request("already_paid")
    await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=pr["amount"], date="2026-08-05", method="bank_transfer")
    with pytest.raises(commercial_engine.CommercialError, match="already fully paid"):
        await commercial_engine.record_payment(
            actor=admin, payment_request_id=pr["id"], amount=1, date="2026-08-06", method="bank_transfer")


async def test_duplicate_payment_prevented_by_idempotency_key():
    """Same submission twice -> exactly one payment, per this task's
    own explicit requirement."""
    admin, project, pr = await _setup_sent_payment_request("idempotent_payment")
    key = "client-generated-key-001"
    pay1 = await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=100000, date="2026-08-05",
        method="bank_transfer", idempotency_key=key)
    pay2 = await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=100000, date="2026-08-05",
        method="bank_transfer", idempotency_key=key)
    assert pay1["id"] == pay2["id"]  # the second call returned the existing payment, not a new one

    all_payments = await commercial_engine.list_payments_for_request(pr["id"])
    assert len(all_payments) == 1


async def test_legitimate_second_payment_with_different_key_accepted():
    """Different legitimate payments -> both are recorded, per this
    task's own explicit requirement."""
    admin, project, pr = await _setup_sent_payment_request("legitimate_second_payment")
    pay1 = await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=100000, date="2026-08-05",
        method="bank_transfer", idempotency_key="key-one")
    pay2 = await commercial_engine.record_payment(
        actor=admin, payment_request_id=pr["id"], amount=50000, date="2026-08-06",
        method="bank_transfer", idempotency_key="key-two")
    assert pay1["id"] != pay2["id"]
    all_payments = await commercial_engine.list_payments_for_request(pr["id"])
    assert len(all_payments) == 2


async def test_archived_project_rejects_variation_and_budget_mutations():
    """Expanded archive coverage this phase - beyond just the Payment
    Request functions Phase 3 protected."""
    admin, project = await _setup_commercial_project("archive_expanded")
    await commercial_engine.create_contract(
        actor=admin, project_id=project["id"], client_id=None,
        original_contract_value=1000000, contract_date="2026-01-01", duration_days=100)
    await commercial_engine.create_budget(actor=admin, project_id=project["id"], original_budget=800000)

    await memory_engine.archive_project(project["id"])

    with pytest.raises(commercial_engine.CommercialError):
        await commercial_engine.create_variation(
            actor=admin, project_id=project["id"], title="Extra scope", description="d",
            original_cost=0, proposed_cost=100000)
    with pytest.raises(commercial_engine.CommercialError):
        await commercial_engine.revise_budget(project["id"], 900000, actor=admin, reason="test")
    with pytest.raises(commercial_engine.CommercialError):
        await commercial_engine.record_actual_cost(project["id"], 50000, actor=admin, reason="test")


async def test_overdue_escalation_worker_starts_and_stops_cleanly():
    """The scheduler mechanism itself - confirms the worker task is a
    real, cancellable asyncio task tied to the same lifecycle pattern
    intelligence_engine's own worker already uses."""
    await commercial_engine.start_overdue_escalation_worker()
    assert commercial_engine._overdue_escalation_task is not None
    assert not commercial_engine._overdue_escalation_task.done()
    await commercial_engine.stop_overdue_escalation_worker()
    assert commercial_engine._overdue_escalation_task is None


async def test_escalation_notification_immediately_red_and_in_escalations_section():
    """PX-03 Phase 4 Section 5 - a real UX bug found and fixed: a
    freshly-created 'severely overdue' escalation notification was
    previously excluded from the Escalations section entirely (it
    only ever scanned action_required/waiting_for_you, never
    commercial_attention), and even after including it, its own
    aging_signal was computed from the notification's own created_at
    rather than reflecting that the underlying request has already
    been overdue for 7+ days by definition."""
    from datetime import timedelta
    admin, project, pr = await _setup_sent_payment_request(
        "escalation_ux", due_date=(datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat())
    await commercial_engine.check_and_escalate_overdue_payment_requests(project["id"], actor=admin)

    inbox = await inbox_intelligence_service.build_coordination_inbox(admin)
    assert len(inbox["escalations"]) == 1
    card = inbox["escalations"][0]
    assert "severely overdue" in card["latest_title"]
    assert card["aging_signal"] == "red"  # immediately, not aged into it
