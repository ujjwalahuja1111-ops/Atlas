# Atlas Reference Portfolio (RP-01)

**Status: partially delivered.** This document describes what was actually built and verified, what was deliberately scoped down from the brief's numeric targets (with reasoning), and what genuinely was not attempted - matching this engagement's standing practice of accurate accounting over the appearance of completeness.

## What this is

Two permanent, coexisting projects for regression testing, demonstration, and future AI validation - never overwriting each other, seedable independently or together:

- RP-001 - the existing Atlas Canonical Demo Project (ACDP) villa, unmodified in identity and scale, with Commercial reference data added.
- RP-002 - Neoteric Corporate Office, a new commercial interior fit-out project, built from scratch this session.

## An important finding, stated plainly: RP-001 does not currently classify as Healthy

The brief specifies "Expected Health: GREEN" for RP-001. Verified directly against the live system: RP-001 currently computes as Critical (health score 40), not Healthy - because ACDP's workflow is essentially complete (358 of 361 activities finished) while carrying 135 still-open operational items, 11 of them critical-priority, accumulated across its 18-month simulated history without being resolved at a matching rate.

This is a pre-existing characteristic of ACDP's own seed data, confirmed present before any Reference Portfolio work touched it this session - not something this sprint introduced. Deliberately not "fixed" here: closing 135 operational items to force a Healthy classification would mean either fabricating resolution events with no real story behind them (exactly what "do not generate random demo data" warns against) or a substantial rewrite of ACDP's own multi-month simulation logic, which is real, separate work outside this sprint's scope. Flagged here as a genuine, actionable finding for whoever next touches ACDP's own generator, rather than silently worked around or left for someone to discover by surprise.

RP-002, by contrast, computes as Healthy (score 93) - a project 52% into its schedule with one blocked activity and a handful of open operational items scores better than a nearly-finished project carrying a large unresolved backlog. This is itself informative: it demonstrates the health calculation is genuinely evidence-driven, not simply "how far along is this project," and neither project's number was hand-tuned to hit a target - both are read directly from live output.

## RP-001 - Atlas Demonstration Villa

Unchanged from ACDP: 361 workflow activities, 784 timeline events, 162 operational items (135 open, largely material/labour/quality items accumulated across the full build), 56 AI proposals, 16 CRE reasoning runs. Already substantially exceeds the brief's stated targets (120-150 activities, 20-25 operational items) - treated as "expand it substantially" already satisfied, not shrunk to match a smaller number.

Added this session: Commercial reference data - Contract Rs 2.85 Cr, Approved Variations Rs 12 Lakh, Pending Variations Rs 5 Lakh, Budget Rs 2.32 Cr, Current Cost Rs 1.08 Cr, Forecast Rs 2.39 Cr, Retention 5%, Advance 10%, three RA Bills (two paid, one pending), cash flow signal "healthy" - the exact figures the brief specifies.

## RP-002 - Neoteric Corporate Office

Built from scratch this session, at a deliberately reduced scale from the brief's numbers - stated honestly, not padded to match. 13 shared trade activities (Strip-out through Final Snagging), 22 operational items, across three zones (Ground Floor Reception/Cafeteria, Floor 1 Open Office, Floor 2 Open Office/Server Room), 18,500 sqft, Mohali IT City.

Why 13 activities, not 180: Workflow Engine has no first-class per-zone activity concept - generate_workflow produces one activity per template entry, project-wide, not per-zone instances. ACDP's own ~361-activity scale comes from its fixture generator manually creating one Knowledge Activity per (activity, zone) pair outside generate_workflow itself. Replicating that same hand-built per-zone expansion with genuine, non-repetitive construction reasoning for a second project was not achievable with real quality in the time available this session. Rather than either mechanically repeating the same 13 activities three times (which is not real per-zone data, just padding) or leaving Workflow Engine's per-zone limitation undocumented, this is named directly: a real product gap (Workflow Engine's own per-zone modeling), not a seeding shortcut.

Why 22 operational items, not 50-60: every item is written with a specific, genuine construction reason (a named vendor, a specific delay cause, a specific inspection finding) - covering every category the brief lists (material/labour/equipment requirements, quality/safety observations, client approvals, drawing requests, site issues, commitments, follow-ups, general items, inspections). 22 real, distinct reasons were written; padding to 50+ would have meant either repeating the same handful of causes with different site labels (not real variety) or inventing generic filler - both are exactly what "optimize for realism, not quantity" warns against.

Operational complexity, as specified: a genuinely blocked activity (False Ceiling Grid & Tiles, blocked on a delayed glass-partition delivery - the blocking operational item and the blocked activity tell the same real story, not two disconnected facts), critical-priority items (vendor delivery miss, exposed live wiring, fire inspection failure), escalations (the furniture vendor's missed commitment, escalated directly with the vendor's account manager), and a failed-then-corrected inspection.

Commercial reference data: Contract Rs 4.85 Cr, Approved Variations Rs 48 Lakh, Pending Variations Rs 23 Lakh, Budget Rs 4.05 Cr, Current Cost Rs 2.71 Cr, Forecast Rs 4.29 Cr, Advance Recovery 72%, five RA Bills (three paid, one pending, one under review), cash flow signal "watch" - the exact figures the brief specifies.

Not built: RP-002's own timeline events (the brief's 250-300 target). timeline_event_count in RP-002's expected_state.json is honestly 0 - no Reality Engine events were seeded for this project this session. Everything else (workflow, operations, commercial) is real and verified; timeline population for RP-002 is genuine remaining work, not silently glossed over.

## The Commercial reference data layer - what it honestly is

The Commercial Foundation Engine was Architecture Frozen, not implemented - no Contract/BOQ/Invoice/Payment entities exist anywhere in the codebase. Building the real engine here would directly contradict this sprint's own framing ("not about adding another business engine"). Instead: a single, minimal commercial_reference collection (memory_engine.set_commercial_reference/get_commercial_reference), one document per project, field-shaped to match the frozen specification's own entity names, so a future real implementation can read the same shape without any caller needing to change. Its own docstring in engines/memory_engine.py states this plainly. This is reference data for demonstration and regression purposes - not a claim that Commercial Foundation Engine is live.

## Cross-Project Comparison

GET /api/portfolio/compare?project_ids={id},{id} - verified end-to-end against both real projects. Reuses _project_row (Portfolio Control Center's own per-project calculation) exactly as Client Experience already does, so a project's health in this comparison is byte-identical to its health everywhere else in Atlas - never a fourth, independently-computed number. Returns, per project: health (status/score/explanation), workflow activity counts by status, operational item counts by status (open/blocked/critical), timeline event count, the commercial reference data, variation exposure percentage (computed from commercial figures), and cash flow signal. Client role is correctly blocked (403) - this is a management/PM/developer tool, not a client-facing view.

## Expected State Files

reference_portfolio/RP-001/expected_state.json and reference_portfolio/RP-002/expected_state.json - generated by actually calling the same comparison logic the live API uses (reasoning_engine._project_comparison_row), never hand-typed. This is deliberate: a baseline that could silently drift from what the system actually computes would be worse than no baseline at all. Regenerate them by re-running the generation demonstrated in this session whenever RP-001 or RP-002's underlying data is intentionally changed; a future implementation should fail its own regression check if a rerun produces different numbers without an intentional data change behind it.

## Seeder

backend/scripts/reference_portfolio.py - seed_rp002() (idempotent: checks for existing project/site/activity/item records by name/code before creating, safe to run repeatedly), seed_rp001_commercial_reference(), seed_rp002_commercial_reference(), generate_expected_state(project_id, admin=...).

Not built: the brief's fuller seeder CLI (seed-only-RP-001, seed-only-RP-002, seed-entire-portfolio, reset-portfolio as named commands). RP-001 continues to be seeded via the existing scripts/seed_demo_project.py / python -m scripts.dev seed; RP-002 and the commercial reference layer are seeded by directly calling this module's functions (as demonstrated in this session's own verification runs) rather than through a polished CLI wrapper. A real gap, not a silent omission - worth a short, focused follow-up rather than a rushed CLI added at the end of an already-large session.

## How future reference projects should be added

Follow this session's own pattern: a new project code, an idempotent seeder function (check-before-create at every step), operational items written with specific, real business reasons rather than generated from a template, commercial reference data set via memory_engine.set_commercial_reference, and an expected_state.json generated from the live comparison endpoint, never authored by hand. A new reference project should be added because it exercises a genuinely different construction scenario (a different building type, a different risk profile, a different commercial pattern) - not to pad the portfolio's count.

## Validation utilities - not built this session

The brief's named validation APIs (Portfolio Summary, Engine Comparison, Commercial Comparison, Workflow Comparison, Operational Comparison, Health Comparison, Regression Validation) beyond the single compare_projects endpoint above were not built. compare_projects already surfaces workflow/operations/commercial/health data per project in one call; splitting that into six separate endpoints, or adding an automated regression-validation endpoint that diffs live output against expected_state.json, is real, additional, and reasonably scoped follow-up work - named here rather than left for someone to assume was included.
