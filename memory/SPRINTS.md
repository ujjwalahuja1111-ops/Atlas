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

## V4.1 — Sprint 4.1: Stabilization & QA Pass
**Scope:** first stability audit + full-pass remediation. Fixed every Critical/High/Medium/Low item from the Sprint 4.1 stabilization audit, plus two founder-requested foundations: complete Project Lifecycle management and a Sign Up / Pending Approval / User Management foundation. Explicitly not a feature sprint for anything beyond that list — no new engines, no architectural redesign.

**Critical fix:**
- Operations screen showed a permanent loading spinner for Supervisor and Client roles — the render gate depended on `center` data that's never fetched for those two roles (`showOpsBuckets: false`). Fixed by gating only on `loading`; KPI/multi-bucket UI is now conditionally shown only for roles that have that data.

**High fixes:**
- Event Detail screen polled the backend every 3s forever (stale-closure bug — a `tick` dependency that was never incremented meant the interval's closure never refreshed). Fixed with a ref that always reflects current `ai_status`, and the interval now explicitly clears itself once resolved.
- Home screen's empty-state "START CAPTURE" button was shown to every role including Client, whose Capture tab is hidden — now gated behind the same `showCapture` permission.
- Capture screen had zero role awareness at all (only the tab bar hid it) — now guards itself directly, consistent with the Knowledge screens' pattern.
- Silent failures on initial data load across most screens (Home, Ops, Projects, Knowledge) — added visible retry banners instead of a spinner/empty-state indistinguishable from "no data."
- No global session-expiry handling — a new shared `apiFetch()` wrapper (in the new `src/http.ts`) detects 401s and routes back to Login automatically.

**Medium fixes:**
- Gallery permission denial in Capture gave no feedback (looked like a dead button) — now matches the Camera button's messaging.
- No empty-state messaging when Capture has zero sites available.
- `canManageProjects` — Projects (both screens) and Operations derived "can manage" from the raw backend role instead of the `VIEW_PERMS` abstraction everywhere else uses, which would have given the Client workspace full project-management rights the moment it became reachable again. Added `canManageProjects` to `ViewPerms` as the single source of truth.
- Profile screen was read-only; the only way to fix a typo'd name was re-logging in (which also re-applies whatever role was passed). Added a narrow, self-only `PATCH /api/me`.
- Basic phone format validation added to login/register (was length-only).

**Low fixes:**
- Knowledge workspace search now debounces (300ms) instead of firing a request per keystroke; the category/phase picker lists no longer refetch on every search change.
- Knowledge list endpoint now uses a single batched name-resolution query (`enrich_many`) instead of one query per item.
- Knowledge relationship-target picker candidates capped/documented as a future pagination point (no behaviour change beyond documentation — full pagination deferred, matches "build foundation" framing already used for `applicability`).
- Optimistic concurrency added to Knowledge item writes (`update_item`, `add_relationship`, `remove_relationship`) via atomic `find_one_and_update` version-matched filters — a concurrent edit now surfaces a clear 409 instead of silently losing data.
- Knowledge "not found" vs "bad input" now correctly return 404 vs 400 (`KnowledgeNotFoundError` subclass), and a genuine write conflict returns 409 (`KnowledgeConflictError`).
- `src/http.ts` consolidates the header-building helpers that were duplicated identically across `api.ts`/`ops_api.ts`/`knowledge_api.ts`.
- `LogBox.ignoreAllLogs(true)` in the root layout reviewed and deliberately left unchanged — it's intentional production behaviour (prevents a dev-mode redbox from wedging the UI on an icon-font-loading edge case), not a functional defect; flagged as a live-QA methodology note rather than a code fix.

**Project Lifecycle (founder-requested):**
- Sites already had complete lifecycle management (add/edit/archive/restore/delete-with-dependency-guard) from Sprint 2 — no gap found there.
- Added the missing piece: `DELETE /api/projects/{id}`, mirroring the existing `DELETE /api/sites/{id}` pattern exactly — hard-delete only when the project has zero sites (archived or active), 409 with blocking counts otherwise. Wired into the Projects workspace UI identically to the existing Site delete button.

**Authentication foundation (founder-requested):**
- New `POST /api/auth/register` (Sign Up) — creates a brand-new account only, `approval_status="pending"`, `is_active=true`, `assigned_project_ids=[]`. Completely separate from `/api/auth/login`, which is UNCHANGED — every Sprint 1-4 login flow and test credential keeps working exactly as before.
- New `users` fields (all optional, backward-compatible via `.get(key, <default>)` on every read — no migration needed): `approval_status`, `is_active`, `assigned_project_ids`.
- `is_active=false` is a hard block enforced in the single shared `get_current_user` auth dependency (401). `approval_status != "approved"` is enforced at the frontend (routes to a new Pending Approval screen instead of the app shell) — this is a deliberate scope boundary: full per-project data scoping by `assigned_project_ids` is NOT implemented (nothing filters projects/sites/events by it yet), matching "build only the foundation required for future expansion."
- New admin-only routes (`routes/admin_users.py`, mirroring the existing `_require_admin` pattern from `routes/knowledge.py`): list pending/all users, approve, reject, assign role, assign projects, activate/deactivate. An admin cannot deactivate their own account.
- New User Management screen (`app/users/index.tsx`), reachable from Profile (admin-only nav entry, same pattern as Construction Knowledge).

**Deliberate scope boundaries (documented, not gaps):**
- No per-project data scoping — `assigned_project_ids` is stored and manageable but doesn't filter any existing query yet.
- No email/SMS notification on approval — the Pending screen has a manual "Check Again" button instead.
- No password — authentication model unchanged (phone+name, JWT), per "do not redesign authentication."

## V5 — Future (not started)
Candidates: Workflow Engine (approvals automation), Learning Engine (AI feedback loop), Documents tab on Site Workspace, multi-blocker stack, per-project data scoping using `assigned_project_ids`, and the first real consumer of Construction Knowledge Core (e.g. Scheduling/Baseline reading Activities + dependencies to generate a project plan).
