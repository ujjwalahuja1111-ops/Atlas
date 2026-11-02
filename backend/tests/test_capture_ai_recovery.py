"""Launch-readiness patch 5 - capture -> AI structuring -> human confirmation.

Real app on a blank in-memory database, real onboarding, real event capture,
the real intelligence_engine._process(), proposal emission and acceptance.

THE ONE SIMULATED ELEMENT, STATED PLAINLY: intelligence_engine._structure() -
the call to the AI model. No provider is reachable from this sandbox, so
these tests stand in for it: it either RAISES (simulating a provider outage)
or returns a repo golden-corpus case's hand-built `gold_structured`. That is
simulated model output and is NOT live AI validation; it proves what Atlas
does AROUND the model (durability, retry, duplicate protection, human
confirmation), not what the model says.

Defects reproduced before the fix:
 1. A failed structuring attempt could never be re-run: the UI says "AI can
    be retried later", but startup recovery re-queues only "pending" events
    and regenerate-proposals only replays an existing analysis.
 2. Regenerate (the button always sends force=true) stacked a duplicate
    copy of every pending proposal and re-proposed facts already accepted,
    so accepting the copy created a duplicate operational item.

Run from backend/: python -m pytest tests/test_capture_ai_recovery.py -q
"""
from __future__ import annotations

import pytest

pytest.importorskip("mongomock_motor")
httpx = pytest.importorskip("httpx")

from tests import test_step4_blank_onboarding as s4  # noqa: E402
from tests.test_first_operational_workflow import _onboard, _provision, _project_and_site  # noqa: E402
from eval.golden_corpus import CORPUS  # noqa: E402

pytestmark = pytest.mark.anyio

CASE = next(c for c in CORPUS if c["domain"] == "restaurant")  # 80 kg chicken Friday + 20 kg short tomorrow


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


class _Outage(Exception):
    pass


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=s4._server_app()), base_url="http://t")


def _db():
    import core.db as core_db
    return core_db.db


async def _failed_event(h, monkeypatch):
    """Onboard, capture a text event while the AI worker is 'up', and let the
    (simulated) provider fail. Returns (admin, supervisor, site, event_id)."""
    from engines import intelligence_engine as ie
    admin = await _onboard(h, s4.restaurant_rec)
    sup_id, sup = await _provision(h, admin, "9200000101", "Priya", "site_supervisor")
    project, site = await _project_and_site(h, admin)
    await h.post(f"/api/admin/users/{sup_id}/projects", json={"project_ids": [project["id"]], "mode": "add"}, headers=admin)

    monkeypatch.setattr(ie, "is_worker_running", lambda: True)

    async def _down(*a, **k):
        raise _Outage("provider unavailable (simulated)")

    monkeypatch.setattr(ie, "_structure", _down)
    r = await h.post("/api/events", data={"site_id": site["id"], "text": CASE["text"]}, headers=sup)
    assert r.status_code == 201
    event_id = r.json()["id"]
    await ie._process(event_id)  # what the worker loop does for the queued event
    return admin, sup, site, event_id


async def test_ai_failure_leaves_the_capture_stored_retrievable_and_not_duplicated(monkeypatch):
    from engines import intelligence_engine as ie
    await s4._blank_instance()
    async with _client() as h:
        admin, _sup, _site, eid = await _failed_event(h, monkeypatch)

        got = (await h.get(f"/api/events/{eid}", headers=admin)).json()
        assert got["event"]["text_input"] == CASE["text"]          # raw capture preserved verbatim
        assert got["event"]["ai_status"] == "failed"
        assert "provider unavailable" in (await _db().ai_analyses.find_one({"event_id": eid}))["error"]

        # Exactly one fallback note, labelled as automatic, and never a confirmed structured fact.
        items = await _db().operational_items.find({"inherited_evidence_event_id": eid}).to_list(10)
        assert len(items) == 1 and items[0]["category"] == "general" and items[0]["origin_type"] == "manual"
        assert "AI processing was unavailable" in items[0]["description"]
        assert await _db().ai_proposals.count_documents({"event_id": eid}) == 0

        await ie._process(eid)  # a second failure must not create a second fallback
        assert await _db().operational_items.count_documents({"inherited_evidence_event_id": eid}) == 1


async def test_failed_structuring_can_be_retried_and_still_needs_human_acceptance(monkeypatch):
    from engines import intelligence_engine as ie
    await s4._blank_instance()
    async with _client() as h:
        admin, sup, _site, eid = await _failed_event(h, monkeypatch)

        # Only management/PM may retry.
        assert (await h.post(f"/api/events/{eid}/regenerate-proposals", headers=sup)).status_code == 403

        async def _recovered(*a, **k):  # SIMULATED model output (repo golden-corpus fixture)
            return dict(CASE["gold_structured"])

        monkeypatch.setattr(ie, "_structure", _recovered)
        r = await h.post(f"/api/events/{eid}/regenerate-proposals?force=true", headers=admin)
        assert r.status_code == 200 and r.json()["status"] == "retried"
        assert r.json()["ai_status"] == "analyzed" and r.json()["generated_count"] == 2

        # The failure row is kept as an audit record; the newest analysis is the one used.
        assert await _db().ai_analyses.count_documents({"event_id": eid}) == 2
        from engines import memory_engine
        assert (await memory_engine.get_ai_analysis(eid))["structured"] is not None
        assert (await h.get(f"/api/events/{eid}", headers=admin)).json()["event"]["ai_status"] == "analyzed"

        # Nothing was auto-confirmed: both proposals are pending, still only the one fallback item.
        props = (await h.get("/api/ai-proposals", params={"event_id": eid}, headers=admin)).json()
        assert len(props) == 2 and {p["decision"] for p in props} == {"pending"}
        assert await _db().operational_items.count_documents({"inherited_evidence_event_id": eid}) == 1

        # Human acceptance creates the item, with provenance back to the event.
        acc = await h.post(f"/api/ai-proposals/{props[0]['id']}/accept", json={}, headers=admin)
        assert acc.status_code == 200, acc.text
        assert (await _db().operational_items.find_one({"id": acc.json()["id"]}))["inherited_evidence_event_id"] == eid

        # Retrying an event that is no longer failed does nothing.
        r = await h.post(f"/api/events/{eid}/regenerate-proposals", headers=admin)
        assert r.json()["status"] == "skipped_existing"  # normal path; not a retry, nothing duplicated
        assert len((await h.get("/api/ai-proposals", params={"event_id": eid}, headers=admin)).json()) == 2


async def test_retry_while_ai_is_unavailable_or_failing_again_changes_nothing(monkeypatch):
    from engines import intelligence_engine as ie
    await s4._blank_instance()
    async with _client() as h:
        admin, _sup, _site, eid = await _failed_event(h, monkeypatch)

        monkeypatch.setattr(ie, "is_worker_running", lambda: False)
        r = await h.post(f"/api/events/{eid}/regenerate-proposals", headers=admin)
        assert r.json()["status"] == "ai_unavailable"
        assert (await h.get(f"/api/events/{eid}", headers=admin)).json()["event"]["ai_status"] == "failed"

        monkeypatch.setattr(ie, "is_worker_running", lambda: True)  # up, but the provider is still down
        r = await h.post(f"/api/events/{eid}/regenerate-proposals", headers=admin)
        assert r.json()["status"] == "retried" and r.json()["ai_status"] == "failed"
        assert await _db().operational_items.count_documents({"inherited_evidence_event_id": eid}) == 1
        assert await _db().ai_proposals.count_documents({"event_id": eid}) == 0
        assert (await h.get(f"/api/events/{eid}", headers=admin)).json()["event"]["text_input"] == CASE["text"]


async def test_regenerate_does_not_duplicate_or_resurrect_decided_proposals(monkeypatch):
    from engines import intelligence_engine as ie
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        _project, site = await _project_and_site(h, admin)

        async def _ok(*a, **k):  # SIMULATED model output (repo golden-corpus fixture)
            return dict(CASE["gold_structured"])

        monkeypatch.setattr(ie, "is_worker_running", lambda: True)
        monkeypatch.setattr(ie, "_structure", _ok)
        eid = (await h.post("/api/events", data={"site_id": site["id"], "text": CASE["text"]}, headers=admin)).json()["id"]
        await ie._process(eid)

        props = (await h.get("/api/ai-proposals", params={"event_id": eid}, headers=admin)).json()
        assert len(props) == 2
        accepted, rejected = props[0], props[1]
        assert (await h.post(f"/api/ai-proposals/{accepted['id']}/accept", json={}, headers=admin)).status_code == 200
        assert (await h.post(f"/api/ai-proposals/{rejected['id']}/reject", json={"reason": "wrong"}, headers=admin)).status_code == 200
        items_before = await _db().operational_items.count_documents({"inherited_evidence_event_id": eid})

        for _ in range(3):  # the UI button always sends force=true
            r = await h.post(f"/api/events/{eid}/regenerate-proposals?force=true", headers=admin)
            assert r.status_code == 200

        after = (await h.get("/api/ai-proposals", params={"event_id": eid}, headers=admin)).json()
        assert sorted(p["decision"] for p in after) == ["accepted", "rejected"]  # nothing stacked, nothing resurrected
        assert await _db().operational_items.count_documents({"inherited_evidence_event_id": eid}) == items_before


async def test_regenerate_replaces_undecided_proposals_instead_of_stacking(monkeypatch):
    from engines import intelligence_engine as ie
    await s4._blank_instance()
    async with _client() as h:
        admin = await _onboard(h, s4.restaurant_rec)
        _project, site = await _project_and_site(h, admin)

        async def _ok(*a, **k):
            return dict(CASE["gold_structured"])

        monkeypatch.setattr(ie, "is_worker_running", lambda: True)
        monkeypatch.setattr(ie, "_structure", _ok)
        eid = (await h.post("/api/events", data={"site_id": site["id"], "text": CASE["text"]}, headers=admin)).json()["id"]
        await ie._process(eid)
        for _ in range(3):
            await h.post(f"/api/events/{eid}/regenerate-proposals?force=true", headers=admin)
        props = (await h.get("/api/ai-proposals", params={"event_id": eid}, headers=admin)).json()
        assert len(props) == 2 and {p["decision"] for p in props} == {"pending"}
