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

## V4.2 — Sprint 4.2: Admin Experience
**Scope:** complete the Admin experience so no administrator needs Git Bash, curl, MongoDB, or browser DevTools to manage Atlas. Extends the User Management foundation from Sprint 4.1 with Search, View Details, and CSV export; adds a new Admin System Information page. One new backend endpoint (`GET /api/admin/system-info`); every other capability reuses existing APIs with zero backend change.

**Delivered:**
- **User Management completion** — Search (client-side, over the already-fetched, already-filtered list — zero backend change), View user details (a dedicated modal showing every field including the resolved Workspace label via the existing `DEFAULT_VIEW_ROLE_FOR` mapping), CSV export. Approve/Reject/Assign Role/Assign Projects/Activate-Deactivate were already complete from Sprint 4.1 and are unchanged.
- **CSV export** (`frontend/src/csv.ts`) — cross-platform without any new native dependency: `Blob`+`<a download>` on web, React Native's built-in `Share` API on native. Exports respect the currently active filter and search.
- **Admin System Information page** (`app/system/index.tsx`, `GET /api/admin/system-info`) — Atlas version, git commit (best-effort `git rev-parse --short HEAD` at server boot, falling back to a `GIT_COMMIT` env var, then `"unknown"`), build date (`BUILD_DATE` env var if set, else server boot time), backend status, database status (a real `db.command("ping")`, not just "the process is running"), server uptime, and live counts (total users, total projects, total sites, pending approvals).
- Admin-only nav entry on Profile, alongside Construction Knowledge and User Management.

**Backend:** one new file (`routes/admin_system.py`), one new router registration in `server.py`. Mirrors the `_require_admin` pattern from `routes/knowledge.py`/`routes/admin_users.py` rather than inventing a new one. Read-only — never writes to any collection.

**No changes to:** `routes/admin_users.py`, `routes/auth.py`, `core/auth.py`, any Sprint 1-4.1 engine, or any existing endpoint's request/response contract.

**Testing:** `backend/tests/test_atlas_v4_2.py` (11 pytest cases). Additionally verified via engine-level mongomock smoke (count-query correctness) and full-stack HTTP-level smoke against the real FastAPI app (18 scenarios: admin gating, full field-presence check, live-count reflection as data changes). Combined with every prior Sprint 4/4.1 smoke suite re-run: 131 total scenarios, zero regressions.

**Known limitations carried forward:**
- CSV export on native platforms goes through the OS share sheet rather than a direct file-system write (no `expo-file-system`/`expo-sharing` dependency added — see ADR-024). Functionally complete, slightly less direct than a native "Downloads" save.
- `git_commit`/`build_date` are best-effort: they reflect whatever's actually available in the deployed process (a `.git` directory, or `GIT_COMMIT`/`BUILD_DATE` env vars). A deploy pipeline that ships neither will show `"unknown"` and the server's own boot time respectively — still accurate, just less precise than a dedicated CI-stamped build manifest.
- Search is client-side over a list capped at 1000 users server-side (consistent with every other list endpoint in Atlas) — fine at current and near-term scale; would need a server-side `?q=` param if the user base grows past that cap.

## V4.3 — Sprint 4.3: Identity & Access Foundation
**Scope:** complete the user identity model so Atlas has a stable foundation for future development. Three additions: Sign Up now collects "User Type" (a requested workspace, informational only), Admin can now explicitly assign a Workspace independent of the automatic role-based derivation, and project/site visibility can now be scoped to `assigned_project_ids` for accounts opted into the new model — while every account that existed before this sprint is migrated safely with zero behavioural change.

**Refresh note:** this sprint was originally built on the Sprint 4.1 tip, before Sprint 4.2 ("Admin Experience") was merged into `main`. It was resynchronized against `main` post-merge: the backend changes (all of `memory_engine.py`/`admin_users.py`/`auth.py`/`projects.py`) applied with zero conflicts, since Sprint 4.2 never touched those files. Only `frontend/app/users/index.tsx` and the four canonical docs needed manual reconciliation, since both sprints independently extended them — no functionality from either sprint was dropped or duplicated; see the refreshed sprint's own summary for the merge detail.

**Identity model additions (all new, optional `users` fields):**
- `workspace` (`client|supervisor|pm|admin`, default `null`) — admin-assigned UI experience, validated against the account's role via `WORKSPACE_ROLE_MAP` (a supervisor can only be assigned the `supervisor` workspace; a coordinator can be assigned `client` OR `pm`; management can only be assigned `admin`). This is what finally makes the `client` workspace reachable — previously impossible per ADR-020, since there was no backend signal distinguishing a "client" coordinator from a "PM" coordinator. Now there is one, but only via explicit admin assignment, never automatic guessing.
- `requested_workspace` — the "User Type" collected at Sign Up. Purely informational: shown to the admin during approval, never auto-applied to `workspace`. This is what makes "Sign Up collects User Type" and "no workspace until assigned" both true at once.
- `scope_projects` (bool, default `false`) — gates whether `GET /api/projects`/`GET /api/sites` are filtered to `assigned_project_ids`. `register_user()` sets this `true` for every new Sign Up; `upsert_user()` (plain login) never sets it, so it's absent (→ `false`, unrestricted) for every account that predates this sprint. Management role is always unrestricted regardless of this flag — "Admin has unrestricted access" is unconditional.

**Backend:**
- `memory_engine.py`: `WORKSPACE_ROLE_MAP`, `set_user_workspace()` (validates role-compatibility), `set_user_role()` now clears an incompatible stored `workspace` on role change (prevents the impossible state of workspace="admin" with role≠management), `list_projects()`/`list_sites()` gain an optional `user` kwarg that applies scoping only when `_is_project_scoped(user)` is true.
- `routes/projects.py`: the two list endpoints now pass the caller through for scoping. The internal `/projects/seed` existing-data check is unaffected (calls the engine functions without the `user` kwarg, staying globally unrestricted, exactly as before).
- `routes/auth.py`: `POST /auth/register` gains `requested_workspace`.
- `routes/admin_users.py`: new `POST /admin/users/{id}/workspace`, mirroring the existing `_require_admin` gate. Sprint 4.2's existing endpoints in this file are untouched.

**Frontend:**
- `roles.ts`: `completeLoginRouting()` now prefers an explicit `user.workspace` when present, falling back to the existing `DEFAULT_VIEW_ROLE_FOR[role]` derivation for every account without one — this is the entire backward-compatibility mechanism for workspace resolution, in one line. New `WORKSPACE_OPTIONS_FOR_ROLE` mirrors the backend's `WORKSPACE_ROLE_MAP` for the assignment UI.
- `login.tsx`: Sign Up form gains a "User Type" chip selector (Client/Supervisor/Project Manager/Admin).
- `users/index.tsx`: the Role assignment modal gains a Workspace section (role-filtered chip options) and displays `requested_workspace` on pending rows as a hint for the admin. Sprint 4.2's Search, View Details modal, and CSV export are all preserved intact — the View Details modal's Workspace row was additionally updated to show the real admin-assigned value when one exists, falling back to the derived default otherwise, rather than always showing the pure derivation as it did in the pre-4.3 Sprint 4.2 version.

**Testing:** `backend/tests/test_atlas_v4_3.py` (16 pytest cases). Additionally verified via engine-level mongomock smoke (14 new scenarios covering scoping, workspace validation, role-change consistency) and full-stack HTTP-level smoke against the real FastAPI app (14 new scenarios, full end-to-end Sign Up → Approve → Assign Workspace/Role/Projects → scoped visibility). Combined with every prior applicable smoke suite re-run (Sprint 4, 4.1, 4.2, and this sprint): zero regressions.

**Migration:** no migration script exists or is needed; every new field defaults to its pre-Sprint-4.3 equivalent behaviour when absent, verified explicitly by `test_legacy_account_sees_all_projects_unaffected` and companion tests in `test_atlas_v4_3.py`.

**Deliberate scope boundaries (documented, not gaps):**
- Only `GET /api/projects` and `GET /api/sites` are scoped. Deeper endpoints (project summary by ID, site requirements, events/timeline/operational-items) are NOT scoped in this pass — "keep changes minimal" per the brief. A user could still fetch a specific non-assigned project's summary if they somehow know its ID. Worth closing in a future pass if this becomes a real concern; not done here to avoid a much larger, riskier change.
- No UI surfaces "you are approved but have no workspace assigned yet" as a distinct blocking state — an approved account with no explicit workspace simply falls back to the existing automatic derivation (their role's default workspace) while `scope_projects` keeps them seeing nothing until projects are assigned. Functionally safe (no data exposure), just not a dedicated screen state.

## V5 — Sprint 5: Construction Workflow Engine
**Scope:** build the first Construction Engine on top of the existing Knowledge Core (Sprint 4), extending rather than redesigning the platform. No scheduling (no dates/calendar/critical path), no AI, no resource/cost calculations, no notifications, no dashboards — all explicitly out of scope.

**Note on naming:** this is the "Construction Workflow Engine" (Activity Library → Templates → project-scoped activity instances → dependency-respecting status). It is distinct from the still-unbuilt "Workflow Engine" (Engine 7, approvals automation) referenced in `HANDOFF.md`'s engine map and prior sprint notes — that candidate remains in V6 below, unrenamed and unbuilt.

**1. Activity Library** — `knowledge_items` (`type="activity"`) gains three new fields, meaningful only for activities (same established pattern as `document_kind` for `required_document`): `trade`, `unit`, `requires_inspection`. Category/Phase/Description/Applicability/Duration were already there from Sprint 4 — zero change. "Active" reuses `status == "active"` directly rather than a new boolean, per "no duplicated logic."

**2. Activity relationships** — Sprint 4's generic `relationships[]` absorbed almost all of this as pure data: Depends On (`depends_on`), Required Documents (`linked_document`), Checklist Template (generic `uses`), Materials (`linked_material`) and Equipment (`linked_equipment`) were all already reserved types from Sprint 4 needing zero schema change. Only one genuinely new type was needed — `linked_labour` — plus one for templates, `includes_activity` (see below). "Unlocks" is deliberately **not** a second stored relationship (would be two sources of truth for one fact) — it's a new computed reverse-lookup, `compute_unlocks()`/`compute_unlocks_many()`, wired into `enrich()`/`enrich_many()` for activity items only.

**3. Workflow Templates** (Villa, Residential, Commercial, Interior, Renovation) — `workflow_template` added to `knowledge_items` `TYPES`. A template is just another master-data kind in the same collection, getting CRUD/search/archive/versioning for free — zero new endpoints for template management, `routes/knowledge.py` already serves it entirely. "Templates reference Activity Library items only" is enforced for free via the new `includes_activity` relationship type, since `add_relationship()` already guarantees every target is a real knowledge item; order is captured in `relationships[].metadata.order`. New idempotent `POST /api/workflow-templates/seed-defaults` creates the five named templates as empty shells (mirrors `POST /api/projects/seed`'s exact shape) — deliberately not pre-populated with fabricated activity content, which an admin curates via the existing, reused relationship UI.

**4. Project Creation → Generate Workflow** — new `engines/workflow_engine.py` and a new `workflow_activities` collection: project-scoped, denormalized activity *instances*, deliberately separate from `knowledge_items` (which stays global, versioned reference data) — the same separation `operational_items` has from `events`. `generate_workflow()` reads a template's `includes_activity` relationships in order, denormalizes each activity's Sprint 5 fields onto a new instance, and translates knowledge-level `depends_on` relationships into concrete sibling-instance ids within the project (a dependency pointing outside the template's set is silently skipped, not errored — keeps generation robust to partially-curated templates). Refuses to regenerate an already-generated project. New `POST /api/projects/{id}/workflow/generate`, gated the same way project management already is (coordinator/management only).

**5. Activity Status** — `not_started | ready | in_progress | blocked | completed`. Transitioning to `in_progress`/`completed` is blocked (409) unless every dependency is already `completed` — the literal "Respect dependencies" requirement. `blocked` is an orthogonal signal, settable from any state. Completing an activity cascades: every sibling that depends on it is re-evaluated and auto-promoted from `not_started` to `ready` once fully satisfied — the project-level mirror of the Activity Library's Unlocks concept. New `POST /api/workflow-activities/{id}/status`, open to any authenticated role (mirrors `operational_items`' on-site status transitions) — Sprint 4.3's project-scoping foundation is reused (not duplicated) here too, so a scoped user who can't see a project can't touch its workflow either.

**6. Workflow Viewer** — new `GET /api/projects/{id}/workflow`, enriched with dependency names+status. New `frontend/app/workflow/[id].tsx`: a simple list grouped by phase, showing activities/dependencies/status — no Gantt, no dates. New "Generate Workflow" trigger + template picker on the Project Detail screen. The Knowledge workspace gains a Workflow Templates tab and the three new Activity Library fields in its existing create/detail UI; the relationship-type chips for `linked_labour`/`includes_activity` appear automatically via the already-dynamic `GET /api/knowledge-meta` — zero UI code needed for that part.

**Testing:** `backend/tests/test_atlas_v5.py` (14 pytest cases, 150 total across all sprints). Additionally verified via engine-level mongomock smoke (21 scenarios: full generation + dependency-cascade + scoping-integration walkthrough) and full-stack HTTP-level smoke against the real FastAPI app (23 scenarios, complete Activity Library → Template → Generate → Status → Viewer flow end to end). Every prior sprint's smoke suite re-run: zero regressions (~215 total scenarios passing).

**Deliberate scope boundaries (documented, not gaps):** no scheduling (no dates, no calendar, no critical path — "Duration" is informational only); no AI; no resource/cost calculations; no notifications; no dashboards. Workflow generation is one-time per project — there's no "regenerate/merge" concept, matching the "no scheduling" simplicity. Dependencies pointing outside a template's activity set are silently dropped at generation time, not surfaced as a warning — worth revisiting if template curation errors turn out to be common in practice.

## V6 — Future (not started)
Candidates: Workflow Engine (Engine 7 — approvals automation, distinct from Sprint 5's Construction Workflow Engine above), Learning Engine (Engine 8 — AI feedback loop), Documents tab on Site Workspace, multi-blocker stack, deeper project/site-scoped enforcement on by-ID endpoints (project summary, site requirements — see V4.3's documented boundary), Scheduling (dates/calendar/critical path on top of Sprint 5's dependency graph), and generating a project's initial site/BOQ/material plan from its Workflow.
