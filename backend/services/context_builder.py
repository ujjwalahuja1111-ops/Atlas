"""Context Builder — minimum sufficient operational context.

A reusable retrieval/context layer beneath existing intents, not a new
intent system and not a new architecture. Composes ONLY functions and
relationships that already exist: operations_engine's own item/event
queries, the existing superseded_by_item_id field (forward AND, via the
new find_items_superseded_by, reverse), the existing inherited_evidence_
event_id link (via the new find_sibling_items), and intent_service's own
_present_change_events/_synthetic_creation_entry presentation helpers.

No new collection, no new provenance model, no fuzzy matching, no
inferred relationships. Every relationship this module follows was
already explicit and already stored before this module existed; this
module's only job is retrieving and ordering what is already there.

Primary entry point: build_item_context() — for a focal operational_item,
assembles a compact, deterministic packet: the item's own current fields,
its own chronological history, where it sits in any explicit supersession
chain (both directions), any sibling facts from the same capture, and its
verification/evidence state. Deliberately excludes unrelated project
noise — no closed items merely because they share a project, no fuzzy-
matched "related" items.
"""
from __future__ import annotations

from typing import Optional

from engines import operations_engine


async def build_item_context(*, item_id: str, user: dict) -> dict:
    """Assembles the minimum-sufficient context packet for one focal
    operational item. Raises ValueError (matching every other engine
    function's own convention) if the item does not exist or is not
    visible to this user — callers already handle ValueError from
    operations_engine the same way.
    """
    item = await operations_engine.get_item(item_id)
    if not item:
        raise ValueError("item not found")
    await operations_engine.assert_item_visible(item, user)

    # Imported here, not at module level, to avoid a circular import —
    # intent_service imports engines; this module is imported BY
    # intent_service, so importing it back at module load time would
    # cycle. Both modules already exist; nothing new is introduced by
    # this reuse.
    from services.intent_service import _present_change_events, _synthetic_creation_entry

    raw_events = await operations_engine.list_events_for_item(item_id)
    history = _present_change_events(raw_events)
    synthetic = _synthetic_creation_entry(item)
    if synthetic:
        history = history + [synthetic]
    history.sort(key=lambda e: e.get("when") or "")

    relationships = await build_item_relationships(item)
    return {"history": history, **relationships}


async def build_item_relationships(item: dict) -> dict:
    """The relationship/verification/expected-actual part of the context
    packet, WITHOUT recomputing event history — split out so a caller
    that already has its own events (e.g. _handle_query_change_history,
    which computes them the same way for its own, unrelated reasons)
    can reuse this without duplicating that work. Takes an already-
    fetched item dict (not an id) for the same reason - the caller
    already has it.
    """
    enriched = operations_engine.enrich(item)
    item_id = item["id"]

    # Forward supersession chain — if this item was itself superseded,
    # follow superseded_by_item_id to the current, live position. Bounded
    # and safe: the hardening patch already proved no cycle can exist
    # (every target in the chain must be live at the moment it was used),
    # so this walk is guaranteed to terminate; MAX_CHAIN_DEPTH is a
    # generous, fixed safety bound, not a tuning parameter.
    MAX_CHAIN_DEPTH = 50
    superseded_by_chain: list[dict] = []
    cursor_id = item.get("superseded_by_item_id")
    seen = {item_id}
    for _ in range(MAX_CHAIN_DEPTH):
        if not cursor_id or cursor_id in seen:
            break
        next_item = await operations_engine.get_item(cursor_id)
        if not next_item:
            break
        superseded_by_chain.append(_claim_summary(next_item))
        seen.add(cursor_id)
        cursor_id = next_item.get("superseded_by_item_id")
    current_position = superseded_by_chain[-1] if superseded_by_chain else _claim_summary(item)

    # Reverse supersession — what this item itself replaced, if anything
    # (only ever set by the same explicit, human-triggered mark_
    # superseded() action; never inferred here or anywhere else).
    predecessors_docs = await operations_engine.find_items_superseded_by(item_id)
    superseded_predecessors = [_claim_summary(p) for p in predecessors_docs]

    # Siblings — other facts captured in the SAME utterance as this item
    # (e.g. "180 arrived, the remaining 20 still haven't" naturally
    # producing a materials item and a follow_up item together). A safe,
    # explicit link (same source event), never a name/category guess.
    sibling_docs = await operations_engine.find_sibling_items(
        item.get("inherited_evidence_event_id"), exclude_item_id=item_id)
    siblings = [_claim_summary(s) for s in sibling_docs]

    # Human-confirmed cross-capture linking — forward: if THIS item was
    # itself confirmed as a fulfillment of an earlier expectation, show
    # that expectation (only ever set by the explicit, human-triggered
    # link_as_fulfillment() - never inferred).
    fulfills: Optional[dict] = None
    if item.get("fulfills_item_id"):
        target = await operations_engine.get_item(item["fulfills_item_id"])
        if target:
            fulfills = {"item": _claim_summary(target), "relationship_type": item.get("fulfillment_type")}

    # Reverse — every later item confirmed against this one as its
    # expectation, split by type. "actual" entries feed the arithmetic
    # below; "update" entries (e.g. a related follow_up) do not.
    fulfiller_docs = await operations_engine.find_items_fulfilling(item_id)
    confirmed_actuals = [_claim_summary(f) for f in fulfiller_docs if f.get("fulfillment_type") == "actual"]
    confirmed_updates = [_claim_summary(f) for f in fulfiller_docs if f.get("fulfillment_type") == "update"]

    # Expected -> Actual -> Remaining across MULTIPLE confirmed actuals
    # (Section 6: each actual stays its own independent item; nothing is
    # merged or mutated here, only summed for presentation). Only
    # computed when the focal item genuinely carries an expected
    # quantity or amount - never fabricated for an item with neither,
    # and never computed from "update" relationships, which are not
    # forced into this arithmetic.
    fulfillment_summary = None
    actual_docs = [f for f in fulfiller_docs if f.get("fulfillment_type") == "actual"]
    if item.get("quantity") is not None and actual_docs:
        total_actual = sum(f.get("quantity") or 0 for f in actual_docs)
        fulfillment_summary = {
            "dimension": "quantity", "expected": item["quantity"], "actual": total_actual,
            "remaining": item["quantity"] - total_actual,
        }
    elif item.get("amount") is not None and actual_docs:
        total_actual = sum(f.get("amount") or 0 for f in actual_docs)
        fulfillment_summary = {
            "dimension": "amount", "expected": item["amount"], "actual": total_actual,
            "remaining": item["amount"] - total_actual,
        }

    return {
        "focal_item": _claim_summary(enriched, full=True),
        "current_position": current_position,
        "is_current": not superseded_by_chain,
        "superseded_by_chain": superseded_by_chain,
        "superseded_predecessors": superseded_predecessors,
        "sibling_items": siblings,
        "fulfills": fulfills,
        "confirmed_actuals": confirmed_actuals,
        "confirmed_updates": confirmed_updates,
        "fulfillment_summary": fulfillment_summary,
        "verification": {
            "status": item["status"],
            "verified_by_user_name": item.get("verified_by_user_name"),
            "verified_at": item.get("verified_at"),
            "has_evidence": item.get("has_evidence", False),
        },
        "expected_actual_remaining": {
            "quantity": item.get("quantity"), "actual_quantity": item.get("actual_quantity"),
            "quantity_remaining": enriched["metrics"]["quantity_remaining"],
            "amount": item.get("amount"), "actual_amount": item.get("actual_amount"),
            "amount_remaining": enriched["metrics"]["amount_remaining"],
        },
    }


def _claim_summary(item: dict, *, full: bool = False) -> dict:
    """The compact, provenance-preserving shape used for every item this
    module surfaces (the focal item, chain links, predecessors,
    siblings) — same field set every time, so a caller never has to
    special-case which kind of related item it is looking at. `full`
    additionally includes category/description for the one focal item
    itself; related items stay compact on purpose (the minimum-
    sufficient principle, not a second full item dump per relationship).
    """
    out = {
        "id": item["id"], "title": item.get("title"), "status": item["status"],
        "category": item.get("category"),
        "quantity": item.get("quantity"), "unit": item.get("unit"),
        "required_by": item.get("required_by"), "completed_at": item.get("completed_at"),
        "attributed_to": item.get("attributed_to"),
        "assigned_to_user_id": item.get("assigned_to_user_id"),
        "assigned_to_user_name": item.get("assigned_to_user_name"),
    }
    if full:
        out["description"] = item.get("description")
        out["priority"] = item.get("priority")
        out["created_at"] = item.get("created_at")
    return out
