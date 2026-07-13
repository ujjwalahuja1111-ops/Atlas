"""Construction Workflow Engine routes (Sprint 5, extended Sprint 6.1).

Deliberately thin — every rule (project visibility, dependency-respecting
status transitions, template-to-activity generation, execution-target
storage) lives in engines/workflow_engine.py. This file only translates
HTTP <-> engine calls and maps exceptions to status codes, mirroring the
exact `_raise_for()` pattern already established in routes/knowledge.py.

Workflow Templates themselves are NOT a new endpoint family — they are
just `knowledge_items` with `type="workflow_template"`, fully served by
the existing routes/knowledge.py (list/create/update/archive/relationships
all already work for them with zero code change). Only project-scoped
generation, status tracking, and (Sprint 6.1) scheduling are genuinely
new capabilities.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user
from engines import workflow_engine
from engines.workflow_engine import WorkflowNotFoundError, DependencyNotSatisfiedError

router = APIRouter(prefix="/api", tags=["workflow"])


def _raise_for(e: ValueError) -> None:
    """Same three-way mapping convention as routes/knowledge.py's
    _raise_for(): not-found -> 404, dependency conflict -> 409, everything
    else -> 400."""
    if isinstance(e, WorkflowNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, DependencyNotSatisfiedError):
        raise HTTPException(status_code=409, detail=str(e))
    raise HTTPException(status_code=400, detail=str(e))


class GenerateWorkflowRequest(BaseModel):
    template_id: str


class SetStatusRequest(BaseModel):
    status: str


class SetScheduleRequest(BaseModel):
    # Sprint 6.1 — execution targets. All optional; only provided fields
    # are updated (exclude_unset below), matching the existing
    # KnowledgeItemUpdate/EditItemReq convention elsewhere in the codebase.
    planned_start: Optional[str] = None
    planned_finish: Optional[str] = None
    actual_start: Optional[str] = None
    actual_finish: Optional[str] = None


@router.post("/projects/{project_id}/workflow/generate", status_code=201)
async def generate_workflow(project_id: str, req: GenerateWorkflowRequest, user: dict = Depends(get_current_user)):
    """Generate a project's workflow from a Workflow Template. Gated the
    same way project management already is (routes/projects.py) —
    supervisors can view and update workflow status on-site, but only
    Project Manager/management can generate the initial workflow, matching
    how only they can create/edit/archive a project."""
    if user["role"] not in ("management", "project_manager"):
        raise HTTPException(status_code=403, detail="Only Project Managers/management can generate a project workflow")
    try:
        return await workflow_engine.generate_workflow(project_id, req.template_id, actor=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/workflow")
async def get_workflow(project_id: str, user: dict = Depends(get_current_user)):
    try:
        return await workflow_engine.list_workflow(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.post("/workflow-activities/{activity_id}/status")
async def set_workflow_activity_status(activity_id: str, req: SetStatusRequest, user: dict = Depends(get_current_user)):
    """Open to any authenticated role (mirrors operational_items' status
    transitions, which supervisors can also perform on-site) — project
    visibility is still enforced inside the engine for scoped users."""
    try:
        return await workflow_engine.set_status(activity_id, req.status, actor=user)
    except ValueError as e:
        _raise_for(e)


@router.post("/workflow-activities/{activity_id}/schedule")
async def set_workflow_activity_schedule(activity_id: str, req: SetScheduleRequest, user: dict = Depends(get_current_user)):
    """Sprint 6.1 — Planned/Actual Start/Finish. Open to any authenticated
    role, same as status (a supervisor logging actual dates on-site is
    exactly the intended use). Pure data storage — see
    workflow_engine.set_schedule's docstring for why no validation or
    status-linked inference happens here."""
    try:
        return await workflow_engine.set_schedule(
            activity_id, req.model_dump(exclude_unset=True), actor=user,
        )
    except ValueError as e:
        _raise_for(e)


@router.get("/workflow-meta")
async def workflow_meta(user: dict = Depends(get_current_user)):
    """Static vocab for the frontend Workflow Viewer's status vocabulary,
    matching the GET /api/knowledge-meta convention."""
    return {"statuses": sorted(workflow_engine.STATUSES)}


@router.post("/workflow-templates/seed-defaults")
async def seed_default_templates(user: dict = Depends(get_current_user)):
    """Idempotently creates the five named starter templates (Villa,
    Residential, Commercial, Interior, Renovation) as empty shells, ready
    for an admin to populate via the existing Knowledge relationship
    mechanism. Mirrors POST /api/projects/seed's idempotent shape."""
    if user["role"] not in ("management", "project_manager"):
        raise HTTPException(status_code=403, detail="Only Project Managers/management can seed workflow templates")
    return await workflow_engine.seed_default_templates(actor=user)
