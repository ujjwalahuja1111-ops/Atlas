# Project Atlas — Architecture

## Engine Map (current)

| # | Engine | Module | Responsibility | Status |
|---|---|---|---|---|
| 1 | Reality | `engines/reality_engine.py` | Capture voice/photo/text/GPS; persist immutably; enqueue AI | ✅ V2 |
| 2 | Memory | `engines/memory_engine.py` | The only writer to Mongo. Append-only facts. | ✅ V2 |
| 3 | Intelligence | `engines/intelligence_engine.py` | Async worker; Whisper + GPT-4o; Evidence + Prompt versioning; emits AI Proposals | ✅ V2 + V3 |
| 4 | Timeline | `engines/timeline_engine.py` | Chronological projection over events + analyses + corrections (+ ops via `include=ops`) | ✅ V2 + V3 |
| 5 | **Operations** | `engines/operations_engine.py` | Operational Items lifecycle, CQRS projection over ledger, Health derivation, AI Proposal acceptance | ✅ **V3** |
| 6 | Knowledge | *(reserved)* | Construction Ontology — Trade → Activity → Material → Equipment … | reserved |
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
| `construction_ontology`* | reserved | future Knowledge Engine |

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

## API surface

### V2 (unchanged)
`POST /api/auth/login · GET /api/me · GET/POST /api/projects · POST /api/projects/seed · GET/POST /api/sites · POST/GET /api/events · POST /api/events/{id}/corrections · GET /api/events/{id} · GET /api/timeline · GET /api/raw-assets/{id}`

### V3 (new)
`POST /api/operational-items · GET /api/operational-items · GET /api/operational-items/{id} · POST /api/operational-items/{id}/transition · POST /api/operational-items/{id}/assign · POST /api/operational-items/{id}/comments · POST /api/operational-items/{id}/blocker · DELETE /api/operational-items/{id}/blocker · POST /api/operational-items/{id}/due · POST /api/operational-items/{id}/escalate · GET /api/ai-proposals · POST /api/ai-proposals/{id}/accept · POST /api/ai-proposals/{id}/reject · GET /api/operational-center · GET /api/sites/{id}/requirements · GET /api/timeline?include=ops`

## Backward Compatibility
V2 endpoints and response shapes are unchanged. Timeline default behaviour unchanged. No data migration required.
