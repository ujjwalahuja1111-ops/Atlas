# RC1-HARDENING — Cohesion, Consolidation & Pilot Hardening

Scope honesty, stated first: H1, H2, H3, H4, and H5 are all implemented and verified this pass. Two real bugs were caught and fixed during implementation, not discovered later - both are described in full below because they're as important to this report as the features themselves.

---

## 1. Commercial Consolidation Plan (H1)

Audit confirmed RC-01's own finding: Project Dashboard, Workspace Project Pulse, and Commercial Workspace each independently rendered overlapping commercial tiles.

Plan implemented: Commercial Workspace remains the canonical, full-detail source (unchanged - 10 modal forms, complete tile grids, all real create/edit capability). Workspace's Project Pulse already showed only operational-summary numbers (Cash Flow, Pending Decisions) and required no change. Project Dashboard's own commercial section was reduced from a 9-tile grid to two tiles (Current Contract, Cash Flow Signal) plus a single "Open Commercial Workspace" action - matching this task's own explicit design exactly.

## 2. Legacy Fallback Removal Report (H2)

A more precise finding than RC-01's own characterization. Before removing anything, this pass investigated whether the "legacy commercial field" RC-01 flagged was genuinely dead code. It is not: commercial_reference is an actively-seeded, still-correctly-used lightweight layer specifically for Reference Portfolio demo projects that never received a real Contract, and reasoning_engine.py's own Portfolio Control Center aggregation already correctly distinguishes it from real Commercial Engine data, never fabricating a number it can't back. Deleting this backend layer would have broken Reference Portfolio demos and Portfolio Control Center's own financial rollup - a real regression this task's own "remove dead legacy code paths if they are no longer required" wording explicitly guards against.

The actual, correct fix: projects/[id].tsx no longer silently presents commercial_reference data as if it were equivalent to the real Commercial Engine summary. When only the reference layer is available, the screen now shows an explicit, honest state: "Reference data only - this project has no Contract yet. Open the Commercial Workspace to set one up." - never stale or partial data presented as current, per this task's own rule.

## 3. Memory ↔ Knowledge Graph Integration Design (H3)

Implemented exactly the three named examples, no new storage: "Since Last Visit" changes of kind variation_approved, payment_received, and contract_status_changed/contract_updated are now enriched with causal_context, computed live via KM-01's own get_entity_relationships (a variation approval's originating observation; a payment's originating milestone via a two-hop lookup through its payment request; a contract change's approving variation). Wrapped in try/except so a Knowledge Graph lookup failure never breaks Since Last Visit itself - the same resilience discipline WF-01 established for cross-engine composition. Verified live: a captured observation -> approved variation now correctly surfaces the observation as causal context in the Workspace's own "Since You Were Last Here" card.

A real, non-obvious bug caught during this workstream, not after: the first version's module-level import in reasoning_engine.py caused knowledge_graph_engine.py to be transitively imported earlier in the test suite's own collection order than before - binding its database reference to a real, unconfigured MongoDB client rather than the test's own mock, since Python only imports a module once per process. This only surfaced when the full test suite ran together, never in isolation, and was diagnosed from the actual ServerSelectionTimeoutError traceback, not guessed at. Fixed with a deferred, function-local import - the exact pattern WF-01 already established for this identical class of problem.

## 4. Workspace-First Navigation Recommendation (H4)

Minimum change identified and implemented: once a Project Manager's or Site Supervisor's active project resolves, Home now redirects to that project's own Workspace rather than rendering a second, competing per-project dashboard (the pre-existing MyDaySection/PmCreCards/SupervisorCreCards rendering). Management is deliberately excluded from this redirect - Home genuinely serves them as the cross-project overview this task's own instruction asks it to remain. A user with no resolved project yet (first-ever login, no site created) is unaffected, since the redirect only fires once a real project is active.

## 5. End-to-End Simulation Harness (H5)

backend/scripts/system_simulation.py - all 15 named steps, run via python -m scripts.system_simulation, raising InvariantFailure immediately if any named invariant breaks, per this task's own explicit rule. Confirmed deterministic across 3 repeated runs.

A real test-design bug caught during construction: the first version called the Since Last Visit baseline after ten steps of commercial activity had already occurred, meaning that first call silently consumed every real event as "already seen" - making the later assertion about what changed structurally untestable, not just occasionally flaky. Fixed by establishing the baseline immediately after project creation, before any commercial activity.

## 6. System Invariant Checklist

The 15 invariants the harness enforces, each tied to a real product guarantee:

1. New project defaults to planning stage (PL-01).
2. New contract starts in draft status.
3. Budget's current_budget equals original_budget on creation.
4. Milestone's contract_value derives correctly from planned_percent.
5. A captured event with one photo produces exactly one raw asset.
6. A variation retains the linked_photo_ids it was created with.
7. Approving a variation automatically increases the contract's current_contract_value by the proposed cost (CO-01's own finding, still holding).
8. Milestone transitions correctly to achieved.
9. A payment request correctly references the milestone it was raised against.
10. A payment correctly references the payment request it settles.
11. The Timeline includes every real event kind that occurred.
12. Since Last Visit correctly distinguishes first vs. subsequent visits, never fabricating a summary.
13. Knowledge Graph relationships correctly show both the causing Observation and the modified Contract for a Variation; Impact Trace correctly reaches both.
14. Cash flow signal is one of three known states; outstanding correctly reaches zero after full payment; Explain Health returns a real numeric score.
15. Decision Trace for a Payment correctly shows it settles the Payment Request that generated it.

## 7. Regression Results

- npx tsc --noEmit: clean throughout.
- npm run lint: 25 pre-existing problems, unchanged - verified directly after every workstream, not assumed.
- Backend regression suite: 162/162 passing, confirmed stable across multiple runs (including the run that surfaced H3's real import-order bug, and the clean runs after its fix).
- Simulation harness: 15/15 steps passing, deterministic across 3 repeated runs.
- Two genuine bugs were caught and fixed during this pass (H3's import-order issue, H5's test-baseline-timing issue) - both described in full above, not glossed over as routine debugging.

## 8. Pilot Readiness Delta (Before vs. After Hardening)

| Area | Before | After |
|---|---|---|
| Commercial data on Project Dashboard | 9-tile grid, silently interchangeable with a different, lighter data source | 2-tile snapshot, explicit navigation action, honest "reference data only" state when applicable |
| Legacy fallback behavior | Silent, presented as equivalent to real data | Explicit, honest, distinct messaging |
| Since Last Visit | Showed what changed | Now also shows why, via causal context, for the three kinds this task named |
| PM/Supervisor daily entry point | Home rendered a second, competing per-project dashboard | Home redirects straight to Workspace; Management's own cross-project view is preserved |
| Regression confidence | Manual, ad-hoc verification scripts per package, discarded after use | A permanent, deterministic, 15-step simulation harness any future package can re-run |

PILOT-01's own Conditional Go recommendation is unaffected and unchanged by this pass - GST/retention remains the one real, named blocker requiring pre-pilot communication. This hardening pass improves cohesion and operational trust; it does not change what Atlas can or cannot calculate.

## 9. Merge Readiness

Ready to merge. Every workstream reuses existing infrastructure exclusively - no new business feature, no new AI, no Procurement/Vendors/BOQ, per this task's own explicit rules. Two real bugs were found and fixed during implementation, both fully described rather than silently corrected. Full regression suite and the new simulation harness both pass cleanly and deterministically.
