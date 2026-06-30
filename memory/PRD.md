# Project Atlas v3 — Construction Intelligence Platform

## Vision
Transform everyday construction communication into structured, searchable, trustworthy construction knowledge — and ensure every operational requirement remains visible until resolved. **Not** ERP/CRM/PM.

## Platform Flow
`Reality → Memory → Timeline → Intelligence → Operational Intelligence → Execution → New Reality`

## Engines

| Engine | File | Purpose |
|---|---|---|
| 1 Reality | `engines/reality_engine.py` | Capture voice/photo/text/GPS; persist immutably; enqueue AI |
| 2 Memory | `engines/memory_engine.py` | Only Mongo writer. Append-only facts. |
| 3 Intelligence | `engines/intelligence_engine.py` | Async worker; Whisper + GPT-4o; Evidence + Prompt versioning; **emits AI Proposals (V3)** |
| 4 Timeline | `engines/timeline_engine.py` | Chronological projection (+ optional ops merge) |
| 5 **Operations (V3)** | `engines/operations_engine.py` | Operational Items lifecycle, CQRS, Health, Blockers |
| 6 Knowledge | reserved | Construction Ontology |
| 7 Workflow | reserved | Future approvals automation |
| 8 Learning | reserved | AI feedback loop |

## Operational Categories (V3)
material_requirement · labour_requirement · equipment_requirement · client_approval · drawing_request · site_issue · quality_observation · safety_observation · **commitment** · **inspection** · follow_up · general

## Operational Accountability Principle
Every Operational Item, on every screen, must answer:
1. **Why does this exist?** → `origin_type` + `inherited_evidence_event_id` + creator
2. **Who currently owns it?** → `assigned_to_user_name`
3. **What is preventing completion?** → `blocker.category`

## Lifecycle
`open → assigned → acknowledged → in_progress → fulfilled → verified → closed` (+ `escalated`, `reopened`)

## Health (derived, separate from status)
`on_track / due_soon / overdue / blocked / waiting_external / completed`

## Collections
`users · projects · sites · events · raw_assets · ai_analyses · corrections · prompt_versions · ai_proposals · operational_events · operational_items · ai_feedback* · construction_ontology*` (* reserved)

## Permanent Principles
- AI never blocks workflows — events save in <300 ms.
- Raw data preserved permanently.
- Originals are immutable; corrections + AI outputs live in separate, linked collections.
- Every AI insight must be explainable through Evidence.
- AI proposes; humans accept/edit/reject. Human judgement authoritative.
- Operational Health is derived live, never overwritten.

## API surface (full)
**V2 (unchanged):** auth, /me, projects, sites, /api/events POST+GET, corrections, timeline (default), raw-assets.
**V3 (new):**
- `POST/GET /api/operational-items` · `GET /api/operational-items/{id}` · transition · assign · comments · blocker (POST/DELETE) · due · escalate
- `GET /api/ai-proposals` · `POST /api/ai-proposals/{id}/accept` · `/reject`
- `GET /api/operational-center` · `GET /api/sites/{id}/requirements`
- `GET /api/timeline?include=ops` (opt-in)

## Frontend
4 bottom tabs: TIMELINE · OPS · CAPTURE · PROFILE. New screen `/op/[id]`. The three accountability questions appear on every ops card and on the detail screen — no extra navigation required.

## V3 Acceptance Criteria — all met
✅ Operational items can be created (manual + via AI proposal acceptance).
✅ Items remain linked to Construction Events (origin_reference_id + inherited_evidence_event_id).
✅ Every status change timestamped (ledger row + projection field).
✅ Every follow-up preserved (comments + transitions live in operational_events).
✅ Management can track unresolved requirements (Operational Center + Site Requirements).
✅ Every operational item maintains traceable evidence (inherited from originating event).
✅ Timeline reflects the complete operational history when `include=ops`.
