"""Project Atlas V3.1 — Canonical Proposal Pipeline tests.

Validates the architectural fix that proposal generation:
  * runs on the canonical ai_analyses.structured doc (input-method agnostic)
  * sets lifecycle marker `proposals_status` ∈ {pending, generated, empty, failed}
  * is idempotent (skip when proposals exist unless force=true)
  * is exposed as POST /api/events/{id}/regenerate-proposals
    (coordinator/management only; supervisor → 403)
  * V2/V3 endpoints continue to work — proposals_status/proposals_error
    are purely additive on event docs
"""
import io
import os
import re
import time
import pytest
import requests

BASE_URL = (os.environ.get("EXPO_PUBLIC_BACKEND_URL")
            or "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

PROPOSAL_WAIT_S = 60  # LLM call can take several seconds


# ---- helpers ----
def _no_mongo_id(obj, path="root"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k != "_id", f"Mongo _id at {path}"
            _no_mongo_id(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_mongo_id(v, f"{path}[{i}]")


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    b = r.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


def _wait_for_proposals_status(headers, event_id, target_statuses, timeout=PROPOSAL_WAIT_S):
    """Poll GET /api/events/{id} until event.proposals_status hits target."""
    last = None
    for _ in range(timeout):
        r = requests.get(f"{API}/events/{event_id}", headers=headers, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        ev = body.get("event", body)
        last = ev
        if ev.get("proposals_status") in target_statuses:
            return ev
        time.sleep(1)
    pytest.fail(f"proposals_status never reached {target_statuses}; "
                f"last={last.get('proposals_status') if last else None} "
                f"ai_status={last.get('ai_status') if last else None}")


# ---- fixtures ----
@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("supervisor", "9999988888", "Test User")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def coordinator():
    u, h = _login("coordinator", "9222222222", "Priya Coordinator")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def management():
    u, h = _login("management", "9333333333", "Mr. Sharma")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def site_id(supervisor):
    requests.post(f"{API}/projects/seed", headers=supervisor["headers"], timeout=20)
    sites = requests.get(f"{API}/sites", headers=supervisor["headers"], timeout=20).json()
    assert sites
    return sites[0]["id"]


# Tiny valid JPEG (1x1) used as a photo payload
_TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffdb0043010909090c0b0c180d0d1832211c213232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232323232ffc0001108000100010301220002110103110100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f0100030101010101010101010000000000000102030405060708090a0bffc400b51100020102040403040705040400010277000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a35363738393a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c03010002110311003f00fbfcffd9"
)


# ============== 1. Canonical pipeline: text-only ==============
class TestCanonicalPipelineText:
    def test_text_event_reaches_generated(self, supervisor, site_id):
        payload = {
            "site_id": site_id,
            "text": "kal 30 bag cement chahiye urgent, crane kharab hai",
        }
        r = requests.post(f"{API}/events", data=payload,
                          headers=supervisor["headers"], timeout=20)
        assert r.status_code in (200, 201), r.text
        evt = r.json()
        # New event default state
        assert evt.get("proposals_status") == "pending", \
            f"new event should default to proposals_status='pending'; got {evt.get('proposals_status')}"
        assert evt.get("proposals_error") is None
        eid = evt["id"]

        # Wait for proposals to be generated
        ev = _wait_for_proposals_status(supervisor["headers"], eid,
                                        {"generated", "empty", "failed"})
        assert ev["ai_status"] == "analyzed", f"expected ai_status=analyzed; got {ev}"
        assert ev["proposals_status"] == "generated", \
            f"text event should reach proposals_status=generated; got {ev['proposals_status']}, " \
            f"error={ev.get('proposals_error')}"
        assert ev["proposals_error"] is None

        # Verify proposals exist with both categories
        props = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10).json()
        _no_mongo_id(props)
        cats = [p["category"] for p in props]
        assert "material_requirement" in cats, f"missing material_requirement; cats={cats}"
        assert "site_issue" in cats, f"missing site_issue; cats={cats}"

        # Stash
        pytest.text_event_id = eid
        pytest.text_event_proposal_count = len(props)


# ============== 2. Canonical pipeline: mixed (text + photo) ==============
class TestCanonicalPipelineMixed:
    def test_mixed_event_reaches_generated(self, supervisor, site_id):
        files = {"photos": ("site.jpg", io.BytesIO(_TINY_JPEG), "image/jpeg")}
        data = {"site_id": site_id,
                "text": "kal 30 bag cement chahiye urgent, crane kharab hai"}
        r = requests.post(f"{API}/events", data=data, files=files,
                          headers=supervisor["headers"], timeout=30)
        assert r.status_code in (200, 201), r.text
        evt = r.json()
        assert evt.get("proposals_status") == "pending"
        assert evt["kind"] == "mixed", f"expected kind=mixed; got {evt['kind']}"
        eid = evt["id"]

        ev = _wait_for_proposals_status(supervisor["headers"], eid,
                                        {"generated", "empty", "failed"})
        assert ev["proposals_status"] == "generated", \
            f"mixed event should hit proposals_status=generated; got {ev['proposals_status']}, " \
            f"error={ev.get('proposals_error')}"
        assert ev["proposals_error"] is None
        props = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=supervisor["headers"], timeout=10).json()
        cats = [p["category"] for p in props]
        assert "material_requirement" in cats
        assert "site_issue" in cats
        pytest.mixed_event_id = eid


# ============== 3. Static code parity check ==============
class TestCodeParity:
    """Voice/text/mixed must hit identical proposal code path."""
    def test_intelligence_engine_canonical_path(self):
        src = open("/app/backend/engines/intelligence_engine.py").read()
        # (a) generate_proposals_for_event called unconditionally after analyzed status
        # Find _process and ensure set_event_ai_status(...,'analyzed',...) is followed by
        # generate_proposals_for_event(event_id) within the same try block.
        m = re.search(
            r"set_event_ai_status\(\s*event_id\s*,\s*[\"']analyzed[\"'].*?\)"
            r".*?generate_proposals_for_event\(\s*event_id\s*\)",
            src, re.DOTALL)
        assert m, "generate_proposals_for_event(event_id) is not called unconditionally " \
                  "after set_event_ai_status(..., 'analyzed', ...) inside _process"

        # (b) generate_proposals_for_event reads canonical record via get_ai_analysis(event_id)
        m2 = re.search(
            r"async\s+def\s+generate_proposals_for_event\([^)]*\).*?"
            r"memory_engine\.get_ai_analysis\(\s*event_id\s*\)",
            src, re.DOTALL)
        assert m2, "generate_proposals_for_event must read memory_engine.get_ai_analysis(event_id)"

        # Must reference .structured (the canonical structured field)
        gpfe_block = src.split("async def generate_proposals_for_event", 1)[1]
        assert "structured" in gpfe_block, \
            "generate_proposals_for_event must use the .structured canonical record"

        # Deprecated alias must route through canonical path
        assert "_emit_proposals_from_structured" in src, \
            "_emit_proposals_from_structured (canonical helper) missing"


# ============== 4. Idempotency ==============
class TestIdempotency:
    def test_skipped_existing_when_no_force(self, coordinator):
        eid = pytest.text_event_id
        # Get current proposal count
        before = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                              headers=coordinator["headers"], timeout=10).json()
        n_before = len(before)
        assert n_before >= 2

        r = requests.post(f"{API}/events/{eid}/regenerate-proposals",
                          headers=coordinator["headers"], timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        _no_mongo_id(body)
        assert body["status"] == "skipped_existing", body
        assert body["generated_count"] == n_before, \
            f"skipped_existing.generated_count {body['generated_count']} != existing {n_before}"

        after = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=coordinator["headers"], timeout=10).json()
        assert len(after) == n_before, \
            f"row count grew without force: {n_before} -> {len(after)}"


# ============== 5. Force replay ==============
class TestForceReplay:
    def test_force_grows_rows(self, coordinator):
        eid = pytest.text_event_id
        before = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                              headers=coordinator["headers"], timeout=10).json()
        n_before = len(before)
        r = requests.post(f"{API}/events/{eid}/regenerate-proposals",
                          params={"force": "true"},
                          headers=coordinator["headers"], timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "generated", body
        assert body["generated_count"] > 0
        after = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                             headers=coordinator["headers"], timeout=10).json()
        assert len(after) > n_before, \
            f"force=true did not add rows: before={n_before} after={len(after)}"


# ============== 6. Authorisation ==============
class TestRegenerateAuth:
    def test_supervisor_403(self, supervisor):
        eid = pytest.text_event_id
        r = requests.post(f"{API}/events/{eid}/regenerate-proposals",
                          headers=supervisor["headers"], timeout=15)
        assert r.status_code == 403, f"supervisor must be 403; got {r.status_code} {r.text}"

    def test_coordinator_200(self, coordinator):
        eid = pytest.text_event_id
        r = requests.post(f"{API}/events/{eid}/regenerate-proposals",
                          headers=coordinator["headers"], timeout=30)
        assert r.status_code == 200, r.text

    def test_management_200(self, management):
        eid = pytest.text_event_id
        r = requests.post(f"{API}/events/{eid}/regenerate-proposals",
                          headers=management["headers"], timeout=30)
        assert r.status_code == 200, r.text


# ============== 7. Failure isolation fields surface on GET /events ==============
class TestLifecycleSurface:
    def test_event_has_proposals_fields(self, supervisor):
        eid = pytest.text_event_id
        r = requests.get(f"{API}/events/{eid}", headers=supervisor["headers"], timeout=10)
        body = r.json()
        _no_mongo_id(body)
        ev = body.get("event", body)
        assert "proposals_status" in ev, "event must expose proposals_status"
        assert "proposals_error" in ev, "event must expose proposals_error"
        assert ev["proposals_status"] == "generated"
        assert ev["proposals_error"] is None

    def test_empty_event_marks_empty(self, supervisor, site_id):
        # A pure 'thanks' message shouldn't yield material or issue
        r = requests.post(f"{API}/events", data={"site_id": site_id,
                          "text": "good morning, everything fine today, all clear"},
                          headers=supervisor["headers"], timeout=20)
        assert r.status_code in (200, 201)
        eid = r.json()["id"]
        ev = _wait_for_proposals_status(supervisor["headers"], eid,
                                        {"generated", "empty", "failed"})
        # Accept generated OR empty - LLM might still extract; we just need a terminal state
        # and proposals_error null on success.
        assert ev["proposals_status"] in {"generated", "empty"}
        assert ev.get("proposals_error") is None


# ============== 8. Backward compatibility ==============
class TestBackwardCompat:
    def test_login_me(self, supervisor):
        r = requests.get(f"{API}/me", headers=supervisor["headers"], timeout=10)
        assert r.status_code == 200
        assert r.json()["phone"] == "9999988888"

    def test_sites(self, supervisor):
        r = requests.get(f"{API}/sites", headers=supervisor["headers"], timeout=10)
        assert r.status_code == 200
        _no_mongo_id(r.json())

    def test_operational_items(self, coordinator, site_id):
        r = requests.get(f"{API}/operational-items", params={"site_id": site_id},
                         headers=coordinator["headers"], timeout=10)
        assert r.status_code == 200
        _no_mongo_id(r.json())

    def test_operational_center(self, coordinator):
        r = requests.get(f"{API}/operational-center",
                         headers=coordinator["headers"], timeout=15)
        assert r.status_code == 200
        _no_mongo_id(r.json())

    def test_requirements(self, coordinator, site_id):
        r = requests.get(f"{API}/sites/{site_id}/requirements",
                         headers=coordinator["headers"], timeout=15)
        assert r.status_code == 200
        _no_mongo_id(r.json())

    def test_timeline_default_and_ops(self, supervisor, site_id):
        for params in ({"site_id": site_id}, {"site_id": site_id, "include": "ops"}):
            r = requests.get(f"{API}/timeline", params=params,
                             headers=supervisor["headers"], timeout=15)
            assert r.status_code == 200
            _no_mongo_id(r.json())

    def test_event_factual_fields_intact(self, supervisor):
        eid = pytest.text_event_id
        r = requests.get(f"{API}/events/{eid}", headers=supervisor["headers"], timeout=10)
        body = r.json()
        ev = body.get("event", body)
        assert ev["text_input"] == "kal 30 bag cement chahiye urgent, crane kharab hai"
        assert ev["site_id"]
        assert ev["user_id"]
        assert ev["kind"] == "text"


# ============== 9. Regenerate endpoint edge case ==============
class TestRegenerateNotFound:
    def test_404_unknown_event(self, coordinator):
        r = requests.post(f"{API}/events/evt_does_not_exist/regenerate-proposals",
                          headers=coordinator["headers"], timeout=10)
        assert r.status_code == 404
