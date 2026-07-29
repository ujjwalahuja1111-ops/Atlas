# Beta-02 — Commercial Workspace Completion Report

Scope discipline, per this sprint's own principle: no new engines, no architecture changes. Every number in the new Commercial Workspace comes directly from commercial/summary and commercial/events - the frontend composes, it does not calculate.

---

## Critical Finding: a real, undetected regression from Beta-01, found and fixed by this sprint's own cross-validation testing

While writing the cross-validation tests this sprint explicitly requires (Client Investment vs. Contract, Payment Journey vs. Payment Requests, Variation Centre vs. Variations, Portfolio Financials vs. Summary), one failed in a way that could not be explained by a wrong test assumption: client_variation_centre returned None for RP-001 even though RP-001 was independently confirmed, in the same debugging session, to have a real contract and 2 real variations.

Root cause: client_variation_centre's own function body was missing its closing logic entirely - the views = [_view(v) for v in variations] line and its return {...} statement were absent, so the function fell through to an implicit return None regardless of whether variations existed. This was introduced accidentally in Beta-01, when client_recent_activity was inserted directly after this function - the insertion landed inside client_variation_centre's own body, silently deleting its tail. Beta-01's own verification never caught this because it tested variation creation and decision through the write-side routes directly, never asserting on this specific read function's return shape against real, non-empty data.

Real-world impact: the Client Dashboard's "VARIATION APPROVALS" card (GET /projects/{id}/client-variations, built in CX-01) has been broken since Beta-01 merged - showing an empty state for every project with real variations, silently hiding pending approvals from clients. Confirmed and fixed; the same live route now correctly returns pending and historical variations, verified directly against the exact HTTP endpoint the mobile app calls, not just the underlying function.

This is reported first and most prominently because it is the most consequential finding of this sprint, more significant than any of the completion work below - a regression that shipped silently and remained undetected for one full sprint until a different sprint's own testing requirement happened to surface it.

---

## Commercial Workspace — Completed

A new screen (app/commercial/[id].tsx) completes the existing flat-tile Commercial section into a real financial command centre, reached via a new "Full Workspace" link on the Project Dashboard's existing Commercial section (the summary tiles remain as a quick overview; the full workspace is one tap away - no dead-end, no duplicated screen).

- Contract - original/current value, approved/pending variations, contract date/duration/status.
- Budget - management-only (see RBAC fix below), all six required figures, read directly from commercial/summary's own budget object with zero calculation on screen.
- Cash Flow - status badge, raised/received/outstanding, and the next upcoming payment (see the deduplication below).
- Milestones - sorted by sequence, each showing percentage, contract value, due date, and its linked Payment Request's own status where one exists.
- Payment Requests - filterable (All/Unpaid/Paid/Overdue), each showing amount, remaining balance (computed as a simple subtraction of already-fetched values, not a duplicate financial calculation), due date, and linked milestone.
- Payments - full history, sorted newest-first, amount/date/method/reference/status.
- Variations - filterable (All/Pending/Approved/Rejected/Implemented), each showing before/after cost, cost and schedule impact (both already computed by commercial_engine.calculate_variation_impact, never recomputed here), and approval history. Management/PM can approve or decline directly from the workspace, reusing the exact same decide endpoint the Client dashboard already uses - no new write path.
- Commercial Timeline - all commercial events, newest-first, human-readable labels per event kind.

All sections support collapse/expand, pull-to-refresh, a retry-on-error banner, and an honest empty state when a project has no commercial data yet (never a fabricated number).

---

## A genuine deduplication, not a new duplication

The Cash Flow section's "next payment due" figure previously existed only inside client_investment_summary's own inline calculation. Rather than reimplementing it a second time for the new workspace, it was extracted into commercial_engine.upcoming_payment() - a shared, pure function - and get_project_commercial_summary now includes it directly. client_investment_summary was simplified to read this field instead of recomputing it. Verified the two are now identical by direct comparison, not merely similar (test_commercial_summary_upcoming_payment_reused_not_duplicated).

---

## RBAC — one real gap found and fixed

Verifying "Budget: management only" against the actual API (not just the new screen's own display gating) found that GET /commercial/summary returned the full budget object to any role with project visibility - management, project manager, and supervisor alike. The new workspace already hid the Budget section from non-management roles in the UI, but the underlying data was never actually restricted - gating only in the frontend is not real RBAC, and this sprint's own principle ("never calculate in the frontend") implies the corollary that the backend must not over-share either.

Fixed at the route level (routes/commercial.py), not the engine - commercial_engine.get_project_commercial_summary stays role-agnostic and unchanged, correct for its other internal callers (client_investment_summary never reads budget from it at all, so was never affected). Verified directly across all four roles: management sees full budget data; PM, supervisor, and client all correctly receive budget: null, with every other field (contract, milestones, variations, cash flow) still intact for PM's own "operational commercial visibility."

---

## Cross-Validation — the sprint's own explicit requirement, verified directly

All four checks the brief names, run against RP-001's own real, migrated Commercial Foundation Engine data:

- Client Investment's contract value, paid, outstanding, and variation total all match Commercial Contract's own figures exactly.
- Payment Journey's milestone set and each step's payment status match Payment Requests exactly.
- Variation Centre's variation set, cost, and status match Commercial Variations exactly (only passing after the critical fix above).
- Portfolio Financials' budget, forecast, variance, and cash-flow signal match Commercial Summary exactly.

---

## UX

Loading (spinner on initial load), empty (honest "no commercial data yet" state, not a fabricated zero), error (retry banner, not a silent failure), refresh (pull-to-refresh reloads both summary and events), filtering (Payment Requests and Variations both filterable by status), sorting (Milestones by sequence, Payments and Timeline newest-first) are all present. Search and pagination were not added - payment/variation/milestone counts on any real project observed during this sprint (RP-001: 6 milestones, 2 PRs; RP-002: 5 milestones, 5 PRs) do not yet warrant either, and adding them now would be speculative rather than responsive to an observed need.

---

## Not Reached This Sprint

- Dedicated detail screens for individual milestones/payment requests/payments (the brief asks for "opening milestone details" / "detail screen" for Payment Requests) - built as rich inline rows within the workspace instead, given time constraints, not as separate navigable screens. A real, named gap if fuller per-entity detail (e.g., a Payment Request's own edit history) is needed later.
- Contract detail navigation ("Allow navigation to contract details") - the Contract section is inline in the workspace; no separate Contract screen was built.
- Search across any of the workspace's lists.
- A dedicated commercial regression/RBAC/UI test suite beyond the specific tests added this sprint (cross-validation, budget RBAC) - broader UI-level (component rendering) tests were not attempted; verification here is API- and data-level, matching this engagement's established testing approach, not React component testing.

---

## Testing

- backend/tests/test_dev02_bootstrap_reliability.py - 5 new cross-validation tests, all passing (24 total in this file).
- backend/tests/test_rc01_commercial_visibility.py - 5 new RBAC tests for the budget-stripping fix.
- Established pure-unit + mongomock baseline: 92 passed, 0 failed (up from 87).
- npx tsc --noEmit: zero errors, project-wide, including the new ~500-line workspace screen.
- End-to-end verification against both Reference Portfolio projects through the real bootstrap pipeline: all 13 bootstrap verification checks pass, both projects' commercial data (milestones, payment requests, payments, variations, upcoming payment) renders correctly.

---

## Files Changed

- backend/engines/commercial_engine.py - new upcoming_payment() helper, wired into get_project_commercial_summary.
- backend/engines/reasoning_engine.py - client_investment_summary simplified to reuse the shared helper; critical fix to client_variation_centre, restoring its missing return logic.
- backend/routes/commercial.py - budget stripped from commercial/summary for non-management roles.
- backend/tests/test_dev02_bootstrap_reliability.py - 5 new cross-validation tests.
- backend/tests/test_rc01_commercial_visibility.py - 5 new RBAC tests.
- frontend/src/commercial_api.ts - upcoming_payment added to CommercialSummary; new CommercialEvent type and apiListCommercialEvents.
- frontend/app/projects/[id].tsx - navigation link to the new workspace.
- New: frontend/app/commercial/[id].tsx - the Commercial Workspace screen.

---

## Beta Readiness Assessment

The Commercial Workspace itself is genuinely complete for its core purpose: a PM can review the full financial lifecycle of a project - contract, cash flow, milestones, payment requests, payments, variations with direct approve/decline, and a full commercial history - without leaving Atlas, matching this sprint's own success criteria. Management gets the additional Budget visibility the brief specifies, correctly restricted from every other role now, not just hidden in one screen.

The more important outcome of this sprint is not the workspace itself but what building it exposed: a real, silent regression in already-shipped, client-facing functionality, caught only because this sprint's own cross-validation requirement forced a direct comparison between two views that should agree and, for one sprint, quietly didn't. That is the strongest evidence this sprint can offer that the cross-validation discipline the brief asks for has genuine value, not just checkbox compliance - and a reminder that "verified end-to-end" in a prior sprint's own report should be read as "verified for the scenarios exercised," not as an absolute guarantee.

Recommendation: Stable with Known Issues, not unqualified "Ready" - the Beta-01 regression's mere existence, however promptly caught and fixed here, means the honest posture is continued vigilance rather than confidence that no other silent gaps remain from prior sprints. The named gaps above (detail screens, search) are minor by comparison and do not block real use of the Commercial Workspace as built.
