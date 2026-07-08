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
