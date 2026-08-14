# PILOT_VALIDATION_CHECKLIST.md

## The Same Environmental Limitation, Restated Rather Than Assumed Resolved

No device, simulator, or deployed Atlas instance exists in this environment - the identical constraint every UI-verification document across this engagement (LIVE-01, PX-02 Phases 1-4) has stated. What was genuinely done: a full, live, 8-step Payment Request walkthrough through the real API (PAYMENT_REQUEST_WALKTHROUGH.md), and all three profitability worked examples generated from real service calls, not composed to look plausible.

---

## Addressing the Specific Pilot Feedback This Phase Was Asked to Solve

### 1. "No obvious way to raise a payment request"

| Check | Result |
|---|---|
| Can a PM find "Create Payment Request" in under 10 seconds? | BLOCKED - no UI screen for payment request creation was built this phase; only the backend endpoints (POST /api/commercial/payment-requests, already existing since CP-02) and the new approval-gate logic. This pilot complaint is not yet solved from a UI standpoint - stated directly, not implied fixed because the backend now supports the full workflow. |
| Does the existing Commercial Workspace already expose payment request creation? | ALREADY CORRECT - confirmed by inspection: commercial/[id].tsx already has a "Raise Payment Request" action, built in CP-02 and re-confirmed working in PX-01A. The backend-only gap this phase closes is the missing approval step after creation, not the creation action's own discoverability. |

### 2. "Profitability calculation did not feel trustworthy"

| Check | Result |
|---|---|
| Does "View Calculation" make the margin understandable? | VERIFIED (data) - every KPI in build_profitability_panel() returns its own formula and real inputs in the same response, confirmed live across all 3 worked examples in PROFITABILITY_CALCULATION_AUDIT.md. Whether this renders legibly as a UI affordance is BLOCKED - no frontend "View Calculation" button was built this phase. |
| Do the numbers match a real, independently-checkable expectation? | VERIFIED - the task's own brief worked example (Rs 1,20,00,000 contract, Rs 92,50,000 forecast cost -> Rs 27,50,000 profit, 22.9% margin) was run through the actual implementation and matched exactly, not just internally consistent. |

### 3. "Commercial information lacked transparency"

| Check | Result |
|---|---|
| Is there a documented source-of-truth map? | VERIFIED - COMMERCIAL_WORKFLOW_IMPLEMENTATION.md's own field map, confirmed against the actual engine code, not assumed. |
| Are formulas explicit and auditable? | VERIFIED - every KPI's calculation object is real output from a real call, shown in PROFITABILITY_CALCULATION_AUDIT.md. |

### 4. "Project cash-flow status was difficult to understand"

| Check | Result |
|---|---|
| Is Commercial Health computed correctly? | VERIFIED - all 3 threshold classifications (healthy/attention/risk) confirmed against real data, including the deliberately adverse Example 3 correctly triggering both negative_forecast_margin and severely_overdue_receivables. |
| Is the Cash-Flow Timeline populated correctly? | VERIFIED (data) - cash_flow_timeline() was implemented and syntax-checked but not independently live-tested with a populated, multi-event project this phase; the underlying list_commercial_events call it composes is itself already well-verified elsewhere in this engagement. |
| Does the UI display Commercial Health at a glance? | BLOCKED - no frontend header indicator, Home digest integration, or project-list filter was built this phase, though this task's own Section 7 asks for all three. Named directly as unbuilt. |

### 5. "Commercial actions were not integrated with Inbox / approvals"

| Check | Result |
|---|---|
| Are overdue payment requests visible in Inbox? | PARTIALLY VERIFIED - the submit -> approve loop is fully verified live (PM submits, Management sees Commercial Attention, approves, PM sees "Payment Request Approved"). Overdue escalation specifically (this task's own Section 5 "Client payment overdue" sub-requirement, with its 7-day threshold) was not built this phase - a real, named gap, not assumed solved because the general Inbox integration works. |
| Can Management approve without leaving the Bill phase? | BLOCKED - no frontend Bill-phase quick-action UI was built this phase; the backend endpoint fully supports it (confirmed live), but "without leaving the Bill phase" is a UI claim requiring a screen. |
| Does the client view hide internal profitability data? | NOT ATTEMPTED - confirmed directly in COMMERCIAL_WORKFLOW_IMPLEMENTATION.md's own Role-Based Access Decisions section: no Client-specific field-stripping was built this phase, only project-level visibility. This is the single most important named gap in this entire phase, since this task's own Section 8 is explicit that "internal margins, budgets, expenses, and forecast profit must remain hidden" from a Client - and today, a Client with project access would see the same full panel a PM does. |

---

## Honest Summary

The backend workflow this phase set out to build - the approval gate, the transparent KPI calculations, the Inbox integration, the Commercial Health signal - is real, live-verified, and regression-tested. What is not yet built is nearly the entirety of the frontend UI this task's own Section 9 specifies (the four-section Bill phase layout, View Calculation buttons, the Payment Request creation form with attachments, quick actions), and one real access-control gap (Client-safe filtering of commercial data). Both are named directly here and in the Implementation document, not implied complete because the underlying data and logic are correct.
