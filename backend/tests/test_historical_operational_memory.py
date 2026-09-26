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
