# Project Atlas — Sprint Log

## V1 — Construction Site Assistant
Voice + photo capture → AI structured events. Phone+name auth. Three roles. Hindi/Punjabi/Hinglish/English. Single-file backend.

## V2 — Construction Intelligence Platform
- Renamed to ATLAS · Construction Intelligence.
- Engine-based architecture (Reality / Memory / Intelligence / Timeline).
- Golden Rule (AI never blocks; <300 ms event capture).
- Immutable events + raw_assets + ai_analyses.
- Evidence Model surfaced on Event Detail.
- Prompt Versioning.
- Project → Site hierarchy.
- Async asyncio.Queue worker via FastAPI lifespan.

## V3 — Operational Intelligence Layer
**Scope:** add operational accountability without becoming an ERP.

**Delivered:**
- New **Operations Engine** (Engine #5) with append-only `operational_events` ledger + derived `operational_items` projection.
- **AI Proposal workflow**: Intelligence Engine emits proposals from analysed events (materials → procurement; issues → site_issue). Coordinators/Management accept/edit/reject. Supervisors cannot.
- **11 operational categories** including Commitment, Inspection, Follow-up — extensible without architecture change.
- **Operational lifecycle** with validated transitions: open → assigned → acknowledged → in_progress → fulfilled → verified → closed (+ escalated, reopened).
- **Operational Health** derived live: on_track / due_soon / overdue / blocked / waiting_external / completed. Separate from status.
- **Time Intelligence**: current_age, time_remaining, days_overdue, time_to_complete, verification_delay computed on read.
- **Blocker management** with categorised blockers; external blockers flip Health to `waiting_external`.
- **Origin tracking**: every item records `origin_type` (ai_proposal / manual / coordinator / management / client / architect / future_integration) + `origin_reference_id`.
- **Evidence inheritance**: items link to originating Construction Event; detail screen renders "Why does this exist?" with original transcript, photo, GPS, creator.
- **Three operational questions** answered without opening additional screens, on both list cards and detail.
- **Operational Center** dashboard endpoint + screen — open / overdue / high_priority / awaiting_verification / recently_completed / recently_updated buckets.
- **Site Requirements** workspace endpoint — living checklist filtered to requirement categories.
- **Timeline opt-in merge**: `GET /api/timeline?include=ops` includes operational events.
- **New mobile screens**: OPS tab + Operational Item Detail.
- Canonical docs authored: CONSTITUTION, ARCHITECTURE, DECISIONS, SPRINTS, PRD update.

**Backward compatibility:** All V2 endpoints + response shapes unchanged.

**Risks / debt identified:**
- Projection drift: if a crash occurs between `append_event` and `_save_item`, the projection can lag the ledger by one event. Mitigation path: a `recompute_projection(item_id)` helper that rebuilds from ledger — designed in, not exposed in pilot UI.
- AI proposal acceptance trusts user edits without re-running GPT — fine for pilot, may revisit in V4.
- In-process queue worker still single-instance. Future: Redis/Celery — only `intelligence_engine.enqueue()` needs to change.

## V4 — Sprint 4: Construction Knowledge Core — Architectural Milestone
**Scope:** architecture sprint, not a feature sprint. Activates the reserved Knowledge Engine (#6) slot with reusable, versioned master-data objects. This is the canonical knowledge layer Atlas's next phase is built on: **Project Generation, Baseline Engine, Reality Engine (Activity matching), Material Intelligence, Labour Intelligence, Variance Analysis, and Construction Intelligence** will all read from `knowledge_items` instead of each defining their own vocabulary for what construction work *is*. None of those modules are built here — V4 is deliberately scoped to the data layer and extension points they will need (no scheduling, BOQs, progress tracking, material/labour planning, AI behaviour, or project assignment). All Sprint 1–3 workflows and APIs are unchanged.

**Delivered:**
- New **Knowledge Engine** (Engine #6, `engines/knowledge_engine.py`) — a single collection `knowledge_items`, discriminated by `type`: category / phase / activity / checklist_template / required_document. One generic engine avoids duplicating CRUD/search/archive/versioning logic per type.
- **Generic typed relationships**: `relationships: [{id, type, target_id, metadata, created_at}]` embedded per item — not a hardcoded `depends_on` array. V1 exercises `depends_on` (Activity Dependencies) only; the shape supports `precedes`, `requires`, `references`, `uses`, `inspected_by`, `linked_document`, `linked_material`, `linked_equipment` without any future schema change. No cycle detection in V1 (data shape only).
- **Versioning**: every edit snapshots the pre-edit doc into append-only `knowledge_versions` (mirrors the Corrections ADR pattern) before bumping `version` on the live doc. Full history retrievable per item.
- **Soft-archive / restore**: `archived_at`, identical mechanics to projects/sites.
- **Search + filter**: `?q=` (name/description/code/tags/ai_keywords, case-insensitive), `?type=`, `?category_id=`, `?phase_id=`, `?tag=`, `?include_archived=`.
- **Admin-only mutations**: gated on backend role `management` (the existing target of the frontend `admin` view-role). Reads open to all authenticated roles.
- **New mobile screens**: `/knowledge` (browse/search/filter/create/archive workspace, type tabs) + `/knowledge/[id]` (detail, inline edit, Dependency Viewer, version history) — entry point added to Profile screen, admin-only.
- **Extension points, deliberately not wired to behaviour yet**: `tags`, `ai_keywords`, `default_duration_days` fields exist on Activities for future Search/AI/Scheduling engines to consume; `reference_counts()` helper exists for a future hard-delete guard (V1 only supports archive).
- Canonical docs updated: ARCHITECTURE (Knowledge Engine row, collections table, new architecture section, V4 API surface), DECISIONS (ADR-014 through ADR-017), SPRINTS (this entry).

**Backward compatibility:** Purely additive. No existing route, model, collection, or engine modified. All V1/V2/V3 endpoints and response shapes unchanged.

**Risks / debt identified:**
- No cycle detection on `depends_on` relationships — fine for V1 data entry, must be addressed before any future Scheduling/Baseline engine consumes this graph for sequencing.
- No hard-delete for knowledge items (archive only) — `reference_counts()` is designed in but not exposed, mirroring the site hard-delete guard pattern for when it's needed.
- Relationship `type` is not server-validated against a closed enum (by design, for extensibility) — a typo'd relationship type is stored as-is. Acceptable at V1 scale with a single admin actor; revisit if the vocabulary needs enforcement once other engines start writing relationships.

### Sprint 4 refinement pass (pre-merge review)
Requested before merge to `main`; still unmerged (feature branch only).

1. **Lifecycle `status`** (`draft | active | deprecated | archived`) added alongside `archived_at` — see ADR-018. New items default to `draft`.
2. **`applicability`** freeform dict added and reserved for future project-generation filtering by project/building/construction type and region — see ADR-019. Not read by any filter logic yet.
3. **Relationships** — no changes; generic `relationships[]` shape confirmed as final, reaffirmed rather than restricted to dependencies.
4. **Sprint 3 workspace-selector cleanup** — the manual login role picker is removed. Login now auto-resolves the backend role and routes directly into the matching workspace via a single centralized mapping in `frontend/src/roles.ts` — see ADR-020. No backend API or auth flow changed.
5. **Regression** — re-verified: zero pre-existing engine/route files modified (`git diff main -- backend/engines backend/routes` empty outside `knowledge.py`); zero pre-existing frontend screens modified outside `profile.tsx`'s additive nav link (added in the original Sprint 4 pass) and `login.tsx`/`roles.ts` (this pass, scoped exactly to the workspace-selector removal). Engine logic re-verified via the mongomock smoke harness (25 scenarios total across both passes) plus a standalone logic simulation of the new login-routing cache (6 scenarios). All passing.

## V5 — Future (not started)
Candidates: Workflow Engine (approvals automation), Learning Engine (AI feedback loop), Documents tab on Site Workspace, multi-blocker stack, and the first real consumer of Construction Knowledge Core (e.g. Scheduling/Baseline reading Activities + dependencies to generate a project plan).
