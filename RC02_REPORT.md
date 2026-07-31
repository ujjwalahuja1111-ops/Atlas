# RC-02 — Production Hardening & Pilot Readiness Report

Per this phase's own mandatory requirement, this report begins with the Production Readiness Matrix.

---

## Production Readiness Matrix

| Area | Status | Evidence |
|---|---|---|
| Events' own mutation routes (timeline planning, request-approval, corrections, regenerate-proposals) | BLOCKER, found and fixed this pass | Explicit Beta-06D documented risk, closed. All four routes had zero project-visibility enforcement, confirmed exploitable before fixing. See below. |
| Sites' own mutation routes (update, archive, unarchive, delete) | BLOCKER, found and fixed this pass | Explicit Beta-06D documented risk, closed. All four routes had zero project-visibility enforcement - including a hard delete - confirmed exploitable before fixing. See below. |
| Workflow activity progression's presence in Executive Timeline | BUG, found and fixed this pass | Explicit Beta-06F documented risk, closed within the constraints this phase itself sets. Workflow activities carry no separate event ledger the way operational items do, so the fix is honestly each activity's own most recent status change, not a fabricated full history. See below. |
| Site Engineer's own distinct primary workflows | NOT VALIDATED this pass | Explicit Beta-06G documented risk - not reached. Named rather than assumed adequate. |
| Full six-role continuous lifecycle (Management -> PM -> Supervisor -> Engineer -> PM -> Client -> Management) | NOT VALIDATED this pass | Explicit Beta-06G documented risk - individual adjacent handoffs were verified in prior sprints, but not stitched into one continuous scenario, including this pass. |
| Reference Portfolio qualitative realism | NOT VALIDATED this pass | Named as a remaining risk in three consecutive prior sprints (06E, 06F implicitly, 06G) - still not performed. |
| Phase 2 - Production Configuration (bootstrap, permissions, onboarding, project creation from clean environment) | NOT VALIDATED this pass | Not attempted given time constraints; this phase's own scope is large and Phase 1's documented risks were prioritized as the highest-confidence source of real, demonstrable defects. |
| Phase 3 - Operational Recovery (wrong assignment, duplicate capture, accidental closure, etc.) | NOT VALIDATED this pass | Not attempted. |
| Phase 4 - Performance | NOT MEASURED this pass | Not attempted. |
| Phase 5 - UX Polish | NOT PERFORMED this pass | Not attempted beyond what this pass's own two fixes directly touched (Executive Timeline's new workflow source, correctly labeled). |
| Phase 6 - Documentation | NOT ASSESSED this pass | Not attempted. |
| Phase 7 - Scale assessment (1/5/20 concurrent projects, multiple PMs/supervisors/clients, months of daily use) | NOT ASSESSED this pass | Not attempted. |

---

## Phase 1 — Remaining Beta Risk Review — Full Account

Per this phase's own explicit instruction ("nothing previously listed as Remaining Risk should remain unverified without explanation"), each item from Beta-06D/E/F/G's own documented risk lists was checked directly. This pass closed three of the highest-confidence items and explicitly did not reach the rest, rather than attempting shallow coverage across all of them.

### Events' and Sites' mutation routes — the two highest-priority documented risks, both real

Beta-06D's own report named these as "the single most likely place this same class of bug still exists," given the pattern already found four times (read fixed, write never checked) across Operational Items and Commercial. That prediction held.

Demonstrated concretely before fixing: a management-role event's PATCH /events/{id}/timeline, POST /events/{id}/request-approval, POST /events/{id}/corrections, and POST /events/{id}/regenerate-proposals all succeeded (200/201) when called by a project-manager account genuinely scoped to a different project. request-approval is particularly consequential: it creates a real operational item and could trigger a real client-facing approval request for a project the caller has no relationship to.

The same pattern held for Sites: PATCH /sites/{id}, POST /sites/{id}/archive, POST /sites/{id}/unarchive, and - most seriously - DELETE /sites/{id} all succeeded for an outsider before this fix. The delete path was verified not just to return an error after the fix, but that the site genuinely still exists afterward (re-fetched and confirmed, not merely inferred from the response code).

Fixed by reusing commercial_engine.assert_project_visible directly, the identical primitive established in Beta-06B/C/D - no new authorization mechanism. Verified three ways for all eight endpoints: the exploit demonstrated, the exploit confirmed absent (404) after the fix, and legitimate access confirmed unaffected against real ACDP data (a real PM adding a correction and requesting approval on a real event, both succeeding normally).

### Workflow activity progression in Executive Timeline — real, fixed within an honest limit

Beta-06F's own report predicted this exact gap. Confirmed directly: two real set_status calls (in_progress, then completed) on a real activity produced zero Executive Timeline events before the fix.

The honest limit of this fix, stated plainly: workflow activities have no separate event ledger - unlike operational items' operational_events collection, there is no per-transition history to read back. Building one would be a new data model, explicitly out of this phase's own scope ("do not build new features," "do not redesign architecture"). The fix implemented is therefore narrower than the operational-items fix: it surfaces each activity's own current status and when it last changed (fields set_status already writes on every call) as a single timeline entry - not a fabricated multi-transition history. This is stated in the code's own comments and in this report rather than presented as more complete than it is.

### What was not reached, named explicitly

Site Engineer's own distinct workflows, the full six-role continuous chain, and Reference Portfolio qualitative realism remain exactly as documented in Beta-06G - not attempted this pass, given the time this session had available was spent on the two highest-confidence, most consequential findings (Events/Sites mutation authorization) plus one predicted-and-confirmed functional gap (Workflow Timeline).

---

## Testing

- 4 new regression tests, mongomock-based (135 total in the established baseline, up from 133, all passing).
- 8 new regression tests added to the live-URL test file (test_rc01_commercial_visibility.py), following its established pattern - require a deployed server to execute, consistent with every other test in that file; underlying fixes independently verified via constructed httpx/ASGI-transport scenarios in this session.
- npx tsc --noEmit: zero errors, project-wide, after the Executive Timeline frontend update.
- Every fix verified three ways: exploit demonstrated, exploit confirmed blocked, legitimate real-ACDP-data access confirmed unaffected.

---

## Files Changed

- backend/routes/events.py - visibility checks added to all four mutation routes.
- backend/routes/projects.py - visibility checks added to all four Site mutation routes.
- backend/engines/reasoning_engine.py - executive_timeline() extended with an honest, single-most-recent-status workflow source.
- backend/tests/test_dev02_bootstrap_reliability.py - 4 new tests.
- backend/tests/test_rc01_commercial_visibility.py - 8 new tests.
- frontend/app/executive-timeline.tsx - workflow source icon, labeling, and filter option.
- frontend/src/cre_api.ts - ExecutiveTimelineEvent's source type extended.

---

## Remaining Risks — Named Explicitly, Not Minimized

This phase's own brief is large - seven phases, most of which this pass did not reach at all. Naming them plainly rather than implying partial coverage means broader validation:

1. Phases 2 through 7 in their entirety - production configuration, operational recovery, performance, UX polish, documentation, and the concurrent-scale assessment were not attempted this pass.
2. Site Engineer's own workflows, the full six-role chain, and Reference Portfolio realism - carried forward unresolved from Beta-06G, still not reached.
3. Given the pattern that produced this pass's own two findings (an authorization check applied inconsistently across sibling resources; a documented capability that quietly wasn't fully wired in), a systematic sweep for other instances of either pattern across the remaining, unaudited write endpoints and screens is the highest-confidence next step, not yet performed.

---

## RC-02 Production Assessment

Two real BLOCKER-class findings (Events' and Sites' own mutation authorization) and one real BUG (Workflow's absence from Executive Timeline) were found, demonstrated with working exploits or reproductions, fixed, and verified - each closing an item this engagement's own prior sprints had explicitly flagged as an open risk rather than silently left unresolved. This is genuine, verified production-hardening work, not a claim of broad coverage.

But this phase's own success criterion is not "were bugs found and fixed" - it is whether Atlas is ready for a real company to deploy Monday morning. That question cannot be honestly answered yes when five of seven named phases in this sprint's own brief were not examined at all, and three explicitly-carried-forward risks from the immediately preceding sprint remain open. An honest assessment cannot report readiness based on the absence of evidence in areas that were simply never looked at.

---

## Release Decision

# NOT READY FOR PILOT

Supporting evidence:

This is not a judgment that Atlas is broken - the platform's core operational lifecycle, commercial chain, executive intelligence, and authorization boundaries have been extensively and repeatedly verified across many prior sprints, and this pass's own findings were closed, not left open. The "not ready" determination reflects unvalidated scope, not known defects: Phases 2 (production configuration - can a company actually deploy this from a clean environment without engineering help?), 3 (operational recovery - can ordinary mistakes be undone?), 4 (performance), 6 (documentation), and 7 (concurrent-scale behavior) were not examined this pass, and this phase's own final constraint is explicit that an untested significant workflow must be stated, not assumed fine.

Blockers requiring resolution before a pilot recommendation, per this phase's own instruction to list only blockers:

1. Production Configuration (Phase 2) has never been validated - whether a construction company can actually stand up a clean Atlas deployment, onboard real users, and create their first real project without developer assistance is currently unknown, not confirmed.
2. Operational Recovery (Phase 3) has never been validated - whether a real user's ordinary mistake (wrong assignment, accidental closure, wrong approval) can be corrected without data corruption or engineering intervention is currently unknown, not confirmed.
3. Site Engineer's own distinct workflows remain unvalidated across two consecutive sprints now (Beta-06G and this one) - this is a named production user role with no independent confirmation it can complete its job.

These three are named as blockers specifically because they are unvalidated, not because a defect was found in them - the honest classification, per this phase's own instruction, is that an untested significant workflow is exactly the condition under which "Complete" or "Ready" cannot be reported.
