"""Historical Operational Memory sprint tests — actor_history().

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Covers the identity investigation's own finding: Atlas has no
supplier/vendor/external-party entity model at all (confirmed by
direct inspection — no matching collection or id field anywhere).
attributed_to is raw, unnormalized, LLM-extracted text; assigned_to_
user_id is a real, validated Atlas account. actor_history() treats
these as genuinely different strengths of identity rather than
pretending they're equivalent (Outcome B, per the sprint's own brief) -
project-scoped only, descriptive counts, every number traceable back
to real items, never a score or ranking.

Run from backend/:  python -m pytest tests/test_historical_operational_memory.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_historical_memory_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_historical_memory_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine  # noqa: E402

for _mod in (memory_engine, operations_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


PM = {"id": "u_hom_pm", "name": "HOM PM", "role": "project_manager"}
ACTOR = {"id": "u_hom_actor", "name": "HOM Actor"}


def _iso(dt):
    return dt.isoformat()


async def _make_project(name: str) -> dict:
    return await memory_engine.insert_project(name=name, code=name.replace(" ", "").upper()[:8])


async def _make_fulfilled_item(project_id, site_id, *, required_by, completed_at,
                                title, attributed_to=None, assigned_to=None,
                                category="material_requirement"):
    item = await operations_engine.create_item(
        actor=ACTOR, site_id=site_id, category=category, title=title,
        required_by=required_by, assigned_to_user=assigned_to)
    extra = {"status": "fulfilled", "completed_at": completed_at}
    if attributed_to:
        extra["attributed_to"] = attributed_to
    await _mock_db.operational_items.update_one({"id": item["id"]}, {"$set": extra})
    item.update(extra)
    return item


async def _make_open_item(project_id, site_id, *, title, attributed_to=None):
    item = await operations_engine.create_item(
        actor=ACTOR, site_id=site_id, category="material_requirement", title=title)
    if attributed_to:
        await _mock_db.operational_items.update_one(
            {"id": item["id"]}, {"$set": {"attributed_to": attributed_to}})
        item["attributed_to"] = attributed_to
    return item


# ==========================================================================
# actor_history() — attributed_to path (the weaker, honest identity).
# ==========================================================================

async def test_attributed_to_aggregation_counts_on_time_and_late():
    project = await _make_project("HOM Attributed Aggregation Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    required = _iso(now - timedelta(days=10))
    await _make_fulfilled_item(project["id"], site["id"], required_by=required,
                                completed_at=required, title="On time 1",
                                attributed_to="ABC Supplier")
    required2 = _iso(now - timedelta(days=5))
    await _make_fulfilled_item(project["id"], site["id"], required_by=required2,
                                completed_at=required2, title="On time 2",
                                attributed_to="ABC Supplier")
    required3 = _iso(now - timedelta(days=8))
    late3 = _iso(now - timedelta(days=5))  # 3 days late
    await _make_fulfilled_item(project["id"], site["id"], required_by=required3,
                                completed_at=late3, title="Late one",
                                attributed_to="ABC Supplier")

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="ABC Supplier")
    assert result["total_commitments"] == 3
    assert result["fulfilled_count"] == 3
    assert result["on_time_count"] == 2
    assert result["late_count"] == 1
    assert result["total_days_late"] == 3
    assert len(result["items"]) == 3  # every number traceable back to real items


async def test_attributed_to_exact_match_only_no_fuzzy():
    project = await _make_project("HOM Exact Match Only Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="ABC item", attributed_to="ABC Supplier")
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Different item", attributed_to="ABC Supplier Co")  # different string

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="ABC Supplier")
    assert result["total_commitments"] == 1  # the "Co" variant is NOT matched - no fuzzy matching


async def test_attributed_to_identity_note_states_the_limitation():
    project = await _make_project("HOM Identity Note Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="Nobody Yet")
    assert "not a verified" in result["identity_note"].lower()


# ==========================================================================
# actor_history() — assigned_to_user_id path (the stronger identity).
# ==========================================================================

async def test_assigned_to_user_id_aggregation():
    project = await _make_project("HOM Assigned User Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    rahul = {"id": "u_hom_rahul", "name": "Rahul", "role": "site_supervisor"}
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Rahul joins release", assigned_to=rahul, category="commitment")

    result = await operations_engine.actor_history(project["id"], user=PM, assigned_to_user_id=rahul["id"])
    assert result["total_commitments"] == 1
    assert result["on_time_count"] == 1
    assert "real, registered Atlas user account" in result["identity_note"]


async def test_assigned_to_user_id_and_attributed_to_are_distinct_scopes():
    """An item assigned to Rahul but with no attributed_to must not
    appear in an attributed_to query for his own name, and vice versa
    - the two identity paths never silently merge."""
    project = await _make_project("HOM Distinct Scopes Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    rahul = {"id": "u_hom_rahul2", "name": "Rahul Two", "role": "site_supervisor"}
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Assigned only", assigned_to=rahul, category="commitment")

    by_user = await operations_engine.actor_history(project["id"], user=PM, assigned_to_user_id=rahul["id"])
    assert by_user["total_commitments"] == 1
    by_text = await operations_engine.actor_history(project["id"], user=PM, attributed_to="Rahul Two")
    assert by_text["total_commitments"] == 0  # no attributed_to was ever set on this item


# ==========================================================================
# Traceability, honesty, never fabricated.
# ==========================================================================

async def test_still_open_item_counted_separately_not_as_fulfilled():
    project = await _make_project("HOM Still Open Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    await _make_open_item(project["id"], site["id"], title="Still open", attributed_to="XYZ Supplier")

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="XYZ Supplier")
    assert result["total_commitments"] == 1
    assert result["fulfilled_count"] == 0
    assert result["still_open_count"] == 1
    assert result["on_time_count"] == 0
    assert result["late_count"] == 0


async def test_no_commitments_returns_honest_zero_not_an_error():
    project = await _make_project("HOM No Commitments Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="Never Mentioned")
    assert result["total_commitments"] == 0
    assert result["items"] == []


async def test_exactly_one_identifier_required():
    project = await _make_project("HOM One Identifier Required Project")
    with pytest.raises(ValueError):
        await operations_engine.actor_history(project["id"], user=PM)
    with pytest.raises(ValueError):
        await operations_engine.actor_history(project["id"], user=PM, attributed_to="X", assigned_to_user_id="y")


# ==========================================================================
# RBAC.
# ==========================================================================

async def test_client_role_denied():
    project = await _make_project("HOM Client Denied Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    client_user = {"id": "u_hom_client", "name": "HOM Client", "role": "client"}
    with pytest.raises(ValueError):
        await operations_engine.actor_history(project["id"], user=client_user, attributed_to="Anyone")


async def test_pm_and_management_allowed():
    project = await _make_project("HOM PM Allowed Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    management = {"id": "u_hom_mgmt", "name": "HOM Mgmt", "role": "management"}
    result_pm = await operations_engine.actor_history(project["id"], user=PM, attributed_to="Anyone")
    result_mgmt = await operations_engine.actor_history(project["id"], user=management, attributed_to="Anyone")
    assert result_pm["total_commitments"] == 0  # ran without error
    assert result_mgmt["total_commitments"] == 0


# ==========================================================================
# Cross-domain — all three universal domains use the identical mechanism.
# ==========================================================================

async def test_cross_domain_construction_software_hospitality():
    project = await _make_project("HOM Cross Domain Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    late_completed = _iso(now)

    # Construction - ABC Supplier, late
    await _make_fulfilled_item(
        project["id"], site["id"], required_by=_iso(now - timedelta(days=2)),
        completed_at=late_completed, title="Tiles", attributed_to="ABC Supplier")
    # Hospitality - Food Co, on time
    await _make_fulfilled_item(
        project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
        title="Chicken", attributed_to="Food Co")
    # Software - a real assigned user
    priya = {"id": "u_hom_priya", "name": "Priya", "role": "site_supervisor"}
    await _make_fulfilled_item(
        project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
        title="Priya joins", assigned_to=priya, category="commitment")

    construction = await operations_engine.actor_history(project["id"], user=PM, attributed_to="ABC Supplier")
    hospitality = await operations_engine.actor_history(project["id"], user=PM, attributed_to="Food Co")
    software = await operations_engine.actor_history(project["id"], user=PM, assigned_to_user_id=priya["id"])

    assert construction["late_count"] == 1
    assert hospitality["on_time_count"] == 1
    assert software["on_time_count"] == 1
    # Same function, same shape, same fields - no construction-specific branching.
    assert set(construction.keys()) == set(hospitality.keys()) == set(software.keys())


# ==========================================================================
# Fix 1 — no silent truncation. Aggregate counts must be correct over
# the COMPLETE matching set, however large; only the traceable `items`
# list is paginated, explicitly, with has_more/items_total saying so.
# ==========================================================================

async def test_more_than_500_matching_items_produce_correct_total():
    """The exact regression this fix targets: the previous .to_list(500)
    would have silently truncated both the total and every derived
    count for any actor with more than 500 matching items."""
    project = await _make_project("HOM Over 500 Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    # 520 fulfilled-on-time items + 30 late items = 550 total, well
    # past the old hard cap.
    for i in range(520):
        required = _iso(now - timedelta(days=1))
        await _make_fulfilled_item(project["id"], site["id"], required_by=required,
                                    completed_at=required, title=f"On time {i}",
                                    attributed_to="Bulk Supplier")
    for i in range(30):
        required = _iso(now - timedelta(days=5))
        late = _iso(now - timedelta(days=3))
        await _make_fulfilled_item(project["id"], site["id"], required_by=required,
                                    completed_at=late, title=f"Late {i}",
                                    attributed_to="Bulk Supplier")

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="Bulk Supplier")
    assert result["total_commitments"] == 550
    assert result["fulfilled_count"] == 550
    assert result["on_time_count"] == 520
    assert result["late_count"] == 30
    assert result["items_total"] == 550


async def test_items_list_paginated_but_counts_remain_complete():
    project = await _make_project("HOM Pagination Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    for i in range(150):
        required = _iso(now)
        await _make_fulfilled_item(project["id"], site["id"], required_by=required,
                                    completed_at=required, title=f"Item {i}",
                                    attributed_to="Paginated Supplier")

    page1 = await operations_engine.actor_history(
        project["id"], user=PM, attributed_to="Paginated Supplier", items_limit=100, items_offset=0)
    assert page1["total_commitments"] == 150  # the count is always complete
    assert len(page1["items"]) == 100  # the page is limited
    assert page1["has_more"] is True
    assert page1["items_total"] == 150

    page2 = await operations_engine.actor_history(
        project["id"], user=PM, attributed_to="Paginated Supplier", items_limit=100, items_offset=100)
    assert len(page2["items"]) == 50
    assert page2["has_more"] is False
    assert page2["total_commitments"] == 150  # counts identical across pages - never recomputed partially


# ==========================================================================
# Fix 2 — semantic boundary. total_commitments must only reflect
# ACTOR_COMMITMENT_CATEGORIES; observations and undefined catch-alls
# must never be counted as if they were promises the actor made.
# ==========================================================================

async def test_site_issue_excluded_from_actor_commitments():
    """A safety/quality observation assigned to someone is not their
    "commitment" - it's a problem assigned to them to resolve, a
    different thing entirely. Must not inflate their commitment count."""
    project = await _make_project("HOM Site Issue Excluded Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Exposed rebar", attributed_to="ABC Supplier",
                                category="site_issue")

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="ABC Supplier")
    assert result["total_commitments"] == 0


async def test_general_category_excluded_from_actor_commitments():
    project = await _make_project("HOM General Excluded Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Vague note", attributed_to="ABC Supplier",
                                category="general")

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="ABC Supplier")
    assert result["total_commitments"] == 0


async def test_follow_up_excluded_from_actor_commitments():
    project = await _make_project("HOM Follow Up Excluded Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Follow up with supplier", attributed_to="ABC Supplier",
                                category="follow_up")

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="ABC Supplier")
    assert result["total_commitments"] == 0


async def test_client_approval_and_material_requirement_both_included():
    """The defensible core: material_requirement (a supplier's own
    delivery promise) and client_approval (a client's own obligation
    to respond) are genuinely different kinds of obligation but both
    legitimately count as something the actor owed."""
    project = await _make_project("HOM Mixed Valid Categories Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Deliver tiles", attributed_to="ABC Supplier",
                                category="material_requirement")
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Approve layout", attributed_to="ABC Supplier",
                                category="client_approval")

    result = await operations_engine.actor_history(project["id"], user=PM, attributed_to="ABC Supplier")
    assert result["total_commitments"] == 2


async def test_actor_commitment_categories_is_a_strict_subset_of_categories():
    """The filter must only ever reference real, existing category
    values - never invent a new one."""
    assert operations_engine.ACTOR_COMMITMENT_CATEGORIES.issubset(operations_engine.CATEGORIES)
    assert operations_engine.ACTOR_COMMITMENT_CATEGORIES < operations_engine.CATEGORIES  # a strict subset, not everything


# ==========================================================================
# find_users_by_name_substring() — the 1000-user ceiling this review
# flagged. Exercises the actual name-resolution path (not merely
# inspecting the implementation) with more than 1000 users in the
# database, where the one genuinely matching user is inserted LAST -
# exactly the case that would have been silently omitted by the old
# .to_list(1000) cap, since find() with no explicit sort gives no
# ordering guarantee about which 1000 of 1000+ documents come back.
# ==========================================================================

class _CappingCursor:
    """Wraps a real cursor and enforces to_list(N) truncation exactly
    as real MongoDB/motor does. mongomock_motor's own cursor does NOT
    enforce this (confirmed by direct testing: to_list(1000) against
    1051 documents returned all 1051) - so a test using the real
    cursor as-is cannot distinguish the fixed implementation from the
    old, buggy one. This wrapper makes the distinction real: it only
    matters whether find_users_by_name_substring()'s own QUERY already
    narrowed the result set before to_list() is called, or whether it
    fetches everything and filters in Python afterward.
    """
    def __init__(self, real_cursor):
        self._real_cursor = real_cursor

    async def to_list(self, length):
        docs = await self._real_cursor.to_list(None)
        if length is not None:
            docs = docs[:length]
        return docs


async def test_user_lookup_immune_to_a_real_cursor_cap():
    """Direct proof the fix works, not merely that mongomock happens
    not to enforce the old cap. A real cap (via _CappingCursor above)
    is applied to whatever db.users.find() itself returns. Under the
    OLD implementation (find({}) - everything, unfiltered, then
    filtered in Python) a cap of 1000 against 1051 total users could
    truncate before reaching the one real match. Under the FIXED
    implementation (find({"name": {"$regex": ...}}) - already
    filtered to only matching documents before to_list is even called)
    the same cap is irrelevant, because only the genuine matches were
    ever fetched."""
    for i in range(1050):
        await memory_engine.upsert_user(
            phone=f"72000{i:05d}", name=f"Padding {i}", role="site_supervisor")
    real_user = await memory_engine.upsert_user(
        phone="7777777777", name="Rahul Distinct Name", role="site_supervisor")

    real_find = type(_mock_db.users).find
    def capped_find(self, *args, **kwargs):
        return _CappingCursor(real_find(self, *args, **kwargs))
    type(_mock_db.users).find = capped_find
    try:
        matches = await memory_engine.find_users_by_name_substring("Rahul Distinct")
    finally:
        type(_mock_db.users).find = real_find

    matched_ids = {u["id"] for u in matches}
    assert real_user["id"] in matched_ids
    assert len(matches) == 1


async def test_user_lookup_finds_match_beyond_old_1000_cap():
    """A more ordinary end-to-end check at scale: >1000 total users,
    the one real match inserted last, resolved correctly."""
    for i in range(1050):
        await memory_engine.upsert_user(
            phone=f"70000{i:05d}", name=f"Filler User {i}", role="site_supervisor")
    real_user = await memory_engine.upsert_user(
        phone="7999999999", name="Zorvath Quennelly", role="site_supervisor")

    matches = await memory_engine.find_users_by_name_substring("Zorvath")
    matched_ids = {u["id"] for u in matches}
    assert real_user["id"] in matched_ids
    assert len(matches) == 1  # no "Zorvath" substring among the 1050 filler names


async def test_actor_history_intent_resolves_user_beyond_old_1000_cap():
    """The full, real query_actor_history path (not just the lookup
    function in isolation) still correctly resolves a legitimate user
    past the old cap."""
    project = await _make_project("HOM Beyond Cap Full Path Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    for i in range(1050):
        await memory_engine.upsert_user(
            phone=f"71000{i:05d}", name=f"Padding Person {i}", role="site_supervisor")
    priya = await memory_engine.upsert_user(
        phone="7888888888", name="Priya Sharma", role="site_supervisor")
    now = datetime.now(timezone.utc)
    await _make_fulfilled_item(project["id"], site["id"], required_by=_iso(now), completed_at=_iso(now),
                                title="Priya's task", assigned_to=priya, category="commitment")

    from services import intent_service
    from unittest.mock import AsyncMock
    intent_service._run_structuring_pass = AsyncMock(return_value={
        "intents": [{"intent": "query_actor_history", "confidence": "high"}],
        "project_reference": None, "attributed_actor_reference": "Priya"})
    result = await intent_service.handle_intent(
        "has Priya done her work?", user=PM, active_project_id=project["id"])
    assert result["result"]["ok"] is True
    assert result["result"]["data"]["assigned_to_user_id"] == priya["id"]
