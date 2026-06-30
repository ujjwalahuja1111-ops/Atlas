"""Project Atlas V3.2 — Operational Completion tests.

Validates:
  * Multi-intent extraction → ≥4 categories from a single utterance
  * Material/labour/equipment detail extraction (qty, unit, trade, count, name)
  * suggested_owner_role populated per category
  * GET /api/users (no phone leak) + ?role= filter
  * Assignment workflow + append-only ledger
  * Accept proposal with optional assigned_to_user_id
  * Accepted item carries suggested_owner_role + ai_details + ai_confidence
  * V3.1 backward compat (smoke)
  * No Mongo _id leak on any touched endpoint
"""
import os, time, pytest, requests

BASE = (os.environ.get("EXPO_PUBLIC_BACKEND_URL") or
        "https://construct-events.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
WAIT = 60


def _no_id(o, p="root"):
    if isinstance(o, dict):
        for k, v in o.items():
            assert k != "_id", f"_id at {p}"
            _no_id(v, f"{p}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _no_id(v, f"{p}[{i}]")


def _login(role, phone, name):
    r = requests.post(f"{API}/auth/login",
                      json={"phone": phone, "name": name, "role": role}, timeout=20)
    assert r.status_code == 200, r.text
    b = r.json()
    return b["user"], {"Authorization": f"Bearer {b['token']}"}


def _wait_props(headers, eid, statuses=("generated", "empty", "failed"), timeout=WAIT):
    for _ in range(timeout):
        r = requests.get(f"{API}/events/{eid}", headers=headers, timeout=10).json()
        ev = r.get("event", r)
        if ev.get("proposals_status") in statuses:
            return ev
        time.sleep(1)
    pytest.fail("proposals_status never settled")


@pytest.fixture(scope="session")
def supervisor():
    u, h = _login("supervisor", "9999988888", "Test User")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def coordinator():
    u, h = _login("coordinator", "9222222222", "Priya Coordinator")
    return {"user": u, "headers": h}


@pytest.fixture(scope="session")
def site_id(supervisor):
    requests.post(f"{API}/projects/seed", headers=supervisor["headers"], timeout=20)
    sites = requests.get(f"{API}/sites", headers=supervisor["headers"], timeout=20).json()
    assert sites
    return sites[0]["id"]


@pytest.fixture(scope="session")
def multi_intent_event(supervisor, site_id):
    text = ("Kal 30 bags cement chahiye, do electrician bhejna, "
            "crane kharab hai aur client approval pending hai")
    r = requests.post(f"{API}/events", data={"site_id": site_id, "text": text},
                      headers=supervisor["headers"], timeout=30)
    assert r.status_code in (200, 201), r.text
    eid = r.json()["id"]
    ev = _wait_props(supervisor["headers"], eid)
    assert ev["proposals_status"] == "generated", f"got {ev['proposals_status']} err={ev.get('proposals_error')}"
    props = requests.get(f"{API}/ai-proposals", params={"event_id": eid},
                         headers=supervisor["headers"], timeout=15).json()
    return {"event_id": eid, "proposals": props}


# 1. Multi-intent extraction
class TestMultiIntent:
    def test_at_least_4_distinct_categories(self, multi_intent_event):
        props = multi_intent_event["proposals"]
        _no_id(props)
        cats = {p["category"] for p in props}
        expected = {"material_requirement", "labour_requirement",
                    "equipment_requirement", "client_approval", "site_issue"}
        got = cats & expected
        assert len(got) >= 4, f"expected ≥4 of {expected}; got {cats}"

    def test_confidence_and_owner_role_set(self, multi_intent_event):
        props = multi_intent_event["proposals"]
        for p in props:
            assert p.get("confidence") in ("low", "medium", "high"), p
            assert p.get("suggested_owner_role"), f"missing suggested_owner_role on {p['category']}"

    def test_owner_role_mapping(self, multi_intent_event):
        roles = {p["category"]: p["suggested_owner_role"] for p in multi_intent_event["proposals"]}
        if "material_requirement" in roles:
            assert roles["material_requirement"] == "coordinator"
        if "client_approval" in roles:
            assert roles["client_approval"] == "client_coordinator"
        if "site_issue" in roles:
            assert roles["site_issue"] == "site_engineer"


# 2. Material/labour/equipment intelligence
class TestExtraction:
    def test_material_quantity_unit(self, multi_intent_event):
        mats = [p for p in multi_intent_event["proposals"] if p["category"] == "material_requirement"]
        assert mats, "no material_requirement"
        d = mats[0].get("details") or {}
        # key shape exists
        assert "quantity" in d and "unit" in d and "required_date" in d
        # speaker said 30 bags
        q = d.get("quantity")
        u = (d.get("unit") or "").lower()
        assert str(q) == "30" or q == 30, f"quantity expected 30; got {q}"
        assert "bag" in u, f"unit expected to mention bags; got {u}"

    def test_labour_trade_count(self, multi_intent_event):
        labs = [p for p in multi_intent_event["proposals"] if p["category"] == "labour_requirement"]
        assert labs, "no labour_requirement"
        d = labs[0].get("details") or {}
        assert d.get("trade"), f"labour trade missing; details={d}"
        assert d.get("count") not in (None, ""), f"labour count missing; details={d}"

    def test_equipment_name(self, multi_intent_event):
        eqs = [p for p in multi_intent_event["proposals"] if p["category"] == "equipment_requirement"]
        assert eqs, "no equipment_requirement"
        d = eqs[0].get("details") or {}
        name = (d.get("name") or d.get("equipment") or "").lower()
        assert "crane" in name, f"equipment name not crane; got {name}"

    def test_each_category_independent_row(self, multi_intent_event):
        props = multi_intent_event["proposals"]
        assert len(props) >= 4, f"expected ≥4 proposals; got {len(props)}"


# 3. Users endpoint
class TestUsers:
    def test_users_list_no_phone(self, coordinator):
        r = requests.get(f"{API}/users", headers=coordinator["headers"], timeout=10)
        assert r.status_code == 200
        users = r.json()
        _no_id(users)
        assert isinstance(users, list) and users
        for u in users:
            assert set(u.keys()) == {"id", "name", "role"}, f"phone may have leaked: {u.keys()}"

    def test_users_role_filter(self, coordinator):
        r = requests.get(f"{API}/users", params={"role": "coordinator"},
                         headers=coordinator["headers"], timeout=10)
        assert r.status_code == 200
        for u in r.json():
            assert u["role"] == "coordinator"


# 4. Assignment workflow (append-only ledger)
class TestAssignmentWorkflow:
    @pytest.fixture(scope="class")
    def open_item(self, coordinator, site_id):
        # Create a fresh manual item
        r = requests.post(f"{API}/operational-items", json={
            "site_id": site_id, "category": "material_requirement",
            "title": "TEST_assign_workflow_item", "priority": "normal",
            "origin_type": "manual",
        }, headers=coordinator["headers"], timeout=10)
        assert r.status_code == 201, r.text
        _no_id(r.json())
        return r.json()

    def test_assign_then_reassign_ledger_grows(self, coordinator, open_item):
        users = requests.get(f"{API}/users", headers=coordinator["headers"], timeout=10).json()
        assert len(users) >= 2
        u1, u2 = users[0], users[1]
        iid = open_item["id"]

        # First assign
        r = requests.post(f"{API}/operational-items/{iid}/assign",
                          json={"assigned_to_user_id": u1["id"]},
                          headers=coordinator["headers"], timeout=10)
        assert r.status_code == 200, r.text
        item = r.json()
        _no_id(item)
        assert item["assigned_to_user_id"] == u1["id"]
        assert item["assigned_to_user_name"] == u1["name"]

        hist1 = requests.get(f"{API}/operational-items/{iid}",
                             headers=coordinator["headers"], timeout=10).json()["history"]
        assigned_evs_1 = [h for h in hist1 if h["kind"] == "assigned"]
        n1 = len(assigned_evs_1)
        assert n1 >= 1, f"no assigned ledger event; history={hist1}"
        first_ev = assigned_evs_1[-1]

        # Reassign to a different user
        r = requests.post(f"{API}/operational-items/{iid}/assign",
                          json={"assigned_to_user_id": u2["id"]},
                          headers=coordinator["headers"], timeout=10)
        assert r.status_code == 200, r.text
        item2 = r.json()
        assert item2["assigned_to_user_id"] == u2["id"]

        hist2 = requests.get(f"{API}/operational-items/{iid}",
                             headers=coordinator["headers"], timeout=10).json()["history"]
        assigned_evs_2 = [h for h in hist2 if h["kind"] == "assigned"]
        assert len(assigned_evs_2) == n1 + 1, \
            f"append-only violated: {n1} -> {len(assigned_evs_2)}"
        # First event must NOT be mutated
        same = [h for h in assigned_evs_2 if h["id"] == first_ev["id"]][0]
        assert same["payload"] == first_ev["payload"], "previous ledger row was mutated"


# 5. Accept proposal with optional assignment
class TestAcceptWithAssign:
    def test_accept_with_assigned_user(self, coordinator, multi_intent_event):
        # find first pending material_requirement proposal
        props = [p for p in multi_intent_event["proposals"]
                 if p["category"] == "material_requirement" and p.get("decision") == "pending"]
        assert props, "no pending material proposal"
        pid = props[0]["id"]

        users = requests.get(f"{API}/users", params={"role": "coordinator"},
                             headers=coordinator["headers"], timeout=10).json()
        if not users:
            users = requests.get(f"{API}/users", headers=coordinator["headers"], timeout=10).json()
        assignee = users[0]

        r = requests.post(f"{API}/ai-proposals/{pid}/accept",
                          json={"assigned_to_user_id": assignee["id"]},
                          headers=coordinator["headers"], timeout=15)
        assert r.status_code == 200, r.text
        item = r.json()
        _no_id(item)
        assert item["assigned_to_user_id"] == assignee["id"], \
            f"expected {assignee['id']}; got {item.get('assigned_to_user_id')}"

        # Carries informational fields
        assert "suggested_owner_role" in item
        assert "ai_details" in item
        assert "ai_confidence" in item
        assert item["ai_confidence"] in ("low", "medium", "high"), item.get("ai_confidence")

        # Ledger has created AND assigned
        hist = requests.get(f"{API}/operational-items/{item['id']}",
                            headers=coordinator["headers"], timeout=10).json()["history"]
        kinds = [h["kind"] for h in hist]
        assert "created" in kinds, kinds
        assert "assigned" in kinds, kinds


# 6. Supervisor → 403 on accept
class TestAcceptAuth:
    def test_supervisor_403(self, supervisor, multi_intent_event):
        props = [p for p in multi_intent_event["proposals"] if p.get("decision") == "pending"]
        if not props:
            pytest.skip("no pending proposals")
        pid = props[0]["id"]
        r = requests.post(f"{API}/ai-proposals/{pid}/accept", json={},
                          headers=supervisor["headers"], timeout=10)
        assert r.status_code == 403, f"got {r.status_code} {r.text}"


# 7. Backward compat smoke
class TestBackwardCompat:
    def test_endpoints_ok_no_id_leak(self, coordinator, site_id):
        endpoints = [
            ("GET", f"{API}/operational-items", {"site_id": site_id}),
            ("GET", f"{API}/operational-center", None),
            ("GET", f"{API}/sites/{site_id}/requirements", None),
            ("GET", f"{API}/timeline", {"site_id": site_id}),
            ("GET", f"{API}/ai-proposals", None),
        ]
        for method, url, params in endpoints:
            r = requests.request(method, url, params=params,
                                 headers=coordinator["headers"], timeout=15)
            assert r.status_code == 200, f"{url} -> {r.status_code} {r.text}"
            _no_id(r.json())
