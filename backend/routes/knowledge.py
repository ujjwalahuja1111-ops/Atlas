"""Construction Knowledge Core routes (Sprint 4 / Engine 6).

Read endpoints are available to any authenticated role, since future engines
and every role's workspace will eventually need to *reference* this data
(e.g. picking an activity when logging an event). Only mutations are gated
admin-only, matching the sprint brief ("Frontend: Admin-only").

"Admin" has no dedicated backend role in Atlas — `frontend/src/roles.ts`
already maps the admin *view role* onto the existing `management` backend
role. We mirror that mapping here rather than introducing a new role.

Sprint 4.1 stabilization fixes applied here:
  - L3: list endpoint uses enrich_many() (one batched query) not a per-item loop.
  - L5: KnowledgeConflictError -> 409, so a concurrent-edit conflict is
    distinguishable from a validation error.
  - L6: KnowledgeNotFoundError -> 404, distinct from a plain ValueError -> 400,
    so "the item you asked for doesn't exist" is no longer conflated with
    "your request body was invalid."
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user
from engines import knowledge_engine
from engines.knowledge_engine import KnowledgeNotFoundError, KnowledgeConflictError

router = APIRouter(prefix="/api", tags=["knowledge"])


def _require_admin(user: dict) -> None:
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="Construction Knowledge Core is admin-only")


def _raise_for(e: ValueError) -> None:
    """Single place mapping engine exceptions to HTTP status codes, so every
    route handles the three cases (not found / conflict / bad input)
    identically instead of re-deriving the mapping per route.
    """
    if isinstance(e, KnowledgeNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, KnowledgeConflictError):
        raise HTTPException(status_code=409, detail=str(e))
    raise HTTPException(status_code=400, detail=str(e))


class KnowledgeItemCreate(BaseModel):
    type: str
    name: str
    description: str = ""
    code: str = ""
    category_id: Optional[str] = None
    phase_id: Optional[str] = None
    tags: list[str] = []
    ai_keywords: list[str] = []
    default_duration_days: Optional[float] = None
    checklist_items: list[dict] = []
    document_kind: Optional[str] = None
    status: str = "draft"
    applicability: dict = {}
    # Sprint 5 — Activity Library fields, meaningful only for type="activity"
    trade: Optional[str] = None
    unit: Optional[str] = None
    requires_inspection: bool = False


class KnowledgeItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    code: Optional[str] = None
    category_id: Optional[str] = None
    phase_id: Optional[str] = None
    tags: Optional[list[str]] = None
    ai_keywords: Optional[list[str]] = None
    default_duration_days: Optional[float] = None
    checklist_items: Optional[list[dict]] = None
    document_kind: Optional[str] = None
    status: Optional[str] = None
    applicability: Optional[dict] = None
    trade: Optional[str] = None
    unit: Optional[str] = None
    requires_inspection: Optional[bool] = None


class RelationshipCreate(BaseModel):
    type: str
    target_id: str
    metadata: dict = {}


@router.get("/knowledge-items")
async def list_knowledge_items(
    type: Optional[str] = None,
    category_id: Optional[str] = None,
    phase_id: Optional[str] = None,
    tag: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    include_archived: bool = False,
    user: dict = Depends(get_current_user),
):
    try:
        items = await knowledge_engine.list_items(
            type_=type, category_id=category_id, phase_id=phase_id,
            tag=tag, status=status, q=q, include_archived=include_archived,
        )
    except ValueError as e:
        _raise_for(e)
    return await knowledge_engine.enrich_many(items)


@router.get("/knowledge-items/{item_id}")
async def get_knowledge_item(item_id: str, user: dict = Depends(get_current_user)):
    item = await knowledge_engine.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return await knowledge_engine.enrich(item)


@router.get("/knowledge-items/{item_id}/versions")
async def get_knowledge_item_versions(item_id: str, user: dict = Depends(get_current_user)):
    item = await knowledge_engine.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return await knowledge_engine.list_versions(item_id)


@router.post("/knowledge-items", status_code=201)
async def create_knowledge_item(req: KnowledgeItemCreate, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        item = await knowledge_engine.create_item(
            actor=user, type_=req.type, name=req.name, description=req.description,
            code=req.code, category_id=req.category_id, phase_id=req.phase_id,
            tags=req.tags, ai_keywords=req.ai_keywords,
            default_duration_days=req.default_duration_days,
            checklist_items=req.checklist_items, document_kind=req.document_kind,
            status=req.status, applicability=req.applicability,
            trade=req.trade, unit=req.unit, requires_inspection=req.requires_inspection,
        )
    except ValueError as e:
        _raise_for(e)
    return await knowledge_engine.enrich(item)


@router.patch("/knowledge-items/{item_id}")
async def update_knowledge_item(item_id: str, req: KnowledgeItemUpdate, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        item = await knowledge_engine.update_item(
            item_id, actor=user, updates=req.model_dump(exclude_unset=True),
        )
    except ValueError as e:
        _raise_for(e)
    return await knowledge_engine.enrich(item)


@router.post("/knowledge-items/{item_id}/archive")
async def archive_knowledge_item(item_id: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        item = await knowledge_engine.archive_item(item_id, actor=user)
    except ValueError as e:
        _raise_for(e)
    return await knowledge_engine.enrich(item)


@router.post("/knowledge-items/{item_id}/unarchive")
async def unarchive_knowledge_item(item_id: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        item = await knowledge_engine.unarchive_item(item_id, actor=user)
    except ValueError as e:
        _raise_for(e)
    return await knowledge_engine.enrich(item)


@router.post("/knowledge-items/{item_id}/relationships", status_code=201)
async def add_relationship(item_id: str, req: RelationshipCreate, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        item = await knowledge_engine.add_relationship(
            item_id, actor=user, type_=req.type, target_id=req.target_id, metadata=req.metadata,
        )
    except ValueError as e:
        _raise_for(e)
    return await knowledge_engine.enrich(item)


@router.delete("/knowledge-items/{item_id}/relationships/{relationship_id}")
async def remove_relationship(item_id: str, relationship_id: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    try:
        item = await knowledge_engine.remove_relationship(item_id, relationship_id, actor=user)
    except ValueError as e:
        _raise_for(e)
    return await knowledge_engine.enrich(item)


@router.get("/knowledge-meta")
async def knowledge_meta(user: dict = Depends(get_current_user)):
    """Static vocab for frontend dropdowns (types + curated relationship types + statuses)."""
    return {
        "types": sorted(knowledge_engine.TYPES),
        "relationship_types": sorted(knowledge_engine.KNOWN_RELATIONSHIP_TYPES),
        "statuses": sorted(knowledge_engine.SETTABLE_STATUSES),
    }
