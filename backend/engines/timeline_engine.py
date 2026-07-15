"""Timeline Engine — chronological projection over events + ai_analyses + corrections.

Reads only. Never writes.
"""
from __future__ import annotations
from typing import Optional
from . import memory_engine


async def for_site(site_id: str, limit: int = 200, include_ops: bool = False) -> list[dict]:
    events = await memory_engine.list_events_for_site(site_id, limit=limit)
    if not events and not include_ops:
        return []
    event_ids = [e["id"] for e in events]
    analyses = await memory_engine.get_ai_analyses(event_ids) if event_ids else {}
    corrections_map = await memory_engine.list_corrections_for_events(event_ids) if event_ids else {}
    # Client Approval Workflow — resolve each event's linked approval
    # request (if any) in one batch query, not one per event.
    from engines import operations_engine
    approvals_map = await operations_engine.find_items_for_events(event_ids, category="client_approval") if event_ids else {}

    items: list[dict] = []
    for e in events:
        # Inline photo previews so the client can render without N+1 fetches
        photo_thumbs: list[dict] = []
        for asset_id in (e.get("photo_asset_ids") or []):
            b64 = await memory_engine.asset_thumb(asset_id)
            if b64:
                photo_thumbs.append({"asset_id": asset_id, "base64": b64})

        approval = approvals_map.get(e["id"])
        items.append({
            "kind": "construction_event",
            "event": e,
            "analysis": analyses.get(e["id"]),
            "corrections": corrections_map.get(e["id"], []),
            "photo_thumbs": photo_thumbs,
            "created_at": e.get("server_created_at"),
            "approval_status": approval["status"] if approval else None,
            "approval_item_id": approval["id"] if approval else None,
        })

    if include_ops:
        from engines import operations_engine
        op_events = await operations_engine.list_events_for_site(site_id, limit=limit)
        # join with items for context
        item_ids = list({oe["operational_item_id"] for oe in op_events})
        op_items_map = {}
        if item_ids:
            docs = await operations_engine.db.operational_items.find(
                {"id": {"$in": item_ids}}, {"_id": 0}
            ).to_list(1000) if hasattr(operations_engine, "db") else []
            # use memory_engine.db instead
            from core.db import db
            docs = await db.operational_items.find({"id": {"$in": item_ids}}, {"_id": 0}).to_list(1000)
            op_items_map = {d["id"]: d for d in docs}
        for oe in op_events:
            items.append({
                "kind": "operational_event",
                "operational_event": oe,
                "operational_item": op_items_map.get(oe["operational_item_id"]),
                "created_at": oe.get("created_at"),
            })
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items


async def single(event_id: str) -> Optional[dict]:
    e = await memory_engine.get_event(event_id)
    if not e:
        return None
    analysis = await memory_engine.get_ai_analysis(event_id)
    corrections = (await memory_engine.list_corrections_for_events([event_id])).get(event_id, [])
    photo_thumbs: list[dict] = []
    for asset_id in (e.get("photo_asset_ids") or []):
        b64 = await memory_engine.asset_thumb(asset_id)
        if b64:
            photo_thumbs.append({"asset_id": asset_id, "base64": b64})
    from engines import operations_engine
    approval = await operations_engine.find_open_item_for_event(event_id, category="client_approval")
    return {
        "event": e, "analysis": analysis, "corrections": corrections, "photo_thumbs": photo_thumbs,
        "approval_status": approval["status"] if approval else None,
        "approval_item_id": approval["id"] if approval else None,
    }
