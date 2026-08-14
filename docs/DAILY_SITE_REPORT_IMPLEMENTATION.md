# DAILY_SITE_REPORT_IMPLEMENTATION.md

## Service Architecture

backend/services/daily_site_report_service.py - a new, standalone directory (backend/services/), matching this task's own suggested path. Deliberately structured as pure composition, the same discipline CM-01's get_since_last_visit and WF-01's own orchestration already established: this file imports memory_engine, commercial_engine, and reasoning_engine, and calls their existing public functions. It contains zero new business logic for anything those engines already compute - its only real logic is grouping, date-bounding, and template-composing narrative text from values those engines already produced.

Three functions:
- generate_daily_report(project_id, target_date, *, user) - the one entry point, always returns the full internal report.
- to_client_safe(report) - a pure view transformation (dict -> dict), per this task's own explicit "implement as a view transformation, not a separate report-generation engine" instruction. There is exactly one generation path.
- render_markdown(report) - pure formatting, no new computation.

backend/routes/daily_report.py - a thin router, matching every other routes/*.py file's own established shape: parse the request, call the service, return the result. No business logic lives here.

## Data Sources Used

| Section | Source | Function/Query |
|---|---|---|
| Work Completed Today | Reality Capture events for the target date | db.events.find({project_id, server_created_at: {$gte, $lt}}) |
| Site Activity Snapshot | Operational items + events, both real-counted | db.operational_items.find({project_id}), filtered in-memory by date/status |
| Blockers & Risks | Operational items with health in ("blocked", "waiting_external") | Same query, filtered on the existing health field set_blocker/derive_health already compute |
| Client Decisions Pending | Operational items with category="client_approval", not yet terminal | Same query, filtered on existing status/category fields |
| Commercial Attention | Commercial events for the target date | commercial_engine.list_commercial_events(project_id), filtered by date and kind |
| Health Status | Existing Explain Health computation | reasoning_engine.explain_health(project_id, user=user) |

No new collection was created. project_id was confirmed already stored directly on operational_items (set at creation time from the site's own project_id) before writing any query against it - not assumed.

## API Endpoints Added

- GET /api/projects/{project_id}/daily-report/today?client_safe=<bool>
- GET /api/projects/{project_id}/daily-report?date=YYYY-MM-DD&client_safe=<bool>
- GET /api/projects/{project_id}/daily-report/export?date=YYYY-MM-DD&format=md&client_safe=<bool>

All three call commercial_engine.assert_project_visible(project_id, user) first - the same authorization convention every other project-scoped route in this codebase already uses (RC-01's own established rule: out-of-scope projects behave as 404, not 403).

## Workspace Integration

A new "Daily Site Report" card added to ReviewPhase.tsx (Phase 1's own Review phase component) - never Execute, per this task's own explicit "do not clutter Execute" instruction. ReviewPhase now receives a projectId prop it didn't need before (the only change to the Workspace shell's own call site). The card's own four actions: Generate Today's Report, Regenerate, Export Markdown (via React Native's built-in Share API - deliberately avoiding any new dependency or Expo/EAS configuration change, both of which this task's own predecessor phases explicitly forbid), and Copy Summary (also via Share, since no clipboard library exists anywhere in this codebase and adding one risked exactly the kind of dependency change this engagement has consistently avoided).

A Client's own card automatically passes client_safe=true - there is no separate UI toggle, since a client only ever needs to see one mode.

## Internal vs. Client-Safe Transformation Rules

to_client_safe() removes exactly two things from the already-generated internal report:
1. The owner field from every entry in blockers_and_risks (title, age, and impact category remain - a client can see that a blocker exists and its likely impact, just not who inside Atlas is responsible for it).
2. The entire commercial_attention list (emptied, not filtered - internal commercial commentary is never client-facing by default, matching this task's own explicit rule).

Everything else - Executive Summary, Work Completed Today, Site Activity Snapshot, Client Decisions Pending, AI Forecast Impact, Attached Photo Summary - is identical between internal and client-safe reports, confirmed by generating both from the same underlying activity and comparing them directly (see SAMPLE_REPORTS.md).
