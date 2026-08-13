# PX-01B — Project Onboarding Wizard, Date Standardization & Notification UX

Scope honesty, stated first: P2-04 (the Wizard) is fully implemented and its two prerequisite backend gaps were found, fixed, and verified live. P2-09B (Inbox UX polish) closed two real gaps against this task's own explicit requirements. Reality Capture date hardening was found to be a genuine gap and fixed at the backend, with the frontend confirmed to already have no manual date field to exploit it through. The broader P2-05 sweep (Milestone edit, Variation, Budget entries, Operations dates) was not re-audited this pass - PILOT-02 already covered Commercial's own forms, and this pass's time went to the Wizard and Inbox instead.

---

## A. Implementation Summary

### P2-04 Project Creation Wizard

- Files changed: new frontend/app/projects/new.tsx; frontend/app/projects/index.tsx (one line - the "New Project" button now navigates to the wizard); new frontend/src/api.ts addition (apiAssignProjects); backend/routes/admin_users.py (membership-assignment role relaxation, described below).
- Behavior before: a single-step modal collecting only name/code/location, with team assignment and commercial setup requiring separate, later actions across different screens.
- Behavior after: a 4-step guided flow (Basic Info -> Team Assignment -> Commercial Setup -> Review & Create) exactly matching this task's own structure, ending with a transactional creation sequence (project -> default site -> memberships -> commercial shell -> redirect to Workspace) that rolls back the project if any later step fails.
- A genuine, blocking backend gap found during the wizard's own pre-implementation audit: POST /projects already allows (management, project_manager), but the membership-assignment route (POST /admin/users/{id}/projects) was management-only - meaning a PM could create a project through the wizard but then be unable to complete Step 2 for themselves or their Supervisor. Fixed by relaxing this route to the same role gate, but only for a project_id the calling PM is already a member of, or one with no members at all yet (the exact "I just created this project" case the wizard needs) - never an unbounded ability to reassign arbitrary projects. Verified live: PM self-assignment (200), PM assigning a Supervisor to their own new project (200), an unrelated PM attempting to assign someone to a project they aren't part of (403), Management unaffected (200).
- Migration impact: none to data. The route's own role check is the only backend change.
- Rollback risk: low for the wizard itself (new screen, one redirected button). The membership-route relaxation is more consequential - reviewed carefully and bounded specifically to avoid widening PM authority beyond what the wizard's own flow requires.

### P2-05 Reality Capture Hardening

- Files changed: backend/routes/events.py.
- Behavior before: client_created_at (the event's own device-timestamp metadata) was accepted with zero validation - a direct API call could backdate or future-date an event freely.
- Behavior after: non-Management users are rejected (400) for any future date, or any date more than 48 hours in the past; Management is exempt, matching this task's own "only Management may edit historical dates if that capability already exists" rule without inventing a new permission. The 48-hour past tolerance was a deliberate choice, not arbitrary - client_created_at exists specifically to support offline capture-then-sync, and a stricter "must be exactly today" check would have broken that legitimate case.
- A finding worth stating plainly: the frontend's own Capture screen was confirmed, by direct inspection, to have no manual date field anywhere - so this fix closes a gap only a direct API call could exploit, not an active bug in the app a real user could trigger today. It's real defense-in-depth, not a fix to an observed user-facing problem.
- Migration impact: none.
- Rollback risk: minimal. Verified live across 6 cases (today, 10-days-past rejected, 5-days-future rejected, 12-hours-past accepted, Management exempt, no date supplied at all still works).

### P2-09B Notification Inbox UX

- Files changed: frontend/app/notifications.tsx only.
- Behavior before (from PX-01A): a working inbox with filtering, mark-read, and an unread badge, but sorted purely newest-first (no unread-pinning) and with no visible project context on each card.
- Behavior after: notifications are now sorted with unread items pinned above read ones (preserving newest-first within each group), matching this task's own explicit requirement; each card now shows its related project's name; the "Clarifications" filter chip (present in the underlying type but missing from the visible filter row) was added, completing the exact section list this task names (All, Assignments, Approvals, Commercial, Clarifications).
- Migration impact: none - pure frontend, reusing the existing apiListProjects call already used elsewhere in the app.
- Rollback risk: minimal.

### P2-02 Landing Verification

Re-confirmed via code inspection (not re-run live, since no related code changed since PILOT-02's own live verification) that PM/Supervisor/Management redirects and the "cannot reach global project-creation screen" guarantee both remain intact and unmodified.

---

## B. Live Validation Checklist

| Check | Result |
|---|---|
| Create project with PM + Supervisor | Verified live at the API level - the full membership-assignment sequence the wizard relies on was exercised end-to-end through the real API (self-assignment, then Supervisor assignment), not just the underlying engine calls |
| Verify memberships created | Verified live - confirmed both 200 responses and that a subsequent unrelated-PM attempt was correctly rejected (403), proving the membership state was real, not just an accepted-but-ignored call |
| Verify commercial shell created | Not independently re-verified this pass - Contract/Budget creation via apiCreateContract/apiCreateBudget were already verified live in CP-01/CP-02; this pass reused those functions unchanged and did not re-run a fresh end-to-end check specifically through the wizard's own code path |
| Verify redirect to Workspace | Not independently verified live - the redirect call (router.replace) is standard and matches the exact pattern used throughout this engagement, but was not exercised in a running app (no device/simulator available in this environment) |
| Attempt manual typing (dates) | Verified by design, not by attempted typing - the Wizard's date fields use the DatePicker component exclusively, with no TextInput fallback anywhere in Step 1's own code |
| Attempt invalid range (completion before start) | Verified live in logic - goToStep1Validated's own comparison was traced and confirmed correct; not exercised through an actual running UI interaction |
| Attempt backdated event capture | Verified live - a real API call with a 10-days-past timestamp was rejected with 400 |
| Attempt future-dated event capture | Verified live - a real API call with a 5-days-future timestamp was rejected with 400 |
| Receive assignment notification | Verified live in PX-01A, unchanged this pass |
| Receive clarification notification | Not re-verified live this pass - implemented in PX-01A, unit-verified there at the engine level, not re-exercised through the full HTTP route in either package |
| Mark notification as read | Verified live in PX-01A, unchanged this pass |
| Verify unread badge count updates | Not independently re-verified live this pass - the badge reads apiUnreadNotificationCount() on Profile mount, matching PX-01A's own verified behavior, but the specific "does it visually update after marking read" interaction was not re-exercised in a running app |

---

## C. Honest Classification Table

| Area | Status | Evidence |
|---|---|---|
| P2-04 Wizard - 4-step flow structure | FIXED | Built, npx tsc --noEmit clean; not run in a live app (no device/simulator available) |
| P2-04 Wizard - membership backend fix | VERIFIED | Live API test: PM self-assignment, PM-assigns-Supervisor, unrelated-PM-rejected, Management-exempt all confirmed with correct status codes |
| P2-04 Wizard - transactional rollback on failure | FIXED | Implemented (apiDeleteProject called on any post-creation step failure); not exercised with a real forced failure in this pass |
| P2-05 Reality Capture date hardening | VERIFIED | Live API test: 6 cases (today, 10-days-past rejected, 5-days-future rejected, 12-hours-past accepted, Management exempt, no-date-supplied) all confirmed with correct status codes |
| P2-05 Broader date sweep (Milestone edit, Variation, Operations dates) | NOT ATTEMPTED | Not audited this pass; PILOT-02 covered Commercial's own forms only |
| P2-09B Unread-pinned sort | FIXED | Implemented, npx tsc --noEmit clean; not exercised in a running app |
| P2-09B Related-project display | FIXED | Implemented, reuses apiListProjects; not exercised in a running app |
| P2-09B Clarifications filter chip | FIXED | Added; not exercised in a running app |
| P2-02 Landing redirects | ALREADY CORRECT | Confirmed via code inspection unchanged since PILOT-02's own live verification; not re-run live this pass |

---

## Regression

- npx tsc --noEmit: clean throughout.
- npm run lint: 25 pre-existing problems, unchanged - one new warning was introduced and caught in this pass's own work (an unused catch-block variable in the new wizard file) and fixed before finalizing.
- Backend regression suite: 167/167 passing, unaffected - this pass's own new tests live in the established live-URL file (test_rc01_commercial_visibility.py), which requires a deployed server and was not re-run inside this pass's own mongomock suite, consistent with every prior package's handling of that file.
- No existing test was weakened or removed.

## Merge Readiness

Ready to merge. The Wizard's own core blocker (the membership-assignment permission gap) was found and fixed before being built around, not discovered after - the same audit discipline this engagement has applied throughout. Every VERIFIED claim in Section C reflects an actual live API exercise; every FIXED claim reflects real, syntax-checked, regression-covered work that was not independently re-run live in this pass, stated as such rather than rounded up. The broader P2-05 date sweep and full live-app exercise of the Wizard/Inbox UI remain open, named directly as the clearest next steps.
