# Project Atlas — Architecture

## Engine Map (current)

| # | Engine | Module | Responsibility | Status |
|---|---|---|---|---|
| 1 | Reality | `engines/reality_engine.py` | Capture voice/photo/text/GPS; persist immutably; enqueue AI | ✅ V2 |
| 2 | Memory | `engines/memory_engine.py` | The only writer to Mongo. Append-only facts. | ✅ V2 |
| 3 | Intelligence | `engines/intelligence_engine.py` | Async worker; Whisper + GPT-4o; Evidence + Prompt versioning; emits AI Proposals | ✅ V2 + V3 |
| 4 | Timeline | `engines/timeline_engine.py` | Chronological projection over events + analyses + corrections (+ ops via `include=ops`) | ✅ V2 + V3 |
| 5 | **Operations** | `engines/operations_engine.py` | Operational Items lifecycle, CQRS projection over ledger, Health derivation, AI Proposal acceptance | ✅ **V3** |
| 6 | **Knowledge** | `engines/knowledge_engine.py` | Construction Knowledge Core — reusable master definitions (Category/Phase/Activity/Checklist Template/Required Document), generic typed relationships, versioning, soft-archive | ✅ **V4** |
| 7 | Workflow | *(reserved)* | Future approvals automation | reserved |
| 8 | Learning | *(reserved — `ai_feedback`)* | Closes the loop from human corrections back into models | reserved |

## V3 Diagram

```
                      Reality Engine
                            │ POST /api/events (multipart)
                            ▼
                       Memory Engine ──── events / raw_assets / corrections
                            │ enqueue
                            ▼
                   Intelligence Engine ──── ai_analyses (+ evidence, prompt_version)
                            │ propose
                            ▼
                      ai_proposals ◀──── coordinator/management decision
                            │ accept/edit
                            ▼
                  ┌─── Operations Engine ────────────────┐
                  │   • operational_events (ledger)      │
                  │   • operational_items (projection)   │
                  │   • Health derivation                │
                  │   • Blocker management               │
                  └──────────────────────────────────────┘
                            │
                            ▼
                Timeline Engine ── optionally merges Construction Events + Operational Events
```

## Collections

| Collection | Mutability | Purpose |
|---|---|---|
| `users` | upsert | name/role/phone |
| `projects`, `sites` | append + small upsert | project→site hierarchy |
| `events` | append-only facts; **only** `ai_status`/`ai_analysis_id` lifecycle markers may change | Construction Events |
| `raw_assets` | immutable | audio + photo bytes + SHA-256 |
| `ai_analyses` | one doc per event, write-once | structured AI output + evidence + prompt_version_id |
| `corrections` | append-only | linked records to events |
| `prompt_versions` | append-only | every prompt version archived |
| `ai_proposals` | append-only; decision recorded once | AI-suggested operational items |
| `operational_events` | **append-only ledger** | every lifecycle/comment/blocker/escalation event |
| `operational_items` | derived projection (rebuildable) | cheap current-state read |
| `ai_feedback`* | reserved | future Learning Engine |
| `knowledge_items` | soft-archive + versioned | Construction Knowledge Core master data, one collection discriminated by `type` (category/phase/activity/checklist_template/required_document); tracks lifecycle `status` (draft/active/deprecated/archived) alongside `archived_at`, and a reserved freeform `applicability` dict for future project-generation filtering |
| `knowledge_versions` | **append-only** | immutable pre-edit snapshots of `knowledge_items`, mirroring the `corrections` pattern |

## Evidence Model
Every `ai_analyses.evidence[]` entry: `{kind, asset_id?, sha256?, value?}` referencing audio/photo/text artefacts. Every `operational_items.inherited_evidence_event_id` links back to the originating Construction Event so all evidence is reachable in one hop.

## Three Operational Questions (always answerable)
Every Operational Item answers without an extra fetch:
- Why does this exist? → `origin_type` + `inherited_evidence_event_id` + `created_by_user_name`
- Who currently owns it? → `assigned_to_user_name` (or “unassigned”)
- What is preventing completion? → `blocker.category` (or “no blocker”)

## Operational Lifecycle
`open → assigned → acknowledged → in_progress → fulfilled → verified → closed`. Lateral: `escalated`, `reopened`. Allowed transitions enforced by `operations_engine.TRANSITIONS`.

## Operational Health (derived, separate from status)
`on_track | due_soon | overdue | blocked | waiting_external | completed`. Computed live from blocker + required_by + status.

## Time Intelligence (computed on read)
`current_age_hours · time_remaining_hours · days_overdue · time_to_complete_hours · verification_delay_hours`.

## Construction Knowledge Core (V4) — Architectural Milestone
V4 is not a feature release — it establishes the **canonical knowledge layer** the next phase of Atlas is built on. Every module that reasons about *what construction work is* (as opposed to what already happened, which Reality/Memory/Timeline own) will read from `knowledge_items` rather than reinventing its own vocabulary:
- **Project Generation** — turn a knowledge-defined Activity graph into a real project plan.
- **Baseline Engine** — schedule dates against `default_duration_days` and `relationships[type=depends_on]`.
- **Reality Engine (future extension)** — match captured events to canonical Activities via `tags`/`ai_keywords`.
- **Material Intelligence / Labour Intelligence** — consume `linked_material`/`linked_equipment` relationships once populated.
- **Variance Analysis** — compare actual progress against knowledge-defined Checklist Templates and Required Documents.
- **Construction Intelligence** — the AI layer reasoning over all of the above needs one stable vocabulary to reason with; that vocabulary is this collection.

None of those modules are built in V4 — this sprint is deliberately scoped to the data layer and extension points they'll need, not their behaviour.

Single collection `knowledge_items`, discriminated by `type`: `category | phase | activity | checklist_template | required_document`. One generic engine avoids duplicating CRUD/search/archive/versioning logic five times.
- **Relationships are generic, typed edges** embedded on the item: `relationships: [{id, type, target_id, metadata, created_at}]`. V1 populates `depends_on` (Activity Dependencies) but the shape supports future edge types (`precedes`, `requires`, `references`, `uses`, `inspected_by`, `linked_document`, `linked_material`, `linked_equipment`) without a schema change. No graph traversal / cycle detection in V1 — data shape only.
- **Lifecycle `status`** (`draft | active | deprecated | archived`) tracked alongside `archived_at`, not instead of it. `archived_at` remains the soft-archive timestamp driving default list visibility (unchanged mechanic, matches projects/sites). `status` is the richer editorial state — new items default to `draft` so future consumers (e.g. Project Generation) can filter to `active` items only, without seeing work-in-progress definitions. `archive_item`/`unarchive_item` keep both fields in sync so there is one owner of "is this archived," not two independent toggles. `status="archived"` is never settable directly through the generic update path — only the archive/unarchive actions set it, in lockstep with `archived_at`.
- **`applicability`** is a deliberately unshaped, freeform dict reserved for future project-generation filtering (project types, building types, construction types, regions, ...). V1 stores and returns it verbatim — no filtering logic reads it yet. Modelled as an open dict rather than hardcoded fields so new applicability axes never require a schema change.
- **Versioning** mirrors the `corrections` ADR pattern: every edit snapshots the pre-edit document into `knowledge_versions` (immutable, append-only) before applying the update, then bumps `version` on the live doc.
- **Soft-archive** via `archived_at`, identical to projects/sites — no new archive paradigm.
- **Admin-only**: mutating endpoints require backend role `management` (the existing mapping target of the frontend `admin` view-role in `roles.ts`). Read endpoints are open to any authenticated role, since future engines/roles will need to reference this data.
- Out of scope for V1 (explicit extension points, not implemented): Scheduling, BOQs, Baseline Engine, Progress Tracking, Material/Labour Planning, AI Behaviour/Recommendations, Project assignment, applicability-based filtering.

## Workspace Auto-Routing (V4 cleanup)
Sprint 3 introduced a manual "pick your workspace" selector at login (Client / Supervisor / PM / Admin), which *derived* the backend role sent to `/api/auth/login` from that choice. This has been removed. Login now goes the other direction: the app resolves the correct backend role automatically (a per-phone, per-device cache of the last-known role — see `frontend/src/roles.ts`, `resolveLoginRole`/`completeLoginRouting`), sends that to the unchanged `/api/auth/login` endpoint, and then auto-routes into the workspace matching the **authoritative** role the backend returns via `DEFAULT_VIEW_ROLE_FOR`. This mapping is centralized in one file; no screen computes it independently. `coordinator` collapses to the `pm` workspace by default (there is no backend signal distinguishing a "client" coordinator from a "PM" coordinator — that was always a manual choice, not an auto-detectable fact); `client` remains fully defined in `VIEW_PERMS`/`TABS_FOR` for any future flow that sets it explicitly. No backend API, auth flow, or permission-gating logic changed.

## API surface

### V2 (unchanged)
`POST /api/auth/login · GET /api/me · GET/POST /api/projects · POST /api/projects/seed · GET/POST /api/sites · POST/GET /api/events · POST /api/events/{id}/corrections · GET /api/events/{id} · GET /api/timeline · GET /api/raw-assets/{id}`

### V3 (new)
`POST /api/operational-items · GET /api/operational-items · GET /api/operational-items/{id} · POST /api/operational-items/{id}/transition · POST /api/operational-items/{id}/assign · POST /api/operational-items/{id}/comments · POST /api/operational-items/{id}/blocker · DELETE /api/operational-items/{id}/blocker · POST /api/operational-items/{id}/due · POST /api/operational-items/{id}/escalate · GET /api/ai-proposals · POST /api/ai-proposals/{id}/accept · POST /api/ai-proposals/{id}/reject · GET /api/operational-center · GET /api/sites/{id}/requirements · GET /api/timeline?include=ops`

### V4 (new)
`GET /api/knowledge-items` (+ `type`, `category_id`, `phase_id`, `tag`, `status`, `q`, `include_archived`) `· POST /api/knowledge-items · GET /api/knowledge-items/{id} · PATCH /api/knowledge-items/{id} · POST /api/knowledge-items/{id}/archive · POST /api/knowledge-items/{id}/unarchive · GET /api/knowledge-items/{id}/versions · POST /api/knowledge-items/{id}/relationships · DELETE /api/knowledge-items/{id}/relationships/{relationship_id} · GET /api/knowledge-meta`

## Backward Compatibility
V2 and V3 endpoints and response shapes are unchanged. Timeline default behaviour unchanged. No data migration required. V4 is purely additive (new collections, new router) — no existing route, model, or engine was modified.
