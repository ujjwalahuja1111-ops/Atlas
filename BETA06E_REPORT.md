# Beta-06E — Reference Portfolio & Multi-Role Operational Validation Report

Per this sprint's own mandatory requirement, this report begins with the audit classification table.

---

## Operational Validation Matrix

| Area Validated | Status | Evidence |
|---|---|---|
| Full item lifecycle via real API calls (create -> assign -> acknowledge -> in_progress -> fulfilled -> verified -> closed), multi-role (PM creates/assigns/verifies/closes, Supervisor acknowledges/works/fulfills) | VERIFIED (state machine and roles), BUG found and fixed (Daily Review visibility) | Every transition succeeded correctly with the right role at each step, and full 7-event history was recorded correctly. But the completed item did not appear in Daily Review's own "finished today" section despite finishing seconds earlier - see full account below. |
| Health score consistency: Portfolio Control Center vs. Explain Health | VERIFIED | Checked directly across all 6 seeded projects (not sampled) - score and status match exactly in every case. |
| Commercial consistency: Commercial Summary vs. Portfolio Financials vs. Commercial Intelligence vs. Client Investment | VERIFIED | Checked the full four-way chain for RP-002 (the project with real variance/cash-flow signal, a more meaningful test than RP-001's now-healthy state) - budget, variance, cash-flow signal, contract value, and outstanding amount all matched exactly across all four views. |
| Daily Review vs. Site Progress scope consistency | VERIFIED | Daily Review's portfolio-wide count and Site Progress's single-project count differ in raw number (366 vs. 358) but the underlying sets, once correctly scoped to the same project, are identical - confirmed this is a scope difference (all-projects vs. one-project), not a data discrepancy. |
| Reference Portfolio quality (#8) | NOT SYSTEMATICALLY EVALUATED this pass | Given time constraints, effort concentrated on functional validation (does the lifecycle actually work end-to-end) over a qualitative review of naming/realism. Named as unaudited rather than assumed adequate. |
| Timeline accuracy (#7 - no missing/duplicate history, correct order) | NOT SYSTEMATICALLY EVALUATED this pass | The completed test item's own 7-event operational history was confirmed complete and correctly ordered as a side effect of the lifecycle simulation, but a dedicated Timeline-Engine-level audit (across Reality, Commercial, and Operational events together) was not performed. |
| Multi-role validation beyond the one lifecycle exercised (Site Engineer, Client roles specifically) | NOT SYSTEMATICALLY EVALUATED this pass | PM and Supervisor were exercised directly through a real lifecycle; Site Engineer and Client were not independently walked through their own primary workflows this pass. |
| Cross-Project Intelligence, Executive Timeline, Portfolio Search consistency with the rest of the executive suite | NOT RE-VERIFIED this pass | Verified in Beta-05 final's own development; not independently re-checked here. |

---

## The Bug Found — Full Account

Simulating one complete operational day, as this sprint's own section 9 asks for, rather than testing pieces of the lifecycle in isolation: a Project Manager created a real operational item via the actual POST /operational-items endpoint, assigned it to a Site Supervisor, and the Supervisor walked it through acknowledged -> in_progress -> fulfilled via the real transition endpoint, before the PM verified and closed it - all through genuine API calls, not synthetic document inserts. Every step succeeded correctly, and the item's own history correctly recorded all 7 events (created, assigned, acknowledged, started, fulfilled, verified, closed) in order.

But when the PM then checked Daily Review - the screen this sprint's own end-of-day scenario specifically names - the item that had just finished did not appear in "finished today."

Root cause, found by reading the actual write path rather than guessing: operational_items documents never carry an updated_at field at all. Every write to an item's status goes through transition_status(), which sets last_updated_at - a different field name. Daily Review's own query for "resolved today" filtered on updated_at, a field that has never existed on this collection. This means Daily Review's operational-items section has returned an empty result for every single item, on every project, since Daily Review was built - not a subtle edge case, but a query that could never have matched anything, in a screen this platform's own prior sprints (Beta-03) built specifically to answer "what got done today."

Why no prior sprint caught this: no existing test asserted on this specific field. Prior verification of Daily Review (in Beta-03's own continuation) checked that the shape of the response was correct and that workflow activities appeared correctly in finished_today.activities - which uses workflow_activities.updated_at, a field that genuinely does exist on that collection, so that half of the same section worked correctly the whole time and likely masked the operational-items half being silently broken.

Fixed by correcting the query (and the display sort key, which had the identical bug) to use last_updated_at, the field that is actually written. Verified directly: re-ran the exact same real lifecycle simulation after the fix, and the item now correctly appears in finished_today, with the section's total count changing from what would have always been 0 to a real, populated 312 for the seeded ACDP portfolio.

---

## Cross-System Consistency Report

The chains checked this pass - health across Portfolio Control Center and Explain Health (all 6 projects), and the full commercial chain across four separate views for RP-002 - held together perfectly. This is meaningful evidence given how many separate sprints built these views independently (Beta-01 through Beta-05): the underlying discipline of "compose existing data, never recalculate" that this engagement has maintained throughout appears to be genuinely paying off in the one place - internal consistency - where duplicated logic would most likely have quietly drifted apart. The one real bug found this pass was not a consistency failure between two views computing the same thing differently; it was a single query using the wrong field name, a narrower and more mechanical class of bug.

---

## Regression Testing

The fix is covered by a permanent test that reproduces the original discovery method directly - walking a real item through create_item and transition_status (the actual functions the API calls) rather than inserting a synthetic document with the "correct" fields already set, which would not have caught this bug in the first place, since the bug was specifically about what the real write path does and doesn't set.

A minor process note worth recording honestly: while writing this test, an editing error introduced an escaped-quote syntax error into the test file. It was caught immediately by the routine syntax check that precedes every test run in this engagement's own established practice, not by a later failure - fixed before the test was ever executed.

---

## Testing

- 1 new regression test (130 total in the established pure-unit + mongomock baseline, up from 129, passing).
- Full regression suite re-run clean after the fix: no existing test broke, confirming this was a genuinely isolated, previously-uncovered gap rather than a change that risked other behavior.
- The fix verified through the same real, multi-step API simulation that discovered it - not a unit-level check in isolation.

---

## Files Changed

- backend/engines/operations_engine.py - daily_review()'s resolved_items_today query and its display sort key corrected to use last_updated_at, the field actually written by transition_status.
- backend/tests/test_dev02_bootstrap_reliability.py - 1 new regression test.

---

## Remaining Risks — Named Explicitly

1. Reference Portfolio qualitative review (#8 - naming realism, narrative usefulness) was not performed this pass.
2. A dedicated Timeline-Engine-level audit across Reality, Commercial, and Operational events together, checking specifically for missing or duplicate history at scale, was not performed - only confirmed correct for the one item exercised in this pass's own simulation.
3. Site Engineer's and Client's own primary daily workflows were not independently walked through this pass; only PM and Supervisor were exercised via a real lifecycle.
4. Given that this exact class of bug (a query silently never matching due to a field-name mismatch) was found once, in one function, it is reasonable to ask whether similar mismatches exist elsewhere in this codebase's many updated_at/last_updated_at/captured_at-style timestamp queries - this was not systematically swept for, and is named as the most likely place a similar issue could still exist.

---

## Beta-06E Assessment

This sprint is not reporting Complete. Per its own Definition of Done ("do not report Complete if any major operational workflow remains unvalidated") - Reference Portfolio quality, a dedicated Timeline audit, and Site Engineer/Client-specific workflows were not reached this pass.

What was accomplished has real weight: a genuine, previously-undetected functional bug was found not by auditing code but by doing exactly what this sprint's own philosophy asks - walking a complete, realistic operational day through the real API as an actual user would, rather than testing components in isolation. The bug had existed, unnoticed, since the feature it broke was first built, and would have continued silently returning an empty "finished today" list to every Project Manager checking Daily Review, indefinitely, without this kind of end-to-end exercise. The cross-system consistency checks performed came back clean, which is itself informative - it suggests the platform's disciplined reuse of existing calculations across many independently-built views has held up, and that the risk surface for this kind of platform is less in views disagreeing with each other and more in individual write paths quietly not doing what a downstream read assumes they did.
