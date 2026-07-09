# Project Atlas — Decisions Log

Running ADR log. Each decision records context + decision + alternatives considered.

## ADR-001 — Engine-based modular architecture
**Context:** V1 mixed capture, AI, and reporting in `server.py`. **Decision:** Split into independent engines (Reality, Memory, Intelligence, Timeline). Memory Engine is the only writer. **Alternatives:** monolith (rejected — coupling), microservices (rejected — premature). Date: V2.

## ADR-002 — AI never blocks event capture (The Golden Rule)
**Context:** Whisper + GPT-4o latency is 2–6 s; supervisors should never wait. **Decision:** `POST /api/events` returns 201 in <300 ms with `ai_status="pending"`. AI work runs in an in-process `asyncio.Queue` worker started by FastAPI `lifespan`. **Alternatives:** synchronous (rejected); Redis/Celery (rejected — premature for pilot). Date: V2.

## ADR-003 — Raw data preserved permanently
**Context:** V1 was discarding audio after transcription. **Decision:** Store all raw bytes in `raw_assets` with SHA-256. AI output is derived; raw is canonical. **Alternatives:** keep transcript-only (rejected — loses ability to re-analyze, audit, or replay). Date: V2.

## ADR-004 — Immutability of Construction Events
**Context:** Need a trustworthy historical record. **Decision:** Event documents never mutate. Only `ai_status` + `ai_analysis_id` lifecycle markers may change. Human edits become Corrections in a separate collection. **Alternatives:** in-place edits with audit log (rejected — adds complexity, loses simplicity of facts vs derivations split). Date: V2.

## ADR-005 — Evidence Model is a first-class concept
**Context:** Every AI conclusion must be explainable. **Decision:** Each `ai_analyses` doc carries an explicit `evidence` array linking back to raw assets + text inputs with sha256 hashes. **Alternatives:** assume evidence (rejected — opaque). Date: V2.

## ADR-006 — Prompts are versioned
**Context:** Debug + reproducibility. **Decision:** `prompt_versions` collection seeded with each named prompt. Each `ai_analyses` doc records `prompt_version_id`, `prompt_name`, `prompt_version`, `model_versions`. **Alternatives:** inline prompt copy (rejected — bloated, deduplicable). Date: V2.

## ADR-007 — Project → Site hierarchy preserved
**Context:** Brief mandated domain hierarchy even if pilot UI is simplified. **Decision:** Separate `projects` and `sites` collections. Events live under sites. Each site references its project. **Alternatives:** collapse into one collection (rejected — would require migration later). Date: V2.

## ADR-008 — CQRS: append-only ledger + derived projection (V3)
**Context:** "History is append-only, nothing is overwritten" vs. "Management needs cheap dashboard reads." **Decision:** `operational_events` is the immutable ledger (source of truth); `operational_items` is a derived projection (cache). The projection holds `last_derived_from_op_event_id` to make its derived nature explicit. **Alternatives:**
  - Pure event sourcing → expensive reads.
  - Mutable items only → violates append-only principle.
Date: V3.

## ADR-009 — AI proposes; humans authorise (V3)
**Context:** "Human decisions remain authoritative." **Decision:** Intelligence Engine writes `ai_proposals` (decision="pending"). Coordinators/Management accept (creates operational item), edit (accepted-with-edits), or reject. Supervisor cannot accept/reject. **Alternatives:**
  - Auto-create items → violates human-authority principle.
  - Skip proposals entirely → loses AI signal value.
Date: V3.

## ADR-010 — Operational Health separate from lifecycle status (V3)
**Context:** Status = process stage; Health = current operational condition. They must not entangle. **Decision:** `status` lifecycle is one field; `health` is automatically derived from `(status, blocker, required_by, now)`. Surfaced separately in UI. Date: V3.

## ADR-011 — Blocker as a first-class concept (V3)
**Context:** The brief explicitly elevated blockers. **Decision:** `operational_items.blocker = {category, note, set_at, set_by}` (single active blocker). Setting/clearing emits ledger events. External-flavoured blockers (`awaiting_client_approval`, `vendor_payment_pending`, etc.) flip Health to `waiting_external`; internal ones to `blocked`. **Alternatives:**
  - Free-text notes (rejected — not queryable).
  - Multi-blocker stack (rejected — pilot premature; can be added when needed).
Date: V3.

## ADR-012 — Evidence inheritance over duplication (V3)
**Context:** Operational items derive from Construction Events. **Decision:** Store only `inherited_evidence_event_id`. The detail screen fetches the originating event's evidence in one extra call. No duplication. **Alternatives:** copy evidence (rejected — drift risk; duplicates raw bytes). Date: V3.

## ADR-013 — Timeline merges operational events only on explicit opt-in (V3)
**Context:** Backward compatibility. **Decision:** `GET /api/timeline?include=ops` merges `operational_events` into the chronological feed. Default behaviour returns only Construction Events. **Alternatives:** Always merge (rejected — breaks V2 clients). Date: V3.

## ADR-014 — Construction Knowledge Core is one discriminated collection, not five (V4)
**Context:** Sprint 4 asked for reusable master definitions across Categories, Phases, Activities, Checklist Templates, and Required Documents — all needing identical CRUD/search/archive/versioning mechanics. `ARCHITECTURE.md` had already reserved a single collection name (`construction_ontology`) for the Knowledge Engine slot. **Decision:** One collection `knowledge_items`, discriminated by `type`. One engine module (`knowledge_engine.py`) implements CRUD/search/archive/versioning once; per-type behaviour (category/phase refs, checklist items, document kind) is just conditional fields on the same shape. **Alternatives:**
  - Five separate collections/routes/engines → rejected: duplicates near-identical logic five times, violates "no duplicated code," and fights the single reserved-collection design already implied in the architecture docs.
Date: V4.

## ADR-015 — Knowledge relationships are generic typed edges, not a fixed `depends_on` list (V4)
**Context:** The brief's initial ask was Activity Dependencies only. On review, dependencies are one instance of a broader need: activities will eventually also link to documents, materials, equipment, and inspections. **Decision:** `knowledge_items.relationships[]` is a generic edge list — `{id, type, target_id, metadata, created_at}`. `type` is a free string; a curated `KNOWN_RELATIONSHIP_TYPES` set drives UI dropdowns but is NOT enforced server-side, so future engines can introduce new edge kinds without a schema change. V1 only exercises `depends_on`. No cycle detection / graph traversal is implemented — this is a data shape, not a scheduling engine. **Alternatives:**
  - `depends_on: [activity_id]` embedded array → rejected: would need a second schema change the moment `linked_document` or `linked_material` was needed.
  - A separate `knowledge_relationships` collection → rejected for V1: adds a join for a Dependency Viewer that always reads relationships alongside the item; revisit if relationship volume or cross-item queries grow.
Date: V4.

## ADR-016 — Knowledge versioning mirrors the Corrections pattern (V4)
**Context:** Sprint 4 requires versioning, and Atlas already has a precedent for "never overwrite a fact in place" (ADR-004, ADR-012). **Decision:** Every `knowledge_items` update snapshots the pre-edit document into append-only `knowledge_versions` before applying the change, then increments `version` on the live doc. **Alternatives:**
  - In-place edit with no history → rejected: brief explicitly requires "Versioning."
  - Full event-sourced ledger (CQRS, like `operational_events`/`operational_items`) → rejected for V1 as over-engineered for slow-moving master data; the corrections-style snapshot gives real audit history at a fraction of the complexity. Revisit if Knowledge items start changing at ledger-worthy frequency.
Date: V4.

## ADR-017 — "Admin-only" maps to the existing `management` backend role (V4)
**Context:** The sprint brief calls the Knowledge frontend "Admin-only," but Atlas has no `admin` backend role — only `supervisor | coordinator | management`. **Decision:** Reuse the mapping `frontend/src/roles.ts` already defines (`admin` view-role → `management` backend role) rather than introduce a new role. Knowledge mutation endpoints gate on `user.role == "management"`; read endpoints stay open to all authenticated roles since future engines/workspaces will need to reference this data. **Alternatives:**
  - Add a new `admin` backend role → rejected: touches auth, login, and every existing role-gated route; out of scope for an architecture sprint whose brief explicitly forbids breaking changes and redesign.
Date: V4.

## ADR-018 — Lifecycle `status` tracked alongside `archived_at`, not instead of it (V4 refinement)
**Context:** Review feedback asked for a `draft | active | deprecated | archived` lifecycle so knowledge items can be authored without immediately being visible to future consumers (e.g. Project Generation). **Decision:** Add `status` as a second, richer signal. `archived_at` keeps its existing job — the soft-archive timestamp that drives default list visibility, unchanged from the projects/sites pattern. `status` defaults to `draft` on creation. `archive_item`/`unarchive_item` keep both fields in sync (archive sets `status="archived"`; unarchive resets to `"active"`) so there remains a single owner of "is this archived," not two independently-mutable toggles that could disagree. `status="archived"` is rejected if sent through the generic `PATCH` update path — it can only be reached via the dedicated archive/unarchive actions. **Alternatives:**
  - Replace `archived_at` with `status` entirely → rejected: would have required reworking the already-shipped, already-tested archive/unarchive/list-visibility mechanics for no functional gain, and diverges from the projects/sites precedent for no reason.
  - Let `status` and `archived_at` be independently settable → rejected: two sources of truth for the same "is this archived" question invites drift (e.g. `status="archived"` with `archived_at=null`).
Date: V4.

## ADR-019 — `applicability` is a freeform dict, not hardcoded filter fields (V4 refinement)
**Context:** Review feedback asked for an extensibility point so a future Project Generation engine can filter knowledge items by project types, building types, construction types, and regions — without fully implementing that filtering now. **Decision:** Add `applicability: dict = {}` to every knowledge item. V1 stores and returns it verbatim on create/update; no code path filters on it yet. Shape is intentionally unopinionated (e.g. `{"project_types": ["residential"], "regions": ["IN-NCR"]}`) so new applicability axes never require a schema or endpoint change. **Alternatives:**
  - Hardcoded fields (`project_types: list[str]`, `building_types: list[str]`, `construction_types: list[str]`, `region: str`, ...) → rejected: locks in today's guess at the axes a future engine will need; the brief explicitly asked for an extensible object instead.
Date: V4.

## ADR-020 — Login auto-routes to a workspace instead of asking the user to pick one (V4 refinement)
**Context:** Sprint 3 added a manual "pick your workspace" selector on the login screen (Client / Supervisor / PM / Admin) as a way to reach all four frontend workspaces without needing four separate real accounts. Review feedback asked for this to be removed and replaced with fully transparent, automatic routing based on backend role. **Decision:** Centralize the mapping in `frontend/src/roles.ts`: `resolveLoginRole(phone)` picks which backend role to authenticate as (the last-known role for that phone on this device, cached in AsyncStorage per-phone; a brand-new phone+device combo falls back to `"supervisor"`, the same default the backend itself already uses), and `completeLoginRouting(phone, backendRole)` — called with the **authoritative** role from the login response, not the guess — resolves and persists the workspace via a single canonical map `DEFAULT_VIEW_ROLE_FOR` (`supervisor→supervisor`, `coordinator→pm`, `management→admin`) and remembers the role for next time. No backend endpoint, request/response shape, or auth mechanism changed — `apiLogin()`'s signature and the `/api/auth/login` contract are untouched; only what the frontend passes into it changed from "whatever the user clicked" to "an auto-resolved value." **Alternatives:**
  - Look up the account's role before logging in → rejected: no unauthenticated "role by phone" endpoint exists, and adding one would violate "do not modify backend APIs."
  - Always send a hardcoded default role on every login → rejected: since the backend's `upsert_user` overwrites `role` on every login call, this would silently downgrade returning coordinator/management users back to supervisor unless they re-selected their role every single time — which was already how the Sprint 3 selector behaved by default (its `useState` also defaulted to `'supervisor'` on every screen mount) but is worth avoiding rather than perpetuating.
  - Preserve `client` as an auto-reachable workspace → rejected: there is no backend-level signal distinguishing a "client" coordinator from a "PM" coordinator (both authenticate as backend role `coordinator`); auto-detecting a manual UI choice that was never persisted server-side isn't possible without adding backend state, which is out of scope. `client` remains fully defined in `VIEW_PERMS`/`TABS_FOR` for future use.
Date: V4.

## ADR-021 — Sign Up is a separate endpoint from Login, not a merged upsert (V4.1)
**Context:** The founder asked for a Sign Up option that creates a pending, unassigned account, while every Sprint 1-4 login flow (including documented test credentials and the entire pytest suite) relies on `/api/auth/login`'s upsert-on-first-use behaviour continuing to work exactly as before. **Decision:** Add `POST /api/auth/register` as a wholly separate path. It only ever creates a brand-new account (`memory_engine.register_user` raises if the phone already exists — never merges), sets `approval_status="pending"`, `is_active=true`, `assigned_project_ids=[]`, and a placeholder `role="supervisor"` that's functionally irrelevant until an admin assigns a real one. `/api/auth/login` is completely untouched. **Alternatives:**
  - Make `/api/auth/login` itself default new accounts to pending → rejected: would break every existing demo/test credential and the entire pytest suite's assumption that logging in with a new phone number is immediately usable, directly violating "preserve all Sprint 1-4 functionality."
  - Reuse `upsert_user` for registration too → rejected: its merge-on-existing-phone semantics are wrong for Sign Up, which must never silently reactivate or reset someone else's account.
Date: V4.1.

## ADR-022 — Pending-approval is enforced at the frontend; only `is_active=false` is a hard backend block (V4.1)
**Context:** "New users must not receive access to any project automatically... remain in Pending Approval state until assigned by an Administrator," while also "do not redesign authentication. Do not redesign permissions. Build only the foundation required for future expansion." No existing endpoint (projects/sites/events/timeline/operational-items) scopes its results by which project a user is assigned to — that's a genuinely larger, out-of-scope change. **Decision:** `is_active=false` is checked in the one shared `get_current_user` dependency and hard-blocks with 401 — this is a real, unbypassable security boundary appropriate for "Deactivate." `approval_status != "approved"` is NOT blocked at the backend; instead, the frontend's boot check (`app/index.tsx`) and login flow route a pending/rejected account to a new `/pending` screen instead of the app shell, and that screen shows no project or operational data. **Alternatives:**
  - Block `approval_status` at `get_current_user` too → rejected: would also have to special-case `/api/me` so the Pending screen can show *something*, adding branching to the single most security-sensitive function in the codebase for a product-workflow concern, not a security one. The frontend gate achieves the actual requirement (no automatic access to real workflows) without that complexity.
  - Scope every existing endpoint by `assigned_project_ids` → rejected: this is the real "future expansion" the brief points to. `assigned_project_ids` is stored and admin-manageable now so that scoping is a pure query-filter change later, not a data-model change.
Date: V4.1.

## ADR-023 — Knowledge Core optimistic concurrency via atomic `find_one_and_update`, not a separate lock (V4.1)
**Context:** Stabilization audit flagged that `update_item`/`add_relationship`/`remove_relationship` read-then-wrote without any concurrency check — a race between two concurrent edits could silently overwrite one of them despite both being recorded in version history. **Decision:** Every write now uses `find_one_and_update` with a `{"id": item_id, "version": item["version"]}` filter — atomically both the concurrency check and the pre-image capture for the version snapshot in one operation. A `None` result (no document matched, because the version moved) raises a new `KnowledgeConflictError` → HTTP 409, distinct from `KnowledgeNotFoundError` → 404 and plain `ValueError` → 400. **Alternatives:**
  - A separate advisory lock collection → rejected: unnecessary complexity for a single-collection, single-document-per-edit conflict; MongoDB's atomic single-document operations already provide exactly the guarantee needed.
  - Leave it unguarded, accept last-write-wins → rejected now that Sprint 5's Project Generation Engine is expected to start writing to this data programmatically alongside human admins, which meaningfully raises the odds of a genuine concurrent write.
Date: V4.1.

## ADR-024 — CSV export uses platform-native mechanisms, no new dependency (V4.2)
**Context:** Sprint 4.2 asked for CSV export of the User Management list. Atlas is a React Native/Expo app; a "download a file" feature on web and on native (iOS/Android) are fundamentally different operations, and the obvious native solution (`expo-file-system` + `expo-sharing`) would add two new native module dependencies requiring a rebuild this development environment cannot verify end-to-end. **Decision:** `frontend/src/csv.ts` branches on `Platform.OS`: on web, the standard `Blob` + temporary `<a download>` browser pattern (zero new dependencies, DOM globals accessed via an untyped `globalThis` cast so the file type-checks regardless of the project's `lib` config); on native, React Native's built-in `Share` API (already part of the `react-native` core package, not a new dependency) hands the CSV text to the OS share sheet, letting the person save it to Files, email it, AirDrop it, etc. **Alternatives:**
  - Add `expo-file-system`/`expo-sharing` for a literal on-device file write → rejected for this pass: a genuinely nicer native UX, but introduces a native dependency change that needs a real device/simulator build to verify, which isn't available in this development workflow. Worth revisiting once that verification path exists.
  - Backend-generated CSV (`GET /api/admin/users?format=csv` or similar) → rejected: the export needs to reflect whatever filter/search the admin currently has applied in the UI, which is client-side state; generating it client-side from the already-fetched list is simpler and needs zero new backend surface, matching "reuse existing APIs wherever possible."
Date: V4.2.
