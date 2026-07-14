# Construction Reasoning Engine (CRE) — Innovation Sprint 01

Branch: `innovation/construction-reasoning-engine` (independent; touches no
authentication, user-management, or role logic; merges alongside FAC-line work).

> **Sprint 01A refinement (see final section):** the insight schema
> described below was refined to v2 — explicit evidence sections,
> structured explainable confidence, the observation→risk→recommendation
> →suggested-action chain, five-dimension health, feedback + relationship
> substrates. The canonical architecture document for all future
> intelligence work is **`CRE_ARCHITECTURE.md`**; this file records
> sprint history and product rationale.

---

## Phase 1 — Repository review

### Engine map as found (verified against code, commit `75fb789`)

| Engine | Module | What it actually does | CRE relationship |
|---|---|---|---|
| Reality | `engines/reality_engine.py` | Captures voice/photo/text/GPS; persists before AI; <300ms | upstream source (read-only) |
| Memory | `engines/memory_engine.py` | Sole writer of core facts; users/projects/sites/events/assets | reused for project lookup + `_is_project_scoped` |
| Intelligence | `engines/intelligence_engine.py` | Async worker; Whisper + GPT-4o per single event; evidence + prompt versioning; emits proposals | pattern donor: evidence arrays, optional-AI, failure isolation |
| Timeline | `engines/timeline_engine.py` | Chronological projection | sibling projection |
| Operations | `engines/operations_engine.py` | Item lifecycle over an append-only ledger; `derive_health` per item | upstream source (read-only) |
| Knowledge | `engines/knowledge_engine.py` | Global curated reference data (activities, dependencies, `requires_inspection`) | indirect source via denormalized workflow instances |
| Construction Workflow | `engines/workflow_engine.py` | Project-scoped activity instances; dependency-gated status; Sprint 6.1 planned/actual dates stored **with analytics explicitly deferred** | primary upstream source |
| #7 (reserved) | — | "reasoning/automation" slot in ARCHITECTURE.md | **CRE fills this slot** |

### Current data flow (verified)

capture → events/raw_assets → AI analysis (per-event) → proposals → human
decision → operational items → per-item health. Every intelligence step is
**local**: one event, one item. Nothing reads *across* the project.

### Extension points found (and used)

1. `workflow_activities.planned_/actual_*` (Sprint 6.1) — stored, never
   analyzed. The sprint docstring literally says it is "the foundation for
   future delay detection / schedule variance reporting, not that reporting
   itself." CRE is that reporting.
2. `depends_on_activity_ids` — a per-project dependency graph already
   denormalized from the Knowledge Core. CRE's construction-logic rules
   generalize over it instead of hardcoding sequences.
3. Activity `requires_inspection` (Sprint 5) — stored, never enforced or
   monitored. CRE's quality rule closes that loop advisorily.
4. `operational_items` health/required_by/category — per-item signals CRE
   aggregates into project-level meaning.
5. `events.activity_id` (Sprint 6.1, reserved) — future join between raw
   reality and workflow activities; CRE's snapshot already carries it.

### Assumptions checked, not assumed

- No existing cross-project reasoning exists (confirmed: engine slot #7 reserved).
- Operational items carry `project_id` since Sprint 2 but old docs may not —
  snapshot queries by `project_id OR site_id ∈ project sites`.
- Auth surface under active change → CRE reuses only the stable
  `get_current_user` dependency and the `workspace == "client"` /
  `role == "supervisor"` gating conventions; zero auth files modified.

---

## Phase 2 — CRE design

### One-sentence responsibility

Continuously answer, with evidence: *"what does everything happening across
this project collectively mean, and what should a human do next?"*

### Architecture (three strictly separated layers)

```
            ┌────────────────────────────────────────────────┐
            │  Snapshot layer (async, READ-ONLY over Mongo)  │
            │  build_project_snapshot(project_id) → dict     │
            └───────────────────────┬────────────────────────┘
                                    ▼
            ┌────────────────────────────────────────────────┐
            │  Reasoning layer (PURE, no I/O)                │
            │  rule registry: snapshot → findings            │
            │  compute_project_health: snapshot → projection │
            │  + optional additive AI review (never blocks)  │
            └───────────────────────┬────────────────────────┘
                                    ▼
            ┌────────────────────────────────────────────────┐
            │  Persistence layer (writes ONLY CRE's own      │
            │  collections): dedupe → reasoning_insights,    │
            │  audit → reasoning_runs                        │
            └────────────────────────────────────────────────┘
```

Why this shape:
- **Read-only over other engines' data** makes "CRE never executes work"
  a structural property, not a policy. The smoke suite asserts it.
- **Pure rules** make every piece of construction logic unit-testable
  without a database (`tests/test_cre_rules.py`, 20 tests) and make a
  future replay/simulation mode trivial (persist snapshot → re-reason).
- **Reason first, AI second**: deterministic rules are the product; the
  LLM pass is additive, optional (off without a key, off by default per
  run), capped, schema-validated, and failure-isolated — the exact
  pattern Sprint 5.0.2 established for the Intelligence worker.

### The insight contract (sprint-mandated, enforced by `_finding()` asserts)

Every insight carries: `observation`, `evidence[]` (typed refs to the
concrete documents that justify it, mirroring `ai_analyses.evidence`),
`reasoning`, `confidence` (low/medium/high — *honest*: direct-state rules
are high, absence-of-evidence inferences are medium), `project_id`/`name`,
`affected_activity_id`/`name`, `recommended_action`, `severity`,
`rule_id`, `dedupe_key`.

### Storage

| Collection | Mutability | Purpose |
|---|---|---|
| `reasoning_insights` | status lifecycle only; decisions appended to in-doc `status_history` | one doc per distinct open finding; `open → acknowledged → actioned/dismissed`; no reopen (recurrence emits a fresh insight — cleaner audit) |
| `reasoning_runs` | append-only | who ran reasoning, when, snapshot stats, rules evaluated, new vs refreshed counts, AI on/off |

Idempotency: `dedupe_key = rule_id:subject_id`. Re-running on unchanged
state refreshes `last_seen_at`/`times_seen` on the open insight instead of
duplicating. A human-resolved key is free again — recurrence is new signal.

### MVP rule set (8 deterministic rules across 7 mandated domains)

| Rule | Domain | Confidence | Logic |
|---|---|---|---|
| `schedule.planned_start_missed` | schedule | high | planned_start past, unstarted |
| `schedule.planned_finish_missed` | schedule | high | planned_finish past, incomplete; names downstream dependents (critical-path awareness) |
| `construction_logic.successor_not_started` | construction_logic | high | all dependencies completed ≥3 days, successor untouched — the generalized "Excavation done → begin PCC", derived from the project's own dependency graph |
| `construction_logic.activity_blocked` | construction_logic | high | blocked activity halts its chain |
| `quality.completed_without_inspection` | quality | **medium** | `requires_inspection` activity completed, no inspection item recorded since it began → *verify*, don't assert |
| `safety.unresolved_high_priority` | safety | high | high/critical safety observation open >24h |
| `procurement.material_lead_time` | procurement | high | open material need within/past 3-day lead window |
| `management.stale_open_item` | management | high | open item silent ≥7 days |
| `client_communication.progress_update_due` | client_communication | medium | ≥3 completions in 7 days, no client-facing item since |

Labour/equipment/weather/cost rules are deliberately deferred (Phase 4) —
current data is too thin to reason honestly about them, and a rule that
guesses erodes trust in every rule that doesn't.

### API (thin routes, established `_raise_for` convention)

```
POST /api/projects/{id}/reasoning/run     coordinator/management; {include_ai}
GET  /api/projects/{id}/insights          internal roles; ?status=&domain=
GET  /api/projects/{id}/health            derived projection, never stored
GET  /api/projects/{id}/reasoning/runs    audit trail
POST /api/insights/{id}/status            coordinator/management; the human decision
GET  /api/reasoning-meta                  vocab for a future Insights UI
```

Client workspace is blocked from all of it (Sprint 6.2 client-permission
philosophy: internal operational intelligence stays internal). Supervisors
read but don't trigger/decide (same split as workflow generation).

### Access + scoping

Project visibility reuses the exact `_assert_project_visible` convention
from `workflow_engine` (out-of-scope → 404). No auth file touched.

---

## Phase 3 — Implementation (this branch)

| File | Nature |
|---|---|
| `backend/engines/reasoning_engine.py` | new engine (snapshot + 9 rules + health + optional AI + persistence) |
| `backend/routes/reasoning.py` | new thin router |
| `backend/server.py` | +2 additive lines (import, include_router) |
| `backend/core/db.py` | +4 additive lines (CRE indexes) |
| `backend/tests/test_cre_rules.py` | 20 pure unit tests — every rule, contract completeness, dedupe determinism, malformed-data survival, health math |
| `backend/tests/test_cre_smoke_mongomock.py` | 10 full-stack tests: real app over HTTP (mongomock-backed Motor); proves idempotent reruns, read-only guarantee, lifecycle, all gates |
| `backend/tests/test_atlas_cre.py` | live-deployment suite (FAC-03 bootstrap conventions); builds the scenario through public APIs only and verifies CRE end-to-end on the running application |

Verified in this sprint: 30/30 tests pass locally (unit + mongomock
full-stack); app imports cleanly with all 6 endpoints registered in the
OpenAPI schema. The live suite is committed for execution against the
deployed environment per the standard verification process.

---

## Phase 4 — Roadmap

**MVP (this branch):** on-demand reasoning runs, 9 rules, health, insight
lifecycle, run audit, optional AI review.

**V2 — event-driven + closing the loop**
- Trigger reasoning automatically from an in-process hook (the same
  asyncio-queue worker pattern as the Intelligence engine) on: workflow
  status change, proposal acceptance, item transitions, daily schedule.
  Done as a *subscription* the emitting engines call into via one added
  line each — deferred now purely for branch discipline.
- "Create operational item from insight": one-tap conversion of a
  recommendation into an assigned item (`origin_type` gains
  `reasoning_insight`) — the human still decides; CRE still never acts.
- Join `events.activity_id` (already reserved) so site reality
  auto-corroborates workflow status ("photos of brickwork on an activity
  still marked not_started").
- Insights UI: project health card + insight inbox in the PM/Admin
  workspaces, consuming `/reasoning-meta` vocab.

**V3 — learning + prediction**
- Outcome feedback: dismissed-with-note insights feed rule threshold
  tuning per company (the reserved Learning engine's first real consumer).
- Duration learning: actual_start/actual_finish across completed projects
  → company-specific duration priors per activity/trade → probabilistic
  delay forecasts instead of binary overdue flags.
- Procurement lead-time learning per material/vendor from item lifecycles.
- Labour/equipment reasoning once capture density supports it.
- External signals (weather, procurement systems) as additional snapshot
  sections — the snapshot layer is the single integration point, so new
  sources require zero rule-layer changes.

**Long term:** cross-project portfolio reasoning ("every project using
vendor X is slipping"), simulation ("what happens to handover if PCC slips
a week" — replay over persisted snapshots), and knowledge-base authoring
suggestions ("projects keep inserting an unmodelled curing step after
brickwork — add it to the Activity Library?").

---

## Phase 5 — Competitive advantage

Every construction tool on the market records; a few analyze single
artifacts. Atlas with CRE is different in kind, not degree:

1. **The moat compounds.** CRE's construction logic is derived from the
   customer's own curated Knowledge Core, dependency graphs, and (V3)
   their measured durations and vendor lead times. A competitor can copy
   the rule engine in a quarter; they cannot copy years of a company's
   accumulated workflows, corrections, and outcome history — which is
   what makes CRE's output *right for that company*.
2. **Trust by construction.** Structurally read-only, every insight
   evidence-backed with honest confidence, every human decision recorded.
   Construction firms will not hand judgment to a black box; they will
   adopt an advisor that shows its work and never touches the project.
   That trust profile is the adoption wedge competitors' "AI copilot"
   framing lacks.
3. **AI where it earns its keep.** Deterministic reasoning is free,
   instant, explainable, and works offline-cheap; the LLM adds
   cross-cutting pattern detection on top. Cost and reliability scale
   with customers; pure-LLM competitors' costs and hallucination risk do.
4. **It converts existing capture into new value.** Every voice note a
   supervisor already records makes project-level reasoning sharper —
   the platform's daily use *is* the training of its intelligence layer.

### Assumption challenged

The brief says "continuously." True continuity (V2 event-driven triggers)
is deliberately not in the MVP: it requires one-line hooks inside engines
the parallel sprint may be touching, and shipping the reasoning substrate
first — pure, tested, idempotent — means the V2 trigger change is trivial
and conflict-free later. The MVP's on-demand run + idempotent dedupe
already behaves correctly under arbitrary trigger frequency, so the
event-driven upgrade changes *when* reasoning happens, not *what* it does.

---

## Innovation Sprint 01A — Architectural refinement (no new rules)

Objective: refine CRE into the long-term reasoning architecture while
FAC-04 stabilization continues independently. No new rules, no new AI
features, no operational workflow changes, no production branch changes.

What changed (insight schema v1 → v2):

1. **Evidence-based reasoning.** `evidence` became an explicit object
   with seven always-present sections — workflow_activities,
   operational_items, events, media, approvals, knowledge_items, and
   `absences` (negative evidence: what was looked for and not found).
   Site events linked to an activity (`events.activity_id`) and their
   captured media now corroborate — or contradict — schedule and
   construction-logic findings. Knowledge Core traceability
   (`knowledge_activity_id`) is cited where the rule's logic came from it.
2. **Structured confidence.** The single value became
   `{level, reason, missing_evidence, assumptions, contradictions}` —
   every insight answers "why did CRE reach this conclusion?"
3. **Recommendation chain.** Findings separated from actions:
   observation → risk → recommendation → suggested_operational_action
   (reusing the Operations Engine's existing category vocabulary — no
   new taxonomies) → suggested_responsible_role → suggested_due_date
   (severity-scaled). All suggestions are inert data; CRE never executes.
4. **Five-dimension health.** Schedule / Quality / Safety /
   Communication / Operational, each {score, explanation,
   contributing_factors}, computed purely from a fresh rule evaluation —
   not AI, never stored, no new collections. Overall leans toward the
   weakest dimension.
5. **Canonical lifecycle** documented for all future intelligence
   modules: open → acknowledged → operational_item_created → resolved /
   dismissed / expired (today's `actioned` implements `resolved`;
   `operational_item_created` and `expired` arrive with V2 flows).
6. **Human feedback loop (preparation only).** Insights store
   accepted / rejected / modified / ignored verdicts with optional human
   reasoning and full history. Nothing reads feedback back — learning is
   deliberately not implemented.
7. **Insight relationships.** previous / duplicate / supports /
   conflicts, same-project, idempotent; recurrence after human
   resolution auto-links `previous`, so reasoning history forms a chain.
8. **Explicit domain metadata.** Every rule registers with
   `@rule(id, domain, description)`; findings are re-checked against
   their rule's domain. `commercial`, `documentation`,
   `resource_planning` reserved as metadata-only domains.
9. **Stable knowledge interface.** All Mongo reads live in
   `build_project_snapshot` (versioned contract); knowledge-derived
   facts are read only through accessor helpers. Upstream schema
   evolution is absorbed there; rules never change for schema reasons.
10. **Canonical architecture document** — `CRE_ARCHITECTURE.md` —
    including the permanent boundary: CRE remains a deterministic
    construction reasoning layer; AI enhances explanation and
    summarization and may add bounded, clearly-typed observations
    (never operational suggestions); CRE must never evolve into a
    general LLM agent.

API additions: `POST /api/insights/{id}/feedback`,
`POST /api/insights/{id}/relationships`; `/api/reasoning-meta` now
exposes rules-with-domains, canonical lifecycle, evidence kinds,
feedback verdicts, relation types, and health dimensions.

Verification: 25 pure rule unit tests + 12 full-stack HTTP tests (real
app on mongomock-motor) — 37/37 passing locally; live-deployment suite
updated to the v2 contract. The two structural guarantees (read-only
runs, no conclusions without evidence) are pinned by tests.

---

## Innovation Sprint 01B — Construction Reasoning Evolution

Objective: evolve CRE from a rule engine into a **Construction Project
Intelligence Layer** — preserving the deterministic, explainable core.
New module `engines/reasoning_projections.py` holds every new capability
as pure functions over snapshots (no I/O), imported by the engine.

1. **Stage awareness.** Canonical lifecycle (pre_construction …
   handover) inferred deterministically from the workflow itself via a
   transparent keyword/trade vocabulary; snapshot carries `stage`; every
   insight is stamped `project_stage`.
2. **Look-ahead intelligence.** `GET /projects/{id}/lookahead`: next
   expected activities, why expected (dependency graph), readiness
   prerequisites, possible blockers, recommended preparation.
3. **Construction readiness.** "What is ready?" — frontier activities
   with zero readiness gaps surface as "Ready for X".
4. **Delay forecast.** `GET /projects/{id}/forecast` + new rule
   `schedule.forecast_finish_slip`: progress → measured productivity
   (median actual/planned) → dependency propagation → likely slip →
   structural confidence. Deterministic; no AI estimation; the
   optimistic floor is a stated assumption.
5. **Material readiness.** New rule `procurement.frontier_material_gap`:
   sequence clear + unfulfilled materials in the lead window → risk +
   recommendation, with the missing activity-material mapping honestly
   named in confidence. No procurement automation.
6. **Quality readiness.** `activity_readiness` checks: dependencies,
   predecessor inspection (shared `inspection_covered` definition with
   the quality rule), drawings, client approvals, materials; checklists
   reported `unknown` until modelled.
7. **Multi-project awareness — interfaces only.** `project_digest`
   frozen as the unit of portfolio reasoning;
   `compare_projects_at_stage` reserved (NotImplementedError) until
   Construction Memory accumulates baselines.
8. **Executive questions.** `GET /reasoning/executive?question=…` —
   fixed vocabulary (attention_today, greatest_risk, top_blocker,
   overdue_approvals, stalled_projects, tomorrow, supervisor_load),
   deterministic answers over the caller's visible projects, each with
   an explanation. Unknown questions are a 400 — no conversational AI.
9. **PM daily briefing.** `GET /projects/{id}/briefing`: completed
   yesterday, today's priorities, blocked activities, required
   decisions, upcoming milestones, client actions, material risks,
   safety reminders.
10. **Client communication intelligence.**
    `GET /projects/{id}/client-summary`: deterministic plain-English
    draft from workflow facts only (no internal ids, no safety detail);
    always for human review; AI may later enhance wording, never content.
11. **Construction memory.** CRE-owned `construction_memory` collection:
    per completed activity — planned/actual duration, variance, stage,
    material delays / approvals / issues in window, explicit
    placeholders for weather and labour. Captured idempotently during
    runs; **nothing reads it back** (no learning).
12. **Permanent boundary documented** in CRE_ARCHITECTURE.md §2: CRE
    must never modify workflow, assign work, complete activities,
    approve work, or change project state. *CRE exists to reason.
    Humans execute.* Plus the three-layer intelligence model
    (Operational / Construction / Business) as the platform's target
    shape — executive/briefing/client views are layer-3 views over
    layer-2 outputs, isolated for clean future migration.

Scope discipline held: zero shared production files (core/db.py index
registration deferred via lazy in-engine ensure), zero auth changes,
zero operational-engine changes; server.py untouched (router was already
wired). Verification: 25 + 15 + 19 = 59 tests passing locally across
three layers; live suite extended with the 01B surface.

---

## Innovation Sprint 01C — Merge Readiness (architectural audit)

No new features. Every change below exists to make CRE safer to merge
and cheaper to maintain; each entry states the WHY.

**Synchronization.** `main` moved during the innovation track
(75fb789 → 42fe7e7: FAC-04 Final Authorization Model Freeze, FAC-OPS
sprints). The branch was **rebased onto the new main** so all testing
runs against the real production base, not a stale one. The full suite
passed post-rebase unchanged — which itself exposed the audit's most
important finding: CRE's role gates were testing against their own stale
seeds, not the frozen model.

**1. FAC-04 role-model alignment** *(merge-critical correctness)*
- Route gates: `workspace == "client"` → `role == "client"` (client is a
  first-class role; workspace is derived); supervisor-deny →
  management/project_manager allowlist, mirroring main's own routes.
- `SUGGESTED_ROLES` → `{site_supervisor, project_manager, management}`;
  every rule's suggested owner updated; executive supervisor-load
  queries `role == "site_supervisor"`.
- All three test suites seed the frozen vocabulary; a guard test pins
  `SUGGESTED_ROLES` and route role-literals to `memory_engine.ROLES`, so
  the next vocabulary change fails CI instead of shipping stale gates.

**2. Shared-file merge surface minimized** — CRE's four index lines
removed from `core/db.py` (now byte-identical to main); the engine
ensures all its indexes lazily (`_ensure_indexes_once`). The branch's
entire shared diff is server.py's two additive router lines. WHY: the
smaller the shared surface, the smaller the conflict space for every
parallel FAC sprint between now and merge.

**3. Single responsibility / interface audit**
- Project-visibility enforcement moved fully INSIDE the engine
  (`list_insights` now takes `user`; status/feedback/relationship assert
  the insight's project); routes no longer call the engine's private
  `_assert_project_visible` or prefetch insights. WHY: one place owns
  authorization-adjacent logic; routes are pure HTTP translation (and a
  guard test now enforces that routes never touch db or engine privates).
- Routes' import edge reduced to `reasoning_engine` only (projection
  vocab reached through the engine). WHY: one dependency direction.
- Deleted overlapping public API `list_rule_ids` (kept `list_rules`).

**4. Duplication consolidated**
- One `TERMINAL_ITEM_STATUSES` + `active_items()` (projections), used by
  rules, readiness, briefing and executive answers — previously three
  copies of the terminal-status tuple.
- One snapshot clock: `snapshot_now()` replaces six repetitions of
  `_parse_iso(snap["generated_at"]) or _now()`. WHY: replayability is a
  property of having exactly one clock.
- `frontier()` made public (it was cross-module private access).
- Dead code deleted: no-op branch in `project_lookahead`, unused `kref`,
  redundant conditional around successor knowledge evidence,
  `blocking_impact`'s per-iteration map rebuild hoisted.

**5. Idempotency bug fixed** — the client-communication insight's dedupe
key embedded the ISO week, so a long-open insight re-emitted every week
as a duplicate. Subject is now the project id; a guard test pins the
stable key. WHY: dedupe keys are identity — identity must not rotate
with the calendar.

**6. Contradiction eliminated** — `successor_not_started` could say
"Begin PCC" while `frontier_material_gap` said "hold the start until
materials clear". The successor rule is now readiness-aware: with gaps
it recommends clearing them then beginning; clean pipeline restores the
plain "Begin". A guard test asserts the two rules can never pull in
opposite directions.

**7. AI evidence honesty** — AI-cited references were dumped under the
`events` evidence kind. They are now classified into the correct kinds
by Atlas' deterministic id prefixes (wfa_/op_/evt_/ast_/prop_/kn_);
unrecognized citations are named as such under `absences`. AI-inclusive
runs record `ai_prompt {name, version, model}` in the run audit
(intelligence-engine convention) — making the previously-unused prompt
constants purposeful and the AI Gateway seam fully auditable. Run docs
also record `memory_records_captured`.

**8. Determinism hardened** — tie-breaker keys added to every ranked
output (forecast per-activity, blocking impact, executive rankings and
load) so equal scores order identically on every replay.

**9. New guard infrastructure** (`test_cre_architecture_guards.py`,
9 tests): layer-purity source scans (projections: no I/O of any kind;
engine mutates only its three collections; routes: no db), role-drift
guard, a full-registry contract snapshot that fires ALL 11 rules and
validates the complete schema-v2 contract on each, byte-identical
determinism + snapshot-immutability + snapshot-clock replay tests, the
non-contradiction test, and the dedupe-stability regression. WHY: the
permanent boundaries are now machine-verified on every run, not
documented aspirations.

**10. Integration seams documented** (CRE_ARCHITECTURE.md §12): AI
Gateway → `_ai_review` only; Context Builder → `build_project_snapshot`
only; Knowledge Graph → knowledge accessors + `stage_of_activity` only;
Memory expansion → `build_memory_record` + schema version only. If a
future integration needs to touch more than its seam, the design is
wrong.

**Regression:** 68/68 locally (25 rules + 15 projections + 9 guards +
19 full-stack HTTP on the real app), pyflakes-clean, app boots on the
FAC-04 base with all 14 CRE endpoints registered. Live suite updated to
frozen-model bootstrap (no workspace endpoint).

> When in doubt, prefer deleting, simplifying or consolidating over
> adding new code.
