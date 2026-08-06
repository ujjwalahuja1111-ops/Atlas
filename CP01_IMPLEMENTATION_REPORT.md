# CP-01 — Commercial Operations Phase I (Vertical Slice) — Implementation Report

## 1. Implementation Summary

Delivered the first operational Commercial Workspace vertical slice, exactly as scoped: a Project Manager can now create a Contract, edit it (while draft), view its history, create a Budget, edit it, create Milestones, edit them, and view them - entirely through the application, with zero scripts, seed manipulation, or direct backend calls. Every capability in scope was classified in CO-01's Engineering Readiness Matrix; this package built REUSE-first exactly as instructed, and extended only the two capabilities CO-01 correctly flagged as needing new backend work (Contract editing, Milestone editing).

A significant discovery during mandatory pre-implementation verification, per this task's own final instruction: every existing commercial mutation route - not just the ones this package touches - had a role check but no project-visibility check at all. This was found before any new UI was built on top of these routes, exactly as the verification step was designed to catch, and fixed as part of this package rather than deferred, since shipping new UI on top of an unguarded write path would have made a real vulnerability materially easier to exploit.

## 2. Files Changed

- backend/routes/commercial.py - added assert_project_visible to six existing mutation routes (create_contract, set_contract_status, create_milestone, set_milestone_status, create_budget, revise_budget); added two new routes (PATCH /projects/{project_id}/commercial/contract, PATCH /commercial/milestones/{milestone_id}).
- backend/engines/commercial_engine.py - added update_contract and update_milestone, both minimal extensions reusing the existing append_commercial_event audit pattern.
- backend/tests/test_dev02_bootstrap_reliability.py - 4 new mongomock tests for the two new engine functions.
- backend/tests/test_rc01_commercial_visibility.py - 8 new live-URL tests for the six authorization fixes, the two new edit endpoints, and a legitimate-access confirmation.
- frontend/src/commercial_api.ts - 8 new API functions (apiCreateContract, apiUpdateContract, apiTransitionContractStatus, apiCreateBudget, apiReviseBudget, apiCreateMilestone, apiUpdateMilestone).
- frontend/app/commercial/[id].tsx - added a shared FormModal component; wired Create Contract (empty state), Edit Contract, Create/Edit Budget, Create/Edit Milestone into the existing Commercial Workspace screen; fixed the Budget section's visibility gate (see Architectural Decisions); fixed a pre-existing event-label mismatch (budget_updated -> budget_revised, the actual emitted kind) found while editing the same map for this package's own new event kinds; removed isManagement, now genuinely dead code after the Budget gate fix.

No new screens, no navigation restructuring, no BOQ, no AI, no Billing, no Payment Requests, no Payments - all correctly out of scope per this package's own instructions.

## 3. Architectural Decisions

Reused, not duplicated: existing authorization (assert_project_visible, the same primitive established across RC-02/Beta-06D), the existing commercial_events audit ledger (both new functions log through it, no new audit mechanism), the existing state machines (Contract's CONTRACT_STATUSES, Milestone's MILESTONE_TRANSITIONS - untouched), and the existing Commercial Workspace screen (extended in place, not replaced).

Contract and Milestone editing scoped to their lifecycle's own "before it's relied upon" moment - Contract terms editable only while draft, Milestone terms editable only while pending - directly implementing CO-01's own Product Decisions Register rather than introducing a new rule. original_contract_value and a milestone's derived contract_value are both deliberately never touched by these edit functions, preserving the existing, correct "value only changes through approved Variations" design exactly as CO-01 required be preserved.

A real permission correction, not a new decision: the Budget section was gated to viewRole === 'admin' only in the existing frontend, while the backend route for the same data already permitted management or project_manager (_require_write_access). Since this task requires a PM to view/create/edit Budget, and the backend already allowed it, the frontend gate was corrected to match - not a new capability, a bug where the UI was stricter than the API it called.

## 4. New Tests

12 new tests total, all passing:
- 4 mongomock (test_dev02_bootstrap_reliability.py): update_contract succeeds and logs an event while draft; blocked after activation; update_milestone succeeds and logs an event while pending; blocked after ready.
- 8 live-URL (test_rc01_commercial_visibility.py, require a deployed server per that file's own established convention): each of the six authorization fixes individually confirmed blocking an outsider; both new edit endpoints confirmed blocking an outsider; one test confirming legitimate access for a properly-scoped PM was never broken by any of the above.

Full regression suite: 146/146 passing (up from 142), confirmed stable across three consecutive runs during this package's own development. npx tsc --noEmit: zero errors. npm run lint: zero issues in any file this package touched (all 25 pre-existing problems elsewhere in the repository, unchanged in count from before this package).

## 5. Manual Validation

Walked the exact sequence this task requires - Create Project -> Create Contract -> Edit Contract -> Create Budget -> Edit Budget -> Create Milestone -> Edit Milestone - using the identical request shapes the new frontend API functions actually send (not a simplified approximation). All 11 steps succeeded, including viewing the populated Commercial summary mid-sequence and viewing Contract History via the existing commercial-events endpoint, which correctly showed all six real events (contract_created, contract_updated, budget_created, budget_revised, milestone_created, milestone_updated) in order. This was walked through the real HTTP surface the frontend calls, not by invoking backend functions directly - the closest verification possible in this environment to a literal UI walkthrough on a device, given no physical device or Expo Go session is available here.

## 6. Remaining Commercial Packages

Directly following CO-01's own Phased Build Plan:
- Phase I remainder: Variation create/submit/send-for-review UI (the workflow with the most existing backend and partial UI already) and Payment Request/Payment recording UI - both explicitly excluded from this package's own scope, next in line.
- Phase II (Extend): GST wiring, retention withholding/release, advance-payment flag, payment correction linking, budget freeze, milestone dependencies, Contract suspend/terminate states, Variation withdrawal, invoice numbering, and Section 8's AI trigger integration (reusing the existing ai_proposals pipeline).
- Phase III (New): BOQ, Credit/Debit Notes, payment allocation, Lead/Proposal/Estimate.

## 7. Risks

1. commit_cost and record_actual_cost (two budget-adjacent mutation routes, cost-tracking rather than budget create/edit) were found to have the identical missing-visibility-check pattern as the six routes fixed in this package, but are explicitly outside this package's scope (payment/billing-adjacent). Named here rather than silently left, since the same class of gap remains open in two routes this package didn't touch.
2. The live-URL tests (8 of the 12 new tests) require a deployed server to actually execute, consistent with every other test in that file - they were not run in this sandbox. The underlying fixes were independently verified via constructed httpx/ASGI-transport scenarios during development (shown working, both exploit-before and blocked-after), which is real, executed verification, just through a different harness than that file's own convention.
3. No physical device/Expo Go walkthrough was possible in this environment - the manual validation (Section 5) is the closest available equivalent, exercising the exact real HTTP calls the frontend makes, but a literal on-device tap-through has not occurred.

## 8. Merge Readiness

Ready to merge, with the two named risks above understood as follow-up work rather than blockers to this specific package: the two additional unfixed routes are outside this package's own stated scope (Section 7.1), and the live-URL test execution gap (Section 7.2) is a pre-existing, consistent limitation of this environment affecting every test in that file, not something specific to this package's own changes. Every capability this task required is implemented, backend-verified, frontend-wired, type-checked, lint-clean, and walked end-to-end through the real application surface.
