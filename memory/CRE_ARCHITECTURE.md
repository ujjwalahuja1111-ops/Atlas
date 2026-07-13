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

**CRE must never:**
- create, modify, or delete any document owned by another engine — no
  operational items, no workflow status changes, no events, no knowledge
  edits. The insight's `suggested_operational_action` is inert data; the
  conversion into a real item is a *human* action in a *different*
  engine (V2), attributed to that human.
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

## 3. Data flow

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
   │ proposal decisions. SNAPSHOT_SCHEMA_VERSION documented.  │
   └────────────────────────────┬─────────────────────────────┘
                                ▼
   ┌──────────────────────────────────────────────────────────┐
   │ REASONING LAYER (pure, no I/O)                           │
   │  rule registry: snapshot -> findings (schema v2)         │
   │  compute_project_health: snapshot -> 5 dimensions        │
   │  optional bounded AI review (additive only)              │
   └────────────────────────────┬─────────────────────────────┘
                                ▼
   ┌──────────────────────────────────────────────────────────┐
   │ PERSISTENCE LAYER (writes ONLY CRE's own collections)    │
   │  dedupe -> reasoning_insights   audit -> reasoning_runs  │
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

## 4. The insight contract (schema v2)

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

## 5. Insight lifecycle (canonical for all future intelligence modules)

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

## 6. Human feedback loop (learning preparation — NOT learning)

Every insight can store a human verdict — `accepted`, `rejected`,
`modified`, `ignored` — with optional reasoning, revisable, with full
`feedback_history`. **Nothing reads feedback back today.** The future
learning layer consumes it under these rules: learning may tune rule
*parameters* (thresholds, windows, weights) per company from feedback and
outcomes; it may never invent rules, alter evidence, or bypass the
deterministic layer. Same boundary as AI: learning adjusts the dials on
explainable machinery; it does not replace the machinery.

## 7. Insight relationships (multi-step reasoning preparation)

Insights can reference other insights: `previous` (auto-set on
recurrence), `duplicate`, `supports`, `conflicts` — same project only,
idempotent per (target, relation). This is the substrate for future
multi-step reasoning (chains of findings that jointly imply a
higher-order conclusion) without any schema change later.

## 8. Project health

Five reasoned dimensions — Schedule, Quality, Safety, Communication,
Operational — each `{score, explanation, contributing_factors}`, computed
purely from a fresh rule evaluation over the snapshot. Not AI. Never
stored (recomputed on read, like `derive_health`; it cannot go stale and
needs no new collections). The overall score deliberately leans toward
the weakest dimension: a project is not "green on average" while safety
is on fire.

## 9. Extension points

| To add… | Touch… | Never touch… |
|---|---|---|
| a new rule | one pure function + `@rule(id, domain, description)` + unit tests | snapshot layer, persistence, routes |
| a new domain | `DOMAINS` (metadata) | existing rules |
| a new upstream data source | `build_project_snapshot` (+ knowledge accessors if knowledge-derived) | any rule |
| event-driven triggers (V2) | a subscription hook other engines call; runs stay idempotent so trigger frequency is a non-issue | rule semantics |
| insight→item conversion (V2) | Operations Engine route acting on `suggested_operational_action`, attributed to the human; sets `operational_item_created` | CRE write scope |
| scheduled runs + `expired` (V2) | run orchestration | lifecycle semantics |
| learning (V3) | a separate layer consuming `feedback_history` + outcomes, tuning rule parameters | rule structure, evidence, the deterministic core |
| AI explanation/summarization | presentation of deterministic findings | `suggested_*` fields, finding content, health |

## 10. Verification obligations for future intelligence work

Anything extending CRE inherits the three-layer verification convention:
pure unit tests for reasoning logic (no DB), full-stack HTTP tests
against the real app (mongomock-motor), and the live-deployment suite.
Two structural tests must never be weakened: the read-only guarantee
(reasoning runs change nothing outside CRE's collections) and the
contract test (no conclusions without evidence, no unexplained
confidence).
