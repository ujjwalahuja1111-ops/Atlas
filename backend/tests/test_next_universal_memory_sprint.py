"""Next Universal Memory Sprint tests — fulfilled_on_time/days_late.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Covers the real gap this sprint found: required_by (the promise) and
completed_at (the actual outcome) both already existed on every
operational item, and nothing anywhere compared them - confirmed by
direct inspection (compute_metrics() computed days_overdue, time_to_
complete_hours, verification_delay_hours, but never a promised-vs-
actual comparison at all). Date-only comparison (not full timestamps),
researched directly against Jira's own established due-date/resolved-
date pattern and its own documented pitfall of flagging same-day
completions as "late" over a few hours' difference.

Run from backend/:  python -m pytest tests/test_next_universal_memory_sprint.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_next_universal_memory_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_next_universal_memory_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine  # noqa: E402

for _mod in (memory_engine, operations_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ACTOR = {"id": "u_nums_actor", "name": "NUMS Actor"}


def _iso(dt):
    return dt.isoformat()


# ==========================================================================
# compute_metrics() — direct, unit-level.
# ==========================================================================

def test_fulfilled_late_detected():
    required = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    completed = required + timedelta(days=2)
    item = {"created_at": _iso(required), "required_by": _iso(required),
            "assigned_at": None, "completed_at": _iso(completed), "verified_at": None}
    metrics = operations_engine.compute_metrics(item)
    assert metrics["fulfilled_on_time"] is False
    assert metrics["days_late"] == 2


def test_fulfilled_on_time_exact_match():
    required = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    item = {"created_at": _iso(required), "required_by": _iso(required),
            "assigned_at": None, "completed_at": _iso(required), "verified_at": None}
    metrics = operations_engine.compute_metrics(item)
    assert metrics["fulfilled_on_time"] is True
    assert metrics["days_late"] == 0


def test_fulfilled_same_calendar_day_not_flagged_late():
    """The exact pitfall found in research against Jira's own
    documented behavior: comparing full timestamps would flag a
    same-day completion a few hours after the deadline's own moment as
    late. Date-only comparison must not do this."""
    required = datetime(2026, 9, 21, 9, 0, 0, tzinfo=timezone.utc)
    completed = datetime(2026, 9, 21, 23, 0, 0, tzinfo=timezone.utc)  # same day, 14 hours later
    item = {"created_at": _iso(required), "required_by": _iso(required),
            "assigned_at": None, "completed_at": _iso(completed), "verified_at": None}
    metrics = operations_engine.compute_metrics(item)
    assert metrics["fulfilled_on_time"] is True
    assert metrics["days_late"] == 0


def test_fulfilled_early_is_on_time():
    required = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    completed = required - timedelta(days=1)
    item = {"created_at": _iso(required), "required_by": _iso(required),
            "assigned_at": None, "completed_at": _iso(completed), "verified_at": None}
    metrics = operations_engine.compute_metrics(item)
    assert metrics["fulfilled_on_time"] is True
    assert metrics["days_late"] == 0


def test_no_required_by_never_fabricated():
    completed = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    item = {"created_at": _iso(completed), "required_by": None,
            "assigned_at": None, "completed_at": _iso(completed), "verified_at": None}
    metrics = operations_engine.compute_metrics(item)
    assert metrics["fulfilled_on_time"] is None
    assert metrics["days_late"] is None


def test_not_yet_completed_never_fabricated():
    required = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    item = {"created_at": _iso(required), "required_by": _iso(required),
            "assigned_at": None, "completed_at": None, "verified_at": None}
    metrics = operations_engine.compute_metrics(item)
    assert metrics["fulfilled_on_time"] is None
    assert metrics["days_late"] is None


# ==========================================================================
# End-to-end: transition_status() -> get_item() -> compute_metrics()
# via enrich(), the real function every item-fetch route calls.
# ==========================================================================

async def test_real_transition_then_enrich_shows_late():
    site = await memory_engine.insert_site(
        project_id=(await memory_engine.insert_project(name="NUMS Project", code="NUMSPRJ"))["id"],
        name="Site")
    required = _iso(datetime.now(timezone.utc) - timedelta(days=3))
    item = await operations_engine.create_item(
        actor=ACTOR, site_id=site["id"], category="material_requirement",
        title="Late tiles", required_by=required)
    await operations_engine.transition_status(item_id=item["id"], to_status="assigned", actor=ACTOR)
    await operations_engine.transition_status(item_id=item["id"], to_status="in_progress", actor=ACTOR)
    await operations_engine.transition_status(item_id=item["id"], to_status="fulfilled", actor=ACTOR)

    fetched = await operations_engine.get_item(item["id"])
    enriched = operations_engine.enrich(fetched)
    assert enriched["metrics"]["fulfilled_on_time"] is False
    assert enriched["metrics"]["days_late"] >= 3


async def test_cross_domain_all_three_compute_correctly():
    project = await memory_engine.insert_project(name="NUMS Cross Domain Project", code="NUMSXD")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc)

    # Construction - late
    required_a = _iso(now - timedelta(days=5))
    item_a = await operations_engine.create_item(
        actor=ACTOR, site_id=site["id"], category="material_requirement",
        title="Construction tiles", required_by=required_a)
    await _mock_db.operational_items.update_one(
        {"id": item_a["id"]}, {"$set": {"status": "fulfilled",
                                          "completed_at": _iso(now - timedelta(days=3))}})

    # Software - on time
    required_b = _iso(now - timedelta(days=1))
    item_b = await operations_engine.create_item(
        actor=ACTOR, site_id=site["id"], category="commitment",
        title="Rahul joins the release", required_by=required_b)
    await _mock_db.operational_items.update_one(
        {"id": item_b["id"]}, {"$set": {"status": "fulfilled", "completed_at": required_b}})

    # Hospitality - early
    required_c = _iso(now + timedelta(days=2))
    item_c = await operations_engine.create_item(
        actor=ACTOR, site_id=site["id"], category="material_requirement",
        title="Chicken delivery", required_by=required_c)
    await _mock_db.operational_items.update_one(
        {"id": item_c["id"]}, {"$set": {"status": "fulfilled",
                                          "completed_at": _iso(now + timedelta(days=1))}})

    for item_id, expect_on_time in [(item_a["id"], False), (item_b["id"], True), (item_c["id"], True)]:
        fetched = await operations_engine.get_item(item_id)
        metrics = operations_engine.compute_metrics(fetched)
        assert metrics["fulfilled_on_time"] is expect_on_time
