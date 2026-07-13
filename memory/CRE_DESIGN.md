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
