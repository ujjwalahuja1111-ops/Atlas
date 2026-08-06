# CP-02 — Commercial Lifecycle Completion — Implementation Report

This package must increase Atlas's ability to run a real construction company, not merely increase Atlas's feature count. Every capability below is measured against that standard: does a Project Manager or Management team member now do this through the product, without touching Mongo or a seed script.

## Commercial Capability Matrix — REUSE / EXTEND / NEW

Verified fresh against main, not trusted from CO-01's earlier documentation, per this task's own mandatory-audit instruction.

| Capability | Classification | Basis |
|---|---|---|
| Create Variation | REUSE (backend) + NEW (UI) | create_variation existed and worked; zero frontend UI existed before this package |
| Edit Draft Variation | Confirmed absent | No edit_variation function exists anywhere in the backend - genuinely missing, not implemented in this package (out of the explicit walkthrough scope) |
| Withdraw Draft Variation | Confirmed absent | VARIATION_TRANSITIONS has no withdrawal state - genuinely missing, not implemented in this package |
| Submit Variation | REUSE (backend) + NEW (UI) | submit_variation existed; no UI action existed before this package |
| Send for Client Review | REUSE (backend) + NEW (UI) | send_variation_to_client_review existed; no UI action existed before this package |
| Approve / Reject Variation | REUSE | decide_variation and its UI already existed (client-facing, from earlier work) - unchanged |
| Variation History / Timeline | REUSE | Already surfaced via the existing commercial_events ledger and Commercial History modal (UX-02) |
| Contract Revision Surfacing | REUSE (backend) + EXTEND (UI) | Original/Current value tiles already existed (CP-01); added an explicit note stating the change is due to approved variations |
| Payment Request: Create | REUSE (backend) + NEW (UI) | create_payment_request existed; no UI action existed before this package |
| Payment Request: Status/Track | REUSE (backend) + NEW (UI) | transition_payment_request_status existed; wired via the new Record Payment flow |
| Client Payments: Record | REUSE (backend) + NEW (UI) | record_payment existed; no UI action existed before this package |
| Client Payments: Partial | REUSE | record_payment already supports arbitrary amounts against a request - no new logic needed |
| Outstanding Balance / Cash Received | REUSE | outstanding_payments() already correct and already displayed (Cash Flow section, CP-01/UX-02) |
| Budget Consumption Display | REUSE (backend), critical bug found and fixed | The backend computation was correct; the /commercial/summary route was silently stripping budget for any non-management role, including project_manager - see below |
| Commercial Timeline | REUSE | Already complete (UX-02's View History modal over the existing commercial_events ledger) |
| Commercial Dashboard (in-project) | REUSE | Already substantially complete via the existing Cash Flow, Contract, Budget, Milestones sections composed together - no new data source needed |
| Commercial Health | NEW (frontend only) | Simple rule-based banner (green/yellow) reusing only cash_flow_signal (already backend-computed) and budget variance - no new backend computation, no AI |

## Security Findings — Found and Fixed During the Mandatory Audit

Seven mutation routes had zero project-visibility enforcement, identical in nature to what CP-01 found and fixed for Contract/Budget/Milestone, but never applied to Variations and Payment Requests/Payments since those were outside CP-01's own scope: create_variation, submit_variation, send_variation_to_client_review, decide_variation, create_payment_request, set_payment_request_status, record_payment. Each had a role check but no check that the calling user could actually see the project being mutated. Demonstrated live with a real exploit attempt (all seven blocked for an outsider PM) before fixing, and re-verified after. Confirmed legitimate access was never broken.

A separate, critical bug was found while running the required walkthrough, not by inspection alone: the /commercial/summary route - the actual data source the Commercial Workspace screen loads - stripped budget from its response for any role other than management, silently contradicting the direct /commercial/budget route's own _require_write_access rule (management OR project_manager), the exact rule CP-01 built its Budget UI around. The practical effect: a Project Manager opening the Commercial Workspace always saw "No budget set for this project yet," even when a real budget existed, because the screen's actual data source hid it from them. This directly blocked this task's own success criteria - a PM cannot track budget consumption through a screen that always reports no budget exists. Fixed to match the established, correct rule; re-verified that a client still never sees budget (confirming the fix didn't over-widen access).

## Phase Deliverables

1. Variation Management - Create, Submit, Send for Client Review now have real UI, completing the full state machine (draft -> submitted -> client_review -> approved/rejected -> implemented) with an action at every PM-controllable step. Approve/Reject (client-facing) was already complete and is unchanged. Edit Draft and Withdraw Draft are confirmed genuinely absent from the backend - not implemented in this package, named explicitly as a remaining gap rather than silently skipped.

2. Contract Revision - The existing Original/Current Contract Value tiles (CP-01) already made the change visible; this package adds an explicit note ("Contract value changed by Rs X through approved variations") whenever the two differ, directly answering this task's "surface this clearly" instruction without introducing a second contract concept or a separate revision screen.

3. Payment Requests - Create now has real UI, reachable directly from an achieved milestone via a "Raise Payment Request" inline action (pre-filled with the milestone's own contract value). Status tracking is visible via the existing status pill; explicit status transitions beyond payment recording (e.g., manual cancellation) were not built as a separate UI in this pass, since the walkthrough's own sequence doesn't require it.

4. Client Payments - Record Payment now has real UI, reachable directly from any payment request with a remaining balance. Partial payment is inherently supported (the backend already accepts any amount). No accounting module, no invoice generation - commercial tracking only, per this task's own constraint.

5. Budget Consumption - Already fully displayed (Budget/Forecast/Actual/Variance/Remaining, CP-01) once the visibility bug above is fixed. No new backend work needed.

6. Commercial Timeline - Already complete (UX-02). No changes needed in this package.

7. Commercial Dashboard - Already substantially complete via the existing Cash Flow, Contract, Budget, and Milestones sections viewed together within the project. No new analytics, no new data source - per this task's own explicit constraint.

8. Commercial Health - New: a simple two-state banner (green Healthy / yellow Attention Required) at the top of the Commercial Workspace, computed entirely from cash_flow_signal (already correct, backend-computed) and budget variance. No AI, no new backend logic - a single frontend rule.

## Walkthrough — Every Step Verified Through the Real API

New Project -> Contract -> Budget -> Milestone -> Variation (create -> submit -> send for review) -> Approval (client decides) -> Payment Request (raised from the achieved milestone) -> Payment (recorded against it) -> Commercial Dashboard -> Commercial Timeline. All 10 steps executed successfully through the real HTTP surface the frontend calls - confirmed the contract value correctly updated from Rs 50,00,000 to Rs 52,00,000 after variation approval, budget correctly visible at Rs 40,00,000, outstanding correctly at Rs 0 after payment, cash flow signal correctly "healthy," and the Commercial Timeline correctly showing all 12 real events in chronological order. No Mongo edits, no seed scripts, no direct backend calls outside the real API routes the frontend itself uses.

## Screenshots

Not produced, for the same reason stated in UX-02: no physical device, simulator, or Expo Go session exists in this environment. npx tsc --noEmit and the live walkthrough above are the verification actually available here.

## Regression Results

- npx tsc --noEmit: clean throughout, checked after every meaningful change.
- npm run lint: 25 pre-existing problems, identical count to before this package.
- Backend regression suite: 146/146 passing, stable across multiple runs during development.
- New tests: live-URL fixtures covering all 7 authorization fixes (individually confirmed blocking an outsider) plus a legitimate-access confirmation, and 2 more confirming the budget-visibility fix (PM now sees budget; client still correctly excluded) - added to test_rc01_commercial_visibility.py, following its established convention; these require a deployed server to execute directly, consistent with every other test in that file, and were independently verified via constructed httpx/ASGI scenarios during development before being written as permanent tests.
- No existing test was weakened, removed, or had its assertions loosened.

## Remaining Commercial Gaps

Named explicitly rather than left implicit:
- Edit Draft / Withdraw Draft Variation - confirmed absent from the backend; a genuine future extension, not implemented here.
- Payment Request explicit cancellation UI - the backend transition exists; no dedicated UI action was built for it in this pass, since the required walkthrough doesn't exercise it.
- commit_cost/record_actual_cost - flagged as a risk in CP-01's own report for having the same missing-visibility pattern; still not fixed, since they remain outside every package's stated scope so far (cost-tracking, not commercial lifecycle operations this task names).

## Merge Readiness

Ready to merge. Every capability this task named is now operable through the application, verified end-to-end via a real walkthrough matching the task's own required sequence, with two genuine security/correctness defects found and fixed before being built on top of - one a re-application of CP-01's own established pattern to routes it hadn't reached yet, one a previously-undiscovered budget-visibility bug that would have made this package's own Budget deliverable non-functional for its primary user. No backend redesign, no schema changes, no new architecture - every change is either a route-level authorization fix, a new but minimal UI wired to an already-correct backend function, or a small frontend-only computation reusing existing data.
