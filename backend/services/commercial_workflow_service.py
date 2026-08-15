"""Atlas Commercial Workflow Service (PX-03 Phase 1, extended PX-03
Phase 2).

Pure composition over the existing commercial_engine — every KPI here
is computed from fields that already exist (Contract, Budget,
PaymentRequest, Payment), never a new financial field. This directly
answers this task's own Section 1 audit requirement: no duplicate
field was created, because none was needed.

Every KPI function returns both the number and its own "view
calculation" breakdown (the exact inputs used) in the same call,
because this task's own Mandatory Transparency Rule requires both to
always be available together, not the number alone with a breakdown
computed separately (which would risk the two drifting apart).

PX-03 Phase 2 Section 6/7 — role-safe access. Before this phase,
assert_project_visible only checked project membership, never role.
A Client or Supervisor legitimately assigned to their own project (the
normal case, not an edge case) received the exact same unrestricted
profitability/health/timeline data Management/PM get. Fixed at the
service layer — the same layer every calculation already lives in —
not by hiding components in React, per this task's own explicit "the
backend response itself must be role-safe" instruction.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional
from engines import commercial_engine as ce

INTERNAL_COMMERCIAL_ROLES = ("management", "project_manager")


class CommercialPermissionError(ce.CommercialError):
    """Raised when a role without internal-commercial access requests
    an endpoint that has no safe client-shaped subset — margin,
    budget, and forecast data are inherently internal, so denial is
    the correct response here, not a reshaped response, matching this
    task's own explicit 'a safe client-shaped response, OR a
    permission denial' framing for endpoints where no safe subset
    exists."""


def _require_internal_commercial_access(user: dict) -> None:
    if user.get("role") not in INTERNAL_COMMERCIAL_ROLES:
        raise CommercialPermissionError(
            "Only Project Managers/management can view internal commercial detail.")


def _round2(n: float) -> float:
    return round(n, 2)


async def build_profitability_panel(project_id: str, *, user: dict) -> Optional[dict]:
    """Section 2 — the KPI table, exactly as this task's own formula
    table specifies, each with a 'View Calculation' breakdown.
    Internal-only (PX-03 Phase 2 Section 6/7) — every field here is
    margin, budget, or cost data with no safe client-facing subset."""
    _require_internal_commercial_access(user)
    await ce.assert_project_visible(project_id, user)
    summary = await ce.get_project_commercial_summary(project_id)
    if not summary:
        return None

    contract_value = summary["contract"]["original_contract_value"]
    approved_variations = summary["approved_variations_total"]
    revenue_potential = contract_value + approved_variations

    budget = summary["budget"]
    if budget:
        actual_expenses = budget["actual_cost"]
        committed_cost = budget["committed_cost"]
        # PX-03 Phase 1 Section 2 — this task's own explicit formula
        # (Budget - Committed Cost) differs from get_budget()'s own
        # existing remaining_budget field (Budget - Actual Cost, a
        # formula CP-01 already established and other screens already
        # depend on). Computed here as a new, separate display value
        # for this panel specifically, rather than changing the
        # existing field and risking every other consumer of it.
        remaining_budget_vs_committed = _round2(budget["current_budget"] - committed_cost)
        forecast_final_cost = budget["forecast_cost"]
    else:
        actual_expenses = committed_cost = remaining_budget_vs_committed = forecast_final_cost = None

    forecast_profit = _round2(revenue_potential - forecast_final_cost) if forecast_final_cost is not None else None
    forecast_margin = _round2((forecast_profit / revenue_potential) * 100) if forecast_profit is not None and revenue_potential > 0 else None

    return {
        "project_id": project_id,
        "kpis": {
            "contract_value": {
                "value": contract_value,
                "calculation": {"formula": "Base contract", "inputs": {"original_contract_value": contract_value}},
            },
            "approved_variations": {
                "value": approved_variations,
                "calculation": {"formula": "Sum of approved variations", "inputs": {"approved_variations_total": approved_variations}},
            },
            "current_revenue_potential": {
                "value": _round2(revenue_potential),
                "calculation": {
                    "formula": "Contract Value + Approved Variations",
                    "inputs": {"contract_value": contract_value, "approved_variations": approved_variations},
                },
            },
            "budget": {
                "value": budget["current_budget"] if budget else None,
                "calculation": {"formula": "Approved project budget", "inputs": {"current_budget": budget["current_budget"] if budget else None}},
            },
            "actual_expenses": {
                "value": actual_expenses,
                "calculation": {"formula": "Sum of recorded expenses", "inputs": {"actual_cost": actual_expenses}},
            },
            "committed_cost": {
                "value": committed_cost,
                "calculation": {
                    "formula": "Actual Expenses + Approved purchase commitments (committed_cost already includes both, per the existing Budget Engine's own tracking)",
                    "inputs": {"committed_cost": committed_cost},
                },
            },
            "remaining_budget": {
                "value": remaining_budget_vs_committed,
                "calculation": {
                    "formula": "Budget - Committed Cost",
                    "inputs": {"budget": budget["current_budget"] if budget else None, "committed_cost": committed_cost},
                },
            },
            "forecast_profit": {
                "value": forecast_profit,
                "calculation": {
                    "formula": "Current Revenue Potential - Forecast Final Cost",
                    "inputs": {"current_revenue_potential": _round2(revenue_potential), "forecast_final_cost": forecast_final_cost},
                },
            },
            "forecast_margin_percent": {
                "value": forecast_margin,
                "calculation": {
                    "formula": "Forecast Profit / Current Revenue Potential",
                    "inputs": {"forecast_profit": forecast_profit, "current_revenue_potential": _round2(revenue_potential)},
                },
            },
        },
    }


async def build_billing_and_collections(project_id: str, *, user: dict) -> Optional[dict]:
    """Section 6 — receivables metrics, reusing the existing
    payment_requests/payments data (already exactly the "receipt"
    fields this task asks for: amount, date, reference) rather than
    a new collection. Client-safe by this task's own explicit Section
    6 list (billed/received/outstanding amounts); Supervisor is still
    excluded (Section 7's own "no detailed commercial values" rule)."""
    if user.get("role") == "site_supervisor":
        raise CommercialPermissionError("Site Supervisors do not have access to detailed commercial values.")
    await ce.assert_project_visible(project_id, user)
    summary = await ce.get_project_commercial_summary(project_id)
    if not summary:
        return None

    billed_statuses = ("raised", "sent", "partially_paid", "paid", "overdue")
    billed_to_date = _round2(sum(pr["amount"] for pr in summary["payment_requests"] if pr["status"] in billed_statuses))
    received_to_date = _round2(sum(p["amount"] for p in summary["payments"] if p["status"] == "recorded"))
    outstanding = _round2(billed_to_date - received_to_date)
    efficiency = _round2((received_to_date / billed_to_date) * 100) if billed_to_date > 0 else None

    return {
        "billed_to_date": {"value": billed_to_date, "calculation": {"formula": "Sum of approved/sent payment requests"}},
        "received_to_date": {"value": received_to_date, "calculation": {"formula": "Sum of confirmed receipts"}},
        "outstanding_receivables": {"value": outstanding, "calculation": {"formula": "Billed - Received"}},
        "collection_efficiency_percent": {"value": efficiency, "calculation": {"formula": "Received / Billed"}},
    }


async def commercial_health(project_id: str, *, user: dict) -> dict:
    """Section 7 — a lightweight, independent signal, deterministic
    thresholds only, never combined with operational health.
    Internal-only (PX-03 Phase 2) — its own reasons
    (negative_forecast_margin, etc.) directly reveal internal
    profitability state, with no safe client-facing subset named
    anywhere in this task's own Section 6 list."""
    _require_internal_commercial_access(user)
    panel = await build_profitability_panel(project_id, user=user)
    billing = await build_billing_and_collections(project_id, user=user)
    if not panel or not billing:
        return {"status": "healthy", "reasons": []}

    margin = panel["kpis"]["forecast_margin_percent"]["value"]
    outstanding = billing["outstanding_receivables"]["value"]
    billed = billing["billed_to_date"]["value"]
    overdue_ratio = (outstanding / billed) if billed and billed > 0 else 0

    reasons = []
    if margin is not None and margin < 0:
        reasons.append("negative_forecast_margin")
    if overdue_ratio > 0.5:
        reasons.append("severely_overdue_receivables")
    if reasons:
        return {"status": "risk", "reasons": reasons}

    reasons = []
    if margin is not None and margin < 10:
        reasons.append("declining_margin")
    if outstanding > 0:
        reasons.append("overdue_receivables_present")
    if reasons:
        return {"status": "attention", "reasons": reasons}

    return {"status": "healthy", "reasons": []}


async def build_client_safe_bill_summary(project_id: str, *, user: dict) -> Optional[dict]:
    """PX-03 Phase 2 Section 6 — the dedicated client-safe response,
    composing exactly this task's own named client-safe field list.
    Never reuses or reshapes build_profitability_panel's own output —
    that endpoint has no safe subset (every field is margin/budget/
    cost). This function only ever reads contract_value, approved
    variations, and payment-request/payment amounts and statuses -
    nothing internal is computed here to redact later."""
    await ce.assert_project_visible(project_id, user)
    summary = await ce.get_project_commercial_summary(project_id)
    if not summary:
        return None

    contract = summary["contract"]
    payment_requests = [
        {
            "number": pr["number"], "amount": pr["amount"], "status": pr["status"],
            "due_date": pr.get("due_date"), "raised_date": pr.get("raised_date"),
        }
        for pr in summary["payment_requests"] if pr["status"] != "draft"  # a draft PR isn't yet a real client-facing request
    ]
    billed_statuses = ("raised", "sent", "partially_paid", "paid", "overdue")
    billed_to_date = _round2(sum(pr["amount"] for pr in summary["payment_requests"] if pr["status"] in billed_statuses))
    received_to_date = _round2(sum(p["amount"] for p in summary["payments"] if p["status"] == "recorded"))

    return {
        "project_id": project_id,
        "approved_contract_amount": contract["original_contract_value"],
        "approved_variations_total": summary["approved_variations_total"],
        "payment_requests": payment_requests,
        "billed_to_date": billed_to_date,
        "received_to_date": received_to_date,
        "outstanding_amount": _round2(billed_to_date - received_to_date),
    }


async def cash_flow_timeline(project_id: str, *, user: dict, limit: int = 20) -> list[dict]:
    """Section 4 — a lightweight coordination view, reusing the
    existing commercial_events ledger and payment request due dates.
    Never a forecasting engine, per this task's own explicit rule.
    Internal-only (PX-03 Phase 2) — mixes safe event kinds
    (payment_request_raised, payment_received) with internal-only ones
    (budget_revised); restricted wholesale rather than partially
    filtered, to avoid an oversight leaking an internal kind through."""
    _require_internal_commercial_access(user)
    await ce.assert_project_visible(project_id, user)
    events = await ce.list_commercial_events(project_id, limit=100)
    summary = await ce.get_project_commercial_summary(project_id)

    items = []
    for e in events:
        if e["kind"] in ("payment_request_raised", "payment_received", "variation_approved", "budget_revised"):
            items.append({"date": e["created_at"][:10], "kind": e["kind"], "payload": e.get("payload", {})})

    if summary:
        for pr in summary["payment_requests"]:
            if pr["status"] in ("raised", "sent") and pr.get("due_date"):
                items.append({"date": pr["due_date"], "kind": "payment_follow_up_due",
                             "payload": {"number": pr["number"], "amount": pr["amount"]}})

    items.sort(key=lambda i: i["date"])
    return items[:limit]
