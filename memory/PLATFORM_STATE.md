# Project Atlas — Platform State

Companion to ARCHITECTURE.md (engine map). This document covers everything
ARCHITECTURE.md doesn't: the entity model, system boundaries, what's
actually implemented today, how to run it, who owns what, and where the
platform is genuinely extensible versus where extension would mean
redesign. Written during the Platform Consolidation Sprint - treat this as
the reference point for the next development phase, not a historical
record of how features were built.

---

## Core Entity Model

```
Project --< Site --< Event --< AiAnalysis --< AiProposal --> OperationalItem
              |         |                                        |
              |         `-- requires_client_approval? --> OperationalItem (category=client_approval)
              |                                                   |
              `--< WorkflowActivity <-- inherited_evidence_event_id (both link this way)
                        |
                        `--> ReasoningInsight / ConstructionMemory (via reasoning_runs)
```

- **Project** - the top-level container. Has `archived_at` (soft delete only - hard delete is guarded by reference counts, see memory_engine.project_reference_counts).
- **Site** - a physical location within a project. Same archive/reference-count guard as Project.
- **Event** - Atlas' primary construction memory object. Immutable Record Time (client_created_at/server_created_at); separate, editable Timeline Planning (planned_start/finish, actual_start/finish - workflow-aware, see below). Optionally linked to a WorkflowActivity via activity_id (reserved field; nothing in the current capture flow sets it yet).
- **AiAnalysis** - one per event, the transcription/extraction result. Optional - an event with ai_status "skipped" has none.
- **AiProposal** - an AI-suggested OperationalItem, always traceable back to its originating event_id. Reviewed inside the canonical Event Detail page.
- **OperationalItem** - the unit of actionable work. Categories: material_requirement, labour_requirement, equipment_requirement, client_approval, drawing_request, site_issue, quality_observation, safety_observation, commitment, inspection, follow_up, general. Assignment Timeline: target_start + required_by (displayed as "Target Finish"), with Start+Finish/Start+Duration/Finish+Duration auto-derivation. Links back to its originating event via inherited_evidence_event_id (category-scoped lookups only - an item is never mistaken for a different category's item just because both point at the same event).
- **WorkflowActivity** - a project-scoped instance generated from a Knowledge Core Workflow Template. The scheduling source of truth: planned_start/finish, actual_start/finish, dependency-respecting status.
- **ReasoningInsight** - a persisted CRE finding (severity, domain, observation, recommendation). Only ever written by run_reasoning(); never auto-resolved - POST /insights/{id}/status is the only dismissal path.
- **ConstructionMemory** - a record of a completed activity, captured automatically inside run_reasoning() when it observes completion. Same dependency as ReasoningInsight: nothing populates this for a project that has never had a reasoning run.

## System Boundaries

**What Atlas does NOT have today** (confirmed absent, not just "not yet visible"):
- Commercial/financial data model, calculations, or UI (Portfolio Control Center Phase 1 explicitly stubbed this out - financials: {enabled: false, ...}, all fields null).
- Search screen or Notifications screen - no route, no UI, anywhere.
- Any send/notification mechanism (email, SMS, push) - this is why the "draft a client update" capability was removed rather than kept as a half-feature; there was nothing to send it with.
- Scheduled/background jobs - run_reasoning() only fires when a human (management/PM) explicitly triggers it via the UI, or when the ACDP seed script calls it directly. There is no cron, queue, or worker that runs it automatically for a live project.
- A "learning layer" that reads AI feedback or insight relationships back into behavior - the write paths that would have fed one were removed in the Consolidation Sprint as they had no reader.

**What Atlas explicitly reuses rather than duplicates** (verified during two consecutive audits):
- One canonical detail page per entity type (Event, Operational Item, Project, Workflow Activity, Knowledge Item) - RBAC gates actions, not navigation.
- One health computation (compute_project_health), reused unmodified by Project Health, Portfolio Control Center, and Executive Dashboard - never recomputed a second way.
- One scheduling source of truth per linkage: Workflow Activities own their own schedule; a linked Event's Timeline Planning reads/writes through to the activity rather than keeping a second copy.

## Current Capability Matrix

| Capability | State |
|---|---|
| Auth & RBAC (management/PM/supervisor/client) | Implemented |
| Projects & Sites | Implemented |
| Event Capture (voice/photo/text) | Implemented |
| Canonical Event Detail (all entry points) | Implemented |
| Timeline Planning (events, workflow-aware) | Implemented |
| Workflow (generation, scheduling, dependencies) | Implemented |
| Operations (items, assignment, Assignment Timeline) | Implemented |
| Client Approval Workflow | Implemented |
| AI Proposals (generate/accept/reject/edit/regenerate) | Implemented |
| Client Dashboard | Implemented |
| Executive Dashboard / reasoning | Implemented |
| Portfolio Control Center | Implemented (Phase 1, schedule-only) |
| Construction Reasoning Engine | Implemented |
| Construction Memory | Implemented (depends on a reasoning run having occurred) |
| Morning Briefings | Implemented |
| Knowledge Core | Implemented |
| Atlas Canonical Demo Project (ACDP) | Implemented |
| Event -> Workflow Activity linkage | Structurally implemented, not yet set by any capture flow |
| Commercial Intelligence | Not started |
| Search | Not started |
| Notifications | Not started |
| Site Supervisor: comment / upload additional media / follow-up events | Not started (named in an early RBAC brief, never built anywhere) |

## Developer Setup

    # Backend
    cd backend
    pip install -r requirements.txt --break-system-packages   # includes openai>=1.0.0 - install it in full
    export MONGO_URL="mongodb://localhost:27017"
    export DB_NAME="atlas_dev"
    export JWT_SECRET="devsecret"                              # optional, defaults to this
    # EMERGENT_LLM_KEY is optional - Atlas is fully functional with zero AI configured

    python -m scripts.dev seed          # regular dev seed + ACDP, one command, idempotent
    python -m scripts.dev reset-seed    # reset then seed, with a confirmation prompt (-y to skip)
    uvicorn server:app --reload

    # Frontend
    cd frontend
    npm install
    npx tsc --noEmit                    # should be clean - zero errors as of the Consolidation Sprint
    npx expo start

No .env is committed (correct - these are deployment-specific secrets), so MONGO_URL/DB_NAME must be set before the backend will start; without them core/settings.py raises KeyError immediately.

## Module Ownership (by directory, not by person)

| Directory | Owns |
|---|---|
| backend/engines/ | All business logic. One file per engine (see ARCHITECTURE.md's table). Routes never contain business logic - they validate, call an engine function, and shape the response. |
| backend/routes/ | HTTP surface only - request/response models, permission checks, delegation to engines/. |
| backend/core/ | Cross-cutting: db.py (connection + indexes), auth.py, settings.py. |
| backend/scripts/ | db_seed.py (regular dev data), seed_demo_project.py + acdp_fixtures.py (ACDP), dev.py (the CLI wrapper both are reached through), db_reset.py. |
| frontend/app/ | Screens, one route per file (Expo Router file-based routing). |
| frontend/src/*_api.ts | Typed API wrappers, one module per backend domain (api.ts for events/auth, ops_api.ts for operations, cre_api.ts for reasoning, workflow_api.ts, knowledge_api.ts, admin_*_api.ts). |
| frontend/src/CreDashboard.tsx | The three internal-role CRE card sets (Management/PM/Supervisor), rendered as a ListHeaderComponent on the Home tab. |
| memory/ | Documentation (this file, ARCHITECTURE.md, CRE_ARCHITECTURE.md, CRE_DESIGN.md, ACDP_README.md, ACDP_TIMELINE.md, PROJECT_CONSTITUTION.md, DECISIONS.md, SPRINTS.md). |

## Current Collections

users, projects, sites, events, ai_analyses, ai_proposals, operational_items, operational_events, corrections, prompt_versions, knowledge_items, knowledge_versions, workflow_activities, reasoning_runs, reasoning_insights, construction_memory, raw_assets, seed_metadata

All indexes defined in core/db.py's ensure_indexes(), applied idempotently on every startup. Verified zero orphaned references across every relationship in this graph as of the Platform Health Audit and re-confirmed after the Consolidation Sprint's endpoint removals.

## Current API Modules (by router file)

auth, projects (incl. sites), events, operational_items, ai_proposals, workflow, knowledge, reasoning (incl. Portfolio Control Center), admin_users, admin_system

Every endpoint in every module has at least one frontend caller as of the Platform Consolidation Sprint - the Orphan Endpoint Audit removed the seven that didn't and confirmed the two that looked orphaned but weren't (POST /insights/{id}/status, the list_rules() engine function used by CRE's own test suite).

## Known Extension Points

Genuine seams, not aspirational ones - each of these already has a place designed for it:

- **Commercial Intelligence**: Portfolio Control Center's financials object on every project row is the exact shape a Phase 2 needs to fill - {enabled, budget, forecast_cost, cost_variance, profitability, cash_flow}. No redesign required, just population.
- **Event -> Workflow Activity linkage at capture time**: activity_id already exists on the event schema and Timeline Planning already honors it end-to-end (reads/writes through to the linked activity). The only missing piece is a capture-flow UI step to set it.
- **Scheduled reasoning runs**: reasoning_engine.run_reasoning() is a plain async function with no dependency on being called from an HTTP request - a background scheduler could call it directly, exactly as the ACDP seed script already does, without touching the function itself.
- **Insight feedback / relationships**: the write paths were removed as genuinely dead code (zero readers), but the underlying fields (related_insights, auto-populated by run_reasoning()'s own "previous" linking) were left untouched. A future learning layer has real data to read from related_insights even without the manual-add endpoint that was removed.
- **Search / Notifications**: no code exists to build on, but no code exists to conflict with either - these are true greenfield additions, not gaps in an existing implementation.
