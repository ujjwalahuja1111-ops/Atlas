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

## V4 — Future (not started)
Candidates: Construction Ontology (Knowledge Engine), Workflow Engine (approvals automation), Learning Engine (AI feedback loop), Documents tab on Site Workspace, multi-blocker stack.
