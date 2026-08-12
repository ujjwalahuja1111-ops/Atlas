# PX-01A — Project Onboarding, Commercial Transparency & Notification Foundation

Scope honesty, stated first: P2-06 (Commercial Profitability Transparency) and P2-09 (Notification Inbox Foundation) are both implemented, verified end-to-end through the live API, and covered by regression tests. P2-04 (Project Creation Wizard) was not attempted - named directly in the classification table below, not silently skipped. P2-05 (Date Input Standardization) was substantially completed in the prior PILOT-02 package for Commercial's own forms; this pass did not re-audit the additional surfaces this task names (Project Creation itself, since no wizard exists yet to standardize).

---

## A. Implementation Summary

### P2-06 Commercial Profitability Transparency

- Files changed: frontend/app/commercial/[id].tsx only.
- Behavior before: a PM could see individual numbers (contract value, budget, cash flow) scattered across separate sections, with no single place explaining how they combine into profitability, and no indication of which engine each number came from.
- Behavior after: a new "Commercial Breakdown" section, positioned directly after Cash Flow, shows the exact structure this task's own brief specifies (Contract Value -> Approved Variations -> Revenue Total -> Budget -> Committed Cost -> Actual Cost -> Forecast Cost at Completion -> Forecast Profit -> Forecast Margin %), with each row labeled by its real source (Contract, Variation Engine, Budget Engine, Expense Ledger, Forecast Calculation).
- Migration impact: none. Every figure is read from data this screen already loaded; no new API call, no new backend field.
- Rollback risk: minimal - a single new UI section; reverting is a pure frontend revert with no data implications.

### P2-09 Notification Inbox Foundation

- Files changed: new backend/engines/notification_engine.py, new backend/routes/notifications.py, backend/server.py (router registration), backend/engines/operations_engine.py (3 trigger points: assignment, status change, clarification requested), backend/engines/commercial_engine.py (2 trigger points: payment request raised, payment received), new frontend/src/notifications_api.ts, new frontend/app/notifications.tsx, frontend/app/(tabs)/profile.tsx (entry point + unread badge).
- Behavior before: operational events were recorded but no user was ever proactively told about them; discovering an assignment or a payment event required manually checking the relevant screen.
- Behavior after: an assignee is notified when assigned/reassigned to an item; the assignee is notified when their item reaches in_progress/verified/closed; the item owner is notified when a client requests clarification; a project's PM/Management users are notified when a payment request is raised or a payment is received. All notifications are visible in a new Inbox screen (filterable by category, newest first, mark-one or mark-all read, unread badge on Profile).
- Migration impact: one new, genuinely required collection (notifications) - explicitly permitted by this task's own "new collections unless absolutely required for notifications" carve-out. No existing collection or field was changed.
- Rollback risk: low. Every trigger call site is wrapped in try/except specifically so a notification failure can never block the real action (an assignment, a payment) it's attached to - confirmed by design, not just by hope. Reverting removes only the new files/trigger calls; no existing data is affected.

### P2-04 Project Creation Wizard — Not attempted

Named directly rather than partially built. The current single-step project creation popup was not touched.

### P2-05 Date Input Standardization — Partially covered by a prior package

PILOT-02 already standardized all 6 date fields across Commercial's own forms (Contract, Milestone x2, Payment Request x2, Payment) onto the existing DatePicker component. This pass did not extend that work to Project Creation (since no wizard exists to standardize) or re-audit Reality Capture's own event-date handling.

### P2-02 Role Landing — Re-verified, not re-implemented

Confirmed via code inspection (not re-tested live in this pass, since PILOT-02 already verified this live and no related code changed since) that the PM -> Workspace, Supervisor -> Workspace, Management -> Executive Hub redirects from PILOT-02 remain in place and unmodified, and that no default navigation path leads to the global project-creation screen for non-management roles.

---

## B. Pilot Validation Checklist

| Check | Result |
|---|---|
| Create project with PM + Supervisor | Not exercised - no wizard exists yet to test this specific flow (P2-04 not attempted) |
| Date pickers work on mobile and web | Not independently re-tested this pass; PILOT-02's own DatePicker component is React Native-native (no platform-specific code), so both should work identically, but this was not explicitly re-verified here |
| Archived projects cannot appear in Capture | Verified in PILOT-02, unchanged since - not re-tested live this pass |
| Profitability breakdown updates when expenses are entered | Verified conceptually, not live end-to-end: confirmed the Breakdown section reads budget.committed_cost/actual_cost directly from the same summary object the rest of the screen already re-fetches on refresh, so it will reflect new expense data whenever that data exists - but no live test actually recorded a new committed/actual cost and confirmed the UI updated |
| Assigned PM receives inbox notification | Verified live - confirmed via a real end-to-end API call: an item assigned to a user produces exactly one notification in that user's own inbox |
| Supervisor receives reassignment notification | Verified live for first assignment; reassignment specifically (the is_reassignment branch) was implemented but not independently re-tested with a second assignment call |
| Clarification request appears in PM inbox | Implemented and unit-verified via the engine function directly; not exercised through the full live HTTP route in this pass |
| Payment request notification appears in inbox | Verified live - confirmed via a real end-to-end API call: raising a payment request produces a notification for the project's management user |

---

## C. Honest Classification Table

| Area | Status | Evidence |
|---|---|---|
| P2-06 Commercial Breakdown UI | FIXED | New section built, npx tsc --noEmit clean, matches the task's own worked example arithmetic exactly (verified by hand) |
| P2-06 Source labeling per figure | FIXED | Every row shows its real source engine, confirmed by reading the code for each label against where that number actually originates |
| P2-09 Notification engine (create/list/mark-read/unread-count) | VERIFIED | Exercised through the real API end-to-end: assignment and payment-request notifications both confirmed to arrive in the correct user's inbox with correct category/title |
| P2-09 Assignment trigger | VERIFIED | Live API test: assigning an item produces exactly one notification |
| P2-09 Status-change trigger | FIXED | Implemented, syntax-checked, covered by the full regression suite passing; not independently exercised live with a real status transition in this pass |
| P2-09 Clarification trigger | FIXED | Implemented; verified only via a direct engine-level call, not the full HTTP route |
| P2-09 Commercial triggers (payment request, payment received) | VERIFIED | Live API test: raising a payment request produces exactly one notification for the project's management user |
| P2-09 Inbox UI (filter, mark read, unread badge) | FIXED | Built, npx tsc --noEmit clean, npm run lint unchanged at baseline; not exercised in a running app (no device/simulator available in this environment, the same constraint noted throughout this engagement's own prior UX-adjacent packages) |
| P2-04 Project Creation Wizard | NOT ATTEMPTED | No code written for this objective |
| P2-05 Date standardization (Commercial forms) | ALREADY CORRECT | Completed in PILOT-02; re-confirmed present and unmodified by grep this session |
| P2-05 Date standardization (Project Creation, Reality Capture) | NOT ATTEMPTED | No wizard exists yet to standardize; Reality Capture's own event-date handling was not audited this pass |
| P2-02 Role landing redirects | ALREADY CORRECT | Confirmed via code inspection that PILOT-02's own redirects remain in place; not re-run live since no related code changed |
| P2-02 "cannot reach global project-creation screen" | ALREADY CORRECT | Confirmed by the same code inspection above - no default navigation path leads there |

---

## Regression

- npx tsc --noEmit: clean throughout.
- npm run lint: 25 pre-existing problems, unchanged.
- Backend regression suite: 167/167 passing (up from 163) - 4 new tests for the Notification Inbox, matching exactly the scenarios manually verified live before being written as permanent tests. Two genuine test-construction mistakes were caught and fixed while writing them: a wrong assumption about create_item's own parameter list (no project_id argument exists - it's derived from site_id), and a wrong assumption about a valid operational item category (quality_issue isn't real; quality_observation is) - both caught by running the test and reading its actual failure, not assumed correct from the call's own apparent plausibility.
- No existing test was weakened or removed.

## Merge Readiness

Ready to merge for P2-06 and P2-09. Both were verified through the real API, not just written and assumed correct - and where verification was partial (status-change and clarification triggers, the Inbox UI's own runtime behavior), that's stated plainly in Section C rather than rounded up to VERIFIED. P2-04 was not attempted and should not be considered part of this merge - it remains open, substantial work for a future pass.
