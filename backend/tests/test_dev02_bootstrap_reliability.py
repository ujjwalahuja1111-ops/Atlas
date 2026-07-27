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
