"""Construction Knowledge Graph routes (KM-01).

Deliberately thin — every relationship, trace, and lookup lives in
engines/knowledge_graph_engine.py. This file only translates
HTTP <-> engine calls, matching the exact `_raise_for()` convention
routes/reasoning.py, routes/commercial.py, and routes/knowledge.py
already established.

Access model: read-only, internal roles only — the Knowledge Graph
surfaces why commercial and operational records exist, the same class
of internal reasoning routes/reasoning.py already keeps out of the
client workspace.
"""
from fastapi import APIRouter, Depends, HTTPException
from core.auth import get_current_user
from engines import knowledge_graph_engine as kg

router = APIRouter(prefix="/api", tags=["knowledge-graph"])


def _forbid_client(user: dict) -> None:
    if user["role"] == "client":
        raise HTTPException(status_code=403, detail="Not available to client accounts.")


def _raise_for(e: ValueError) -> None:
    if isinstance(e, kg.KnowledgeGraphNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    raise HTTPException(status_code=400, detail=str(e))


@router.get("/knowledge-graph/{entity_type}/{entity_id}/relationships")
async def get_entity_relationships(entity_type: str, entity_id: str, user: dict = Depends(get_current_user)):
    _forbid_client(user)
    try:
        return await kg.get_entity_relationships(entity_type, entity_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/knowledge-graph/events/{event_id}/impact-trace")
async def get_impact_trace(event_id: str, user: dict = Depends(get_current_user)):
    _forbid_client(user)
    try:
        return await kg.impact_trace(event_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/knowledge-graph/{entity_type}/{entity_id}/decision-trace")
async def get_decision_trace(entity_type: str, entity_id: str, user: dict = Depends(get_current_user)):
    _forbid_client(user)
    try:
        return await kg.decision_trace(entity_type, entity_id, user=user)
    except ValueError as e:
        _raise_for(e)
