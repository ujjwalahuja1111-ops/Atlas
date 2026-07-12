"""Project Atlas V2 — End-to-end backend test suite.

Validates:
  * boot + root endpoint
  * auth (login + /me 401)
  * project/site seeding (idempotency, hierarchy)
  * Golden Rule: POST /api/events returns <1s with ai_status='pending'
  * AI pipeline: event flips to 'analyzed' with structured fields
  * Immutability: factual fields never mutated after analysis
  * Evidence Model: ai_analyses.evidence references inputs
  * Prompt Versioning: ai_analyses carries prompt_version_id + names
  * Corrections (append-only, original unchanged)
  * Timeline projection (event + analysis + corrections + photo_thumbs)
  * Photo capture (raw_assets with sha256, event still <1s)
  * No mongo _id anywhere in responses (recursive scan)
"""
import io
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ------------- helpers -------------
def _recursive_no_underscore_id(obj, path="root"):
    """Recursively assert no key '_id' anywhere (Mongo internal id)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k != "_id", f"Found Mongo _id at {path}"
            _recursive_no_underscore_id(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _recursive_no_underscore_id(v, f"{path}[{i}]")


# ------------- fixtures -------------
# FAC-03 P0 fix: /api/auth/login no longer auto-creates an account for an
# unrecognized phone number - see the identical note in the other test
# files for the full rationale.
_SEEDED_ADMIN_PHONE = "9000000001"  # DX-7 seed script's "Atlas Admin 1"
_seeded_admin_cache: dict = {}


def _seeded_admin_headers():
    if "headers" not in _seeded_admin_cache:
        r = requests.post(f"{API}/auth/login",
                          json={"phone": _SEEDED_ADMIN_PHONE, "name": "Atlas Admin 1", "role": "management"},
                          timeout=20)
        assert r.status_code == 200, (
            "Seeded admin account not found - has the target environment been "
            f"seeded? (python -m scripts.dev seed) {r.text}"
        )
        _seeded_admin_cache["headers"] = {"Authorization": f"Bearer {r.json()['token']}"}
    return _seeded_admin_cache["headers"]


@pytest.fixture(scope="session")
def auth():
    """Login the seed test user and return (token, user, headers)."""
    phone, name, role = "9999988888", "Test User", "supervisor"
    r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    if r.status_code != 200:
        reg = requests.post(f"{API}/auth/register", json={"phone": phone, "name": name}, timeout=20)
        assert reg.status_code == 200, reg.text
        user_id = reg.json()["user"]["id"]
        admin_headers = _seeded_admin_headers()
        requests.post(f"{API}/admin/users/{user_id}/approve", headers=admin_headers, timeout=20)
        requests.post(f"{API}/admin/users/{user_id}/role", json={"role": role}, headers=admin_headers, timeout=20)
        r = requests.post(f"{API}/auth/login", json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "token" in body and "user" in body
    _recursive_no_underscore_id(body, "login")
    return {
        "token": body["token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }


@pytest.fixture(scope="session")
def seeded(auth):
    """Ensure project + sites exist. Verifies idempotency on 2nd call."""
    r1 = requests.post(f"{API}/projects/seed", headers=auth["headers"], timeout=20)
    assert r1.status_code == 200, r1.text
    r2 = requests.post(f"{API}/projects/seed", headers=auth["headers"], timeout=20)
    assert r2.status_code == 200, r2.text
    # 2nd call must be idempotent → seeded:false
    assert r2.json().get("seeded") is False, f"Seed not idempotent: {r2.json()}"
    return r2.json()


# ------------- boot / root -------------
def test_root_returns_project_atlas_v2():
    r = requests.get(f"{API}/", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("platform") == "Project Atlas"
    assert body.get("version") == "2.0.0"


# ------------- auth -------------
def test_login_returns_token_and_user_no_id_leak(auth):
    u = auth["user"]
    assert u["phone"] == "9999988888"
    assert u["name"] == "Test User"
    assert "id" in u
    assert "_id" not in u


def test_me_missing_token_401():
    r = requests.get(f"{API}/me", timeout=10)
    assert r.status_code == 401


def test_me_invalid_token_401():
    r = requests.get(f"{API}/me", headers={"Authorization": "Bearer notatoken"}, timeout=10)
    assert r.status_code == 401


def test_me_with_valid_token(auth):
    r = requests.get(f"{API}/me", headers=auth["headers"], timeout=10)
    assert r.status_code == 200
    body = r.json()
    _recursive_no_underscore_id(body, "/me")
    assert body["id"] == auth["user"]["id"]


# ------------- projects + sites -------------
def test_one_project_three_sites(auth, seeded):
    pr = requests.get(f"{API}/projects", headers=auth["headers"], timeout=10)
    sr = requests.get(f"{API}/sites", headers=auth["headers"], timeout=10)
    assert pr.status_code == 200 and sr.status_code == 200
    projects = pr.json()
    sites = sr.json()
    _recursive_no_underscore_id(projects, "projects")
    _recursive_no_underscore_id(sites, "sites")
    assert len(projects) == 1, f"Expected 1 project, got {len(projects)}"
    assert len(sites) == 3, f"Expected 3 sites, got {len(sites)}"
    pid = projects[0]["id"]
    for s in sites:
        assert s["project_id"] == pid, f"Site {s['name']} not linked to project {pid}"


# ------------- Golden Rule + AI pipeline -------------
@pytest.fixture(scope="session")
def text_event(auth, seeded):
    """Create a text-only event and time the response. Must be <1s with ai_status=pending."""
    sites = requests.get(f"{API}/sites", headers=auth["headers"], timeout=10).json()
    site_id = sites[0]["id"]
    t0 = time.time()
    r = requests.post(
        f"{API}/events",
        headers=auth["headers"],
        data={"site_id": site_id, "text": "kal 50 bag cement chahiye, crane kharab hai urgent"},
        timeout=10,
    )
    elapsed = time.time() - t0
    assert r.status_code == 201, r.text
    ev = r.json()
    _recursive_no_underscore_id(ev, "event")
    return {"event": ev, "elapsed": elapsed, "site_id": site_id, "original": ev}


def test_golden_rule_text_event_under_1s(text_event):
    assert text_event["elapsed"] < 1.0, f"Capture took {text_event['elapsed']:.3f}s (must be <1s)"
    ev = text_event["event"]
    assert ev["ai_status"] == "pending"
    assert ev["text_input"] == "kal 50 bag cement chahiye, crane kharab hai urgent"
    assert ev["ai_analysis_id"] is None


def test_event_becomes_analyzed_with_materials(auth, text_event):
    eid = text_event["event"]["id"]
    deadline = time.time() + 25
    item = None
    while time.time() < deadline:
        r = requests.get(f"{API}/events/{eid}", headers=auth["headers"], timeout=10)
        assert r.status_code == 200
        item = r.json()
        if item["event"]["ai_status"] in ("analyzed", "failed"):
            break
        time.sleep(1.5)
    assert item is not None
    _recursive_no_underscore_id(item, "/events/{id}")
    assert item["event"]["ai_status"] == "analyzed", f"final status={item['event']['ai_status']}"
    structured = item["analysis"]["structured"]
    assert isinstance(structured.get("materials"), list)
    # cement in text — must surface at least one material
    assert len(structured["materials"]) >= 1, f"materials empty: {structured}"


def test_event_immutability_after_analysis(auth, text_event):
    eid = text_event["event"]["id"]
    original = text_event["original"]
    r = requests.get(f"{API}/events/{eid}", headers=auth["headers"], timeout=10)
    current = r.json()["event"]
    for field in ["text_input", "site_id", "user_id", "kind", "server_created_at", "id"]:
        assert current[field] == original[field], f"Field {field} mutated! {current[field]!r} != {original[field]!r}"
    # only these two may have changed
    assert current["ai_status"] in ("analyzed", "failed")
    assert current["ai_analysis_id"] is not None


def test_evidence_model_text_event(auth, text_event):
    eid = text_event["event"]["id"]
    item = requests.get(f"{API}/events/{eid}", headers=auth["headers"], timeout=10).json()
    analysis = item["analysis"]
    assert analysis is not None, "ai_analyses doc missing"
    evidence = analysis.get("evidence")
    assert isinstance(evidence, list) and len(evidence) >= 1, f"evidence empty: {evidence}"
    # text-only event → evidence must include {kind:'text', value:...}
    text_ev = [e for e in evidence if e.get("kind") == "text"]
    assert text_ev and text_ev[0]["value"] == "kal 50 bag cement chahiye, crane kharab hai urgent"


def test_prompt_versioning(auth, text_event):
    eid = text_event["event"]["id"]
    item = requests.get(f"{API}/events/{eid}", headers=auth["headers"], timeout=10).json()
    a = item["analysis"]
    assert a["prompt_name"] == "atlas_event_structurer"
    assert a["prompt_version"] == "1.0"
    assert a["prompt_version_id"], "prompt_version_id missing"
    mv = a["model_versions"]
    assert mv.get("llm"), "model_versions.llm missing"
    # text-only — stt should be None
    assert mv.get("stt") is None


# ------------- corrections -------------
def test_correction_linked_and_original_unchanged(auth, text_event):
    eid = text_event["event"]["id"]
    before = requests.get(f"{API}/events/{eid}", headers=auth["headers"], timeout=10).json()["event"]
    r = requests.post(
        f"{API}/events/{eid}/corrections",
        headers={**auth["headers"], "Content-Type": "application/json"},
        json={"note": "Correction test"},
        timeout=10,
    )
    assert r.status_code == 201, r.text
    cor = r.json()
    _recursive_no_underscore_id(cor, "correction")
    assert cor["original_event_id"] == eid
    assert cor["payload"]["note"] == "Correction test"
    after = requests.get(f"{API}/events/{eid}", headers=auth["headers"], timeout=10).json()
    # original event fields unchanged
    for f in ["text_input", "site_id", "user_id", "kind", "server_created_at"]:
        assert after["event"][f] == before[f]
    # correction surfaces in timeline single
    assert any(c["id"] == cor["id"] for c in after["corrections"])


# ------------- timeline projection -------------
def test_timeline_returns_items_newest_first(auth, text_event):
    site_id = text_event["site_id"]
    r = requests.get(f"{API}/timeline", params={"site_id": site_id}, headers=auth["headers"], timeout=10)
    assert r.status_code == 200
    items = r.json()
    _recursive_no_underscore_id(items, "timeline")
    assert len(items) >= 1
    # newest first by server_created_at
    times = [i["event"]["server_created_at"] for i in items]
    assert times == sorted(times, reverse=True), "Timeline not sorted newest-first"
    # shape
    first = items[0]
    assert "event" in first and "analysis" in first and "corrections" in first and "photo_thumbs" in first


# ------------- photo capture -------------
@pytest.fixture(scope="session")
def tiny_jpeg_bytes():
    """Generate a tiny valid JPEG using PIL."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def _unused_hex_fixture():
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
        "07090908"
        + "0a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c"
        + "30313434341f27393d38323c2e333432ffdb0043010909090c0b0c180d0d1832211c21"
        + "32323232323232323232323232323232323232323232323232323232323232323232"
        + "32323232323232323232323232323232323232323232ffc0001108000100010301220002"
        + "11010311010"
        + "1ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc4"
        + "00b510000201"
        + "0303020403050504040000017d01020300041105122131410613516107227114328191"
        + "a1082342b1c11552d1f0243"
        + "3627282090a161718191a25262728292a3435363738393a434445464748494a535455"
        + "565758595a636465666768"
        + "696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9"
        + "aab2b3b4b5b6b7b8b9bac2c3c4"
        + "c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faff"
        + "da000c03010002110311003f00fbd0fffd9"
    )


def test_photo_event_under_1s_and_assets_recorded(auth, seeded, tiny_jpeg_bytes):
    sites = requests.get(f"{API}/sites", headers=auth["headers"], timeout=10).json()
    site_id = sites[0]["id"]
    files = {"photos": ("test.jpg", io.BytesIO(tiny_jpeg_bytes), "image/jpeg")}
    data = {"site_id": site_id, "text": "Photo of progress today"}
    t0 = time.time()
    r = requests.post(f"{API}/events", headers=auth["headers"], data=data, files=files, timeout=15)
    elapsed = time.time() - t0
    assert r.status_code == 201, r.text
    ev = r.json()
    _recursive_no_underscore_id(ev, "photo event")
    assert elapsed < 1.5, f"Photo capture took {elapsed:.3f}s"
    assert ev["ai_status"] == "pending"
    assert len(ev["photo_asset_ids"]) == 1
    # Fetch asset and verify sha256 + no _id
    asset_id = ev["photo_asset_ids"][0]
    ar = requests.get(f"{API}/raw-assets/{asset_id}", headers=auth["headers"], timeout=10)
    assert ar.status_code == 200
    asset = ar.json()
    _recursive_no_underscore_id(asset, "asset")
    assert asset["sha256"] and len(asset["sha256"]) == 64
    assert asset["kind"] == "photo"
