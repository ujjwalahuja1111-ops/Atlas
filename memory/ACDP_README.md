# Atlas Canonical Demo Project (ACDP)

## Purpose

One permanent, realistic, 18-month construction project — the Atlas
Demonstration Villa — that exercises every Atlas engine (Reality
Engine capture, Intelligence Engine / AI proposals, Operations Engine,
Workflow Engine, Construction Reasoning Engine) through the same
production code paths real traffic uses. This is the dataset every
future sprint, regression test, and founder validation session should
use to see Atlas as it will actually be used, not a handful of
disconnected sample records.

It is not the regular developer seed (python -m scripts.dev seed /
scripts/db_seed.py) — that remains completely untouched and unaware
this exists. ACDP lives in its own project, its own six sites, and its
own five users on a phone-number range (9800000xxx) that can never
collide with the regular dev seed's (9000000xxx). Seed both into the
same database and neither notices the other.

See memory/ACDP_TIMELINE.md for the full narrative this dataset
implements — read that first if you want to understand why the data
looks the way it does, not just what commands to run.

## How To Seed

The regular developer seed now includes ACDP automatically:

    cd backend
    python -m scripts.dev seed           # regular dev seed + ACDP, one command
    python -m scripts.dev reset-seed     # reset, then the same

This is the command most people already know and use — as of this
audit, it now also seeds ACDP, on the same database connection, right
after the regular dev seed finishes. Nothing else changes about it: the
same confirmation prompt on reset/reset-seed, the same --yes/-y skip
flag, the same output for the regular dev seed data.

If you want to seed ONLY the Atlas Canonical Demo Project, without
touching (or requiring) the regular dev seed data, the standalone
command still works exactly as before:

    cd backend
    python -m scripts.seed_demo_project

Idempotent and deterministic either way:
- Re-running against an already-seeded database detects the existing
  Atlas Demonstration Villa project (by its fixed code, ACDP-VILLA)
  and does nothing — it will never duplicate data, however many times
  you run dev.py seed or the standalone command, in any order.
- Every run against a fresh database produces byte-identical content
  (same events, same AI proposal decisions, same delay episodes) — the
  generator uses a fixed random seed, never the system clock, for every
  choice it makes. The only thing that changes run-to-run is which
  absolute calendar dates the story maps to (see "How time works" in
  the timeline doc) — the story itself never changes.
- Takes a few minutes to run (it performs several thousand real engine
  calls — the same ones a real 18 months of usage would have made).

## Founder Testing Workflow

Log in as any of the five ACDP users (role and name shown at the end of
the seed script's own output):

| Phone | Name | Role | What to check |
|---|---|---|---|
| 9800000001 | Ravinder Kapoor | Management | Portfolio Health, Executive Briefing, Highest Risks |
| 9800000002 | Ananya Sharma | Project Manager | Today's Priorities, Look Ahead, Blockers, Suggested Actions |
| 9800000003 / 9800000004 | Suresh Yadav / Manpreet Singh | Site Supervisor | Activities Ready, Pending Inspections, Assigned to Me |
| 9800000005 | Dr. Vikram Mehta | Client | Client Dashboard, Pending Approvals, Shared Timeline |

Suggested pass, roughly in order:

1. Authentication — log in as each of the five roles; confirm each
   lands in the correct workspace.
2. Dashboard — as management, confirm Portfolio Health and Executive
   Briefing show real numbers (not empty states) — this project has
   16-19 real reasoning runs behind it, so it will.
3. Project Feed — as project manager or a supervisor, open any of the
   six sites' timelines and scroll — several hundred events per
   project, genuinely enough to scroll for pages, not a handful of
   entries.
4. Event Capture — capture a fresh event on any site; confirm it
   appears alongside the historical ones immediately (the seed data
   never blocks or interferes with new capture).
5. Voice — open a few of the seeded voice-kind events; the transcript
   text is short, plain site-supervisor language ("PCC completed
   today...") — deliberately not fabricated STT artefacts.
6. AI Proposals — open the AI Proposals list; you'll find examples in
   all four decision states (accepted, rejected, edited/modified, and
   still-pending/ignored).
7. Operational Items — assign one to a supervisor, watch it appear in
   their Assigned to Me feed; comment on an existing seeded item.
8. Client Approvals — as the client, open Pending Approvals; you'll
   find items awaiting a decision, plus already-decided ones (approved,
   rejected, and a few with a clarification question attached) in the
   project history — a real mixed backlog, not a uniform state.
9. CRE — as management/PM/supervisor, open Project Health, Insights,
   Look Ahead, and Briefing; as the client, open the Client Dashboard
   (Progress Summary, Current Stage, Upcoming Milestones) and confirm
   the client account is still correctly blocked from every internal
   reasoning endpoint.
10. Executive Dashboard — as management, try each question under
    /api/reasoning-meta's executive_questions (attention_today,
    greatest_risk, top_blocker, overdue_approvals, stalled_projects,
    tomorrow, most_loaded_supervisor) — every one has real data behind
    it from this project's history.

## Expected Dashboards

- Client Dashboard: a real current stage (mid-to-late "Finishes" or
  "Testing & Commissioning" for most zones, given ~95% completion), a
  plain-English progress summary, a handful of upcoming milestones, and
  a small, real backlog of pending approvals.
- Management/Executive Dashboard: Portfolio Health shows a meaningful
  score (not 100 — real delay episodes exist in the data); Highest
  Risks shows real, specific insights CRE's rules genuinely found
  (schedule delays, safety observations, approval bottlenecks);
  Executive Briefing correctly reports how many projects (of your
  visible portfolio) need attention today.
- PM Dashboard: Today's Priorities and Suggested Actions are never
  empty — with ~135 operational items and dozens of reasoning insights
  across 18 months of history, there is always something for a PM to
  triage.
- Supervisor Dashboard: Activities Ready reflects genuinely unblocked
  next-in-line work (the generated dependency graph is real, not
  decorative) and Pending Inspections reflects the requires_inspection
  activities actually due.

## Expected CRE Outputs

Because reasoning_engine.run_reasoning() was called at real monthly
checkpoints throughout the simulated history (not just once at the
end), the data supports:

- A genuinely evolving Project Health score (it will not be a flat
  100 — the delay episodes and open risks are real).
- Reasoning Insights covering schedule warnings, quality/safety
  observations, and client-approval-related reminders — because the
  rules that produce these (engines/reasoning_engine.py's
  evaluate_rules, completely unmodified) were run against real
  in-progress and delayed activities, real safety observations, and a
  real client-approval backlog.
- Construction Memory with a real record for every workflow activity
  CRE observed complete at one of its ~16-19 checkpoints — enough
  history to meaningfully demonstrate "learning from what's already
  been built," per the brief's own framing, even though no new
  learning logic was added here.
- Delay forecasts and look-ahead recommendations grounded in the real
  dependency graph the template's depends_on relationships produce —
  not placeholder text.

## What This Script Does Not Do (By Design)

Per the task's own constraints:
- No new database schema, no new collection, no new document shape —
  every ACDP record is created through the exact same engine functions
  (memory_engine, operations_engine, knowledge_engine, workflow_engine,
  intelligence_engine, reasoning_engine) real application traffic
  already uses.
- No CRE rule, projection, or architecture change — evaluate_rules,
  compute_project_health, project_lookahead, compose_daily_briefing,
  stage_of_activity, and every other CRE function are called exactly
  as they exist today, unmodified.
- No authentication or role-model change.
- No dependency-scheduling engine — see the timeline doc's explanation
  of why a hand-authored phase calendar was chosen over a computed
  critical-path scheduler for a demonstration dataset's purposes.

## Files

- backend/scripts/seed_demo_project.py — the generator (entry point).
- backend/scripts/acdp_fixtures.py — the phase/activity/zone catalog
  and content templates (pure data, no database access — safe to
  import and inspect standalone).
- memory/ACDP_TIMELINE.md — the full narrative.
- memory/ACDP_README.md — this file.
