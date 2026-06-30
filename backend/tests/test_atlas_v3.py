"""Project Atlas V3 — Operational Intelligence Layer tests.

Validates:
  * V2 backward compatibility (login/me/events/timeline)
  * AI proposal emission from event analysis (material + issue)
  * Proposal accept/reject authorisation (supervisor 403, coordinator OK)
  * Lifecycle transitions + invalid transition rejection
  * Append-only ledger history
  * Blocker management + health derivation
  * Time intelligence metrics
  * Operational center buckets + site requirements filtering
  * Comments don't mutate status
  * Timeline include=ops semantics
  * Immutability of Construction Events after V3 ops activity
  * No Mongo _id anywhere in V3 responses (recursive)
"""
import os
import time
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

PROPOSAL_WAIT_S = 45  # generous - LLM call


# ------------- helpers -------------
def _no_mongo_id(obj, path="root"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k != "_id", f"Mongo _id at {path}"
            _no_mongo_id(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_mongo_id(v, f"{path}[{i}]")


def _login(role="supervisor", phone="9999988888", name="Test User"):
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["user"], {"Authorization": f"Bearer {body['token']}"}


# ------------- fixtures -------------
@pytest.fixture(scope="session")
def supervisor():
    t, u, h = _login("supervisor", "9999988888", "Test User")
    return {"token": t, "user": u, "headers": h}


@pytest.fixture(scope="session")
def coordinator():
    t, u, h = _login("coordinator", "9222222222", "Priya Coordinator")
    return {"token": t, "user": u, "headers": h}


@pytest.fixture(scope="session")
def site_id(supervisor):
    r = requests.post(f"{API}/projects/seed", headers=supervisor["headers"], timeout=20)
    assert r.status_code == 200
    sites = requests.get(f"{API}/sites", headers=supervisor["headers"], timeout=20).json()
    assert sites and len(sites) >= 1
    return sites[0]["id"]


@pytest.fixture(scope="session")
def ai_event(supervisor, site_id):
    """Capture event that should produce 1 material + 1 issue proposal."""
    payload = {
        "site_id": site_id,
        "text": "kal 30 bag cement chahiye urgent, crane kharab hai",
    }
    r = requests.post(f"{API}/events", data=payload, headers=supervisor["headers"], timeout=20)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ============== V2 backward compatibility ==============
class TestV2BackwardCompat:
    def test_root_ok(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200

    def test_login_me(self, supervisor):
        r = requests.get(f"{API}/me", headers=supervisor["headers"], timeout=10)
        assert r.status_code == 200
        assert r.json()["phone"] == "9999988888"

    def test_me_unauth_401(self):
        r = requests.get(f"{API}/me", timeout=10)
        assert r.status_code == 401

    def test_projects_sites(self, supervisor, site_id):
        sites = requests.get(f"{API}/sites", headers=supervisor["headers"], timeout=10).json()
        _no_mongo_id(sites)
        assert any(s["id"] == site_id for s in sites)

    def test_events_post_get(self, supervisor, site_id):
        r = requests.post(f"{API}/events", data={"site_id": site_id, "text": "v2 compat"},
                          headers=supervisor["headers"], timeout=10)
        assert r.status_code in (200, 201), r.text
        eid = r.json()["id"]
        r2 = requests.get(f"{API}/events/{eid}", headers=supervisor["headers"], timeout=10)
        assert r2.status_code == 200
        _no_mongo_id(r2.json())

    def test_timeline_default_only_construction(self, supervisor, site_id):
        r = requests.get(f"{API}/timeline", params={"site_id": site_id},
                         headers=supervisor["headers"], timeout=10)
        assert r.status_code == 200
        body = r.json()
        # Default returns construction events; either flat list of events or {kind:construction_event}
        _no_mongo_id(body)
        items = body if isinstance(body, list) else body.get("items", [])
        for it in items:
            if "kind" in it:
                assert it["kind"] == "construction_event"


# ============== AI Proposal emission ==============
class TestAIProposals:
    def test_proposals_emitted(self, supervisor, ai_event):
        """After ~5-30s, expect 1 material + 1 site_issue proposal pending."""
        eid = ai_event["id"]
        props = []
        for _ in range(PROPOSAL_WAIT_S):
            r = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10)
            assert r.status_code == 200
            props = r.json()
            if len(props) >= 2:
                break
            time.sleep(1)
        _no_mongo_id(props)
        cats = [p["category"] for p in props]
        assert "material_requirement" in cats, f"expected material proposal; got {cats}"
        assert "site_issue" in cats, f"expected site_issue proposal; got {cats}"
        for p in props:
            assert p["decision"] == "pending"
            assert p["confidence"] == "high"
            assert p["event_id"] == eid

    def test_supervisor_cannot_accept(self, supervisor, ai_event):
        eid = ai_event["id"]
        props = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10).json()
        assert props, "no proposals to test against"
        r = requests.post(f"{API}/ai-proposals/{props[0]['id']}/accept", json={},
                          headers=supervisor["headers"], timeout=10)
        assert r.status_code == 403

    def test_supervisor_cannot_reject(self, supervisor, ai_event):
        eid = ai_event["id"]
        props = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10).json()
        r = requests.post(f"{API}/ai-proposals/{props[0]['id']}/reject", json={"reason": "no"},
                          headers=supervisor["headers"], timeout=10)
        assert r.status_code == 403

    def test_coordinator_accept_creates_item(self, supervisor, coordinator, ai_event):
        eid = ai_event["id"]
        props = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10).json()
        material = [p for p in props if p["category"] == "material_requirement"][0]
        r = requests.post(f"{API}/ai-proposals/{material['id']}/accept", json={},
                          headers=coordinator["headers"], timeout=15)
        assert r.status_code == 200, r.text
        item = r.json()
        _no_mongo_id(item)
        assert item["origin_type"] == "ai_proposal"
        assert item["origin_reference_id"] == material["id"]
        assert item["inherited_evidence_event_id"] == eid
        # proposal decision flipped
        check = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10).json()
        updated = [p for p in check if p["id"] == material["id"]][0]
        assert updated["decision"] in ("accepted", "edited")
        assert updated["operational_item_id"] == item["id"]
        # stash for later tests
        pytest.material_item_id = item["id"]

    def test_coordinator_reject_no_item(self, supervisor, coordinator, ai_event):
        eid = ai_event["id"]
        props = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10).json()
        issue = [p for p in props if p["category"] == "site_issue" and p["decision"] == "pending"][0]
        r = requests.post(f"{API}/ai-proposals/{issue['id']}/reject", json={"reason": "duplicate"},
                          headers=coordinator["headers"], timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["decision"] == "rejected"
        # confirm no operational_item created for it
        ck = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                          headers=supervisor["headers"], timeout=10).json()
        upd = [p for p in ck if p["id"] == issue["id"]][0]
        assert upd["decision"] == "rejected"
        assert upd.get("operational_item_id") in (None, "")
        assert upd.get("decided_by_user_id") == coordinator["user"]["id"]
        assert upd.get("decided_at")
        assert upd.get("decision_reason") == "duplicate"


# ============== Operational items: lifecycle ==============
@pytest.fixture(scope="session")
def fresh_item(coordinator, site_id):
    r = requests.post(f"{API}/operational-items",
                      json={"site_id": site_id, "category": "material_requirement",
                            "title": "TEST_lifecycle item", "priority": "high"},
                      headers=coordinator["headers"], timeout=10)
    assert r.status_code == 201, r.text
    return r.json()


class TestLifecycle:
    def test_invalid_transition_400(self, coordinator, fresh_item):
        r = requests.post(f"{API}/operational-items/{fresh_item['id']}/transition",
                          json={"to_status": "verified"},
                          headers=coordinator["headers"], timeout=10)
        assert r.status_code == 400

    def test_full_lifecycle(self, coordinator, fresh_item):
        item_id = fresh_item["id"]
        for to in ["in_progress", "fulfilled", "verified", "closed"]:
            r = requests.post(f"{API}/operational-items/{item_id}/transition",
                              json={"to_status": to}, headers=coordinator["headers"], timeout=10)
            assert r.status_code == 200, f"{to}: {r.text}"
            assert r.json()["status"] == to
        # history check
        det = requests.get(f"{API}/operational-items/{item_id}",
                           headers=coordinator["headers"], timeout=10).json()
        _no_mongo_id(det)
        hist = det["history"]
        assert hist == sorted(hist, key=lambda e: e["created_at"]), "history not asc"
        kinds = [h["kind"] for h in hist]
        assert kinds[0] == "created"
        assert "started" in kinds and "fulfilled" in kinds and "verified" in kinds and "closed" in kinds
        # health on fulfilled/verified/closed
        assert det["item"]["health"] == "completed"

    def test_history_no_dup_on_same_status(self, coordinator, site_id):
        r = requests.post(f"{API}/operational-items",
                          json={"site_id": site_id, "category": "material_requirement",
                                "title": "TEST_dup history"},
                          headers=coordinator["headers"], timeout=10)
        iid = r.json()["id"]
        requests.post(f"{API}/operational-items/{iid}/transition",
                      json={"to_status": "in_progress"}, headers=coordinator["headers"], timeout=10)
        before = requests.get(f"{API}/operational-items/{iid}",
                              headers=coordinator["headers"], timeout=10).json()["history"]
        # Same transition again — engine returns item without appending event
        requests.post(f"{API}/operational-items/{iid}/transition",
                      json={"to_status": "in_progress"}, headers=coordinator["headers"], timeout=10)
        after = requests.get(f"{API}/operational-items/{iid}",
                             headers=coordinator["headers"], timeout=10).json()["history"]
        assert len(after) == len(before), f"history dup: before={len(before)} after={len(after)}"


# ============== Blocker + Health ==============
class TestBlockerAndHealth:
    def test_blocker_waiting_external(self, coordinator, site_id):
        r = requests.post(f"{API}/operational-items",
                          json={"site_id": site_id, "category": "material_requirement",
                                "title": "TEST_blocker external"},
                          headers=coordinator["headers"], timeout=10).json()
        iid = r["id"]
        b = requests.post(f"{API}/operational-items/{iid}/blocker",
                          json={"category": "vendor_payment_pending"},
                          headers=coordinator["headers"], timeout=10).json()
        assert b["blocker"]["category"] == "vendor_payment_pending"
        assert b["health"] == "waiting_external"

    def test_blocker_internal_blocked(self, coordinator, site_id):
        r = requests.post(f"{API}/operational-items",
                          json={"site_id": site_id, "category": "material_requirement",
                                "title": "TEST_blocker internal"},
                          headers=coordinator["headers"], timeout=10).json()
        iid = r["id"]
        b = requests.post(f"{API}/operational-items/{iid}/blocker",
                          json={"category": "material_not_delivered"},
                          headers=coordinator["headers"], timeout=10).json()
        assert b["health"] == "blocked"
        # clear
        c = requests.delete(f"{API}/operational-items/{iid}/blocker",
                            headers=coordinator["headers"], timeout=10).json()
        assert c["blocker"] is None
        # ledger has blocker_cleared
        det = requests.get(f"{API}/operational-items/{iid}",
                           headers=coordinator["headers"], timeout=10).json()
        assert any(h["kind"] == "blocker_cleared" for h in det["history"])

    def test_health_overdue(self, coordinator, site_id):
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
        r = requests.post(f"{API}/operational-items",
                          json={"site_id": site_id, "category": "material_requirement",
                                "title": "TEST_overdue", "required_by": past},
                          headers=coordinator["headers"], timeout=10).json()
        assert r["health"] == "overdue"
        assert r["metrics"]["days_overdue"] >= 2

    def test_health_due_soon(self, coordinator, site_id):
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=6)).isoformat()
        r = requests.post(f"{API}/operational-items",
                          json={"site_id": site_id, "category": "material_requirement",
                                "title": "TEST_due_soon", "required_by": soon},
                          headers=coordinator["headers"], timeout=10).json()
        assert r["health"] == "due_soon"

    def test_health_completed_overrides_due(self, coordinator, site_id):
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
        item = requests.post(f"{API}/operational-items",
                             json={"site_id": site_id, "category": "material_requirement",
                                   "title": "TEST_complete past due", "required_by": past},
                             headers=coordinator["headers"], timeout=10).json()
        iid = item["id"]
        requests.post(f"{API}/operational-items/{iid}/transition",
                      json={"to_status": "in_progress"}, headers=coordinator["headers"], timeout=10)
        r = requests.post(f"{API}/operational-items/{iid}/transition",
                          json={"to_status": "fulfilled"},
                          headers=coordinator["headers"], timeout=10).json()
        assert r["health"] == "completed"


# ============== Metrics ==============
class TestMetrics:
    def test_metrics_fields(self, coordinator, site_id):
        r = requests.post(f"{API}/operational-items",
                          json={"site_id": site_id, "category": "material_requirement",
                                "title": "TEST_metrics"},
                          headers=coordinator["headers"], timeout=10).json()
        iid = r["id"]
        det = requests.get(f"{API}/operational-items/{iid}",
                           headers=coordinator["headers"], timeout=10).json()
        m = det["item"]["metrics"]
        for k in ("current_age_hours", "time_remaining_hours", "days_overdue",
                  "time_to_complete_hours", "verification_delay_hours"):
            assert k in m
        assert m["current_age_hours"] is not None
        assert m["time_to_complete_hours"] is None  # not yet completed
        assert m["verification_delay_hours"] is None


# ============== Comments ==============
class TestComments:
    def test_comment_no_status_change(self, coordinator, site_id):
        r = requests.post(f"{API}/operational-items",
                          json={"site_id": site_id, "category": "material_requirement",
                                "title": "TEST_comment"},
                          headers=coordinator["headers"], timeout=10).json()
        iid = r["id"]
        prev_status = r["status"]
        c = requests.post(f"{API}/operational-items/{iid}/comments",
                          json={"text": "note here"},
                          headers=coordinator["headers"], timeout=10)
        assert c.status_code == 201
        det = requests.get(f"{API}/operational-items/{iid}",
                           headers=coordinator["headers"], timeout=10).json()
        assert det["item"]["status"] == prev_status
        assert any(h["kind"] == "comment" and h["payload"].get("text") == "note here"
                   for h in det["history"])


# ============== Operational Center ==============
class TestOperationalCenter:
    def test_center_buckets_and_counts(self, coordinator):
        r = requests.get(f"{API}/operational-center", headers=coordinator["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        _no_mongo_id(body)
        for k in ("open", "overdue", "high_priority", "awaiting_verification",
                  "recently_completed", "recently_updated"):
            assert k in body, f"missing bucket {k}"
        for k in ("open", "overdue", "high_priority", "awaiting_verification", "blocked"):
            assert k in body["counts"], f"missing count {k}"


# ============== Site Requirements ==============
class TestSiteRequirements:
    def test_requirements_filters_issue(self, coordinator, site_id):
        # Create a site_issue (manual) and a material_requirement; only material should appear
        requests.post(f"{API}/operational-items",
                      json={"site_id": site_id, "category": "site_issue",
                            "title": "TEST_issue exclude"},
                      headers=coordinator["headers"], timeout=10)
        requests.post(f"{API}/operational-items",
                      json={"site_id": site_id, "category": "material_requirement",
                            "title": "TEST_mat include"},
                      headers=coordinator["headers"], timeout=10)
        r = requests.get(f"{API}/sites/{site_id}/requirements",
                         headers=coordinator["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        _no_mongo_id(body)
        for k in ("pending", "fulfilled", "verified", "counts"):
            assert k in body
        all_items = body["pending"] + body["fulfilled"] + body["verified"]
        cats = {i["category"] for i in all_items}
        assert "site_issue" not in cats
        assert all(c in {"material_requirement", "labour_requirement", "equipment_requirement",
                          "drawing_request", "client_approval", "inspection"} for c in cats)


# ============== Timeline include=ops ==============
class TestTimelineOps:
    def test_timeline_include_ops(self, supervisor, site_id):
        r = requests.get(f"{API}/timeline", params={"site_id": site_id, "include": "ops"},
                         headers=supervisor["headers"], timeout=15)
        assert r.status_code == 200
        body = r.json()
        _no_mongo_id(body)
        items = body if isinstance(body, list) else body.get("items", [])
        assert len(items) > 0
        kinds = {it.get("kind") for it in items}
        assert kinds.issubset({"construction_event", "operational_event"})
        assert "operational_event" in kinds, f"expected ops events in timeline; got {kinds}"
        # sorted desc
        ts = [it.get("created_at") for it in items if it.get("created_at")]
        assert ts == sorted(ts, reverse=True), "timeline not sorted desc"


# ============== Immutability ==============
class TestImmutability:
    def test_construction_event_unchanged(self, supervisor, ai_event):
        eid = ai_event["id"]
        r = requests.get(f"{API}/events/{eid}", headers=supervisor["headers"], timeout=10)
        assert r.status_code == 200
        body = r.json()
        ev = body.get("event", body)
        # original factual fields
        assert ev["site_id"] == ai_event["site_id"]
        assert ev["text_input"] == ai_event["text_input"]
        assert ev["user_id"] == ai_event["user_id"]
        assert ev["kind"] == ai_event["kind"]
        assert ev["server_created_at"] == ai_event["server_created_at"]


# ============== Recursive _id absence (extra coverage) ==============
class TestNoMongoId:
    def test_all_v3_responses(self, coordinator, supervisor, site_id):
        # list items
        r = requests.get(f"{API}/operational-items", params={"site_id": site_id},
                         headers=coordinator["headers"], timeout=10).json()
        _no_mongo_id(r)
        # center
        c = requests.get(f"{API}/operational-center", headers=coordinator["headers"], timeout=10).json()
        _no_mongo_id(c)
        # requirements
        req = requests.get(f"{API}/sites/{site_id}/requirements",
                           headers=coordinator["headers"], timeout=10).json()
        _no_mongo_id(req)
        # ai-proposals list
        ap = requests.get(f"{API}/ai-proposals", headers=coordinator["headers"], timeout=10).json()
        _no_mongo_id(ap)
        # timeline ops
        tl = requests.get(f"{API}/timeline", params={"site_id": site_id, "include": "ops"},
                          headers=supervisor["headers"], timeout=10).json()
        _no_mongo_id(tl)
