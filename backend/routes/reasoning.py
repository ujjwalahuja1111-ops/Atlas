"""Construction Reasoning Engine routes (Innovation Sprint 01).

Deliberately thin — every rule (snapshot assembly, rule evaluation,
dedupe, insight lifecycle, project health, optional AI review) lives in
engines/reasoning_engine.py. This file only translates HTTP <-> engine
calls and maps exceptions to status codes via the exact `_raise_for()`
convention routes/knowledge.py and routes/workflow.py established.

Access model (reusing established gates, touching no auth code):

  * Client workspace: blocked from ALL reasoning endpoints. Insights are
    internal operational intelligence (delay risk, safety exposure,
    procurement gaps) — the class of information the Sprint 6.2 client
    permission work deliberately keeps out of the client workspace. Same
    `workspace == "client"` guard convention as routes/operational_items.py.
  * Triggering a run / deciding an insight: coordinator + management only
    (supervisors execute work; reasoning triage is a coordination
    function) — the same role split routes/workflow.py applies to
    workflow generation.
  * Reading insights / health / runs: any internal role with project
    visibility (a supervisor seeing "begin PCC" for their own project is
    the point). Project scoping is enforced inside the engine, same as
    workflow_engine.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user
from engines import reasoning_engine
from engines.reasoning_engine import (
    ReasoningNotFoundError, InvalidInsightTransitionError,
)

router = APIRouter(prefix="/api", tags=["reasoning"])


def _raise_for(e: ValueError) -> None:
    """Same three-way mapping as routes/knowledge.py and routes/workflow.py:
    not-found -> 404, state conflict -> 409, everything else -> 400."""
    if isinstance(e, ReasoningNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    if isinstance(e, InvalidInsightTransitionError):
        raise HTTPException(status_code=409, detail=str(e))
    raise HTTPException(status_code=400, detail=str(e))


def _forbid_client(user: dict) -> None:
    if user.get("workspace") == "client":
        raise HTTPException(
            status_code=403,
            detail="Clients cannot access project reasoning.")


def _require_coordination_role(user: dict, action: str) -> None:
    if user["role"] == "supervisor":
        raise HTTPException(
            status_code=403, detail=f"Supervisors cannot {action}.")


class RunReasoningRequest(BaseModel):
    # Optional AI review pass on top of the deterministic rules. Off by
    # default: reasoning must be fully useful with zero AI configured,
    # matching the Optional AI Worker principle (Sprint 5.0.2).
    include_ai: bool = False


class InsightStatusRequest(BaseModel):
    status: str
    note: str = ""


class InsightFeedbackRequest(BaseModel):
    # Human feedback loop (Sprint 01A): accepted | rejected | modified |
    # ignored, with optional human reasoning. Stored for a FUTURE
    # learning layer; nothing reads it back today.
    verdict: str
    note: str = ""


class InsightRelationshipRequest(BaseModel):
    # previous | duplicate | supports | conflicts — substrate for future
    # multi-step reasoning.
    related_insight_id: str
    relation: str
    note: str = ""


@router.post("/projects/{project_id}/reasoning/run", status_code=201)
async def run_reasoning(project_id: str, req: RunReasoningRequest,
                        user: dict = Depends(get_current_user)):
    _forbid_client(user)
    _require_coordination_role(user, "trigger a reasoning run")
    try:
        return await reasoning_engine.run_reasoning(
            project_id, actor=user, include_ai=req.include_ai)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/insights")
async def list_insights(project_id: str,
                        status: Optional[str] = None,
                        domain: Optional[str] = None,
                        user: dict = Depends(get_current_user)):
    _forbid_client(user)
    try:
        await reasoning_engine._assert_project_visible(project_id, user)
        return await reasoning_engine.list_insights(
            project_id, status=status, domain=domain)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/health")
async def get_project_health(project_id: str,
                             user: dict = Depends(get_current_user)):
    _forbid_client(user)
    try:
        return await reasoning_engine.project_health(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/reasoning/runs")
async def list_reasoning_runs(project_id: str,
                              user: dict = Depends(get_current_user)):
    _forbid_client(user)
    try:
        return await reasoning_engine.list_runs(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.post("/insights/{insight_id}/status")
async def set_insight_status(insight_id: str, req: InsightStatusRequest,
                             user: dict = Depends(get_current_user)):
    _forbid_client(user)
    _require_coordination_role(user, "decide reasoning insights")
    try:
        # Project visibility: resolve the insight's project and apply the
        # same scoping rule as every read endpoint above.
        insight = await reasoning_engine.get_insight(insight_id)
        if insight:
            await reasoning_engine._assert_project_visible(
                insight["project_id"], user)
        return await reasoning_engine.set_insight_status(
            insight_id, req.status, actor=user, note=req.note)
    except ValueError as e:
        _raise_for(e)


@router.post("/insights/{insight_id}/feedback")
async def record_insight_feedback(insight_id: str,
                                  req: InsightFeedbackRequest,
                                  user: dict = Depends(get_current_user)):
    _forbid_client(user)
    _require_coordination_role(user, "record feedback on reasoning insights")
    try:
        insight = await reasoning_engine.get_insight(insight_id)
        if insight:
            await reasoning_engine._assert_project_visible(
                insight["project_id"], user)
        return await reasoning_engine.record_insight_feedback(
            insight_id, req.verdict, actor=user, note=req.note)
    except ValueError as e:
        _raise_for(e)


@router.post("/insights/{insight_id}/relationships")
async def add_insight_relationship(insight_id: str,
                                   req: InsightRelationshipRequest,
                                   user: dict = Depends(get_current_user)):
    _forbid_client(user)
    _require_coordination_role(user, "relate reasoning insights")
    try:
        insight = await reasoning_engine.get_insight(insight_id)
        if insight:
            await reasoning_engine._assert_project_visible(
                insight["project_id"], user)
        return await reasoning_engine.add_insight_relationship(
            insight_id, req.related_insight_id, req.relation,
            actor=user, note=req.note)
    except ValueError as e:
        _raise_for(e)


@router.get("/reasoning-meta")
async def reasoning_meta(user: dict = Depends(get_current_user)):
    """Static vocab for a future Insights UI — matches the established
    GET /api/knowledge-meta and GET /api/workflow-meta convention."""
    _forbid_client(user)
    return {
        "schema_version": reasoning_engine.INSIGHT_SCHEMA_VERSION,
        "domains": sorted(reasoning_engine.DOMAINS),
        "confidence_levels": reasoning_engine.CONFIDENCE_LEVELS,
        "severities": reasoning_engine.SEVERITIES,
        "insight_statuses": sorted(reasoning_engine.INSIGHT_STATUSES),
        "canonical_lifecycle": reasoning_engine.CANONICAL_LIFECYCLE,
        "evidence_kinds": reasoning_engine.EVIDENCE_KINDS,
        "feedback_verdicts": sorted(reasoning_engine.FEEDBACK_VERDICTS),
        "relation_types": sorted(reasoning_engine.RELATION_TYPES),
        "health_dimensions": sorted(reasoning_engine.HEALTH_DIMENSIONS),
        "rules": reasoning_engine.list_rules(),
    }
