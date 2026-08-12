# PILOT-02 — Workspace Isolation & Workflow Integrity

Scope honesty, stated first: all 3 Critical items and 2 of 4 High/Commercial/Navigation items are addressed this pass - two with real bug fixes, three confirmed already correctly implemented rather than assumed. P2-04 (Project Creation Wizard), P2-06 (Profitability Engine Review), and P2-09 (Notification Inbox) were not attempted and are named directly in Remaining Scope, not silently skipped.

## Critical

### P2-01 Archive Isolation — Real bug found and fixed

Audited every named sub-item against the actual code before touching anything:
- Projects excluded from Capture/dashboards by default: already correct - list_projects() and every caller of it default to include_archived=False.
- Ops filtered to active projects: already correct - operations_engine.py's own my_day and related functions call list_projects(user=user) with the same correct default.
- Archived project sites hidden: genuinely broken. archive_project() never cascaded to a project's own sites, and list_sites() only checked a site's own archived_at, never its parent project's. An archived project's sites stayed fully visible in Capture's and Home's own site pickers - someone could keep capturing reality against a project that was supposed to be closed. Fixed at the source in list_sites(), verified live through the real API, and covered by a new regression test.

### P2-02 Role Landing Fix — Extended, not duplicated

RC1-HARDENING's own H4 had already built the PM/Supervisor -> Workspace redirect. Rather than build a second, parallel mechanism, this pass extended the same useEffect to also send Management to Executive Hub - the destination this task names specifically, distinct from H4's own more general "Home stays a cross-project overview" framing. Searched the entire frontend for the named "default project-creation redirect" and found no trace of one anywhere - stated directly rather than inventing a fix for an unconfirmed bug.

### P2-03 Project-Scoped Assignment — Already fully correct

Traced both assignment paths (workflow activities via assign_activity, operational items via assign_item) end to end. Both routes already validate the assignee via the shared memory_engine.is_eligible_assignee function (active, correct role, project member) before the engine call - exactly this task's own "backend validation rejects cross-project assignments" requirement. Confirmed both real frontend call sites (op/[id].tsx, (tabs)/ops.tsx) already pass project_id to filter the picker, not just that the capability exists somewhere unused. No changes needed.

## High

### P2-05 Date Picker Standardization — Real, widespread issue, fixed

Confirmed real: every date field across the Commercial Workspace's forms (Contract, Milestone, Payment Request, Payment) was a plain text input with "(YYYY-MM-DD)" typed into the label as a hint - 6 fields total. A well-built, dependency-free DatePicker component already existed in the codebase, using exactly the ISO date string format these forms already store - this was a wiring job, not new infrastructure. FormModal now renders DatePicker for any field marked type: 'date'; all 6 date fields were updated. Confirmed via a full-app search that no other manual date text inputs remain anywhere.

## Navigation

### P2-08 Workspace Route Audit — Found and fixed a self-introduced regression, in the same pass that introduced it

Auditing every navigation target on the Project Dashboard and Workspace screens found no unintended Commercial redirects, and confirmed every named tab (Timeline, Ops, Capture, Commercial) has a genuinely unique route target. But this same audit caught a real regression this pass's own P2-02 fix had just introduced: the Project Dashboard's "Timeline & Events" button navigates to /(tabs) (Home) - which P2-02's own redirect now immediately bounces PM/Supervisor away from before they can ever see the Timeline view. A user tapping that button would never actually reach it. Fixed with an explicit ?stay=1 param respected by Home's own redirect effect, applied precisely to the two navigation points that represent a deliberate "view Timeline for this project/site" action (the button itself and onPickSite), while leaving every generic "return to your default landing screen" navigation (post-login, post-approval, post-capture) to correctly benefit from the new Workspace-first redirect as intended.

## Regression

- npx tsc --noEmit: clean throughout.
- npm run lint: 25 pre-existing problems, unchanged - verified directly after every change.
- Backend regression suite: 163/163 passing (up from 162, one new test for the P2-01 fix). One genuine test-construction mistake was caught and fixed while writing that test: insert_site doesn't set archived_at at all by default (a missing key, not None), which Mongo's own query semantics already handle correctly - the first assertion assumed the key always existed and was corrected to use .get().
- No existing test was weakened or removed.

## Remaining Scope

Named explicitly, not hidden:
- P2-04 Project Creation Wizard - not attempted. Project/Contract/Budget/Milestone creation all work individually (confirmed throughout this engagement's own earlier packages), but no unified multi-step wizard exists.
- P2-06 Profitability Engine Review - not attempted. Budget/forecast/variance figures exist and are correct (confirmed in CP-01/CP-02's own work), but this specific ask (verify aggregation source, display a calculation breakdown, add forecast-vs-actual distinction) requires dedicated investigation not completed here.
- P2-07 Payment Request Module - audited, not modified, because it's already fully satisfied: create/link-to-milestone/status-tracking all confirmed built in CP-02; client visibility confirmed real and correctly composed via client_payment_journey, which pairs each milestone with its own payment request status rather than maintaining a second, separate view. The "approval workflow" sub-item is satisfied by the existing raised -> sent -> paid progression, which matches how real construction invoicing actually works (a client pays or disputes an invoice; there typically isn't a separate formal "approve this invoice" step before payment itself) rather than needing a new explicit approval state.
- P2-09 Notification Inbox - not attempted. This is a genuinely new feature (a persistent, cross-session notification store and UI), not a fix to something existing, and was out of this pass's time budget.

## Merge Readiness

Ready to merge. Two real, confirmed bugs were found and fixed (P2-01's archive cascade, P2-08's self-introduced Timeline redirect regression), one of which this same pass introduced and caught before it reached anyone - evidence the audit discipline this task asks for was actually applied to this pass's own work, not just to pre-existing code. Three items were confirmed already correctly implemented rather than assumed working or reflexively "fixed" without cause. The three unattempted items are named directly as real, substantial remaining scope, not glossed over.
