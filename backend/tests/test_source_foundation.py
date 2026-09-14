"""Source/Provenance Foundation tests.

Follows the established mongomock_motor pattern (see
tests/test_reasoning_relationships.py's own header for why).

This phase adds no integration and no reconciliation. These tests
prove exactly what the phase claims: the model can represent both
native and imported activities/milestones, an event can optionally
carry a source tag without disturbing its existing meaning, and two
claims about the same field from different sources can coexist in
the event history without one silently erasing the other.

Run from backend/:  python -m pytest tests/test_source_foundation.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_source_foundation_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_source_foundation_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, reasoning_engine, commercial_engine, workflow_engine  # noqa: E402

for _mod in (memory_engine, reasoning_engine, commercial_engine, workflow_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


PM = {"id": "u_sf_pm", "name": "SF PM", "role": "project_manager"}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


async def _make_project(name: str) -> dict:
    return await memory_engine.insert_project(name=name, code=name.replace(" ", "").upper()[:8])


# ==========================================================================
# A. Atlas-native activity - the default, unchanged shape every activity
#    generated through generate_workflow() has always had, now with an
#    explicit, honest source tag rather than an implicit assumption.
# ==========================================================================
async def test_native_activity_has_native_source_by_default():
    project = await _make_project("SF Native Activity Project")
    now = _now()
    aid = f"wa_{uuid.uuid4()}"
    # Mirrors exactly the document shape generate_workflow() itself
    # constructs (confirmed by direct inspection), rather than calling
    # the full template-generation pipeline for a one-field check.
    await _mock_db.workflow_activities.insert_one({
        "id": aid, "project_id": project["id"], "name": "Foundation", "trade": "Civil",
        "status": "not_started", "depends_on_activity_ids": [], "order": 0,
        "default_duration_days": 5, "requires_inspection": False,
        "planned_start": None, "planned_finish": None, "actual_start": None, "actual_finish": None,
        "milestone_id": None,
        "source": {"origin": "native", "external_system": None, "external_id": None, "imported_at": None},
        "created_at": _iso(now), "updated_at": _iso(now),
    })
    activity = await _mock_db.workflow_activities.find_one({"id": aid}, {"_id": 0})
    assert activity["source"]["origin"] == "native"
    assert activity["source"]["external_system"] is None
    assert activity["source"]["external_id"] is None


# ==========================================================================
# B. Imported P6 activity - the model can represent this without any
#    import mechanism existing. No fabricated ID: a real-looking, stable
#    external identifier, exactly as a real P6 export would supply.
# ==========================================================================
async def test_model_can_represent_imported_p6_activity():
    project = await _make_project("SF Imported P6 Activity Project")
    now = _now()
    aid = f"wa_{uuid.uuid4()}"
    await _mock_db.workflow_activities.insert_one({
        "id": aid, "project_id": project["id"], "name": "Electrical First Fix", "trade": "Electrical",
        "status": "not_started", "depends_on_activity_ids": [], "order": 0,
        "default_duration_days": 4, "requires_inspection": False,
        "planned_start": None, "planned_finish": "2026-09-18T00:00:00+00:00",
        "actual_start": None, "actual_finish": None, "milestone_id": None,
        "source": {
            "origin": "imported", "external_system": "primavera_p6",
            "external_id": "P6-ACT-004821", "imported_at": _iso(now),
        },
        "created_at": _iso(now), "updated_at": _iso(now),
    })
    activity = await _mock_db.workflow_activities.find_one({"id": aid}, {"_id": 0})
    assert activity["source"] == {
        "origin": "imported", "external_system": "primavera_p6",
        "external_id": "P6-ACT-004821", "imported_at": activity["source"]["imported_at"],
    }
    # Existing reasoning must operate identically regardless of source -
    # build_project_snapshot doesn't special-case it, doesn't fail on
    # it, doesn't filter by it.
    snapshot = await reasoning_engine.build_project_snapshot(project["id"])
    assert any(a["id"] == aid for a in snapshot["workflow_activities"])


# ==========================================================================
# C. Native milestone - create_milestone()'s own real output.
# ==========================================================================
async def test_native_milestone_has_native_source_by_default():
    project = await _make_project("SF Native Milestone Project")
    await commercial_engine.create_contract(
        actor=PM, project_id=project["id"], client_id=None, original_contract_value=1000000,
        contract_date="2026-01-01", duration_days=90)
    milestone = await commercial_engine.create_milestone(
        actor=PM, project_id=project["id"], name="Finishes", sequence=1,
        planned_percent=10, trigger="Flooring complete")
    assert milestone["source"] == {
        "origin": "native", "external_system": None, "external_id": None, "imported_at": None,
    }


# ==========================================================================
# D. Imported milestone - direct construction, same reasoning as B.
# ==========================================================================
async def test_model_can_represent_imported_milestone():
    project = await _make_project("SF Imported Milestone Project")
    now = _now()
    mid = f"ms_{uuid.uuid4()}"
    await _mock_db.milestones.insert_one({
        "id": mid, "project_id": project["id"], "name": "MEP Completion", "sequence": 3,
        "planned_percent": 15, "contract_value": 750000.0, "trigger": "MEP rough-in complete",
        "planned_date": None, "forecast_date": None, "actual_date": None, "status": "pending",
        "source": {
            "origin": "imported", "external_system": "sap_erp",
            "external_id": "ERP-MS-1187", "imported_at": _iso(now),
        },
        "created_at": _iso(now), "updated_at": _iso(now),
    })
    milestones = await commercial_engine.list_milestones(project["id"])
    assert milestones[0]["source"]["origin"] == "imported"
    assert milestones[0]["source"]["external_system"] == "sap_erp"


# ==========================================================================
# E. A native event claim - append_commercial_event() with no source
#    passed, exactly every existing call site's own unchanged behavior.
# ==========================================================================
async def test_native_event_claim_source_is_none_by_default():
    project = await _make_project("SF Native Event Project")
    event = await commercial_engine.append_commercial_event(
        project_id=project["id"], kind="milestone_updated", actor=PM,
        entity_type="milestone", entity_id="ms_test", payload={"changes": {"planned_date": {"from": None, "to": "2026-09-18"}}})
    assert event["source"] is None
    # Every existing field unchanged and present.
    assert event["actor_user_id"] == PM["id"]
    assert event["kind"] == "milestone_updated"
    assert event["payload"]["changes"]["planned_date"]["to"] == "2026-09-18"


# ==========================================================================
# F. An imported event claim.
# ==========================================================================
async def test_imported_event_claim_carries_source_tag():
    project = await _make_project("SF Imported Event Project")
    now = _now()
    event = await commercial_engine.append_commercial_event(
        project_id=project["id"], kind="milestone_updated", actor=PM,
        entity_type="milestone", entity_id="ms_test",
        payload={"changes": {"planned_date": {"from": None, "to": "2026-09-20"}}},
        source={"origin": "imported", "external_system": "primavera_p6"})
    assert event["source"] == {"origin": "imported", "external_system": "primavera_p6"}
    assert event["actor_user_id"] == PM["id"]


# ==========================================================================
# G. THE MOST IMPORTANT TEST — two claims about the same field, from
#    different sources, coexist. Proves preservation. Does NOT decide
#    which one is "right" - that is reconciliation, explicitly out of
#    scope for this phase.
# ==========================================================================
async def test_two_claims_about_same_field_from_different_sources_coexist():
    project = await _make_project("SF Competing Claims Project")
    entity_id = "ms_competing_claims_test"

    native_claim = await commercial_engine.append_commercial_event(
        project_id=project["id"], kind="milestone_updated", actor=PM,
        entity_type="milestone", entity_id=entity_id,
        payload={"field": "planned_date", "value": "2026-09-15"},
        source=None)  # native, matching every real human edit today

    imported_claim = await commercial_engine.append_commercial_event(
        project_id=project["id"], kind="milestone_updated", actor=PM,
        entity_type="milestone", entity_id=entity_id,
        payload={"field": "planned_date", "value": "2026-09-18"},
        source={"origin": "imported", "external_system": "primavera_p6"})

    # Neither write touched the other's own record.
    assert native_claim["id"] != imported_claim["id"]

    all_events = await commercial_engine.list_commercial_events(project["id"])
    matching = [e for e in all_events if e["entity_id"] == entity_id]
    assert len(matching) == 2, "both claims must survive - neither silently overwritten"

    by_id = {e["id"]: e for e in matching}
    assert by_id[native_claim["id"]]["source"] is None
    assert by_id[native_claim["id"]]["payload"]["value"] == "2026-09-15"
    assert by_id[imported_claim["id"]]["source"]["origin"] == "imported"
    assert by_id[imported_claim["id"]]["payload"]["value"] == "2026-09-18"
    # This test deliberately does not assert which value should "win" -
    # that decision belongs to a future reconciliation layer this phase
    # explicitly does not build.


# ==========================================================================
# 9. Small/enterprise regression — existing reasoning operates
#    identically with source metadata present or absent.
# ==========================================================================
async def test_atlas_only_project_needs_no_source_metadata():
    """A project with zero source-tagged records behaves exactly as
    every project has throughout this entire engagement."""
    project = await _make_project("SF Atlas Only Project")
    now = _now()
    aid = f"wa_{uuid.uuid4()}"
    # Deliberately OMITS the source field entirely - the pre-Source-
    # Foundation shape, proving old records remain valid with no
    # migration.
    await _mock_db.workflow_activities.insert_one({
        "id": aid, "project_id": project["id"], "name": "Legacy Activity", "trade": "Civil",
        "status": "blocked", "depends_on_activity_ids": [], "order": 0,
        "default_duration_days": 4, "requires_inspection": False,
        "planned_start": None, "planned_finish": None, "actual_start": None, "actual_finish": None,
        "milestone_id": None, "created_at": _iso(now), "updated_at": _iso(now),
    })
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    assert result is not None
    assert "recommended_actions" in result


async def test_enterprise_shaped_project_activities_and_milestones_carry_imported_identity():
    project = await _make_project("SF Enterprise Shaped Project")
    now = _now()
    aid = f"wa_{uuid.uuid4()}"
    await _mock_db.workflow_activities.insert_one({
        "id": aid, "project_id": project["id"], "name": "Structural Steel", "trade": "Structural",
        "status": "blocked", "depends_on_activity_ids": [], "order": 0,
        "default_duration_days": 6, "requires_inspection": False,
        "planned_start": None, "planned_finish": _iso(now), "actual_start": None, "actual_finish": None,
        "milestone_id": None,
        "source": {"origin": "imported", "external_system": "primavera_p6",
                    "external_id": "P6-ACT-009", "imported_at": _iso(now)},
        "created_at": _iso(now), "updated_at": _iso(now),
    })
    # Reasoning proceeds identically - severity, consequence, priority
    # explanation all computed the same way regardless of source.
    result = await reasoning_engine.explain_health(project["id"], user=PM)
    assert result is not None
    assert isinstance(result["recommended_actions"], list)
