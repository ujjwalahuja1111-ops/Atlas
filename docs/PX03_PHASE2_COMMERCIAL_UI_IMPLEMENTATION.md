# PX03_PHASE2_COMMERCIAL_UI_IMPLEMENTATION.md

## Files Changed

- backend/services/commercial_workflow_service.py - added the security-critical role gate (CommercialPermissionError, _require_internal_commercial_access) and the new build_client_safe_bill_summary() function.
- backend/routes/commercial_workflow.py - rebuilt with proper exception handling (CommercialPermissionError -> HTTP 403) and the new /client-safe-bill-summary endpoint.
- backend/engines/commercial_engine.py - fixed a real, pre-existing defect in record_payment() (see below), and added the "Returned for Revision" notification trigger.
- backend/tests/test_dev02_bootstrap_reliability.py - 2 existing tests updated (both had been recording payments against draft-status requests, a pattern the new validation correctly now rejects), plus 5 new tests for the security fix and the payment-timing fix.
- frontend/app/commercial/[id].tsx - the primary UI work: Commercial Health banner (consolidated into the existing one, not duplicated - see below), "View Calculation" modal, Billing & Collections section, Cash-Flow Timeline section, Payment Request approval actions (Submit for Review / Approve / Return for Revision), and a fix to the frontend's own canPay logic to match the backend's new validation.
- frontend/app/executive-hub.tsx - 2 pre-existing lint errors fixed (unrelated to this phase's own logic, fixed opportunistically while touching lint output).

## Components Created

- frontend/src/commercial_workflow_api.ts - the typed client for all 5 PX-03 endpoints (profitability panel, billing/collections, health, cash-flow timeline, client-safe summary).
- No new React component files - every addition lives inside the existing commercial/[id].tsx, reusing its own established Section/BreakdownRow/Tile components rather than introducing new ones, per this task's own "use the existing Atlas design system" instruction.

## Existing APIs Reused

Every KPI, health signal, and timeline entry comes from the 4 endpoints PX-03 Phase 1 already built and tested (profitability-panel, billing-collections, health, cash-flow-timeline). No new calculation exists in this phase - Phase 2 is UI and access-control only, exactly as this task's own brief specifies.

## A Real Duplication Caught and Removed Before It Shipped

Mid-implementation, a new Commercial Health banner was added at the top of the screen using the new PX-03 commercialHealth state - only to discover an existing, more complete banner already lower on the screen (from UX-01), which already correctly branches on commercialHealth being available and falls back to the older cash_flow_signal-based logic for Client/Supervisor (where the new endpoint returns 403/null). The newly-added banner was removed rather than leave two competing Commercial Health indicators on one screen - this task's own Section 3 explicitly warns against merging Commercial Health with other signals, and having two separate renderings of the same signal would have been its own form of confusion.

## Role-Based Visibility Rules

Enforced at the service layer (commercial_workflow_service.py), not hidden in React, per this task's own explicit "the backend response itself must be role-safe" instruction:

| Endpoint | Management | PM | Site Supervisor | Client |
|---|---|---|---|---|
| profitability-panel | Full access | Full access | 403 | 403 |
| commercial/health | Full access | Full access | 403 | 403 |
| cash-flow-timeline | Full access | Full access | 403 | 403 |
| billing-collections | Full access | Full access | 403 | Full access (explicitly client-safe per this task's own Section 6) |
| client-safe-bill-summary | Accessible (not restricted) | Accessible (not restricted) | Not gated (project-visibility only) | The intended, dedicated response |

build_client_safe_bill_summary() is a genuinely separate function, not a reshape of the internal panel - it only ever reads contract_value, approved variations, and payment-request/payment amounts and statuses. There is no code path where an internal field (margin, budget, committed cost, health reasons) is computed and then redacted; those values are never read by this function at all.

## Payment Request Workflow

The full state machine (draft -> under_review -> raised -> sent -> partially_paid -> paid, plus under_review -> draft for return-for-revision and -> cancelled for rejection) is unchanged from PX-03 Phase 1 - this phase only added the UI actions that call the existing apiSetPaymentRequestStatus transition endpoint directly, per this task's own explicit "do not recreate the transition logic in frontend code" instruction. PM sees "Submit for Review" on their own draft; Management sees "Approve" and "Return for Revision" specifically when viewRole === 'admin' and status is under_review - a PM cannot approve their own request, matching this task's own explicit rule, enforced by gating the UI action to the admin role specifically rather than the broader canDecide (which also covers PM).

## A Second Real Defect Found This Phase

While wiring the payment-recording UI action, the frontend's own canPay logic was found to allow "Record Payment" for any status except cancelled/draft - including the new under_review state, which should never accept a payment. Tracing this to the backend revealed record_payment() itself had the identical gap (only cancelled was ever blocked), a pre-existing defect that predates this phase's own under_review addition. Fixed at the backend (the authoritative check) and the frontend (so the UI doesn't offer an action that would fail). Fixing the backend broke 2 existing tests that had been unknowingly relying on the loose behavior - both fixed by adding the real, correct state progression, not by weakening the new check.

## Notification Paths

Preserved from Phase 1 (submit -> Commercial Attention for Management; approve -> "Payment Request Approved" for the PM who raised it) and extended with the "Returned for Revision" path this task's own Section 8 names explicitly. Not built this phase, named directly: payment received, partial payment received, and overdue payment notifications. All three are real, valuable gaps - not silently assumed complete because the submit/approve/return loop works.

## Calculation-Display Implementation

The "View Calculation" modal is a single, reusable component (viewCalculation state + one Modal) rendering exactly the format this task's own Section 1 example specifies: formula, real input values, result - sourced directly from each KPI's own calculation object in the API response, never recomputed or hardcoded in the frontend.

## Date-Picker Implementation

No new date input was introduced this phase - the existing Payment Request creation form (from CP-02, unmodified) already uses the DatePicker component for raised_date/due_date, confirmed by inspection before assuming new work was needed here.

## Client-Safe Response Design

A dedicated endpoint and function, not a reshaped internal one - see "Role-Based Visibility Rules" above for the full reasoning.
