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
| `users` | upsert (login) + admin-managed (V4.1/V4.3) | name/role/phone; V4.1 adds optional `approval_status` (pending/approved/rejected), `is_active`, `assigned_project_ids`; V4.3 adds optional `workspace`, `requested_workspace`, `scope_projects` — all default to approved/active/[]/null/null/false when absent, so every pre-V4.1 and pre-V4.3 account needs no migration |
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

## Sign Up / Pending Approval / User Management (V4.1)
`POST /api/auth/register` is a separate, create-only path from the unchanged `/api/auth/login` — see ADR-021. New accounts start `approval_status="pending"`, `is_active=true`, `assigned_project_ids=[]`. `is_active=false` is a hard 401 block in `get_current_user` (the single shared auth dependency every route uses); `approval_status` is enforced at the frontend only — a pending/rejected account is routed to `app/pending.tsx` instead of the app shell (see ADR-022). Admin-only management lives in `routes/admin_users.py` (list/approve/reject/assign-role/assign-workspace/assign-projects/activate-deactivate), mirroring the `_require_admin` pattern from `routes/knowledge.py`, surfaced via `app/users/index.tsx`. `assigned_project_ids` now filters `GET /api/projects`/`GET /api/sites` for accounts with `scope_projects=true` — see the Identity & Access Foundation (V4.3) section below for how this was made backward-compatible for every pre-existing account.

## Project Lifecycle (V4.1)
Sites already had complete lifecycle management since Sprint 2 (add/edit/archive/restore/delete-with-dependency-guard). `DELETE /api/projects/{id}` was the one missing piece, added mirroring `DELETE /api/sites/{id}` exactly: hard-delete only when `project_reference_counts()` (sites under this project, archived or active) is all-zero; 409 with blocking counts otherwise.

## Stabilization fixes (V4.1)
Knowledge Core: `enrich_many()` batches list-response name resolution into one query (previously one query per item); `find_one_and_update`-based optimistic concurrency on writes, surfacing a 409 (`KnowledgeConflictError`) on a genuine conflict instead of silent last-write-wins; `KnowledgeNotFoundError` (404) is now distinct from a plain validation `ValueError` (400) — see ADR-023. `frontend/src/http.ts` consolidates the duplicated header-building helpers from `api.ts`/`ops_api.ts`/`knowledge_api.ts` and adds `apiFetch()`, a drop-in `fetch` replacement that clears the session and redirects to Login on a 401 from any authenticated endpoint. See `memory/SPRINTS.md`'s V4.1 entry for the full Critical/High/Medium/Low fix list.

## Admin Experience (V4.2)
Goal: no administrator should need Git Bash, curl, MongoDB, or browser DevTools to manage Atlas. Two additions:
- **User Management completion** (`app/users/index.tsx`) — Search (client-side over the already-fetched, already-filtered list, zero backend change), View Details (a modal surfacing every field, including the Workspace label computed via the existing `DEFAULT_VIEW_ROLE_FOR` mapping from `roles.ts`), and CSV export (`frontend/src/csv.ts` — see ADR-024 for why it's dependency-free rather than using `expo-file-system`/`expo-sharing`). Approve/Reject/Assign Role/Assign Projects/Activate-Deactivate are unchanged from V4.1.
- **Admin System Information** (`app/system/index.tsx`, `GET /api/admin/system-info`) — one new, read-only, admin-only endpoint (`routes/admin_system.py`, mirroring the existing `_require_admin` pattern) returning version/git-commit/build-date, backend and database health (a real `db.command("ping")`), server uptime, and live counts (users/projects/sites/pending-approvals).

## Identity & Access Foundation (V4.3)
Two new, independent, optional `users` fields complete the identity model:
- **`workspace`** — admin-assigned UI experience (client/supervisor/pm/admin), validated against the account's role via `WORKSPACE_ROLE_MAP` (mirrored in `frontend/src/roles.ts` as `WORKSPACE_OPTIONS_FOR_ROLE`). `completeLoginRouting()` prefers this over the pre-existing `DEFAULT_VIEW_ROLE_FOR[role]` derivation when present, falling back to it otherwise — this single fallback is the entire backward-compatibility mechanism. This is what makes the `client` workspace reachable for the first time (previously impossible per ADR-020) — but only via explicit admin assignment, never automatic guessing. See ADR-026.
- **`scope_projects`** — gates whether `GET /api/projects`/`GET /api/sites` filter to `assigned_project_ids`. Defaults `false` (unrestricted, today's behaviour) for every account; only `register_user()` sets it `true`. Management role is always unrestricted regardless. See ADR-025 for why this is a dedicated flag rather than inferred from other fields.
- **`requested_workspace`** ("User Type" at Sign Up) is informational only — shown to the admin, never auto-applied — which is what lets Sign Up collect a workspace preference while "no workspace until assigned" stays literally true.

## API surface

### V2 (unchanged)
`POST /api/auth/login · GET /api/me · GET/POST /api/projects · POST /api/projects/seed · GET/POST /api/sites · POST/GET /api/events · POST /api/events/{id}/corrections · GET /api/events/{id} · GET /api/timeline · GET /api/raw-assets/{id}`

### V3 (new)
`POST /api/operational-items · GET /api/operational-items · GET /api/operational-items/{id} · POST /api/operational-items/{id}/transition · POST /api/operational-items/{id}/assign · POST /api/operational-items/{id}/comments · POST /api/operational-items/{id}/blocker · DELETE /api/operational-items/{id}/blocker · POST /api/operational-items/{id}/due · POST /api/operational-items/{id}/escalate · GET /api/ai-proposals · POST /api/ai-proposals/{id}/accept · POST /api/ai-proposals/{id}/reject · GET /api/operational-center · GET /api/sites/{id}/requirements · GET /api/timeline?include=ops`

### V4 (new)
`GET /api/knowledge-items` (+ `type`, `category_id`, `phase_id`, `tag`, `status`, `q`, `include_archived`) `· POST /api/knowledge-items · GET /api/knowledge-items/{id} · PATCH /api/knowledge-items/{id} · POST /api/knowledge-items/{id}/archive · POST /api/knowledge-items/{id}/unarchive · GET /api/knowledge-items/{id}/versions · POST /api/knowledge-items/{id}/relationships · DELETE /api/knowledge-items/{id}/relationships/{relationship_id} · GET /api/knowledge-meta`

### V4.1 (new)
`POST /api/auth/register · PATCH /api/me · DELETE /api/projects/{id} · GET /api/admin/users` (+ `approval_status`) `· POST /api/admin/users/{id}/approve · POST /api/admin/users/{id}/reject · POST /api/admin/users/{id}/role · POST /api/admin/users/{id}/projects · POST /api/admin/users/{id}/active`

### V4.2 (new)
`GET /api/admin/system-info`

### V4.3 (new)
`POST /api/admin/users/{id}/workspace` — the only new endpoint. `POST /api/auth/register` gains an optional `requested_workspace` field (request-body extension, not a new endpoint). `GET /api/projects` and `GET /api/sites` gain scoped filtering behind the `scope_projects` flag — same endpoints, same response shape, conditionally narrower result set.

## Backward Compatibility
V2 and V3 endpoints and response shapes are unchanged. Timeline default behaviour unchanged. No data migration required. V4 is purely additive (new collections, new router) — no existing route, model, or engine was modified. V4.1 is a stabilization + additive-foundation sprint: every V1-V4 endpoint, request/response shape, and permission rule is unchanged; the only behavioural change to an existing code path is `get_current_user` gaining the `is_active` check, which is a no-op for every account that predates V4.1 (the field defaults to active when absent). V4.2 adds exactly one new, read-only endpoint and zero changes to any existing route, model, or engine — every V1-V4.1 request/response contract is byte-for-byte unchanged. V4.3 adds one new endpoint and two new optional fields; `GET /api/projects`/`GET /api/sites` response shapes are unchanged, only the result set is conditionally narrower, and only for accounts explicitly opted into the new model (`scope_projects=true`) — every account that existed before this sprint sees identical results to before, verified explicitly in `test_atlas_v4_3.py`.
