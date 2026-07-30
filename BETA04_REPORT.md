# Beta-04 — Site Engineer Experience Report

Per this sprint's own mandatory requirement, this report begins with the Capability Audit.

---

## Capability Audit

| # | Capability | Status | Action Taken |
|---|---|---|---|
| 1 | Assigned Operational Items / Due today / Ready to start / Waiting for materials / Blocked work / Recently assigned | VERIFIED | Confirmed all present in supervisor's existing My Day (_my_day_supervisor). No changes made. |
| 1 | Overdue | EXTENDED | Genuinely missing - named explicitly alongside "Due today" but no equivalent existed. Added, reusing the same overdue-detection pattern PM's My Day already used for delayed_activities. A real bug caught in development: the first version didn't exclude completed activities, which would have wrongly flagged a finished activity with a past due date as overdue - fixed before considering it done, with a permanent regression test guarding both the positive and negative case. |
| 2 | Photos / Voice notes / Text updates / Site association / Workflow association / Operational Item association (Capture Experience) | VERIFIED | The unified capture screen (app/(tabs)/capture.tsx) already supports all three modalities with site, workflow activity (activity_id), and operational item association, confirmed in prior sprints. No changes made this pass. |
| 3 | Completion Evidence | NEW - built this pass | Did not exist. Built memory_engine.list_events_for_activity, a visibility-checked workflow_engine.get_activity_evidence, a new route, and a collapsible evidence panel on the Workflow detail screen. See below for the full account, including a real limitation discovered during verification. |
| 4 | Site Progress | NEW - built this pass | Did not exist. Built operations_engine.site_progress and a new screen, composing Reality captures (via timeline_engine.for_site, reused directly), Workflow completions, Operations issues, and inspection status into one project-scoped story. See below. |
| 5 | Inspection requirements / completion / evidence / linkage | VERIFIED | Confirmed reusing STAB-01's own reasoning_projections.inspection_covered directly in both Site Progress and the pre-existing My Day/Daily Review - never a second inspection system. No changes made to the inspection logic itself. |
| 6 | Operational Item lifecycle from the Site Engineer perspective (assign -> acknowledge -> work -> evidence -> fulfilled -> verified -> closed), comments, attachments, voice, photos, history, assignment changes | VERIFIED | Confirmed in the previous Beta-03 continuation's own audit and re-confirmed here: the item detail screen supports the full lifecycle including comments, evidence (photo thumbnails, voice transcripts), and history. No changes made. |
| 7 | Timeline Experience - chronological order, linked captures, workflow/operational updates, navigation | VERIFIED | Confirmed via direct reuse in Site Progress's own latest_updates section - timeline_engine.for_site already resolves photos, analyses, and operational-item linkage in one call. No duplicate Timeline implementation introduced. |
| 7 | Commercial events in Timeline (where appropriate) | GAP - not addressed this pass | timeline_engine.for_project_commercial exists separately (built in CX-01) but was not merged into Site Progress's own latest_updates this pass, given time constraints. Named explicitly. |
| 8 | Offline & Recovery Behaviour | NOT AUDITED this pass | No changes made; not investigated fresh. Every new screen built this pass (Site Progress, Completion Evidence) follows the same load/error/retry pattern already established across Daily Review and the Commercial Workspace (a retry banner on failure, not a silent error) - consistent with the existing pattern, not independently re-verified against real network-failure conditions. |
| 9 | UX Review (loading, empty states, touch targets, taps) | PARTIALLY VERIFIED | Both new screens include loading spinners, honest empty states per section (not fabricated data), and pull-to-refresh. A full UX audit of every existing Site Engineer screen was not performed this pass. |
| 10 | Cross-validation | PARTIALLY VERIFIED | Site Progress's latest_updates verified structurally identical to timeline_engine.for_site's own item shape (a permanent regression test guards this). The fuller chains this sprint names (Capture->Timeline->Workflow->Dashboard->Client View; Inspection->Quality->Health->Timeline->Dashboard) were not independently re-audited this pass. |
| 11 | Role validation | VERIFIED for the two new capabilities specifically | Confirmed directly via live HTTP/engine calls: client correctly blocked from both Site Progress and Completion Evidence's own visibility check; management/PM/supervisor all correctly succeed. Broader role validation across all Site Engineer screens was not re-audited - no new findings beyond what prior sprints already established. |
| 12 | End-to-end walkthrough using RP-001/RP-002 | PARTIALLY COMPLETED | Site Progress verified end-to-end against real, live ACDP data (see below). Completion Evidence's own chain was verified end-to-end but NOT against RP-001/RP-002 - see the honest limitation named below. |

---

## Completion Evidence — full account, including a real limitation found during verification

Built as designed: memory_engine.list_events_for_activity (matching the established list_events_for_site pattern exactly), a visibility-checked wrapper in workflow_engine, a new route, and a collapsible "Evidence" panel added to each activity row on the Workflow detail screen, showing linked captures with navigation to each one.

A genuine limitation, found while trying to verify this against real Reference Portfolio data, not assumed away: RP-001's own seed generator (seed_demo_project.py) hardcodes every event's activity_id to None - a pre-existing, deliberate property of that script, unrelated to this fix. This means the feature, while correctly built, currently shows an honest empty state for every activity in RP-001 and RP-002, because the underlying seed data never links captures to activities in the first place.

Rather than reaching into seed_demo_project.py's own simulation loop under time pressure to wire this through - a large, intricate script with real risk of introducing the kind of silent breakage this engagement has specifically learned to guard against - the chain was instead verified with a manually-constructed but structurally real scenario: a real project, a real workflow activity, and a real event submitted through the actual multipart-form /api/events endpoint with activity_id set the same way a live field capture would set it. The evidence panel correctly returned that capture. This proves the mechanism works; it does not prove RP-001/RP-002 currently demonstrate it, and that gap is named explicitly rather than glossed over.

---

## Site Progress — full account

Built as operations_engine.site_progress(project_id, user), composing:
- Today's work - activities currently ready or in progress.
- Completed recently - activities completed today.
- Current issues - open, high/critical-priority operational items.
- Latest updates - the most recent captures across every site in the project, via timeline_engine.for_site called once per site and merged, reused directly rather than a second Timeline read.
- Inspections pending - the exact same inspection_covered check STAB-01, My Day, and Daily Review already use.

Available to management, project_manager, and site_supervisor; not available to client (Client Experience has its own separate Photos/Timeline views from CX-01). Verified end-to-end against live ACDP data: 20 real recent captures, 358 real completed activities, 71 real current issues, correct 403 for client.

---

## Cross-Validation

- Site Progress's latest_updates confirmed structurally identical to timeline_engine.for_site's own item shape (kind, event, created_at all present) - a permanent regression test guards this specifically so a future change can't silently make this a second, diverging implementation.
- Not independently re-verified this pass: the fuller Capture->Timeline->Workflow->Dashboard->Client View chain, and Inspection->Quality->Health->Timeline->Dashboard.

---

## Remaining Known Gaps — Named Explicitly

1. Completion Evidence cannot currently be demonstrated against RP-001/RP-002 - the seed generator itself would need a careful, separate pass to wire activity_id through its simulation loop. Named as the most concrete, actionable next step from this sprint.
2. Commercial events are not yet part of Site Progress's own Timeline section - timeline_engine.for_project_commercial exists but wasn't merged in this pass.
3. Offline & Recovery Behaviour was not audited fresh.
4. A full UX audit of every existing Site Engineer screen was not performed.
5. The fuller cross-validation and role-validation chains this sprint names were not independently re-verified beyond what this pass's own two new capabilities directly touched.

---

## Testing

- 9 new regression tests (107 total in the established pure-unit + mongomock baseline, up from 98, all passing, confirmed stable across two consecutive full-suite runs).
- npx tsc --noEmit: zero errors, project-wide.
- End-to-end verification: Site Progress against real, live ACDP data; Completion Evidence's chain against a real, manually-constructed capture scenario (given the RP-001 seed-data limitation above).

A genuine test-ordering bug was caught and fixed during this pass, the same category this engagement has hit before: test_site_progress_composes_real_data initially asserted RP-001 would have a nonzero open-items count, which is only true before the STAB-01 closeout tests elsewhere in the same shared, module-scoped fixture have run - a legitimate, expected state depending on test execution order, not a real defect. Fixed by using the closed_out_rp001 fixture (built in STAB-01 specifically to give a deterministic post-closeout state) and asserting only what's true regardless of order.

---

## Files Changed

- backend/engines/memory_engine.py - new list_events_for_activity.
- backend/engines/workflow_engine.py - new get_activity_evidence.
- backend/engines/operations_engine.py - supervisor My Day's new overdue section; new site_progress.
- backend/routes/workflow.py - new /workflow-activities/{id}/evidence route.
- backend/routes/operational_items.py - new /projects/{id}/site-progress route.
- backend/tests/test_dev02_bootstrap_reliability.py - 9 new tests.
- frontend/src/workflow_api.ts - new ActivityEvidenceEvent type and apiGetActivityEvidence.
- frontend/app/workflow/[id].tsx - Completion Evidence panel per activity.
- frontend/src/ops_api.ts - new SiteProgress type and apiSiteProgress.
- frontend/app/projects/[id].tsx - Site Progress navigation entry point.
- New: frontend/app/site-progress/[id].tsx.

---

## Beta-04 Readiness Assessment

Both capabilities this sprint's own brief names as "confirmed gaps" from the previous Beta-03 pass are now genuinely built and verified - Site Progress fully, against real Reference Portfolio data; Completion Evidence correctly, though its demonstration against RP-001/RP-002 specifically depends on a seed-data change not made this pass. A real bug (the overdue-completed-activity conflict) and a real test-ordering issue were both caught and fixed before being considered done, not discovered later.

Recommendation: Stable with Known Issues — not "Complete." The two most concretely-named gaps from the previous sprint are closed, but this sprint's own broader scope (offline/recovery review, a full UX audit, the fuller cross-validation chains, commercial events in Site Progress's own timeline) remains only partially addressed, as the Capability Audit above states plainly. The single most valuable next step is a focused, careful pass at seed_demo_project.py's own event-to-activity linkage - not because Completion Evidence doesn't work, but because a Site Engineer feature that can't be shown working on the platform's own reference data isn't yet demonstrably complete in the way this sprint's success criteria describe.
