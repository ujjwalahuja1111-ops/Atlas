# Commercial Foundation Engine (CF-01)

The financial operating system for a construction project — backend/engines/commercial_engine.py. Replaces the lightweight commercial_reference snapshot (which still exists, and remains the fallback for any project without real Commercial Foundation Engine data — see Integration Points below).

## Reconciliation with the frozen architecture specification

memory/COMMERCIAL_FOUNDATION_ENGINE.md (the earlier, architecture-only specification) treated Milestone as derived — a reference to a Workflow stage, never stored — and folded "Payment Request" into a generalized Invoice entity. This sprint's brief defines Milestone with its own genuine billing lifecycle (Payment Requested / Paid / Closed states no Workflow Activity has any business owning) and asks for Payment Request as the billing document directly.

Both are adopted here as real, superseding refinements, not silent reversals. Milestone's richer lifecycle is a legitimate reason for it to be a first-class entity the original specification's narrower "billing trigger" framing didn't anticipate. Payment Request is functionally the same object the frozen spec called Invoice, under this sprint's own naming. This document is the current authority on the domain model; the frozen specification remains correct on everything it doesn't address here (Work Package, BOQ, Cost Code, Procurement Package, Commercial Snapshot's flag-based Baseline design — all retained unmodified).

## Domain Model

| Entity | Collection | Owns |
|---|---|---|
| Contract | contracts | One per project. current_contract_value is always derived (original + approved variation deltas) — never stored, never manually edited. |
| Milestone | milestones | A billing schedule line with its own lifecycle. contract_value is derived once at creation (a deliberate snapshot, not a live computation — a milestone's billed amount shouldn't drift every time an unrelated later variation changes the contract total). |
| Payment Request | payment_requests | The billing document raised against an achieved Milestone. Sequential per-project numbering (PR-001, PR-002, ...). |
| Payment | payments | Actual money received against a Payment Request. Supports partial and multiple payments, and adjustment entries (is_adjustment=True). |
| Variation | variations | Cost/scope change proposal, with its own approval lifecycle. Approval is the one place with real, automatic side effects. |
| Budget | budgets | One per project, internal-only (never client-visible). Original/Current Budget and Committed/Actual Cost are stored; Forecast Cost, Variance, and Remaining Budget are always computed. |
| Commercial Event | commercial_events | Single, unified, append-only ledger every mutation above writes to — the same CQRS shape Operations Engine's own operational_events already proved at scale. |
| Commercial Snapshot | commercial_snapshots | Point-in-time, immutable capture of a project's full commercial state, with an is_baseline flag (per the frozen specification's own resolution — one entity, not two). |

## State Machines

Contract: draft -> review -> approved -> active -> completed -> closed. review can return to draft. Every other transition is one-directional and terminal at closed.

Milestone: pending -> ready -> achieved -> payment_requested -> paid -> closed. ready can return to pending (a readiness check failed). achieved auto-timestamps actual_date. Raising a Payment Request against a Milestone requires it to be achieved — enforced, not just documented — and auto-transitions the Milestone to payment_requested. A Payment Request reaching paid auto-transitions its Milestone to paid.

Payment Request: draft -> raised -> sent -> {partially_paid | paid | overdue} -> paid. Status is re-derived from the full payment history on every payment recorded — never incremented ad hoc. cancelled is reachable from draft/raised/sent only.

Variation: draft -> submitted -> client_review -> {approved | rejected} -> implemented. A decision (approved/rejected) is only legal from client_review — a variation cannot be approved directly from draft or submitted, enforced by the same transition table every other check in this engine uses.

No route ever sets a status field directly on any of the above — every transition goes through its own named engine function (transition_contract_status, transition_milestone_status, transition_payment_request_status, decide_variation), per Atlas Engineering Standards v1 §5's absolute rule.

## Calculation Rules

All of the following are computed fresh on every read, never stored as a second, potentially-stale field:

- Current Contract Value = Original Contract Value + sum(approved variation approved_cost - original_cost).
- Outstanding Payments = sum(non-cancelled Payment Request amounts) minus sum(all Payments recorded).
- Forecast Cost = max(Actual Cost, Committed Cost) — the project's cost can never be forecast below what's already spent.
- Variance = Current Budget - Forecast Cost. Remaining Budget = Current Budget - Actual Cost.
- Milestone Completion % = sum(planned_percent of every Milestone in achieved/payment_requested/paid/closed).
- Cash Flow Signal (healthy/attention/critical) = a fixed threshold on received/raised across non-cancelled Payment Requests, with any single overdue Payment Request forcing critical regardless of the ratio. Deterministic — no AI, no judgment call.

## Client Impact Engine

calculate_variation_impact(variation) — one pure function, called identically from the approval flow and reusable by any future consumer:

```
cost_impact       = (approved_cost or proposed_cost) - original_cost
schedule_impact_days = time_impact_days
payment_impact    = cost_impact if status == "approved" else 0
forecast_impact   = cost_impact if status == "approved" else 0
```

Payment/forecast impact are correctly zero before approval — a variation under review has no real financial consequence yet; reporting one would be a fabricated number.

## Event Flow (Commercial Timeline)

Every mutation above appends exactly one commercial_events entry (past-tense kind: contract_created, variation_approved, payment_received, milestone_closed, ...). timeline_engine.for_project_commercial(project_id) reads this ledger directly and translates it into a timeline-compatible shape — it duplicates none of timeline_engine.py's existing Reality/Analysis/Correction composition logic, and commercial events are never merged into that composition; they're a parallel, separately-exposed feed (GET /api/projects/{id}/commercial-timeline), matching the brief's "integrates into existing Timeline Engine, do not duplicate timeline logic" instruction precisely.

## Integration Points

- Existing Commercial section (Project Dashboard, app/projects/[id].tsx): unmodified this sprint. GET /api/projects/{id}/commercial-reference (the lightweight layer) remains the data source that screen reads. GET /api/projects/{id}/commercial/summary is the new, richer composed read a future frontend pass should switch to — extending, not breaking, the existing screen, per the brief's own "existing UI should automatically become richer... do not break existing screens" instruction. This sprint delivers the backend; wiring the existing screen to prefer the richer summary when present is named explicitly as remaining work below.
- RBAC: write operations are management/project_manager-only, matching every other commercially-adjacent action in Atlas. Reads are open to any role with project visibility, including client — except Budget, which is never client-visible (internal-only, per the frozen specification's own §6). Deciding a Variation is deliberately open to the client too, matching the existing client_approval pattern's precedent that approval decisions on a client's own contract belong to the client.
- Reference Portfolio: RP-001 (ACDP) migrated to real Commercial Foundation Engine data (scripts/reference_portfolio.py::migrate_rp001_to_commercial_engine) — a genuine Contract, six Milestones with a real achieved/paid history, an approved Variation and a pending one, and a Budget — using the exact figures the lightweight commercial_reference already established, so the two layers agree rather than silently disagreeing about RP-001's own numbers. RP-002 migration is not done this sprint — named explicitly below.

## Future Expansion — Compatibility, Not Implementation

This engine's boundaries are designed so the following can be added without redesigning anything above:

- Client Experience Layer: reads get_project_commercial_summary directly; no schema change needed.
- Executive Dashboard: consumes cash_flow_signal/variance/milestone_completion_percent as inputs to a future CRE-level synthesis — this engine publishes plain indicators, it never synthesizes an overall judgment itself (the same boundary the frozen specification's own §8.4 Commercial Health section already established).
- Vendor Management / Procurement / Purchase Orders: commit_cost/record_actual_cost already accept an arbitrary amount_delta and reason — a future Procurement Engine calls these the same way this sprint's own migration script does, without needing a schema change here.
- Invoicing (in the generic accounting sense): Payment Request already is the billing document; a future accounting integration exports it, it doesn't replace it.
- ERP Integrations / Financial Reporting: commercial_events is already a complete, append-only audit trail in a stable shape — the natural export source for either, without this engine needing to know anything about the external system's own data model.

None of the above are implemented this sprint — only the extension points are confirmed to exist.

## What Was Not Done This Sprint — Named Explicitly

- RP-002 migration. RP-001 was migrated with genuine, verified data; RP-002 (the Commercial Office) was not — the lightweight commercial_reference remains its only commercial data source. Real remaining work, not silently skipped.
- Frontend wiring. The existing Project Dashboard's Commercial section was not changed to prefer get_project_commercial_summary over the lightweight reference layer. The backend is ready; the frontend switch is a small, well-scoped follow-up.
- Work Package / BOQ / Cost Code / Procurement Package from the frozen specification remain unimplemented — this sprint's brief scoped a simpler six-entity model (Contract, Milestone, Payment Request, Payment, Variation, Budget), and that simpler model is what was built. The frozen specification's fuller model remains the reference for whenever that additional scope is picked up.
- Milestone forecast-date recalculation. forecast_date is a plain field a caller can update via transition_milestone_status's own forecast_date parameter — there is no automatic schedule-variance-driven recalculation of it yet (that would naturally consume Workflow Engine's own schedule variance data, a genuine future integration, not built here).
