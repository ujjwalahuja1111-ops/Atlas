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
