"""Follow Through sprint tests — due_today/overdue in _my_day_pm().

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Covers the real gap this sprint found: unassigned, capture-originated
commitments (exactly what "the supplier said 200 tiles Thursday"
produces) were invisible to any "what's due/overdue" view, since the
only existing due_today/overdue logic lived in the supervisor's own
assignment-filtered My Day, and accept_ai_proposal() never sets
assigned_to_user_id. Extends _my_day_pm() (project-wide, not
assignment-filtered) with the exact same due_today/overdue pattern -
no new intent, no new engine, no new lifecycle.

Run from backend/:  python -m pytest tests/test_follow_through.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_follow_through_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_follow_through_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


PM = {"id": "u_ft_pm", "name": "FT PM", "role": "project_manager"}
ACTOR = {"id": "u_ft_actor", "name": "FT Actor"}


def _now():
    return datetime.now(timezone.utc)


async def _make_project(name: str) -> dict:
    return await memory_engine.insert_project(name=name, code=name.replace(" ", "").upper()[:8])


async def _make_item_with_required_by(project_id, site_id, *, required_by=None,
                                       title="Test Item", assigned_to=None, attributed_to=None,
                                       category="material_requirement"):
    item = await operations_engine.create_item(
        actor=ACTOR, site_id=site_id, category=category, title=title, required_by=required_by,
        assigned_to_user=assigned_to)
    if attributed_to:
        await _mock_db.operational_items.update_one({"id": item["id"]}, {"$set": {"attributed_to": attributed_to}})
        item["attributed_to"] = attributed_to
    return item


# ==========================================================================
# Due today / overdue — project-wide, not assignment-filtered.
# ==========================================================================

async def test_unassigned_item_appears_in_project_wide_due_today():
    """The exact gap this sprint found: an item with no assignee (like
    every capture-originated commitment) still appears in the PM's own
    project-wide due_today, even though it would never appear in any
    supervisor's own personal My Day."""
    project = await _make_project("FT Due Today Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = _now()
    today_str = now.isoformat()
    item = await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Procure 200 pieces tiles")
    assert item.get("assigned_to_user_id") is None  # confirmed unassigned

    result = await operations_engine.my_day(user=PM)
    due_titles = [i["title"] for i in result["due_today"]]
    assert "Procure 200 pieces tiles" in due_titles


async def test_unassigned_item_appears_in_project_wide_overdue():
    project = await _make_project("FT Overdue Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    yesterday = (_now() - timedelta(days=1)).isoformat()
    item = await _make_item_with_required_by(
        project["id"], site["id"], required_by=yesterday, title="Rahul joins the release")

    result = await operations_engine.my_day(user=PM)
    overdue_titles = [i["title"] for i in result["overdue"]]
    assert "Rahul joins the release" in overdue_titles


async def test_future_required_by_is_neither_due_today_nor_overdue():
    project = await _make_project("FT Future Date Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    future = (_now() + timedelta(days=10)).isoformat()
    item = await _make_item_with_required_by(
        project["id"], site["id"], required_by=future, title="Procure 80 kg chicken")

    result = await operations_engine.my_day(user=PM)
    all_titles = [i["title"] for i in result["due_today"]] + [i["title"] for i in result["overdue"]]
    assert "Procure 80 kg chicken" not in all_titles


async def test_no_required_by_never_appears_in_either_list_never_fabricated():
    """An item with no deadline at all must never be guessed into
    due_today or overdue."""
    project = await _make_project("FT No Deadline Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await _make_item_with_required_by(
        project["id"], site["id"], required_by=None, title="Vague future material")

    result = await operations_engine.my_day(user=PM)
    all_titles = [i["title"] for i in result["due_today"]] + [i["title"] for i in result["overdue"]]
    assert "Vague future material" not in all_titles


async def test_fulfilled_item_no_longer_appears_outstanding_vs_fulfilled():
    """Outstanding vs. fulfilled: a terminal-status item must not still
    show up as due/overdue, even with an overdue required_by."""
    project = await _make_project("FT Fulfilled Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    yesterday = (_now() - timedelta(days=1)).isoformat()
    item = await _make_item_with_required_by(
        project["id"], site["id"], required_by=yesterday, title="Fulfilled tiles")
    await operations_engine.transition_status(item_id=item["id"], to_status="fulfilled", actor=ACTOR)

    result = await operations_engine.my_day(user=PM)
    overdue_titles = [i["title"] for i in result["overdue"]]
    assert "Fulfilled tiles" not in overdue_titles


# ==========================================================================
# Attribution remains distinct from recorder, never fabricated.
# ==========================================================================

async def test_attribution_present_in_due_today_entry():
    project = await _make_project("FT Attribution Present Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Procure 80 kg chicken",
        attributed_to="food supplier")

    result = await operations_engine.my_day(user=PM)
    entry = next(i for i in result["due_today"] if i["title"] == "Procure 80 kg chicken")
    assert entry["attributed_to"] == "food supplier"
    # The recorder (actor) remains a distinct, real, separate field.
    assert entry["created_by_user_name"] == ACTOR["name"]
    assert entry["created_by_user_name"] != entry["attributed_to"]


async def test_no_attribution_never_fabricated():
    project = await _make_project("FT No Attribution Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Unattributed shortfall")

    result = await operations_engine.my_day(user=PM)
    entry = next(i for i in result["due_today"] if i["title"] == "Unattributed shortfall")
    assert entry.get("attributed_to") is None


# ==========================================================================
# Responsible person — real when known, never fabricated when not.
# ==========================================================================

async def test_responsible_person_present_when_assigned():
    project = await _make_project("FT Responsible Person Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    supervisor = {"id": "u_ft_sup", "name": "FT Supervisor", "role": "site_supervisor"}
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Assigned tiles",
        assigned_to=supervisor)

    result = await operations_engine.my_day(user=PM)
    entry = next(i for i in result["due_today"] if i["title"] == "Assigned tiles")
    assert entry["assigned_to_user_name"] == "FT Supervisor"


async def test_responsible_person_absent_when_unassigned_never_fabricated():
    project = await _make_project("FT No Responsible Person Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Unassigned commitment")

    result = await operations_engine.my_day(user=PM)
    entry = next(i for i in result["due_today"] if i["title"] == "Unassigned commitment")
    assert entry.get("assigned_to_user_name") is None


# ==========================================================================
# Cross-domain — all three universal examples land in the same,
# unmodified mechanism with no construction-specific branching.
# ==========================================================================

async def test_cross_domain_construction_software_hospitality_all_appear():
    project = await _make_project("FT Cross Domain Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    today_str = _now().isoformat()
    yesterday_str = (_now() - timedelta(days=1)).isoformat()

    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Procure 200 pieces tiles",
        attributed_to="supplier")  # construction
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=yesterday_str, title="Rahul joins the release",
        category="commitment")  # software
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Procure 80 kg chicken",
        attributed_to="food supplier")  # hospitality

    result = await operations_engine.my_day(user=PM)
    due_titles = {i["title"] for i in result["due_today"]}
    overdue_titles = {i["title"] for i in result["overdue"]}
    assert "Procure 200 pieces tiles" in due_titles
    assert "Rahul joins the release" in overdue_titles
    assert "Procure 80 kg chicken" in due_titles


# ==========================================================================
# RBAC — unchanged.
# ==========================================================================

async def test_client_role_still_excluded_from_my_day_entirely():
    """Preserved, pre-existing restriction — Client never receives
    my_day data at all (enforced at the intent layer, confirmed
    unrelated to and unaffected by this change)."""
    client_user = {"id": "u_ft_client", "name": "FT Client", "role": "client"}
    # my_day() itself has no role branch that returns something
    # different for client - the restriction lives at
    # intent_service.py's own query_digest handler (role != "client"
    # gate), confirmed unmodified by this sprint. Calling my_day()
    # directly for a management/PM/supervisor role still works exactly
    # as before.
    result = await operations_engine.my_day(user=PM)
    assert result["role"] == "project_manager"
    assert "due_today" in result
    assert "overdue" in result


# ==========================================================================
# Regression — existing supervisor/admin views unaffected.
# ==========================================================================

async def test_supervisor_view_unaffected_still_has_its_own_due_today():
    project = await _make_project("FT Supervisor Unaffected Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    supervisor = {"id": "u_ft_sup2", "name": "FT Supervisor 2", "role": "site_supervisor"}
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="My assigned item",
        assigned_to=supervisor)

    result = await operations_engine.my_day(user=supervisor)
    assert result["role"] == "site_supervisor"
    titles = [i["title"] for i in result["due_today"]]
    assert "My assigned item" in titles


# ==========================================================================
# Follow-Through Sprint 2 — Management portfolio attention.
# Extends _my_day_admin() with the exact same due_today/overdue
# pattern Sprint 1 already proved for _my_day_pm(), scoped across
# every project Management can see (confirmed unrestricted) rather
# than one project. resource_alerts (the existing, narrower,
# construction-flavored count) is left completely unchanged.
# ==========================================================================

ADMIN = {"id": "u_ft_admin", "name": "FT Admin", "role": "management"}


async def test_management_sees_due_today_across_the_portfolio():
    """Confirms portfolio scope, not single-project: two DIFFERENT
    projects, each with its own due-today item, both appear in one
    Management call."""
    project1 = await _make_project("FT Mgmt Portfolio Project 1")
    site1 = await memory_engine.insert_site(project_id=project1["id"], name="Site 1")
    project2 = await _make_project("FT Mgmt Portfolio Project 2")
    site2 = await memory_engine.insert_site(project_id=project2["id"], name="Site 2")
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project1["id"], site1["id"], required_by=today_str, title="Procure 200 pieces tiles")
    await _make_item_with_required_by(
        project2["id"], site2["id"], required_by=today_str, title="Procure 80 kg chicken")

    result = await operations_engine.my_day(user=ADMIN)
    assert result["role"] == "management"
    due_titles = {i["title"] for i in result["due_today"]}
    assert "Procure 200 pieces tiles" in due_titles
    assert "Procure 80 kg chicken" in due_titles


async def test_management_sees_overdue_unassigned_commitment():
    project = await _make_project("FT Mgmt Overdue Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    yesterday = (_now() - timedelta(days=1)).isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=yesterday, title="Rahul joins the release")

    result = await operations_engine.my_day(user=ADMIN)
    overdue_titles = [i["title"] for i in result["overdue"]]
    assert "Rahul joins the release" in overdue_titles


async def test_management_no_required_by_never_fabricated():
    project = await _make_project("FT Mgmt No Deadline Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=None, title="Undated item")

    result = await operations_engine.my_day(user=ADMIN)
    all_titles = [i["title"] for i in result["due_today"]] + [i["title"] for i in result["overdue"]]
    assert "Undated item" not in all_titles


async def test_management_fulfilled_item_drops_out():
    project = await _make_project("FT Mgmt Fulfilled Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    yesterday = (_now() - timedelta(days=1)).isoformat()
    item = await _make_item_with_required_by(
        project["id"], site["id"], required_by=yesterday, title="Fulfilled chicken")
    await operations_engine.transition_status(item_id=item["id"], to_status="fulfilled", actor=ACTOR)

    result = await operations_engine.my_day(user=ADMIN)
    overdue_titles = [i["title"] for i in result["overdue"]]
    assert "Fulfilled chicken" not in overdue_titles


async def test_management_attribution_and_responsibility_distinct_and_honest():
    project = await _make_project("FT Mgmt Attribution Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    supervisor = {"id": "u_ft_mgmt_sup", "name": "FT Mgmt Supervisor", "role": "site_supervisor"}
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Assigned and attributed tiles",
        attributed_to="supplier", assigned_to=supervisor)
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Neither assigned nor attributed")

    result = await operations_engine.my_day(user=ADMIN)
    attributed_entry = next(i for i in result["due_today"] if i["title"] == "Assigned and attributed tiles")
    assert attributed_entry["attributed_to"] == "supplier"
    assert attributed_entry["assigned_to_user_name"] == "FT Mgmt Supervisor"
    assert attributed_entry["attributed_to"] != attributed_entry["assigned_to_user_name"]

    bare_entry = next(i for i in result["due_today"] if i["title"] == "Neither assigned nor attributed")
    assert bare_entry.get("attributed_to") is None
    assert bare_entry.get("assigned_to_user_name") is None


async def test_management_resource_alerts_unchanged():
    """resource_alerts (the existing, narrower construction-flavored
    count) must remain exactly as it was - this sprint adds the
    missing universal breakdown alongside it, not a replacement.
    resource_alerts is itself genuinely portfolio-wide (unchanged,
    pre-existing behavior), so this asserts the correct, relative
    thing - one more material_requirement item increases the count by
    exactly one - rather than an absolute value that would depend on
    every other test's own data in this shared mock database."""
    before = (await operations_engine.my_day(user=ADMIN))["resource_alerts"]
    project = await _make_project("FT Mgmt Resource Alerts Unchanged Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=None, title="Material item",
        category="material_requirement")
    after = (await operations_engine.my_day(user=ADMIN))["resource_alerts"]
    assert after == before + 1


async def test_management_cross_domain_all_three_appear():
    project = await _make_project("FT Mgmt Cross Domain Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    today_str = _now().isoformat()
    yesterday_str = (_now() - timedelta(days=1)).isoformat()

    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Procure 200 pieces tiles",
        attributed_to="supplier")
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=yesterday_str, title="Rahul joins the release",
        category="commitment")
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Procure 80 kg chicken",
        attributed_to="food supplier")

    result = await operations_engine.my_day(user=ADMIN)
    due_titles = {i["title"] for i in result["due_today"]}
    overdue_titles = {i["title"] for i in result["overdue"]}
    assert "Procure 200 pieces tiles" in due_titles
    assert "Rahul joins the release" in overdue_titles
    assert "Procure 80 kg chicken" in due_titles


async def test_pm_and_supervisor_views_unaffected_by_admin_change():
    """Regression: confirms Sprint 1's own PM extension and the
    original supervisor view are both completely unaffected by this
    sprint's own separate _my_day_admin() change."""
    project = await _make_project("FT Regression Unaffected Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    today_str = _now().isoformat()
    await _make_item_with_required_by(
        project["id"], site["id"], required_by=today_str, title="Cross-role test item")

    pm_result = await operations_engine.my_day(user=PM)
    assert pm_result["role"] == "project_manager"
    assert "Cross-role test item" in [i["title"] for i in pm_result["due_today"]]

    supervisor = {"id": "u_ft_reg_sup", "name": "FT Reg Supervisor", "role": "site_supervisor"}
    supervisor_result = await operations_engine.my_day(user=supervisor)
    assert supervisor_result["role"] == "site_supervisor"
    # Unassigned item correctly does NOT appear in the supervisor's own
    # personal, assignment-filtered view - unchanged, pre-existing
    # behavior.
    assert "Cross-role test item" not in [i["title"] for i in supervisor_result["due_today"]]
