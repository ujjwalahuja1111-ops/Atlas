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
    # FAC-04 froze the role model: client is a first-class backend role
    # and workspace is a derived function of role — so the gate checks
    # `role` directly, exactly like routes/operational_items.py on main.
    if user.get("role") == "client":
        raise HTTPException(
            status_code=403,
            detail="Clients cannot access project reasoning.")


def _require_coordination_role(user: dict, action: str) -> None:
    # Same allowlist convention as workflow generation on main
    # (FAC-04: management + project_manager are the coordination roles).
    if user["role"] not in ("management", "project_manager"):
        raise HTTPException(
            status_code=403,
            detail=f"Only management and project managers can {action}.")


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
        return await reasoning_engine.list_insights(
            project_id, user=user, status=status, domain=domain)
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


@router.get("/projects/{project_id}/lookahead")
async def get_project_lookahead(project_id: str,
                                user: dict = Depends(get_current_user)):
    """Look-ahead intelligence: next expected activities, why they are
    expected, readiness prerequisites, possible blockers, recommended
    preparation. Derived projection — never stored, never executed."""
    _forbid_client(user)
    try:
        return await reasoning_engine.project_lookahead_view(
            project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/forecast")
async def get_project_forecast(project_id: str,
                               user: dict = Depends(get_current_user)):
    """Deterministic delay forecast from the project's own measured
    productivity propagated through the dependency graph. No AI."""
    _forbid_client(user)
    try:
        return await reasoning_engine.project_forecast_view(
            project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/briefing")
async def get_project_briefing(project_id: str,
                               user: dict = Depends(get_current_user)):
    """The PM's deterministic morning briefing."""
    _forbid_client(user)
    try:
        return await reasoning_engine.project_briefing_view(
            project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-summary")
async def get_client_summary(project_id: str,
                             user: dict = Depends(get_current_user)):
    """Deterministic plain-English progress DRAFT for the client.
    Served to internal roles only: CRE prepares the words, a human
    reviews and sends them."""
    _forbid_client(user)
    try:
        return await reasoning_engine.client_summary_view(
            project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-dashboard")
async def get_client_dashboard(project_id: str,
                               user: dict = Depends(get_current_user)):
    """CRE Integration — client dashboard cards (Progress Summary,
    Current Stage, Upcoming Milestones). Deliberately the ONE reasoning
    endpoint that does NOT call _forbid_client: it is the pre-sanitized
    client-safe view built specifically for this purpose (see
    reasoning_engine.client_dashboard_view's docstring for exactly what
    is and is not included). Every other role is free to use it too
    (same project-visibility rule as every other view), but it exists
    for the client.
    """
    try:
        return await reasoning_engine.client_dashboard_view(
            project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/construction-memory")
async def list_construction_memory(project_id: str,
                                   user: dict = Depends(get_current_user)):
    """Captured construction-memory records (learning substrate; nothing
    reads these back yet)."""
    _forbid_client(user)
    try:
        return await reasoning_engine.list_construction_memory(
            project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/reasoning/executive")
async def executive_answer(question: str,
                           user: dict = Depends(get_current_user)):
    """Reusable deterministic answers to portfolio-level management
    questions (see /api/reasoning-meta -> executive_questions). Not
    conversational AI: a fixed question vocabulary, each answered by
    explicit reasoning over the caller's visible projects."""
    _forbid_client(user)
    _require_coordination_role(user, "use executive reasoning")
    try:
        return await reasoning_engine.executive_answer(question, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/portfolio/control-center")
async def get_portfolio_control_center(user: dict = Depends(get_current_user)):
    """Portfolio Control Center (Phase 1 — schedule-based monitoring
    only; see engines/reasoning_engine.py's portfolio_control_center
    docstring for exactly which existing CRE outputs each field reuses).
    Management/Admin only, per the brief — narrower than
    /reasoning/executive's management+project_manager allowlist, since
    this is specifically a portfolio-oversight view, not a coordination
    tool a PM would use day to day.
    """
    _forbid_client(user)
    if user["role"] != "management":
        raise HTTPException(
            status_code=403,
            detail="Only management can view the Portfolio Control Center.")
    return await reasoning_engine.portfolio_control_center(user=user)


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
        "stages": reasoning_engine.projections.STAGE_ORDER,
        "stage_labels": reasoning_engine.projections.STAGE_LABELS,
        "executive_questions": reasoning_engine.EXECUTIVE_QUESTIONS,
        "memory_schema_version": reasoning_engine.projections.MEMORY_SCHEMA_VERSION,
        "rules": reasoning_engine.list_rules(),
    }
