"""Universal Operational Memory Pivot tests.

Follows the established mongomock_motor pattern (see
tests/test_source_foundation.py's own header for why).

Covers the two changes this phase actually made, both directly
evidenced by the Universal Capture Proof:
  1. Temporal normalization at proposal-confirmation time
     (_normalize_date_phrase, accept_ai_proposal).
  2. Claim attribution surfaced onto the confirmed item.

Run from backend/:  python -m pytest tests/test_universal_memory_pivot.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_universal_memory_pivot_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_universal_memory_pivot_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, operations_engine, intelligence_engine, reasoning_engine  # noqa: E402

for _mod in (memory_engine, operations_engine, intelligence_engine, reasoning_engine):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


PM = {"id": "u_ump_pm", "name": "UMP PM", "role": "project_manager"}
ACTOR = {"id": "u_ump_actor", "name": "UMP Actor"}


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


async def _make_project(name: str) -> dict:
    return await memory_engine.insert_project(name=name, code=name.replace(" ", "").upper()[:8])


async def _real_event(project_id, site_id, text_input, when=None):
    when = when or _now()
    event_id = memory_engine._new_id("evt_")
    return await memory_engine.insert_event({
        "id": event_id, "site_id": site_id, "project_id": project_id,
        "user_id": "u_ump_actor", "user_name": "UMP Actor", "activity_id": None,
        "kind": "text", "text_input": text_input, "transcript": None,
        "audio_asset_id": None, "photo_asset_ids": [], "gps": None,
        "client_created_at": None, "app_version": None,
        "requires_client_approval": False, "ai_status": "pending", "ai_analysis_id": None,
        "server_created_at": _iso(when),
    })


# ==========================================================================
# _normalize_date_phrase() — unit-level, direct.
# ==========================================================================

def test_normalize_weekday_name():
    ref = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)  # a Monday
    result = operations_engine._normalize_date_phrase("Thursday", reference=ref)
    assert result == "2026-09-24T12:00:00+00:00"


def test_normalize_tomorrow():
    ref = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    result = operations_engine._normalize_date_phrase("tomorrow", reference=ref)
    assert result == "2026-09-22T12:00:00+00:00"


def test_normalize_today():
    ref = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    result = operations_engine._normalize_date_phrase("today", reference=ref)
    assert result == ref.isoformat()


def test_normalize_same_weekday_as_reference_returns_same_day():
    ref = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)  # itself a Thursday
    result = operations_engine._normalize_date_phrase("Thursday", reference=ref)
    assert result == ref.isoformat()


def test_normalize_unparseable_phrase_returns_none_never_fabricated():
    ref = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    assert operations_engine._normalize_date_phrase("asap", reference=ref) is None
    assert operations_engine._normalize_date_phrase("next Thursday", reference=ref) is None
    assert operations_engine._normalize_date_phrase(None, reference=ref) is None
    assert operations_engine._normalize_date_phrase("", reference=ref) is None


def test_normalize_explicit_iso_date_still_works():
    ref = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    result = operations_engine._normalize_date_phrase("2026-10-01", reference=ref)
    assert result.startswith("2026-10-01")


# ==========================================================================
# End-to-end: capture -> proposal -> confirmation -> normalized item.
# ==========================================================================

async def test_material_requirement_gets_normalized_date_and_cre_rule_fires():
    project = await _make_project("UMP Construction Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    event_time = datetime(2026, 9, 21, 5, 0, 0, tzinfo=timezone.utc)  # a Monday
    ev = await _real_event(project["id"], site["id"],
                            "The supplier said he'll deliver 200 tiles Thursday.", when=event_time)
    structured = {
        "materials": [{"name": "tiles", "quantity": 200, "unit": "pieces",
                        "required_date": "Thursday", "priority": "normal",
                        "attributed_to": "supplier", "confidence": "high"}],
        "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
        "inspections": [], "safety_observations": [], "quality_observations": [],
        "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
        "urgency": "normal", "summary": "Tile delivery Thursday",
    }
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
    item = await operations_engine.accept_ai_proposal(proposal_id=proposals[0]["id"], actor=ACTOR)

    assert item["required_by"] == "2026-09-24T05:00:00+00:00"
    assert item["quantity"] == 200
    assert item["unit"] == "pieces"
    assert item["attributed_to"] == "supplier"

    result = await reasoning_engine.explain_health(project["id"], user=PM)
    material_findings = [a for a in result["recommended_actions"] if a["rule_id"] == "procurement.material_lead_time"]
    assert len(material_findings) == 1
    assert "tiles" in material_findings[0]["observation"]


async def test_unparseable_date_phrase_preserves_original_raw_text():
    project = await _make_project("UMP Unparseable Date Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    ev = await _real_event(project["id"], site["id"], "Supplier says materials arriving ASAP.")
    structured = {
        "materials": [{"name": "cement", "quantity": 50, "unit": "bags",
                        "required_date": "ASAP", "priority": "high",
                        "attributed_to": "supplier", "confidence": "high"}],
        "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
        "inspections": [], "safety_observations": [], "quality_observations": [],
        "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
        "urgency": "high", "summary": "Cement ASAP",
    }
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
    item = await operations_engine.accept_ai_proposal(proposal_id=proposals[0]["id"], actor=ACTOR)
    assert item["required_by"] == "ASAP"


async def test_commitment_dates_normalized_independently():
    project = await _make_project("UMP Software Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    event_time = datetime(2026, 9, 21, 5, 0, 0, tzinfo=timezone.utc)  # a Monday
    ev = await _real_event(project["id"], site["id"],
                            "Rahul can join Monday and Priya Wednesday.", when=event_time)
    structured = {
        "materials": [], "labour": [], "equipment": [], "client_approvals": [],
        "drawing_requests": [], "inspections": [], "safety_observations": [], "quality_observations": [],
        "commitments": [
            {"what": "Rahul joins the release", "owed_to": None, "by_when": "Monday",
             "attributed_to": None, "confidence": "high"},
            {"what": "Priya joins the release", "owed_to": None, "by_when": "Wednesday",
             "attributed_to": None, "confidence": "high"},
        ],
        "follow_ups": [], "issues": [], "work_done": [], "urgency": "high",
        "summary": "Staffing for release",
    }
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
    items = [await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=ACTOR) for p in proposals]
    rahul = next(i for i in items if "Rahul" in i["title"])
    priya = next(i for i in items if "Priya" in i["title"])
    assert rahul["required_by"] == "2026-09-21T05:00:00+00:00"
    assert priya["required_by"] == "2026-09-23T05:00:00+00:00"


async def test_hospitality_two_material_facts_both_normalized_independently():
    project = await _make_project("UMP Hospitality Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    event_time = datetime(2026, 9, 21, 5, 0, 0, tzinfo=timezone.utc)  # a Monday
    ev = await _real_event(project["id"], site["id"],
                            "80kg chicken confirmed Friday, 20kg short for tomorrow.", when=event_time)
    structured = {
        "materials": [
            {"name": "chicken", "quantity": 80, "unit": "kg", "required_date": "Friday",
             "priority": "normal", "attributed_to": "food supplier", "confidence": "high"},
            {"name": "chicken", "quantity": 20, "unit": "kg", "required_date": "tomorrow",
             "priority": "high", "attributed_to": None, "confidence": "high"},
        ],
        "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
        "inspections": [], "safety_observations": [], "quality_observations": [],
        "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
        "urgency": "high", "summary": "Chicken delivery and shortfall",
    }
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
    items = [await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=ACTOR) for p in proposals]
    assert len(items) == 2
    confirmed = next(i for i in items if i["quantity"] == 80)
    shortfall = next(i for i in items if i["quantity"] == 20)
    assert confirmed["required_by"] == "2026-09-25T05:00:00+00:00"
    assert confirmed["attributed_to"] == "food supplier"
    assert shortfall["required_by"] == "2026-09-22T05:00:00+00:00"
    assert shortfall.get("attributed_to") is None


async def test_attribution_not_carried_over_at_low_confidence():
    project = await _make_project("UMP Low Confidence Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    ev = await _real_event(project["id"], site["id"], "Maybe the supplier mentioned something about tiles.")
    structured = {
        "materials": [{"name": "tiles", "quantity": 100, "unit": "pieces",
                        "required_date": None, "priority": "low",
                        "attributed_to": "supplier", "confidence": "low"}],
        "labour": [], "equipment": [], "client_approvals": [], "drawing_requests": [],
        "inspections": [], "safety_observations": [], "quality_observations": [],
        "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
        "urgency": "low", "summary": "Uncertain tile mention",
    }
    await intelligence_engine._emit_proposals_from_structured(ev, structured)
    proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
    item = await operations_engine.accept_ai_proposal(proposal_id=proposals[0]["id"], actor=ACTOR)
    assert item.get("attributed_to") is None


async def test_no_required_date_at_all_still_works_exactly_as_before():
    project = await _make_project("UMP No Date Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    ev = await _real_event(project["id"], site["id"], "Safety observation: exposed rebar.")
    structured = {
        "materials": [], "labour": [], "equipment": [], "client_approvals": [],
        "drawing_requests": [], "inspections": [],
        "safety_observations": [{"observation": "Exposed rebar on 2nd floor", "priority": "critical",
                                  "area": "2nd floor", "confidence": "high"}],
        "quality_observations": [], "commitments": [], "follow_ups": [], "issues": [], "work_done": [],
        "urgency": "high", "summary": "Safety issue",
    }
    count = await intelligence_engine._emit_proposals_from_structured(ev, structured)
    assert count == 1
    proposals = await operations_engine.list_ai_proposals(event_id=ev["id"])
    item = await operations_engine.accept_ai_proposal(proposal_id=proposals[0]["id"], actor=ACTOR)
    assert item["required_by"] is None
    assert item.get("attributed_to") is None
