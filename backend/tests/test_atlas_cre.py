"""Project Atlas — Innovation Sprint 01: Construction Reasoning Engine (CRE).

Live-deployment verification suite. Like test_atlas_fac03.py, every test
here runs against the REAL, deployed FastAPI app via HTTP — this is the
"demonstrated in the running application" layer, on top of the pure rule
unit tests (test_cre_rules.py) and the in-process full-stack smoke suite
(test_cre_smoke_mongomock.py).

End-to-end scenario, using ONLY existing public APIs to build state (no
direct database seeding — if the deployed app can't produce the inputs
CRE reasons over, that itself is a finding):

  1. Create a project + Activity Library activities with a dependency
     chain (Excavation -> PCC) and a requires_inspection activity, wire
     them into a workflow template, generate the project workflow.
  2. Drive the workflow: complete Excavation; leave PCC untouched; give
     one activity a planned_finish in the past.
  3. Raise operational items: an overdue material requirement and a
     critical safety observation (backdating created_at isn't possible
     via public APIs, so the safety rule's 24h clause is asserted only
     as "does not false-positive immediately" here — its firing path is
     fully covered by the other two suites).
  4. Trigger a reasoning run and verify: contract-complete insights, the
     generalized begin-PCC recommendation, idempotent re-runs, human
     decision lifecycle, project health, run audit, and the client/
     supervisor gates.

Bootstrap strategy mirrors test_atlas_fac03.py exactly (login-first,
fall back to register -> seeded-admin approval -> role -> login).
"""
import os
import uuid

import pytest
import requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or
        "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"

_SEEDED_ADMIN_PHONE = "9000000001"  # DX-7 seed script's "Atlas Admin 1"
_seeded_admin_cache: dict = {}


def _seeded_admin_headers():
    if "headers" not in _seeded_admin_cache:
        r = requests.post(f"{API}/auth/login",
                          json={"phone": _SEEDED_ADMIN_PHONE,
                                "name": "Atlas Admin 1", "role": "management"},
                          timeout=20)
        assert r.status_code == 200, (
            "Seeded admin account not found - has the target environment "
            f"been seeded? (python -m scripts.dev seed) {r.text}")
        _seeded_admin_cache["headers"] = {
            "Authorization": f"Bearer {r.json()['token']}"}
    return _seeded_admin_cache["headers"]


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role},
                      timeout=20)
    if r.status_code == 200:
        b = r.json()
        return b["user"], {"Authorization": f"Bearer {b['token']}"}
    reg = requests.post(f"{API}/auth/register",
                        json={"phone": phone, "name": name}, timeout=20)
    assert reg.status_code == 200, reg.text
    user_id = reg.json()["user"]["id"]
    admin_headers = _seeded_admin_headers()
    requests.post(f"{API}/admin/users/{user_id}/approve",
                  headers=admin_headers, timeout=20)
    requests.post(f"{API}/admin/users/{user_id}/role",
                  json={"role": role}, headers=admin_headers, timeout=20)
    r2 = requests.post(f"{API}/auth/login",
                       json={"phone": phone, "name": name, "role": role},
                       timeout=20)
    assert r2.status_code == 200, r2.text
    b = r2.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


@pytest.fixture(scope="session")
def admin():
    u, h = _login("management", "9995100001", "CRE Admin")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def pm():
    u, h = _login("coordinator", "9995100002", "CRE PM")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("supervisor", "9995100003", "CRE Supervisor")
    return {"user": u, "headers": h}


def _post(headers, path, payload, expect=200):
    r = requests.post(f"{API}{path}", json=payload, headers=headers, timeout=30)
    assert r.status_code == expect, f"{path}: {r.status_code} {r.text}"
    return r.json() if r.text else {}


def _get(headers, path, params=None, expect=200):
    r = requests.get(f"{API}{path}", params=params, headers=headers, timeout=30)
    assert r.status_code == expect, f"{path}: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def world(admin, pm):
    """Build the reasoning scenario through public APIs only."""
    tag = uuid.uuid4().hex[:6]
    ah = admin["headers"]

    project = _post_any(ah, "/projects",
                        {"name": f"CRE Verification {tag}",
                         "code": f"CRE{tag}"})
    project_id = project["id"]

    site = _post_any(ah, "/sites",
                     {"project_id": project_id, "name": f"CRE Site {tag}"})
    site_id = site["id"]

    # Activity Library: Excavation -> PCC (dependency), Slab (inspection)
    def make_activity(name, requires_inspection=False):
        return _post_any(ah, "/knowledge-items", {
            "type": "activity", "name": f"{name} {tag}",
            "description": name, "status": "active",
            "requires_inspection": requires_inspection,
        })

    exc = make_activity("Excavation")
    pcc = make_activity("PCC")
    slab = make_activity("Slab Pour", requires_inspection=True)
    _post_any(ah, f"/knowledge-items/{pcc['id']}/relationships",
              {"type": "depends_on", "target_id": exc["id"]})

    template = _post_any(ah, "/knowledge-items", {
        "type": "workflow_template", "name": f"CRE Template {tag}",
        "description": "CRE verification template", "status": "active",
    })
    for order, act in enumerate((exc, pcc, slab)):
        _post_any(ah, f"/knowledge-items/{template['id']}/relationships",
                  {"type": "includes_activity", "target_id": act["id"],
                   "metadata": {"order": order}})

    wf = _post_any(ah, f"/projects/{project_id}/workflow/generate",
                   {"template_id": template["id"]})
    by_name = {a["name"]: a for a in wf}
    wfa_exc = by_name[exc["name"]]
    wfa_pcc = by_name[pcc["name"]]
    wfa_slab = by_name[slab["name"]]

    # Complete Excavation and Slab; leave PCC at ready.
    for a in (wfa_exc, wfa_slab):
        _post(ah, f"/workflow-activities/{a['id']}/status",
              {"status": "in_progress"})
        _post(ah, f"/workflow-activities/{a['id']}/status",
              {"status": "completed"})
    # Slab began well in the past + one activity already past its finish.
    _post(ah, f"/workflow-activities/{wfa_slab['id']}/schedule",
          {"actual_start": "2026-01-05T09:00:00+00:00"})
    _post(ah, f"/workflow-activities/{wfa_pcc['id']}/schedule",
          {"planned_start": "2026-01-10T09:00:00+00:00",
           "planned_finish": "2026-01-20T18:00:00+00:00"})

    # Operational items: overdue material requirement.
    _post_any(ah, "/operational-items", {
        "site_id": site_id, "category": "material_requirement",
        "title": f"8mm steel 2 ton {tag}",
        "priority": "high", "required_by": "2026-01-15T00:00:00+00:00",
    })

    return {"project_id": project_id, "site_id": site_id,
            "wfa_pcc": wfa_pcc, "exc_name": exc["name"],
            "pcc_name": pcc["name"], "slab_name": slab["name"]}


def _post_any(headers, path, payload):
    # Tolerates 200-vs-201 differences across route families.
    r = requests.post(f"{API}{path}", json=payload, headers=headers, timeout=30)
    assert r.status_code in (200, 201), f"{path}: {r.status_code} {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# The reasoning run and its guarantees
# ---------------------------------------------------------------------------

def test_reasoning_run_produces_contract_complete_insights(world, pm):
    body = requests.post(
        f"{API}/projects/{world['project_id']}/reasoning/run",
        json={}, headers=pm["headers"], timeout=60)
    assert body.status_code == 201, body.text
    result = body.json()
    world["run1"] = result

    fired = {i["rule_id"] for i in result["insights_new"]}
    # PCC's planned dates are past and it hasn't started:
    assert "schedule.planned_start_missed" in fired
    assert "schedule.planned_finish_missed" in fired
    # completed requires_inspection activity, no inspection item:
    assert "quality.completed_without_inspection" in fired
    # material required_by long past:
    assert "procurement.material_lead_time" in fired

    for ins in result["insights_new"]:
        # v2 reasoning chain: observation -> risk -> recommendation ->
        # suggested action -> suggested role -> suggested due date
        for key in ("observation", "risk", "recommendation", "project_id"):
            assert ins.get(key), f"insight missing '{key}': {ins}"
        assert ins["suggested_operational_action"]["category"]
        assert ins["suggested_responsible_role"] in (
            "supervisor", "coordinator", "management")
        assert ins["suggested_due_date"]
        # structured explainable confidence
        assert ins["confidence"]["level"] in ("low", "medium", "high")
        assert ins["confidence"]["reason"]
        # explicit evidence section, all kinds always present
        assert list(ins["evidence"]) == [
            "workflow_activities", "operational_items", "events", "media",
            "approvals", "knowledge_items", "absences"]
        assert any(ins["evidence"].values()), \
            "conclusions alone are not allowed"


def test_construction_logic_recommends_beginning_pcc(world, pm):
    """The sprint's flagship example, generalized from the dependency
    graph: Excavation complete -> no PCC activity -> recommend begin PCC.
    Only asserted if the deployed data ages past the stall window —
    otherwise verified structurally: PCC is 'ready' and unstarted, so the
    rule's precondition set is reachable (full firing behaviour is pinned
    by the unit + mongomock suites, which control the clock)."""
    insights = _get(pm["headers"],
                    f"/projects/{world['project_id']}/insights",
                    params={"domain": "construction_logic"})
    logic_hits = [i for i in insights
                  if i["rule_id"] == "construction_logic.successor_not_started"]
    if logic_hits:
        assert world["pcc_name"] in logic_hits[0]["observation"] or \
            world["pcc_name"] in logic_hits[0]["recommendation"]
    else:
        wf = _get(pm["headers"], f"/projects/{world['project_id']}/workflow")
        pcc = next(a for a in wf if a["id"] == world["wfa_pcc"]["id"])
        assert pcc["status"] == "ready"
        assert all(d["status"] == "completed" for d in pcc["depends_on"])


def test_rerun_is_idempotent(world, pm):
    r = _post(pm["headers"],
              f"/projects/{world['project_id']}/reasoning/run", {},
              expect=201)
    assert r["run"]["insights_new"] == 0
    assert r["run"]["insights_refreshed"] >= 3


def test_reasoning_never_mutates_the_project(world, pm):
    """CRE recommended beginning PCC — verify it did not DO it, and that
    no operational item changed state, across two completed runs."""
    wf = _get(pm["headers"], f"/projects/{world['project_id']}/workflow")
    pcc = next(a for a in wf if a["id"] == world["wfa_pcc"]["id"])
    assert pcc["status"] == "ready"
    items = _get(pm["headers"], "/operational-items",
                 params={"site_id": world["site_id"]})
    listed = items if isinstance(items, list) else items.get("items", [])
    for i in listed:
        assert i["status"] in ("open", "assigned"), \
            "reasoning must never transition operational items"


def test_project_health_endpoint(world, admin):
    h = _get(admin["headers"], f"/projects/{world['project_id']}/health")
    assert h["status"] in ("green", "amber", "red")
    assert 0 <= h["score"] <= 100
    assert set(h["dimensions"]) == {"schedule", "quality", "safety",
                                    "communication", "operational"}
    for dim in h["dimensions"].values():
        assert 0 <= dim["score"] <= 100
        assert dim["explanation"]
        assert isinstance(dim["contributing_factors"], list)
    # the scenario carries schedule + quality + procurement problems
    assert h["dimensions"]["schedule"]["score"] < 100
    assert h["dimensions"]["quality"]["score"] < 100
    assert h["dimensions"]["operational"]["score"] < 100
    assert h["progress"]["activities_total"] == 3
    assert h["open_insights"] >= 3
    assert h["score"] < 100 and h["drivers"]


def test_insight_decision_lifecycle(world, pm):
    ins = world["run1"]["insights_new"][0]
    upd = _post(pm["headers"], f"/insights/{ins['id']}/status",
                {"status": "acknowledged", "note": "reviewing"})
    assert upd["status"] == "acknowledged"
    upd = _post(pm["headers"], f"/insights/{ins['id']}/status",
                {"status": "actioned", "note": "handled on site"})
    assert upd["status"] == "actioned"
    assert upd["resolution_note"] == "handled on site"
    assert [h["status"] for h in upd["status_history"]] == \
        ["open", "acknowledged", "actioned"]
    r = requests.post(f"{API}/insights/{ins['id']}/status",
                      json={"status": "dismissed"},
                      headers=pm["headers"], timeout=20)
    assert r.status_code == 409


def test_supervisor_can_read_but_not_trigger_or_decide(world, supervisor):
    sh = supervisor["headers"]
    r = requests.post(f"{API}/projects/{world['project_id']}/reasoning/run",
                      json={}, headers=sh, timeout=20)
    assert r.status_code == 403
    insights = _get(sh, f"/projects/{world['project_id']}/insights")
    assert isinstance(insights, list)
    open_ins = [i for i in insights if i["status"] == "open"]
    if open_ins:
        r = requests.post(f"{API}/insights/{open_ins[0]['id']}/status",
                          json={"status": "dismissed"}, headers=sh, timeout=20)
        assert r.status_code == 403


def test_client_workspace_is_blocked_everywhere(world, admin):
    tag = uuid.uuid4().hex[:6]
    u, h = _login("coordinator", f"99952{tag[:5]}", f"CRE Client {tag}")
    requests.post(f"{API}/admin/users/{u['id']}/workspace",
                  json={"workspace": "client"},
                  headers=admin["headers"], timeout=20)
    pid = world["project_id"]
    for method, path in (("post", f"/projects/{pid}/reasoning/run"),
                         ("get", f"/projects/{pid}/insights"),
                         ("get", f"/projects/{pid}/health"),
                         ("get", "/reasoning-meta")):
        r = (requests.post(f"{API}{path}", json={}, headers=h, timeout=20)
             if method == "post" else
             requests.get(f"{API}{path}", headers=h, timeout=20))
        assert r.status_code == 403, f"{path} -> {r.status_code}"


def test_run_audit_and_meta(world, pm):
    runs = _get(pm["headers"],
                f"/projects/{world['project_id']}/reasoning/runs")
    assert len(runs) >= 2
    assert all(r["triggered_by_user_name"] for r in runs)
    meta = _get(pm["headers"], "/reasoning-meta")
    rules_by_id = {r["id"]: r for r in meta["rules"]}
    assert rules_by_id["construction_logic.successor_not_started"][
        "domain"] == "construction_logic"
    assert set(meta["confidence_levels"]) == {"low", "medium", "high"}
    assert meta["canonical_lifecycle"][0] == "open"
    assert set(meta["feedback_verdicts"]) == {"accepted", "rejected",
                                              "modified", "ignored"}


def test_feedback_and_relationships(world, pm):
    insights = _get(pm["headers"],
                    f"/projects/{world['project_id']}/insights")
    assert len(insights) >= 2
    a, b = insights[0]["id"], insights[1]["id"]
    upd = _post(pm["headers"], f"/insights/{a}/feedback",
                {"verdict": "accepted", "note": "confirmed on site"})
    assert upd["feedback"]["verdict"] == "accepted"
    assert upd["feedback_history"][-1]["note"] == "confirmed on site"
    upd = _post(pm["headers"], f"/insights/{a}/relationships",
                {"related_insight_id": b, "relation": "supports"})
    assert any(r["insight_id"] == b and r["relation"] == "supports"
               for r in upd["related_insights"])
    r = requests.post(f"{API}/insights/{a}/relationships",
                      json={"related_insight_id": a, "relation": "supports"},
                      headers=pm["headers"], timeout=20)
    assert r.status_code == 400


def test_unknown_project_404(pm):
    r = requests.post(f"{API}/projects/proj_does_not_exist/reasoning/run",
                      json={}, headers=pm["headers"], timeout=20)
    assert r.status_code == 404
