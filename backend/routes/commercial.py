"""Commercial Foundation Engine routes (CF-01).

Deliberately thin — every rule (state transitions, derived
calculations, the Client Impact Engine, commercial event recording)
lives in engines/commercial_engine.py. This file only translates
HTTP <-> engine calls and maps exceptions to status codes, mirroring
the exact _raise_for() pattern already established in
routes/workflow.py and routes/knowledge.py.

RBAC: write operations (create/transition/approve/record-payment) are
management/project_manager-only, matching the same allowlist every
other commercially-adjacent action in Atlas already uses (assignment,
client approval decisions). Reads are open to any role with project
visibility, including client — a client seeing their own project's
real commercial summary is the whole point of this engine existing;
what a client-facing screen chooses to translate/hide from that data
is a UI concern, not a reason to gate the read here.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from core.auth import get_current_user
from engines import commercial_engine as ce
from engines.commercial_engine import CommercialNotFoundError

router = APIRouter(prefix="/api", tags=["commercial"])


def _raise_for(e: ValueError) -> None:
    if isinstance(e, CommercialNotFoundError):
        raise HTTPException(status_code=404, detail=str(e))
    raise HTTPException(status_code=400, detail=str(e))


def _require_write_access(user: dict) -> None:
    if user["role"] not in ("management", "project_manager"):
        raise HTTPException(status_code=403,
                            detail="Only Project Managers/management can modify commercial data.")


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

class ContractCreate(BaseModel):
    project_id: str
    client_id: Optional[str] = None
    original_contract_value: float
    contract_date: str
    duration_days: int
    retention_percent: float = 5.0
    advance_percent: float = 10.0
    gst_percent: float = 18.0


@router.post("/commercial/contracts", status_code=201)
async def create_contract(req: ContractCreate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.create_contract(actor=user, **req.model_dump())
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/commercial/contract")
async def get_contract(project_id: str, user: dict = Depends(get_current_user)):
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    contract = await ce.get_contract(project_id)
    if not contract:
        return None
    return contract


class ContractStatusUpdate(BaseModel):
    status: str


@router.post("/projects/{project_id}/commercial/contract/status")
async def set_contract_status(project_id: str, req: ContractStatusUpdate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.transition_contract_status(project_id, req.status, actor=user)
    except ValueError as e:
        _raise_for(e)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

class MilestoneCreate(BaseModel):
    project_id: str
    name: str
    sequence: int
    planned_percent: float
    trigger: str
    planned_date: Optional[str] = None
    contract_value: Optional[float] = None


@router.post("/commercial/milestones", status_code=201)
async def create_milestone(req: MilestoneCreate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.create_milestone(actor=user, **req.model_dump())
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/commercial/milestones")
async def list_milestones(project_id: str, user: dict = Depends(get_current_user)):
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    return await ce.list_milestones(project_id)


class MilestoneStatusUpdate(BaseModel):
    status: str
    forecast_date: Optional[str] = None


@router.post("/commercial/milestones/{milestone_id}/status")
async def set_milestone_status(milestone_id: str, req: MilestoneStatusUpdate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.transition_milestone_status(
            milestone_id, req.status, actor=user, forecast_date=req.forecast_date)
    except ValueError as e:
        _raise_for(e)


# ---------------------------------------------------------------------------
# Payment Requests
# ---------------------------------------------------------------------------

class PaymentRequestCreate(BaseModel):
    project_id: str
    milestone_id: str
    amount: float
    raised_date: str
    due_date: str
    notes: str = ""


@router.post("/commercial/payment-requests", status_code=201)
async def create_payment_request(req: PaymentRequestCreate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.create_payment_request(actor=user, **req.model_dump())
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/commercial/payment-requests")
async def list_payment_requests(project_id: str, user: dict = Depends(get_current_user)):
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    return await ce.list_payment_requests(project_id)


class PaymentRequestStatusUpdate(BaseModel):
    status: str


@router.post("/commercial/payment-requests/{payment_request_id}/status")
async def set_payment_request_status(payment_request_id: str, req: PaymentRequestStatusUpdate,
                                     user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.transition_payment_request_status(payment_request_id, req.status, actor=user)
    except ValueError as e:
        _raise_for(e)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class PaymentCreate(BaseModel):
    payment_request_id: str
    amount: float
    date: str
    method: str
    reference: str = ""
    is_adjustment: bool = False


@router.post("/commercial/payments", status_code=201)
async def record_payment(req: PaymentCreate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.record_payment(actor=user, **req.model_dump())
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/commercial/payments")
async def list_payments(project_id: str, user: dict = Depends(get_current_user)):
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    return await ce.list_payments(project_id)


# ---------------------------------------------------------------------------
# Variations
# ---------------------------------------------------------------------------

class VariationCreate(BaseModel):
    project_id: str
    title: str
    description: str
    original_cost: float
    proposed_cost: float
    time_impact_days: int = 0
    linked_drawing_ids: list[str] = []
    linked_photo_ids: list[str] = []
    linked_quotation_ids: list[str] = []


@router.post("/commercial/variations", status_code=201)
async def create_variation(req: VariationCreate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.create_variation(actor=user, **req.model_dump())
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/commercial/variations")
async def list_variations(project_id: str, user: dict = Depends(get_current_user)):
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    return await ce.list_variations(project_id)


@router.post("/commercial/variations/{variation_id}/submit")
async def submit_variation(variation_id: str, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.submit_variation(variation_id, actor=user)
    except ValueError as e:
        _raise_for(e)


@router.post("/commercial/variations/{variation_id}/send-for-client-review")
async def send_variation_for_client_review(variation_id: str, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.send_variation_to_client_review(variation_id, actor=user)
    except ValueError as e:
        _raise_for(e)


class VariationDecision(BaseModel):
    decision: str  # "approved" | "rejected"
    approved_cost: Optional[float] = None


@router.post("/commercial/variations/{variation_id}/decide")
async def decide_variation(variation_id: str, req: VariationDecision, user: dict = Depends(get_current_user)):
    """Deliberately open to client too (unlike other write routes in
    this file) — approving/rejecting a variation is fundamentally the
    client's own decision on their contract, matching the existing
    client_approval pattern's own precedent elsewhere in Atlas.
    Management/PM may also decide on the client's behalf where that's
    the real workflow."""
    if user["role"] not in ("management", "project_manager", "client"):
        raise HTTPException(status_code=403, detail="Not authorized to decide on this variation.")
    try:
        return await ce.decide_variation(variation_id, req.decision, actor=user, approved_cost=req.approved_cost)
    except ValueError as e:
        _raise_for(e)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class BudgetCreate(BaseModel):
    project_id: str
    original_budget: float


@router.post("/commercial/budgets", status_code=201)
async def create_budget(req: BudgetCreate, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.create_budget(actor=user, **req.model_dump())
    except ValueError as e:
        _raise_for(e)


@router.get("/projects/{project_id}/commercial/budget")
async def get_budget(project_id: str, user: dict = Depends(get_current_user)):
    _require_write_access(user)  # Budget is internal-only — never client-visible, per the frozen spec's own §6
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    return await ce.get_budget(project_id)


class BudgetRevision(BaseModel):
    new_current_budget: float
    reason: str = ""


@router.post("/projects/{project_id}/commercial/budget/revise")
async def revise_budget(project_id: str, req: BudgetRevision, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.revise_budget(project_id, req.new_current_budget, actor=user, reason=req.reason)
    except ValueError as e:
        _raise_for(e)


class CostEntry(BaseModel):
    amount_delta: float
    reason: str = ""


@router.post("/projects/{project_id}/commercial/budget/commit-cost")
async def commit_cost(project_id: str, req: CostEntry, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.commit_cost(project_id, req.amount_delta, actor=user, reason=req.reason)
    except ValueError as e:
        _raise_for(e)


@router.post("/projects/{project_id}/commercial/budget/record-actual-cost")
async def record_actual_cost(project_id: str, req: CostEntry, user: dict = Depends(get_current_user)):
    _require_write_access(user)
    try:
        return await ce.record_actual_cost(project_id, req.amount_delta, actor=user, reason=req.reason)
    except ValueError as e:
        _raise_for(e)


# ---------------------------------------------------------------------------
# Commercial Timeline, Snapshot, Summary
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/commercial/events")
async def list_commercial_events(project_id: str, user: dict = Depends(get_current_user)):
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    return await ce.list_commercial_events(project_id)


@router.post("/projects/{project_id}/commercial/snapshot", status_code=201)
async def take_commercial_snapshot(project_id: str, is_baseline: bool = False,
                                   baseline_reason: Optional[str] = None,
                                   user: dict = Depends(get_current_user)):
    _require_write_access(user)
    return await ce.take_commercial_snapshot(
        project_id, actor=user, is_baseline=is_baseline, baseline_reason=baseline_reason)


@router.get("/projects/{project_id}/commercial/summary")
async def get_project_commercial_summary(project_id: str, user: dict = Depends(get_current_user)):
    """The single composed read every UI surface should call — the
    existing Project Dashboard's Commercial section extends to this
    once real Commercial Foundation Engine data exists for a project,
    falling back to the lightweight commercial_reference layer
    otherwise (see routes/reasoning.py's own
    get_project_commercial_reference)."""
    try:
        await ce.assert_project_visible(project_id, user)
    except ValueError as e:
        _raise_for(e)
    return await ce.get_project_commercial_summary(project_id)
