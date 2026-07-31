# Beta-06F — Timeline & Construction History Integrity Validation Report

Per this sprint's own mandatory requirement, this report begins with the Timeline Validation Matrix.

---

## Timeline Validation Matrix

| Event Source | Status | Evidence |
|---|---|---|
| Reality Capture (photos, voice, text) in timeline_engine.for_site | VERIFIED | Confirmed present and correctly formed via direct inspection and real ACDP data (784 real captures render correctly). |
| Commercial Events in timeline_engine.for_project_commercial | VERIFIED | Confirmed present; this source has been separately verified across Beta-02, Beta-05, and Beta-06 without new findings this pass. |
| Operational Item history (creation, assignment, status transitions, comments) in Executive Timeline | BLOCKER, found and fixed this pass | Demonstrated: a real item creation, transition, and comment produced zero Executive Timeline events before the fix, despite the same data being retrievable directly via timeline_engine.for_site(include_ops=True). See full account below. |
| Operational Item history in the item's own detail view (GET /operational-items/{id} -> history) | VERIFIED | Confirmed complete and correctly ordered in Beta-06E's own end-to-end lifecycle simulation (7/7 events present, in order) - this was never the broken part. |
| Client Approvals | VERIFIED, via the Operational Items fix | Client approvals are operational items with category=client_approval - the same fix that restored operational item history to Executive Timeline restores this category too; no separate mechanism exists. |
| Workflow Activity progression (as its own history, distinct from Operational Items) | RISK - not examined this pass | Workflow activities have their own updated_at/status fields but were not traced through Executive Timeline specifically this pass; named rather than assumed included. Workflow activities are NOT part of for_site's include_ops mechanism (that path only covers operational_events, a separate collection from workflow_activities) - this is a real, distinct gap from the one fixed here, and is the most likely remaining place this same class of bug exists. |
| Executive Timeline vs. project-level (per-site) history | VERIFIED, after the fix | Once include_ops=True was wired in, Executive Timeline's own event count for a real, freshly-simulated project matched exactly what for_site(include_ops=True) returns directly for the same site - confirmed by direct comparison, not assumed. |

---

## The Bug — Full Account

Per this sprint's own final engineering constraint - "if this actually happened, could someone reconstruct it using only Atlas?" - the question was tested directly rather than assumed answered by prior sprints' work. A real operational item was created, transitioned to in_progress, and commented on, all through the actual engine functions the API calls (create_item, transition_status, add_comment - not synthetic timeline document inserts). Executive Timeline (built in Beta-05 final) was then queried for that exact project.

It returned zero events. Not a formatting issue, not a filter defaulting wrong - genuinely nothing, for three real, just-happened actions.

Root cause: executive_timeline() calls timeline_engine.for_site(site["id"], limit=50) without passing include_ops=True. for_site() itself has a fully-working mechanism for including operational item events (a separate code path that queries operations_engine.list_events_for_site and joins it with the owning items), confirmed correct by calling it directly with include_ops=True and getting the expected 3 events back. Executive Timeline simply never turned this mechanism on. Since for_site defaults include_ops to False, and Executive Timeline never overrode that default, every single operational item action - creation, assignment, every status transition, every comment, across every project, since Executive Timeline was built - has been invisible to it.

This directly contradicts Executive Timeline's own stated purpose from the sprint that built it: composing "Commercial, Operations, Workflow, Reality, Approvals, Client" into one chronological history. Operations and Approvals (which are operational items under the hood) were named in that original scope and were never actually wired in.

Fixed by passing include_ops=True to the existing for_site call, and labeling each returned item by its own already-present kind field (construction_event -> reality, operational_event -> the new operations source) rather than lumping both under reality, which would have been misleading given they are genuinely different kinds of history.

Verified three ways: the exact discovery scenario re-run after the fix (3 events now correctly appear, all labeled operations); a second, independent scenario confirming every operations-source event traces to a real, existing operational item (never a fabricated or orphaned entry); and against the real ACDP portfolio, where the fix surfaces 100 real operations events in the most-recent-100 view where zero would have appeared before.

---

## Cross-System History Validation

Checked whether the fix creates any new duplication or contradiction: for_site(include_ops=True)'s own operations items and the item's own GET /operational-items/{id} history are sourced from the exact same operational_events collection via the exact same operations_engine.list_events_for_site function - Executive Timeline does not maintain a second copy or a re-derived version of this history, it now correctly reads the same one.

---

## Chronological Integrity

for_site's own include_ops code path sorts its combined reality+operations items by created_at before returning, and Executive Timeline's own outer sort (_sort_key, checking created_at first) re-sorts the full merged set including the new operations events afterward - confirmed no separate, conflicting ordering logic was introduced. Not independently stress-tested for duplicate-timestamp instability or timezone edge cases this pass.

---

## Testing

- 2 new regression tests, both reproducing the exact real-API sequence that found the bug (not synthetic documents with the "correct" fields pre-set, which would not have caught this bug in the first place - the bug was specifically about a missing parameter on a real call).
- 1 existing test updated to reflect the corrected, now-accurate three-source model (reality/operations/commercial) rather than the previous two-source model that silently excluded a whole category of real history - this was not a regression in the fix, but an outdated assertion in a test written before this bug was found.
- Full regression suite: 132/132 passing (up from 130), including the corrected test.
- npx tsc --noEmit: zero errors, project-wide, after updating the frontend's filter UI and event labeling for the new operations source.
- Verified against the real, live ACDP bootstrap: 100 real operational events now correctly appear in Executive Timeline's most-recent view, where the pre-fix behavior would have shown zero for this category across the entire portfolio.

---

## Files Changed

- backend/engines/reasoning_engine.py - executive_timeline() now passes include_ops=True and correctly labels the resulting operations source distinctly from reality.
- backend/tests/test_dev02_bootstrap_reliability.py - 2 new regression tests; 1 existing test corrected to the accurate three-source model.
- frontend/app/executive-timeline.tsx - new operations filter option, source icon, and event labeling (using the operational event's own kind and linked item title).
- frontend/src/cre_api.ts - ExecutiveTimelineEvent's source type extended to include 'operations'.

---

## Remaining Risks — Named Explicitly

1. Workflow activity progression is not part of for_site's include_ops mechanism - that path covers operational items only (a separate collection, operational_events, from workflow_activities). Whether Workflow's own status transitions appear anywhere in Executive Timeline was not traced this pass, and given the exact class of bug just found, this is the single most likely place a similar gap still exists.
2. Chronological integrity under duplicate timestamps or timezone edge cases was not stress-tested - the ordering logic was confirmed not to conflict with itself, but not independently attacked.
3. Append-only / audit-trail tamper resistance for Timeline specifically (as opposed to Operational Items, checked in Beta-06D) was not examined this pass.
4. The bootstrap-timing skew named in Beta-05 final (freshly-created records dominating "most recent" views in a single-session bootstrap) still applies to this fix's own verification - the 100 real operations events surfaced against ACDP are genuinely real, but their prominence in a "most recent" view partly reflects when the seed script ran, not necessarily pure operational significance. This is a known, previously-documented characteristic of testing a fresh bootstrap, not a new finding.

---

## Beta-06F Assessment

This sprint is not reporting Complete. Per its own Definition of Done, Workflow's own presence in Timeline was not traced, and chronological-integrity stress testing was not performed - both named above rather than assumed clean.

What was found and fixed is significant on its own terms: Executive Timeline, built to be the "one chronological operational history" this platform's executive suite promises, had been silently excluding an entire category of real project history - every operational item action, since it was built - because of one missing keyword argument on one function call. This is exactly the kind of defect this sprint's own final constraint asks to be judged against: the underlying operation (creating, transitioning, commenting on an item) succeeded correctly every time; the question this sprint asks is whether the record of it could be reconstructed afterward, and for this entire category of history, it could not. That is now fixed, verified against real data, and permanently guarded by tests that reproduce the real sequence that found it, not a synthetic shortcut that would have missed it the same way the original implementation did.
