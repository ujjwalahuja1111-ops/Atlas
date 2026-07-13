# CRE Architecture — Canonical Design Document for Atlas Intelligence

Status: canonical. Every future intelligence module (reasoning, learning,
automation) is designed against this document. Sprint history and product
rationale live in `CRE_DESIGN.md`; this document defines the architecture
and its boundaries.

---

## 1. What CRE is

The Construction Reasoning Engine is Atlas' project-wide reasoning layer
(engine slot #7). Its single responsibility: consume what every other
engine already knows about a project — read-only — and answer, with
evidence: **"what does everything happening here collectively mean, and
what should a human do next?"**

CRE is a **deterministic construction reasoning layer**. Its product is a
registry of small, pure, explainable rules. It is not a chatbot, not a
copilot, and not an agent.

## 2. The hard boundary — read this before extending CRE

> **CRE must never evolve into a general LLM agent.**

This is the single most important architectural constraint in this
document, and it is load-bearing for the product itself: construction
firms adopt an advisor that shows its work and cannot touch the project;
they do not hand judgment to a black box. Concretely:

**CRE is allowed to:**
- read any collection in Atlas (through the snapshot layer only);
- evaluate deterministic rules over snapshots;
- write insights and run-audit documents to its own two collections
  (`reasoning_insights`, `reasoning_runs`);
- compute derived, never-stored projections (project health);
- record human decisions *about its own insights* (status, feedback,
  relationships);
- optionally invoke a bounded AI pass that ADDS observations.

**CRE must never** *(permanent architectural rule — Sprint 01B item 12)*:
- **modify workflow** — no status changes, no dependency edits, no
  generation, no scheduling;
- **assign work** — suggesting a responsible role is data; assigning a
  person is a human act in the Operations Engine;
- **complete activities** — only site users complete work;
- **approve work** — approvals (client, proposal, inspection) are human
  judgments; CRE may only observe their presence or absence;
- **change project state** — no document owned by another engine is
  ever created, modified, or deleted by CRE. No operational items, no
  events, no knowledge edits. The insight's
  `suggested_operational_action` is inert; the conversion into a real
  item is a *human* action in a *different* engine (V2), attributed to
  that human.

> **CRE exists to reason. Humans execute.**

Additionally, CRE must never:
- execute, schedule, or trigger site work, notifications-as-actions, or
  external side effects;
- let AI output gate, veto, modify, or replace a deterministic finding —
  AI findings are additive and clearly typed (`ai_observation`);
- allow AI to propose operational actions, responsible roles, or due
  dates. Only deterministic rules may populate `suggested_*` fields;
  the engine enforces this (`_ai_review` hardcodes them to None).
- accept free-text instructions as reasoning input. Rules reason over
  structured snapshots, never over prompts;
- touch authentication, authorization, or role logic beyond consuming
  the stable `get_current_user` and visibility conventions.

**The role of AI, permanently:** enhance *explanation and summarization*
of deterministic findings, and contribute clearly-labelled, capped,
optional, failure-isolated additional observations. Deterministic project
reasoning is the product; AI is commentary on it. Any proposal that
inverts this relationship is out of scope by design, not by omission.

## 3. Atlas' three layers of intelligence

Atlas deliberately separates three intelligence layers so the platform
stays a layered decision-support system, never a monolithic AI engine:

| Layer | Question | Lives in | Examples |
|---|---|---|---|
| **1. Operational Intelligence** | *What happened?* | Reality / Intelligence / Operations / Timeline engines | events, activities, progress, per-item health, delays as recorded facts |
| **2. Construction Intelligence (CRE)** | *What should happen next?* | this engine + `reasoning_projections` | stage awareness, readiness, look-ahead, risks, dependencies, forecasts, recommendations |
| **3. Business Intelligence** | *What should management do?* | future module; today only *views* (executive answers, briefings, client summaries) computed from layer 2 | resource allocation, procurement priorities, cash flow, executive summaries |

Layer 1 reflects the site. Layer 2 interprets project execution. Layer 3
supports management decisions. CRE is layer 2; the executive/briefing/
client-summary endpoints are layer-3 *views over layer-2 outputs* and
will migrate into a dedicated Business Intelligence module when one
exists — their logic is already separated (pure composition functions in
`reasoning_projections`) precisely so that migration is a move, not a
rewrite. No layer may bypass the one below it.

## 4. Data flow

```
 Reality Engine ──► events / raw_assets ──► Intelligence (per-event AI)
                                                   │
                                             ai_proposals ──► human decision
                                                   │
 Knowledge Core ──► workflow generation      operational_items (Operations)
        │                  │                        │
        ▼                  ▼                        ▼
   ┌──────────────────────────────────────────────────────────┐
   │ SNAPSHOT LAYER  build_project_snapshot(project_id)       │  reads only
   │ one plain dict: activities, items, events, media links,  │
   │ proposal decisions, inferred lifecycle STAGE.            │
   │ SNAPSHOT_SCHEMA_VERSION documented.                      │
   └────────────────────────────┬─────────────────────────────┘
                                ▼
   ┌──────────────────────────────────────────────────────────┐
   │ REASONING LAYER (pure, no I/O)                           │
   │  rule registry: snapshot -> findings (schema v2,         │
   │    stage-stamped)                                        │
   │  reasoning_projections: stage inference, look-ahead &    │
   │    readiness, delay forecast, briefing, client summary,  │
   │    portfolio digests, blocking impact, memory records    │
   │  compute_project_health: snapshot -> 5 dimensions        │
   │  optional bounded AI review (additive only)              │
   └────────────────────────────┬─────────────────────────────┘
                                ▼
   ┌──────────────────────────────────────────────────────────┐
   │ PERSISTENCE LAYER (writes ONLY CRE's own collections)    │
   │  dedupe -> reasoning_insights   audit -> reasoning_runs  │
   │  learning substrate -> construction_memory (capture      │
   │  only; nothing reads it back)                            │
   └────────────────────────────┬─────────────────────────────┘
                                ▼
                     humans decide (status / feedback /
                     relationships), recorded on the insight
```

All Mongo reads happen in exactly one function
(`build_project_snapshot`); all knowledge-derived facts are read through
the accessor helpers (`_act_requires_inspection`, `_act_dependency_ids`,
`_act_knowledge_ref`). Upstream schema evolution is absorbed in those two
places; rules never change for schema reasons. That is the stable
knowledge interface.

## 5. The insight contract (schema v2)

Every insight must be able to answer *"why did CRE reach this
conclusion?"* without any additional query:

- **Reasoning chain**: `observation` (what is true) → `risk` (what
  happens if ignored) → `recommendation` (what a human should do) →
  `suggested_operational_action` {category from the Operations Engine's
  existing vocabulary, title, description} → `suggested_responsible_role`
  → `suggested_due_date`. All `suggested_*` fields are recommendations
  only; nothing reads them back or executes them.
- **Evidence**: an explicit object with seven always-present sections —
  `workflow_activities`, `operational_items`, `events`, `media`,
  `approvals`, `knowledge_items`, `absences` — each a list of
  `{id, detail}` references to the concrete documents reasoned over.
  `absences` is negative evidence: what CRE looked for and did not find
  (mandatory for absence-of-evidence rules). Conclusions without
  evidence are rejected by tests.
- **Confidence**: `{level, reason, missing_evidence, assumptions,
  contradictions}`. Direct-state rules are `high`; inference over
  absence is `medium` at most, and must name what would raise it.
- **Identity & idempotency**: `dedupe_key = rule_id:subject_id`. Open
  insights are refreshed, never duplicated. Resolved keys re-emit fresh
  insights auto-linked `previous`.

## 6. Insight lifecycle (canonical for all future intelligence modules)

```
open ──► acknowledged ──► operational_item_created ──► resolved
  │            │
  └────────────┴─────────► dismissed          expired (system-set)
```

- `open` — emitted by a reasoning run; refreshed on re-observation.
- `acknowledged` — a human has seen it (optional stop).
- `operational_item_created` — a human converted the suggestion into a
  real operational item (arrives with the V2 conversion flow; the item
  is created by the Operations Engine, attributed to the human).
- `resolved` — the human dealt with it (implemented today as `actioned`).
- `dismissed` — the human judged it not worth acting on.
- `expired` — system-set terminal state for insights whose conditions
  aged out without human action (arrives with scheduled runs).

No reopening, ever: recurrence emits a fresh insight linked `previous`,
so the decision trail is append-only in spirit. Status changes append to
the insight's own `status_history`.

## 7. Human feedback loop (learning preparation — NOT learning)

Every insight can store a human verdict — `accepted`, `rejected`,
`modified`, `ignored` — with optional reasoning, revisable, with full
`feedback_history`. **Nothing reads feedback back today.** The future
learning layer consumes it under these rules: learning may tune rule
*parameters* (thresholds, windows, weights) per company from feedback and
outcomes; it may never invent rules, alter evidence, or bypass the
deterministic layer. Same boundary as AI: learning adjusts the dials on
explainable machinery; it does not replace the machinery.

## 8. Insight relationships (multi-step reasoning preparation)

Insights can reference other insights: `previous` (auto-set on
recurrence), `duplicate`, `supports`, `conflicts` — same project only,
idempotent per (target, relation). This is the substrate for future
multi-step reasoning (chains of findings that jointly imply a
higher-order conclusion) without any schema change later.

## 9. Project health

Five reasoned dimensions — Schedule, Quality, Safety, Communication,
Operational — each `{score, explanation, contributing_factors}`, computed
purely from a fresh rule evaluation over the snapshot. Not AI. Never
stored (recomputed on read, like `derive_health`; it cannot go stale and
needs no new collections). The overall score deliberately leans toward
the weakest dimension: a project is not "green on average" while safety
is on fire.

## 10. The construction intelligence surface (Sprint 01B)

All of the following live in `reasoning_projections.py` as pure
functions over snapshots; the engine only wraps them in visibility
checks. Like health, none of it is stored — recomputed on read, never
stale. None of it is AI.

- **Stage awareness** — `infer_project_stage` classifies activities into
  the canonical lifecycle (pre_construction → excavation → foundation →
  rcc_structure → masonry → waterproofing → mep → finishes →
  testing_commissioning → handover) by transparent keyword/trade
  vocabulary, and derives the current stage from the workflow itself
  (work in flight wins; else earliest incomplete). Every snapshot
  carries `stage`; every insight is stamped `project_stage`. When the
  Knowledge Core later carries explicit stage tags, only
  `stage_of_activity` changes.
- **Look-ahead & readiness** — `project_lookahead` answers *what should
  happen next and is the project ready for it*: frontier activities
  (dependencies complete), why each is expected, readiness prerequisites
  (`activity_readiness`: dependencies, predecessor inspection —
  one shared `inspection_covered` definition with the quality rule —
  drawings, client approvals, materials; checklist honestly `unknown`
  until modelled), possible blockers, recommended preparation, and the
  "Ready for X" list.
- **Delay forecast** — `delay_forecast`: current progress → historical
  productivity (median actual/planned over this project's completed
  activities) → dependency propagation → likely completion vs plan →
  structural confidence (sample depth × planned-date coverage, with
  stated assumptions). Deterministic; no AI estimation; the optimistic
  floor is an explicit assumption. Surfaced as a rule
  (`schedule.forecast_finish_slip`) when slip ≥ 3 days.
- **Daily briefing** — `compose_daily_briefing`: completed yesterday,
  today's priorities, blocked activities, required decisions, upcoming
  milestones, client actions, material risks, safety reminders.
- **Client communication intelligence** — `compose_client_summary`:
  operational facts → construction progress → plain-English draft.
  Built ONLY from workflow-level facts; never leaks internal ids,
  safety detail, or operational data; always a draft for human review.
  AI may later enhance *wording*, never content.
- **Executive reasoning** — a fixed vocabulary of portfolio questions
  (`EXECUTIVE_QUESTIONS`: attention today, greatest risk, top blocker,
  overdue approvals, stalled projects, tomorrow, supervisor load), each
  answered by explicit deterministic reasoning over the caller's visible
  projects. Not conversational AI: unknown questions are a 400.
- **Multi-project awareness** — `project_digest` is the frozen unit of
  portfolio reasoning; `compare_projects_at_stage` is a reserved
  INTERFACE (raises NotImplementedError) for future comparative
  intelligence once Construction Memory accumulates stage dwell-time
  baselines. Comparison will always be against the portfolio's own
  measured baselines, never invented ones.
- **Construction memory** — `construction_memory` (CRE-owned): one
  record per completed activity — planned vs actual duration, variance,
  stage, material delays / approvals / issues in its window, and
  explicit placeholders (weather, labour count) until those sources
  exist. Captured idempotently during reasoning runs. **Nothing reads
  these records back**; the future learning layer consumes them under
  section 7's boundary.

## 11. Extension points

| To add… | Touch… | Never touch… |
|---|---|---|
| a new rule | one pure function + `@rule(id, domain, description)` + unit tests | snapshot layer, persistence, routes |
| a new domain | `DOMAINS` (metadata) | existing rules |
| a new upstream data source | `build_project_snapshot` (+ knowledge accessors if knowledge-derived) | any rule |
| a new projection (briefing section, readiness check, executive question) | a pure function in `reasoning_projections` + a thin view/answer branch | rule semantics, persistence |
| stage vocabulary refinement / Knowledge Core stage tags | `stage_of_activity` only | everything built on stage |
| multi-project comparison (future) | implement `compare_projects_at_stage` against Construction Memory baselines | digest schema (frozen) |
| the Business Intelligence layer (future) | new module consuming layer-2 outputs (digests, briefings, executive answers migrate there) | CRE's reasoning core |
| event-driven triggers (V2) | a subscription hook other engines call; runs stay idempotent so trigger frequency is a non-issue | rule semantics |
| insight→item conversion (V2) | Operations Engine route acting on `suggested_operational_action`, attributed to the human; sets `operational_item_created` | CRE write scope |
| scheduled runs + `expired` (V2) | run orchestration | lifecycle semantics |
| learning (V3) | a separate layer consuming `feedback_history` + outcomes, tuning rule parameters | rule structure, evidence, the deterministic core |
| AI explanation/summarization | presentation of deterministic findings | `suggested_*` fields, finding content, health |

## 12. Verification obligations for future intelligence work

Anything extending CRE inherits the three-layer verification convention:
pure unit tests for reasoning logic (no DB), full-stack HTTP tests
against the real app (mongomock-motor), and the live-deployment suite.
Two structural tests must never be weakened: the read-only guarantee
(reasoning runs change nothing outside CRE's collections) and the
contract test (no conclusions without evidence, no unexplained
confidence).
