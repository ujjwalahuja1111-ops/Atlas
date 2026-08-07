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


@router.get("/projects/{project_id}/since-last-visit")
async def get_since_last_visit(project_id: str, user: dict = Depends(get_current_user)):
    try:
        return await reasoning_engine.get_since_last_visit(project_id, user=user)
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


@router.get("/projects/{project_id}/explain-health")
async def get_explain_health(project_id: str,
                             user: dict = Depends(get_current_user)):
    """Beta-05 — "Explain Health": Score -> Dimensions -> Drivers ->
    Recommended Actions, composed from project_health and
    list_insights exactly as they already exist. Same RBAC as
    /health itself."""
    _forbid_client(user)
    try:
        return await reasoning_engine.explain_health(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/commercial-reference")
async def get_project_commercial_reference(project_id: str,
                                           user: dict = Depends(get_current_user)):
    """Visual Validation (VV-01) — a project's Commercial reference
    data (see memory_engine.set_commercial_reference's own docstring:
    this is deliberately NOT a Commercial Foundation Engine
    implementation, just the reference figures the Reference Portfolio
    seeded). Returns null if none was ever set for this project — the
    frontend is expected to show an honest "not available" state, not
    treat null as an error."""
    _forbid_client(user)
    try:
        return await reasoning_engine.get_commercial_reference(project_id, user=user)
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


@router.get("/projects/{project_id}/client-experience")
async def get_client_experience_dashboard(project_id: str,
                                          user: dict = Depends(get_current_user)):
    """Atlas Client Experience (ACE Sprint 01) — the redesigned client
    landing page's hero + "what needs my attention" sections. Same
    "no _forbid_client" pattern as /client-dashboard above: this IS the
    client-facing view, open to every role with project visibility.
    """
    try:
        return await reasoning_engine.client_experience_dashboard(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-approvals")
async def get_client_approval_centre(project_id: str,
                                     user: dict = Depends(get_current_user)):
    """ACE item 3 — the permanent Approval Centre (pending, approved,
    rejected, and the full timeline). Fixes the brief's own stated
    complaint precisely: "Approve -> Disappears" is not how this view
    works."""
    try:
        return await reasoning_engine.client_approval_centre(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-communications")
async def get_client_communication_centre(project_id: str,
                                          user: dict = Depends(get_current_user)):
    """ACE item 10 — structured communication (Waiting for Contractor /
    Waiting for Client), built entirely from the existing
    request_clarification ledger."""
    try:
        return await reasoning_engine.client_communication_centre(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-timeline")
async def get_client_project_timeline(project_id: str,
                                      user: dict = Depends(get_current_user)):
    """ACE item 6 — project milestones (stage-level only, no workflow
    activity detail exposed)."""
    try:
        return await reasoning_engine.client_project_timeline(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-investment")
async def get_client_investment_summary(project_id: str,
                                        user: dict = Depends(get_current_user)):
    """CX-01 — "Your Investment." Contract Value, Paid, Outstanding,
    Current Variation Total, Upcoming Payment. Never Budget/Forecast/
    internal costs — see reasoning_engine.client_investment_summary's
    own docstring."""
    try:
        return await reasoning_engine.client_investment_summary(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-payment-journey")
async def get_client_payment_journey(project_id: str,
                                     user: dict = Depends(get_current_user)):
    """CX-01 — the visual Contract -> Milestone -> Payment sequence."""
    try:
        return await reasoning_engine.client_payment_journey(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-variations")
async def get_client_variation_centre(project_id: str,
                                      user: dict = Depends(get_current_user)):
    """CX-01 — the client-facing Variation approval centre, each entry
    carrying its own pre-calculated Cost/Schedule/Payment/Forecast
    impact from commercial_engine directly."""
    try:
        return await reasoning_engine.client_variation_centre(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/client-recent-activity")
async def get_client_recent_activity(project_id: str,
                                     user: dict = Depends(get_current_user)):
    """Beta-01 — factual 7-day activity rollup, replacing the client
    dashboard's previous permanent "AI summaries coming soon" stub."""
    try:
        return await reasoning_engine.client_recent_activity(project_id, user=user)
    except ValueError as e:
        _raise_for(e)


@router.get("/portfolio/compare")
async def get_portfolio_comparison(project_ids: str,
                                   user: dict = Depends(get_current_user)):
    """Reference Portfolio (RP-01) — cross-project comparison. project_ids
    is a comma-separated list (?project_ids=prj_a,prj_b). Not
    client-facing — this is a management/PM/developer regression and
    demonstration tool, so (unlike every route above it) this one does
    call _forbid_client."""
    _forbid_client(user)
    ids = [p.strip() for p in project_ids.split(",") if p.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least two project_ids to compare.")
    try:
        return await reasoning_engine.compare_projects(ids, user=user)
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


@router.get("/portfolio/priorities")
async def get_priority_engine(user: dict = Depends(get_current_user)):
    """Priority Engine (Beta-05 continuation) — "Today's Highest
    Priorities," one ranked, cross-project attention list composed
    from portfolio_control_center and explain_health, both unchanged.
    Same RBAC as Portfolio Control Center itself — management only."""
    _forbid_client(user)
    if user["role"] != "management":
        raise HTTPException(
            status_code=403,
            detail="Only management can view Priority Engine.")
    return await reasoning_engine.priority_engine(user=user)


@router.get("/portfolio/cross-project-intelligence")
async def get_cross_project_intelligence(user: dict = Depends(get_current_user)):
    """Cross-Project Intelligence (Beta-05 final) — aggregation only,
    reusing evaluate_rules() exactly as every individual project's own
    health check already runs it. Management only, matching Portfolio
    Control Center."""
    _forbid_client(user)
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="Only management can view Cross-Project Intelligence.")
    return await reasoning_engine.cross_project_intelligence(user=user)


@router.get("/portfolio/commercial-intelligence")
async def get_commercial_intelligence(user: dict = Depends(get_current_user)):
    """Unified Commercial Intelligence (Beta-05 final) — composes
    existing, unmodified Commercial Foundation data across every
    project. Management only — this is explicitly the Budget-adjacent
    view (variance, over-budget), never exposed to non-management
    roles anywhere else in Atlas."""
    _forbid_client(user)
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="Only management can view Commercial Intelligence.")
    return await reasoning_engine.commercial_intelligence(user=user)


@router.get("/portfolio/executive-timeline")
async def get_executive_timeline(project_id: Optional[str] = None, category: Optional[str] = None,
                                 user: dict = Depends(get_current_user)):
    """Executive Timeline (Beta-05 final) — merges timeline_engine's own
    existing reads across every visible project. Management only,
    matching every other portfolio-wide executive view."""
    _forbid_client(user)
    if user["role"] != "management":
        raise HTTPException(status_code=403, detail="Only management can view the Executive Timeline.")
    try:
        return await reasoning_engine.executive_timeline(user=user, project_id=project_id, category=category)
    except ValueError as e:
        _raise_for(e)


@router.get("/portfolio/search")
async def get_portfolio_search(q: str, user: dict = Depends(get_current_user)):
    """Portfolio Search (Beta-05 final) — a thin, federated search over
    existing collections, scoped to the caller's own project
    visibility exactly like every other read in this file. Open to any
    non-client role (a lookup tool a PM or supervisor needs day to day,
    not an executive-only insight) — client keeps its own, separate
    Client Experience surface."""
    _forbid_client(user)
    try:
        return await reasoning_engine.portfolio_search(q, user=user)
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
