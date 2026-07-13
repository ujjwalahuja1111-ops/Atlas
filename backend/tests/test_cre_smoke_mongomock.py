"""CRE full-stack smoke suite — real app, real HTTP, mongomock-backed Mongo.

This is the middle layer of the project's three-layer verification
convention: pure rule unit tests (test_cre_rules.py) below it, live-
deployment HTTP tests (test_atlas_cre.py) above it. Here the REAL FastAPI
app — real routers, real auth dependency, real reasoning engine — is
exercised over HTTP with only the Mongo driver swapped for
mongomock-motor, so the entire request path is verified without needing
a deployed environment.

Skips cleanly if mongomock_motor / httpx are not installed (they are dev
tools, deliberately not added to requirements.txt).

Identity provisioning happens at the DATABASE layer (insert user doc +
core.auth.create_token), NOT through /auth/register//auth/login — a
deliberate choice for branch discipline: the authentication flow is under
active change in the parallel FAC sprint, and this suite must keep
passing regardless of how that flow evolves. What this suite DOES rely on
from auth is only the stable get_current_user contract (JWT -> user doc,
approval/active checks), which the sprint brief says to treat as a stable
dependency.

Run from backend/:  python -m pytest tests/test_cre_smoke_mongomock.py -q
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

mongomock_motor = pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_cre_smoke")

# --- swap the Mongo handle BEFORE the app modules bind to it -------------
import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_cre_smoke"]
core_db.db = _mock_db
core_db.client = _mock_client

# Every module that did `from core.db import db` bound the ORIGINAL handle
# at import time; rebind each one explicitly.
import core.auth as core_auth  # noqa: E402
from engines import (  # noqa: E402
    memory_engine, operations_engine, knowledge_engine,
    workflow_engine, timeline_engine, reasoning_engine,
)

for _mod in (core_auth, memory_engine, operations_engine, knowledge_engine,
             workflow_engine, timeline_engine, reasoning_engine):
    _mod.db = _mock_db

import server  # noqa: E402  (routers bind engines, not db, so import last is fine)

NOW = datetime.now(timezone.utc)


def iso_days_ago(n: float) -> str:
    return (NOW - timedelta(days=n)).isoformat()


def iso_days_ahead(n: float) -> str:
    return (NOW + timedelta(days=n)).isoformat()


async def _seed_user(user_id: str, name: str, role: str,
                     workspace: str | None = None) -> dict:
    doc = {
        "id": user_id, "phone": f"9{user_id[-9:]:>09}", "name": name,
        "role": role, "approval_status": "approved", "is_active": True,
    }
    if workspace:
        doc["workspace"] = workspace
    await _mock_db.users.insert_one({**doc})
    return {"Authorization": f"Bearer {core_auth.create_token(user_id)}"}


async def _seed_world() -> dict:
    """One project with the classic CRE scenario baked in:
    Excavation completed 5 days ago -> PCC ready but untouched (the
    canonical construction-logic case), plus overdue material, an
    unresolved critical safety observation, and a completed
    requires_inspection activity with no inspection recorded."""
    await _mock_db.projects.insert_one({
        "id": "proj_cre", "name": "CRE Villa", "code": "CRE-1",
        "created_at": iso_days_ago(60), "archived_at": None,
    })
    await _mock_db.sites.insert_one({
        "id": "site_cre", "project_id": "proj_cre", "name": "Plot 7",
        "created_at": iso_days_ago(60), "archived_at": None,
    })
    acts = [
        {"id": "wfa_exc", "name": "Excavation", "status": "completed",
         "depends_on_activity_ids": [], "requires_inspection": False,
         "status_updated_at": iso_days_ago(5)},
        {"id": "wfa_pcc", "name": "PCC", "status": "ready",
         "depends_on_activity_ids": ["wfa_exc"], "requires_inspection": False,
         "status_updated_at": iso_days_ago(5)},
        {"id": "wfa_slab", "name": "Slab Pour", "status": "completed",
         "depends_on_activity_ids": [], "requires_inspection": True,
         "actual_start": iso_days_ago(20),
         "status_updated_at": iso_days_ago(8)},
    ]
    for order, a in enumerate(acts):
        await _mock_db.workflow_activities.insert_one({
            "project_id": "proj_cre", "order": order,
            "planned_start": None, "planned_finish": None,
            "actual_start": None, "actual_finish": None,
            "created_at": iso_days_ago(60),
            "status_updated_by_user_name": "Seed", **a,
        })
    items = [
        {"id": "op_steel", "category": "material_requirement",
         "title": "8mm steel 2 ton", "status": "open", "priority": "high",
         "required_by": iso_days_ago(1), "health": "overdue"},
        {"id": "op_safety", "category": "safety_observation",
         "title": "Open shaft unguarded", "status": "open",
         "priority": "critical", "required_by": None, "health": "on_track"},
    ]
    for i in items:
        await _mock_db.operational_items.insert_one({
            "project_id": "proj_cre", "site_id": "site_cre",
            "created_at": iso_days_ago(2), "last_updated_at": iso_days_ago(2),
            **i,
        })
    return {"project_id": "proj_cre"}


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
async def ctx(anyio_backend):
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://cre-smoke") as client:
        world = await _seed_world()
        admin = await _seed_user("usr_admin", "CRE Admin", "management")
        pm = await _seed_user("usr_pm", "CRE PM", "coordinator")
        sup = await _seed_user("usr_sup", "CRE Supervisor", "supervisor")
        cli = await _seed_user("usr_cli", "CRE Client", "coordinator",
                               workspace="client")
        yield {"client": client, "world": world, "admin": admin,
               "pm": pm, "sup": sup, "cli": cli}


pytestmark = pytest.mark.anyio


async def test_reasoning_run_emits_contract_complete_insights(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.post(f"/api/projects/{pid}/reasoning/run", json={},
                     headers=ctx["pm"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["run"]["insights_new"] >= 4
    rules_fired = {i["rule_id"] for i in body["insights_new"]}
    assert {"construction_logic.successor_not_started",
            "quality.completed_without_inspection",
            "safety.unresolved_high_priority",
            "procurement.material_lead_time"} <= rules_fired
    for ins in body["insights_new"]:
        # v2 reasoning chain
        for key in ("observation", "risk", "recommendation",
                    "project_id", "status"):
            assert ins.get(key), f"insight missing {key}"
        # explicit evidence section — all kinds always present, none empty
        # across the whole insight (no conclusions without evidence)
        assert list(ins["evidence"].keys()) == reasoning_engine.EVIDENCE_KINDS
        assert any(ins["evidence"].values())
        # structured explainable confidence
        assert ins["confidence"]["level"] in ("low", "medium", "high")
        assert ins["confidence"]["reason"]
        # deterministic rules always suggest an action, owner and due date
        assert ins["suggested_operational_action"]["category"]
        assert ins["suggested_responsible_role"]
        assert ins["suggested_due_date"]
        # feedback/relationship substrate present from birth
        assert ins["feedback"] is None and ins["feedback_history"] == []
        assert ins["related_insights"] == []
        assert ins["status"] == "open"
    ctx["first_run"] = body


async def test_rerun_is_idempotent_refreshes_not_duplicates(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.post(f"/api/projects/{pid}/reasoning/run", json={},
                     headers=ctx["pm"])
    assert r.status_code == 201
    body = r.json()
    assert body["run"]["insights_new"] == 0
    assert body["run"]["insights_refreshed"] >= 4
    first = ctx["first_run"]["insights_new"][0]["id"]
    doc = await _mock_db.reasoning_insights.find_one({"id": first})
    assert doc["times_seen"] == 2


async def test_run_is_strictly_read_only_over_other_engines_data(ctx):
    """The structural 'never executes work' guarantee, verified: two
    reasoning runs have happened and no document CRE reasons OVER has
    been created, modified, or deleted."""
    assert await _mock_db.workflow_activities.count_documents({}) == 3
    assert await _mock_db.operational_items.count_documents({}) == 2
    assert await _mock_db.events.count_documents({}) == 0
    a = await _mock_db.workflow_activities.find_one({"id": "wfa_pcc"})
    assert a["status"] == "ready"  # CRE recommended starting it; it did NOT start it


async def test_insight_listing_and_domain_filter(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.get(f"/api/projects/{pid}/insights",
                    params={"domain": "safety"}, headers=ctx["sup"])
    assert r.status_code == 200
    assert r.json() and all(i["domain"] == "safety" for i in r.json())
    bad = await c.get(f"/api/projects/{pid}/insights",
                      params={"status": "bogus"}, headers=ctx["sup"])
    assert bad.status_code == 400


async def test_project_health_is_reasoned_across_five_dimensions(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.get(f"/api/projects/{pid}/health", headers=ctx["admin"])
    assert r.status_code == 200
    h = r.json()
    assert h["status"] in ("amber", "red")
    assert h["score"] < 80
    dims = h["dimensions"]
    assert set(dims) == {"schedule", "quality", "safety",
                         "communication", "operational"}
    # scenario: critical safety observation, overdue material, stalled
    # successor, missing inspection — each lands in its dimension
    assert dims["safety"]["score"] < 100
    assert dims["operational"]["score"] < 100
    assert dims["schedule"]["score"] < 100
    assert dims["quality"]["score"] < 100
    assert dims["communication"]["score"] == 100
    for dim in dims.values():
        assert dim["explanation"]
        assert isinstance(dim["contributing_factors"], list)
    assert dims["safety"]["contributing_factors"][0]["severity"] == "critical"
    assert h["drivers"]
    assert h["progress"]["activities_total"] == 3


async def test_insight_lifecycle_and_invalid_transition(ctx):
    c = ctx["client"]
    ins_id = ctx["first_run"]["insights_new"][0]["id"]
    r = await c.post(f"/api/insights/{ins_id}/status",
                     json={"status": "acknowledged", "note": "seen"},
                     headers=ctx["pm"])
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    r = await c.post(f"/api/insights/{ins_id}/status",
                     json={"status": "actioned", "note": "PCC started today"},
                     headers=ctx["pm"])
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_by_user_name"] == "CRE PM"
    assert [h["status"] for h in body["status_history"]] == \
        ["open", "acknowledged", "actioned"]
    # terminal -> anything is a 409 state conflict
    r = await c.post(f"/api/insights/{ins_id}/status",
                     json={"status": "dismissed"}, headers=ctx["pm"])
    assert r.status_code == 409


async def test_resolved_insight_reemits_linked_to_its_predecessor(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.post(f"/api/projects/{pid}/reasoning/run", json={},
                     headers=ctx["admin"])
    assert r.status_code == 201
    body = r.json()
    # exactly one insight was actioned above; its condition still holds,
    # so the run emits a FRESH insight for that dedupe_key...
    assert body["run"]["insights_new"] == 1
    fresh = body["insights_new"][0]
    actioned_id = ctx["first_run"]["insights_new"][0]["id"]
    # ...auto-linked to the resolved predecessor: reasoning history forms
    # a chain instead of resurrecting closed decisions
    assert fresh["related_insights"] == [{
        **fresh["related_insights"][0],
        "insight_id": actioned_id, "relation": "previous"}]
    assert fresh["dedupe_key"] == \
        ctx["first_run"]["insights_new"][0]["dedupe_key"]
    ctx["fresh_reemit"] = fresh


async def test_feedback_loop_stores_verdicts_without_learning(ctx):
    c = ctx["client"]
    ins_id = ctx["first_run"]["insights_new"][1]["id"]
    r = await c.post(f"/api/insights/{ins_id}/feedback",
                     json={"verdict": "accepted",
                           "note": "matches what we saw on site"},
                     headers=ctx["pm"])
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"]["verdict"] == "accepted"
    assert body["feedback"]["by_user_name"] == "CRE PM"
    # feedback may be revised; history preserves both entries
    r = await c.post(f"/api/insights/{ins_id}/feedback",
                     json={"verdict": "modified",
                           "note": "true but wrong owner suggested"},
                     headers=ctx["pm"])
    body = r.json()
    assert body["feedback"]["verdict"] == "modified"
    assert [f["verdict"] for f in body["feedback_history"]] == \
        ["accepted", "modified"]
    # invalid verdict -> 400; supervisors cannot record feedback -> 403
    assert (await c.post(f"/api/insights/{ins_id}/feedback",
                         json={"verdict": "loved_it"},
                         headers=ctx["pm"])).status_code == 400
    assert (await c.post(f"/api/insights/{ins_id}/feedback",
                         json={"verdict": "accepted"},
                         headers=ctx["sup"])).status_code == 403


async def test_manual_insight_relationships(ctx):
    c = ctx["client"]
    a = ctx["first_run"]["insights_new"][1]["id"]
    b = ctx["first_run"]["insights_new"][2]["id"]
    r = await c.post(f"/api/insights/{a}/relationships",
                     json={"related_insight_id": b, "relation": "supports",
                           "note": "same root cause"},
                     headers=ctx["pm"])
    assert r.status_code == 200
    rel = r.json()["related_insights"][-1]
    assert rel["insight_id"] == b and rel["relation"] == "supports"
    # idempotent per (target, relation) pair
    r = await c.post(f"/api/insights/{a}/relationships",
                     json={"related_insight_id": b, "relation": "supports"},
                     headers=ctx["pm"])
    assert len([x for x in r.json()["related_insights"]
                if x["insight_id"] == b and x["relation"] == "supports"]) == 1
    # self-link and unknown relation are rejected
    assert (await c.post(f"/api/insights/{a}/relationships",
                         json={"related_insight_id": a,
                               "relation": "supports"},
                         headers=ctx["pm"])).status_code == 400
    assert (await c.post(f"/api/insights/{a}/relationships",
                         json={"related_insight_id": b,
                               "relation": "caused_by"},
                         headers=ctx["pm"])).status_code == 400


async def test_role_and_workspace_gates(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    # supervisor: may read, may not trigger or decide
    assert (await c.post(f"/api/projects/{pid}/reasoning/run", json={},
                         headers=ctx["sup"])).status_code == 403
    ins_id = ctx["first_run"]["insights_new"][-1]["id"]
    assert (await c.post(f"/api/insights/{ins_id}/status",
                         json={"status": "dismissed"},
                         headers=ctx["sup"])).status_code == 403
    assert (await c.get(f"/api/projects/{pid}/insights",
                        headers=ctx["sup"])).status_code == 200
    # client workspace: blocked from every reasoning endpoint
    for method, url in (("post", f"/api/projects/{pid}/reasoning/run"),
                        ("get", f"/api/projects/{pid}/insights"),
                        ("get", f"/api/projects/{pid}/health"),
                        ("get", "/api/reasoning-meta")):
        resp = await (c.post(url, json={}, headers=ctx["cli"])
                      if method == "post" else c.get(url, headers=ctx["cli"]))
        assert resp.status_code == 403, url
    # unauthenticated: 401
    assert (await c.get(f"/api/projects/{pid}/insights")).status_code == 401


async def test_unknown_project_is_404_and_meta_lists_rules(ctx):
    c = ctx["client"]
    assert (await c.post("/api/projects/proj_nope/reasoning/run", json={},
                         headers=ctx["pm"])).status_code == 404
    meta = await c.get("/api/reasoning-meta", headers=ctx["pm"])
    assert meta.status_code == 200
    m = meta.json()
    rules_by_id = {r["id"]: r for r in m["rules"]}
    assert rules_by_id["construction_logic.successor_not_started"][
        "domain"] == "construction_logic"
    assert all(r["description"] for r in m["rules"])
    assert m["canonical_lifecycle"] == [
        "open", "acknowledged", "operational_item_created",
        "resolved", "dismissed", "expired"]
    assert set(m["feedback_verdicts"]) == {"accepted", "rejected",
                                           "modified", "ignored"}
    assert set(m["relation_types"]) == {"previous", "duplicate",
                                        "supports", "conflicts"}
    assert m["evidence_kinds"] == reasoning_engine.EVIDENCE_KINDS
    # reserved metadata-only domains are already in the taxonomy
    assert {"commercial", "documentation",
            "resource_planning"} <= set(m["domains"])


async def test_run_audit_trail_is_recorded(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.get(f"/api/projects/{pid}/reasoning/runs", headers=ctx["pm"])
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 3
    for run in runs:
        assert run["triggered_by_user_name"]
        assert run["snapshot_stats"]["workflow_activities"] == 3
        assert run["include_ai"] is False  # no AI key in this environment


# ---------------------------------------------------------------------------
# Sprint 01B — construction intelligence surface
# ---------------------------------------------------------------------------

async def test_stage_awareness_on_insights_and_lookahead(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    # world: Excavation (excavation) complete, PCC (foundation) ready,
    # Slab Pour (rcc) complete -> earliest incomplete stage = foundation
    insights = (await c.get(f"/api/projects/{pid}/insights",
                            headers=ctx["pm"])).json()
    assert insights and all(i.get("project_stage") == "foundation"
                            for i in insights if i.get("project_stage"))
    r = await c.get(f"/api/projects/{pid}/lookahead", headers=ctx["sup"])
    assert r.status_code == 200
    look = r.json()
    assert look["stage"]["current"] == "foundation"
    nxt = look["next_expected"]
    assert nxt["name"] == "PCC"
    assert "Excavation" in nxt["why_expected"]
    # the overdue steel makes PCC not ready; blockers + preparation named
    assert nxt["ready"] is False
    checks = {x["check"]: x["status"] for x in nxt["prerequisites"]}
    assert checks["materials_available"] == "not_ready"
    assert checks["dependencies_complete"] == "ready"
    assert nxt["recommended_preparation"]


async def test_forecast_endpoint_is_honest_without_planned_dates(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.get(f"/api/projects/{pid}/forecast", headers=ctx["pm"])
    assert r.status_code == 200
    fc = r.json()
    assert fc["forecast_slip_days"] is None  # world has no planned dates
    assert fc["confidence"]["level"] == "low"
    assert fc["confidence"]["missing_evidence"]


async def test_daily_briefing_endpoint(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.get(f"/api/projects/{pid}/briefing", headers=ctx["pm"])
    assert r.status_code == 200
    b = r.json()
    assert b["stage"] == "foundation"
    assert b["next_expected"]["name"] == "PCC"
    assert len(b["safety_reminders"]) == 1
    assert len(b["material_risks"]) == 1
    assert b["todays_priorities"]
    assert b["required_decisions"]["open_insights_awaiting_review"] >= 1


async def test_client_summary_is_internal_only_and_leak_free(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.get(f"/api/projects/{pid}/client-summary", headers=ctx["pm"])
    assert r.status_code == 200
    cs = r.json()
    text = cs["summary_text"].lower()
    assert "excavation" in text
    assert "pcc" in text and "expected to begin" in text
    # internal ids and safety detail never leak into client wording
    assert "wfa_" not in text and "op_" not in text
    assert "shaft" not in text and "safety" not in text
    assert "review" in cs["disclaimer"].lower()
    # a draft for internal humans — the client workspace never sees it
    assert (await c.get(f"/api/projects/{pid}/client-summary",
                        headers=ctx["cli"])).status_code == 403


async def test_construction_memory_captured_idempotently(ctx):
    c, pid = ctx["client"], ctx["world"]["project_id"]
    r = await c.get(f"/api/projects/{pid}/construction-memory",
                    headers=ctx["pm"])
    assert r.status_code == 200
    records = r.json()
    # three runs have happened; the two completed activities were
    # captured exactly once each
    assert sorted(m["name"] for m in records) == ["Excavation", "Slab Pour"]
    for m in records:
        assert m["schema_version"] == 1
        assert m["stage"] in ("excavation", "rcc_structure")
        assert "material_delay_item_ids" in m
        assert m["weather_impacts"] == [] and m["labour_count"] is None


async def test_executive_reasoning_endpoint(ctx):
    c = ctx["client"]
    r = await c.get("/api/reasoning/executive",
                    params={"question": "greatest_risk"},
                    headers=ctx["admin"])
    assert r.status_code == 200
    body = r.json()
    assert body["scope"]["projects_considered"] == 1
    assert body["answer"]["greatest_risk"]["project_id"] == \
        ctx["world"]["project_id"]
    assert body["answer"]["greatest_risk"]["health_score"] < 100
    assert body["explanation"]

    r = await c.get("/api/reasoning/executive",
                    params={"question": "attention_today"},
                    headers=ctx["admin"])
    assert r.json()["answer"]["total_open_urgent"] >= 1

    r = await c.get("/api/reasoning/executive",
                    params={"question": "tomorrow"}, headers=ctx["pm"])
    plan = r.json()["answer"]["projects"]
    assert plan and plan[0]["next_expected"]["name"] == "PCC"

    r = await c.get("/api/reasoning/executive",
                    params={"question": "top_blocker"}, headers=ctx["admin"])
    assert r.status_code == 200  # nothing blocked in world -> empty, not error
    assert r.json()["answer"]["top"] is None

    # fixed vocabulary, not conversational AI
    assert (await c.get("/api/reasoning/executive",
                        params={"question": "tell me a story"},
                        headers=ctx["admin"])).status_code == 400
    # supervisors and clients are outside executive reasoning
    assert (await c.get("/api/reasoning/executive",
                        params={"question": "greatest_risk"},
                        headers=ctx["sup"])).status_code == 403
    assert (await c.get("/api/reasoning/executive",
                        params={"question": "greatest_risk"},
                        headers=ctx["cli"])).status_code == 403


async def test_meta_exposes_stages_and_executive_vocabulary(ctx):
    c = ctx["client"]
    m = (await c.get("/api/reasoning-meta", headers=ctx["pm"])).json()
    assert m["stages"][0] == "pre_construction"
    assert m["stages"][-1] == "handover"
    assert "greatest_risk" in m["executive_questions"]
    assert m["memory_schema_version"] == 1
    ids = {r["id"] for r in m["rules"]}
    assert {"schedule.forecast_finish_slip",
            "procurement.frontier_material_gap"} <= ids
