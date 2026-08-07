"""Construction Knowledge Graph — Engine (KM-01).

Not a graph database, not Neo4j, not new infrastructure — a
relationship-inference layer over collections that already exist.
Every relationship this engine surfaces is derived from a foreign-key
style field that was already present before this package (project_id,
milestone_id, payment_request_id, activity_id, entity_type/entity_id
on commercial_events, event_id on raw_assets, linked_photo_ids on
variations) or from the CRE's own already-explicit evidence structure.

Per this package's own mandatory audit (see KM01_KNOWLEDGE_GRAPH.md):
the one relationship this audit found storage for but never wired to
any real UI is Observation -> Variation, via variation.linked_photo_ids
-> raw_asset.event_id -> the originating event. This engine traverses
that chain; it does not add new storage for it, since the field
already existed.

Design discipline matching every other Atlas engine: no new
collection, no duplicated computation — every function here reads
data other engines already own and are already correct, and composes
it into a navigable structure. If a relationship can be inferred from
an existing field, it is inferred fresh on every call, never cached
or duplicated into a second store.
"""
from typing import Optional
from core.db import db
from engines import memory_engine, commercial_engine

__all__ = ["get_entity_relationships", "impact_trace", "decision_trace"]


class KnowledgeGraphError(ValueError):
    pass


class KnowledgeGraphNotFoundError(KnowledgeGraphError):
    pass


async def _assert_project_visible(project_id: str, user: dict) -> dict:
    """Same convention as every other engine in this codebase:
    out-of-scope projects behave as if they do not exist."""
    project = await memory_engine.get_project(project_id)
    if not project:
        raise KnowledgeGraphNotFoundError(f"Project '{project_id}' not found")
    if memory_engine._is_project_scoped(user):
        if project_id not in (user.get("assigned_project_ids") or []):
            raise KnowledgeGraphNotFoundError(f"Project '{project_id}' not found")
    return project


def _ref(entity_type: str, entity_id: str, label: str, relationship: str) -> dict:
    """One edge in the graph: what kind of thing, which one, a human
    label, and how it relates to the entity being explored."""
    return {"entity_type": entity_type, "entity_id": entity_id, "label": label, "relationship": relationship}


async def _get_event(event_id: str) -> Optional[dict]:
    return await db.events.find_one({"id": event_id}, {"_id": 0})


async def _get_payment(payment_id: str) -> Optional[dict]:
    return await db.payments.find_one({"id": payment_id}, {"_id": 0})


async def _get_workflow_activity(activity_id: str) -> Optional[dict]:
    return await db.workflow_activities.find_one({"id": activity_id}, {"_id": 0})


async def _get_operational_item(item_id: str) -> Optional[dict]:
    return await db.operational_items.find_one({"id": item_id}, {"_id": 0})


# ---------------------------------------------------------------------------
# Entity relationship lookup — the Relationship Explorer's own backend.
# Given any entity, return what it directly points to and what
# directly points to it. Every case here reuses an existing field;
# nothing is invented.
# ---------------------------------------------------------------------------

async def get_entity_relationships(entity_type: str, entity_id: str, *, user: dict) -> dict:
    """One entity, its direct neighbors. Deliberately shallow (one hop)
    — impact_trace/decision_trace below do the deep, directional
    walks; this is the building block both are made from."""
    outgoing: list[dict] = []
    incoming: list[dict] = []

    if entity_type == "milestone":
        m = await commercial_engine.get_milestone(entity_id)
        if not m:
            raise KnowledgeGraphNotFoundError(f"Milestone '{entity_id}' not found")
        await _assert_project_visible(m["project_id"], user)
        outgoing.append(_ref("project", m["project_id"], "Project", "BELONGS_TO"))
        prs = await db.payment_requests.find({"milestone_id": entity_id}, {"_id": 0}).to_list(50)
        for pr in prs:
            incoming.append(_ref("payment_request", pr["id"], pr["number"], "GENERATED"))

    elif entity_type == "payment_request":
        pr = await commercial_engine.get_payment_request(entity_id)
        if not pr:
            raise KnowledgeGraphNotFoundError(f"Payment request '{entity_id}' not found")
        await _assert_project_visible(pr["project_id"], user)
        m = await commercial_engine.get_milestone(pr["milestone_id"]) if pr.get("milestone_id") else None
        if m:
            outgoing.append(_ref("milestone", m["id"], m["name"], "GENERATED_BY"))
        payments = await db.payments.find({"payment_request_id": entity_id}, {"_id": 0}).to_list(100)
        for p in payments:
            incoming.append(_ref("payment", p["id"], f"Rs {p['amount']:,.0f}", "SETTLED_BY"))

    elif entity_type == "payment":
        p = await _get_payment(entity_id)
        if not p:
            raise KnowledgeGraphNotFoundError(f"Payment '{entity_id}' not found")
        await _assert_project_visible(p["project_id"], user)
        pr = await commercial_engine.get_payment_request(p["payment_request_id"])
        if pr:
            outgoing.append(_ref("payment_request", pr["id"], pr["number"], "SETTLES"))

    elif entity_type == "variation":
        v = await commercial_engine.get_variation(entity_id)
        if not v:
            raise KnowledgeGraphNotFoundError(f"Variation '{entity_id}' not found")
        await _assert_project_visible(v["project_id"], user)
        outgoing.append(_ref("project", v["project_id"], "Project", "BELONGS_TO"))
        if v.get("status") == "approved":
            outgoing.append(_ref("contract", v["project_id"], "Contract", "MODIFIED"))
        # Observation -> Variation: traverses linked_photo_ids (already
        # existed on Variation, confirmed unused by any UI before this
        # package) -> raw_asset.event_id -> the originating event.
        for asset_id in v.get("linked_photo_ids", []):
            asset = await memory_engine.get_asset(asset_id)
            if asset and asset.get("event_id"):
                ev = await _get_event(asset["event_id"])
                if ev:
                    incoming.append(_ref("event", ev["id"], ev.get("text") or ev.get("type", "observation"), "CAUSED"))

    elif entity_type == "contract":
        c = await commercial_engine.get_contract(entity_id)  # entity_id is project_id for contract (one per project)
        if not c:
            raise KnowledgeGraphNotFoundError(f"Contract for project '{entity_id}' not found")
        await _assert_project_visible(entity_id, user)
        outgoing.append(_ref("project", entity_id, "Project", "BELONGS_TO"))
        variations = await commercial_engine.list_variations(entity_id)
        for v in variations:
            if v.get("status") == "approved":
                incoming.append(_ref("variation", v["id"], v["title"], "MODIFIED"))

    elif entity_type == "event":
        ev = await _get_event(entity_id)
        if not ev:
            raise KnowledgeGraphNotFoundError(f"Event '{entity_id}' not found")
        if ev.get("activity_id"):
            act = await _get_workflow_activity(ev["activity_id"])
            if act:
                outgoing.append(_ref("workflow_activity", act["id"], act["name"], "EVIDENCES"))
        assets = await memory_engine.get_assets_for_event(entity_id)
        asset_ids = {a["id"] for a in assets}
        if asset_ids:
            # Which variations, if any, cite one of this event's own assets.
            candidate_variations = await db.variations.find(
                {"linked_photo_ids": {"$in": list(asset_ids)}}, {"_id": 0}).to_list(20)
            for v in candidate_variations:
                outgoing.append(_ref("variation", v["id"], v["title"], "CAUSED"))

    elif entity_type == "operational_item":
        item = await _get_operational_item(entity_id)
        if not item:
            raise KnowledgeGraphNotFoundError(f"Operational item '{entity_id}' not found")
        if item.get("last_derived_from_op_event_id"):
            outgoing.append(_ref("operational_event", item["last_derived_from_op_event_id"], "Last event", "DERIVED_FROM"))

    else:
        raise KnowledgeGraphError(f"Unsupported entity_type '{entity_type}' for relationship lookup.")

    return {"entity_type": entity_type, "entity_id": entity_id, "outgoing": outgoing, "incoming": incoming}


# ---------------------------------------------------------------------------
# Impact Trace — forward walk from an observation: what did this
# eventually cause? Bounded depth (a handful of hops), since
# construction causality chains are short in practice and an unbounded
# walk risks looping through data this package didn't design a
# guaranteed-acyclic structure for.
# ---------------------------------------------------------------------------

async def impact_trace(event_id: str, *, user: dict, max_hops: int = 4) -> dict:
    ev = await _get_event(event_id)
    if not ev:
        raise KnowledgeGraphNotFoundError(f"Event '{event_id}' not found")
    if ev.get("site_id"):
        site = await db.sites.find_one({"id": ev["site_id"]}, {"_id": 0})
        if site:
            await _assert_project_visible(site["project_id"], user)

    chain = [{"entity_type": "event", "entity_id": event_id,
             "label": ev.get("text") or ev.get("type", "observation")}]
    frontier = [("event", event_id)]
    seen = {("event", event_id)}
    hop = 0
    while frontier and hop < max_hops:
        hop += 1
        next_frontier = []
        for etype, eid in frontier:
            try:
                rel = await get_entity_relationships(etype, eid, user=user)
            except KnowledgeGraphError:
                # A neighbor of a supported type (e.g. "project") that
                # this engine doesn't itself expand further — a dead
                # end for the walk, not a failure of the whole trace.
                continue
            for edge in rel["outgoing"] + rel["incoming"]:
                key = (edge["entity_type"], edge["entity_id"])
                if key in seen:
                    continue
                seen.add(key)
                chain.append({"entity_type": edge["entity_type"], "entity_id": edge["entity_id"],
                              "label": edge["label"], "via": edge["relationship"]})
                next_frontier.append(key)
        frontier = next_frontier

    return {"origin": {"entity_type": "event", "entity_id": event_id}, "chain": chain, "hops_walked": hop}


# ---------------------------------------------------------------------------
# Decision Trace — backward walk: why does this record exist / why
# does it have this value? Answers with evidence (the actual linked
# records and events), never opinion or AI.
# ---------------------------------------------------------------------------

async def decision_trace(entity_type: str, entity_id: str, *, user: dict) -> dict:
    rel = await get_entity_relationships(entity_type, entity_id, user=user)
    evidence = []

    for edge in rel["outgoing"] + rel["incoming"]:
        evidence.append({
            "entity_type": edge["entity_type"], "entity_id": edge["entity_id"],
            "label": edge["label"], "relationship": edge["relationship"],
        })

    # Commercial events give the "who and when" half of "why" for any
    # commercially-tracked entity — reused directly, never recomputed.
    events: list[dict] = []
    if entity_type in ("milestone", "payment_request", "payment", "variation", "contract"):
        project_id = None
        if entity_type == "contract":
            project_id = entity_id
        else:
            getter = {
                "milestone": commercial_engine.get_milestone,
                "payment_request": commercial_engine.get_payment_request,
                "variation": commercial_engine.get_variation,
            }.get(entity_type)
            if getter:
                rec = await getter(entity_id)
                project_id = rec["project_id"] if rec else None
            elif entity_type == "payment":
                p = await _get_payment(entity_id)
                project_id = p["project_id"] if p else None
        if project_id:
            all_events = await commercial_engine.list_commercial_events(project_id, limit=200)
            events = [e for e in all_events if e["entity_id"] == entity_id]

    return {"entity_type": entity_type, "entity_id": entity_id, "evidence": evidence, "commercial_events": events}
