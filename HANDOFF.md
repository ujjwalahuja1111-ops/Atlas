# Project Atlas — Engineering Handoff (V3.3 RC1)

> A construction-intelligence platform that turns voice / photo / text site
> communication into structured, queryable knowledge.
>
> **Reality → Memory → Timeline → Intelligence → Operational Intelligence → Execution**

This document is the single onboarding artefact for a new senior engineer.
Pair it with the **canonical docs in `/memory`** which remain authoritative.

---

## Table of Contents
1. [Quick orientation](#1-quick-orientation)
2. [Tech stack](#2-tech-stack)
3. [Repository layout](#3-repository-layout)
4. [Local development](#4-local-development)
5. [Environment variables](#5-environment-variables)
6. [Dependencies](#6-dependencies)
7. [Architecture overview](#7-architecture-overview)
8. [MongoDB collections & indexes](#8-mongodb-collections--indexes)
9. [API documentation](#9-api-documentation)
10. [Authentication, roles & authorization matrix](#10-authentication-roles--authorization-matrix)
11. [Business rules, state machines & lifecycles](#11-business-rules-state-machines--lifecycles)
12. [Operational item categories & workflow](#12-operational-item-categories--workflow)
13. [Timeline & immutable ledger rules](#13-timeline--immutable-ledger-rules)
14. [AI prompts in use](#14-ai-prompts-in-use)
15. [Seed scripts](#15-seed-scripts)
16. [Test suite](#16-test-suite)
17. [Known bugs & functional limitations](#17-known-bugs--functional-limitations)
18. [Open TODOs / deferred features](#18-open-todos--deferred-features)
19. [Full changelog V1 → V3.3](#19-full-changelog-v1--v33)
20. [Canonical documents](#20-canonical-documents)

---

## 1. Quick orientation

* **Frontend** — Expo (React Native) with `expo-router` file-based routing, served by Metro on `:3000`.
* **Backend** — FastAPI + Motor on `:8001`. All routes are prefixed `/api`.
* **Database** — MongoDB on `mongodb://localhost:27017` (collections created lazily, no migrations).
* **AI** — OpenAI GPT-4o (event structuring + voice-update summaries) + Whisper (STT), via the
  `emergentintegrations` library using the **Emergent Universal LLM key**.
* **Auth** — phone + name + role login (no OTP) returning a JWT (`Authorization: Bearer …`).
* **Golden rule** — AI never blocks user workflow. `POST /api/events` returns 201 in <300 ms;
  Whisper + GPT-4o run in an async worker.

A new engineer should be able to:
1. Read `/memory/PROJECT_CONSTITUTION.md` (principles that never change).
2. Read `/memory/ARCHITECTURE.md` (engines + collections + diagram).
3. Read this file (`HANDOFF.md`) for surface-level facts + run instructions.
4. Run the local dev loop in [section 4](#4-local-development).
5. Look at `/memory/SPRINTS.md` + `/memory/DECISIONS.md` to understand the historical "why".

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Mobile | Expo SDK (React Native), `expo-router`, `expo-audio`, `expo-image`, `expo-image-picker`, `expo-location`, `expo-haptics` |
| State | React component state + `@react-native-async-storage/async-storage` for tokens |
| HTTP | native `fetch` (no axios) |
| Backend | Python 3.11, FastAPI, Uvicorn |
| DB driver | Motor (async MongoDB) |
| AI / LLM | OpenAI GPT-4o + Whisper through `emergentintegrations.llm.chat.LlmChat` |
| Auth | PyJWT HS256, phone+name registration on first login |
| Lint | ruff (Python), ESLint (TS) |
| Tests | pytest + httpx async client |
| Process manager | `supervisord` (services: `backend`, `expo`, `mongodb`, `nginx-code-proxy`) |

---

## 3. Repository layout

```
/app
├── backend/
│   ├── server.py                       # FastAPI app + lifespan + worker boot
│   ├── core/
│   │   ├── auth.py                     # JWT encode/decode, get_current_user dep
│   │   ├── db.py                       # Motor client + ensure_indexes()
│   │   └── settings.py                 # env loading
│   ├── engines/
│   │   ├── reality_engine.py           # event capture + asset persistence
│   │   ├── memory_engine.py            # ONLY Mongo writer
│   │   ├── intelligence_engine.py      # async worker, Whisper, GPT-4o, proposals
│   │   ├── timeline_engine.py          # chronological projection
│   │   └── operations_engine.py        # operational items + ledger + CQRS
│   ├── routes/
│   │   ├── auth.py                     # /api/auth/login, /api/me
│   │   ├── projects.py                 # projects + sites CRUD + archive
│   │   ├── events.py                   # POST/GET /api/events + corrections
│   │   ├── raw_assets.py               # asset download
│   │   ├── timeline.py                 # /api/timeline
│   │   ├── ai_proposals.py             # accept/reject
│   │   ├── operational_items.py        # full ops surface
│   │   └── operational_center.py       # dashboard buckets + site requirements
│   ├── tests/
│   │   ├── test_atlas_v3_2.py          # 13/13 passing
│   │   ├── test_atlas_v2.py            # legacy V2 regression
│   │   └── test_construction.py        # legacy V1 smoke
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── _layout.tsx                 # Root Stack + font preloading
│   │   ├── login.tsx                   # ATLAS login screen
│   │   ├── (tabs)/
│   │   │   ├── _layout.tsx             # 4-tab bar (Timeline / Ops / Capture / Profile)
│   │   │   ├── index.tsx               # Timeline
│   │   │   ├── ops.tsx                 # Operational Center (lists + per-card assign)
│   │   │   ├── capture.tsx             # Voice + photo + text capture
│   │   │   └── profile.tsx             # User + logout
│   │   ├── event/[id].tsx              # Construction Event detail (transcript, photos, proposals)
│   │   ├── op/[id].tsx                 # Operational Item detail (edit, voice-update, activity)
│   │   └── projects/index.tsx          # V3.3 project management screen
│   ├── src/
│   │   ├── api.ts                      # auth, projects, sites, timeline, events
│   │   ├── ops_api.ts                  # operational items, proposals, voice-update, duplicate
│   │   ├── theme.ts
│   │   ├── hooks/use-icon-fonts.ts
│   │   └── utils/
│   ├── constants/                      # shared testIds + colours
│   ├── assets/                         # fonts + images
│   ├── app.json
│   ├── metro.config.js
│   ├── tsconfig.json
│   └── package.json
├── memory/                             # CANONICAL DOCUMENTATION
│   ├── PROJECT_CONSTITUTION.md
│   ├── ARCHITECTURE.md
│   ├── PRD.md
│   ├── DECISIONS.md
│   ├── SPRINTS.md
│   └── test_credentials.md
├── HANDOFF.md                          # this file
└── README.md
```

---

## 4. Local development

```bash
# Backend
cd /app/backend
cp .env.example .env                    # fill EMERGENT_LLM_KEY, JWT_SECRET, MONGO_URL
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Frontend
cd /app/frontend
cp .env.example .env                    # set EXPO_PUBLIC_BACKEND_URL
yarn install
yarn expo start --port 3000
```

MongoDB must be reachable at `MONGO_URL`. Collections create lazily on first insert.

In the hosted environment we use supervisor:
```bash
sudo supervisorctl restart backend
sudo supervisorctl restart expo
```

> **Never** edit `EXPO_PACKAGER_PROXY_URL`, `EXPO_PACKAGER_HOSTNAME`, or `MONGO_URL` in `.env`.

---

## 5. Environment variables

### `backend/.env.example`
```env
MONGO_URL="mongodb://localhost:27017"
DB_NAME="construct_events"
EMERGENT_LLM_KEY="REPLACE_WITH_EMERGENT_LLM_KEY"
JWT_SECRET="REPLACE_WITH_LONG_RANDOM_SECRET"
# EMERGENT_BASE_URL="https://integrations.emergentagent.com/llm/openai/v1"   # optional override
```

### `frontend/.env.example`
```env
EXPO_PUBLIC_BACKEND_URL="http://localhost:8001"
# Managed by Emergent preview (do NOT hardcode for local dev):
# EXPO_TUNNEL_SUBDOMAIN=""
# EXPO_PACKAGER_HOSTNAME=""
# EXPO_PACKAGER_PROXY_URL=""
EXPO_USE_FAST_RESOLVER="1"
METRO_CACHE_ROOT="./.metro-cache"
```

---

## 6. Dependencies

**Python** (`backend/requirements.txt`) — key packages:
`fastapi`, `uvicorn[standard]`, `motor`, `pymongo`, `python-multipart`, `pyjwt`, `python-dotenv`,
`pydantic`, `openai`, `emergentintegrations`, `httpx`, `pytest`, `pytest-asyncio`.
Full pinned list lives in `requirements.txt`.

**Node** (`frontend/package.json`) — key packages:
`expo`, `expo-router`, `expo-audio`, `expo-image`, `expo-image-picker`, `expo-location`,
`expo-haptics`, `expo-font`, `expo-splash-screen`, `react`, `react-native`, `react-native-safe-area-context`,
`react-native-screens`, `react-native-gesture-handler`, `react-native-reanimated`,
`@react-native-async-storage/async-storage`, `@expo/vector-icons`, `typescript`, `eslint`.
Full pinned tree lives in `package.json` + `yarn.lock`.

---

## 7. Architecture overview

> Authoritative diagram + collection map: see `/memory/ARCHITECTURE.md`.

Six engines, each single-purpose:

| # | Engine | Responsibility |
|---|---|---|
| 1 | **Reality** (`reality_engine.py`) | Validates and persists capture (voice/photo/text/GPS) into `events` + `raw_assets`. Enqueues to Intelligence. Returns to user in <300 ms. |
| 2 | **Memory** (`memory_engine.py`) | The only writer to MongoDB. Enforces append-only on facts. Exposes `set_event_ai_status`, `set_event_proposals_status` lifecycle markers — *not* fact mutators. |
| 3 | **Intelligence** (`intelligence_engine.py`) | Async `asyncio.Queue` worker started by FastAPI lifespan. Whisper → GPT-4o → `ai_analyses` (with explicit evidence + prompt_version_id) → `ai_proposals`. Idempotent. Includes V3.2.2 recovery for analyzed-without-proposals orphans. |
| 4 | **Timeline** (`timeline_engine.py`) | Read-only chronological projection over `events + ai_analyses + corrections`. Opt-in merge of operational events via `?include=ops`. |
| 5 | **Operations** (`operations_engine.py`) | CQRS: `operational_events` is the append-only ledger; `operational_items` is a derived projection (rebuildable). Owns lifecycle transitions, blocker management, health derivation, time intelligence, AI proposal acceptance, V3.3 edits, voice updates, duplicate marking. |
| 6 | **Knowledge** (`knowledge_engine.py`) | Construction Knowledge Core (V4). One collection `knowledge_items` discriminated by `type` (category/phase/activity/checklist_template/required_document). Generic typed `relationships[]` edges, versioning via `knowledge_versions` snapshots, soft-archive. Admin-only mutations. |

Engines 7–8 (Workflow / Learning) remain reserved; `ai_feedback` collection placeholder exists.

### Request → write → projection flow

```
POST /api/events  ─►  Reality Engine  ─►  Memory Engine writes events+raw_assets ─►
                                                                                  enqueue
                                                                                       │
                                                                                       ▼
                                                                  Intelligence Engine
                                                                  ├─ Whisper (audio→text)
                                                                  ├─ GPT-4o (structured JSON)
                                                                  ├─ Memory.put_ai_analysis()
                                                                  └─ generate_proposals_for_event()
                                                                            │
                                                                            ▼
                                                                  ai_proposals (decision=pending)
                                                                            │  /accept (coordinator/management)
                                                                            ▼
                                                                  Operations.create_item()
                                                                  ├─ operational_events (created)
                                                                  └─ operational_items (projection)
```

---

## 8. MongoDB collections & indexes

| Collection | Mutability | Purpose | Key fields |
|---|---|---|---|
| `users` | upsert by `phone` (login) + admin-managed (V4.1) | name / role / phone | `id`, `phone`, `name`, `role`, `created_at`, `approval_status?` (V4.1: pending/approved/rejected, default approved when absent), `is_active?` (V4.1: default true when absent), `assigned_project_ids?` (V4.1: default [] when absent) |
| `projects` | insert + small upsert | project root | `id`, `name`, `code`, `location`, `image_url`, `created_at`, `archived_at?`, `updated_at?` |
| `sites` | insert + small upsert | site under project | `id`, `project_id`, `name`, `location`, `image_url`, `created_at` |
| `events` | **append-only facts**; only `ai_status`, `ai_analysis_id`, `proposals_status`, `proposals_error` markers may change | Construction Events | `id`, `site_id`, `user_id`, `user_name`, `kind`, `text_input`, `audio_asset_id`, `photo_asset_ids`, `gps`, `server_created_at`, `client_created_at`, `app_version`, `ai_status`, `ai_analysis_id`, `proposals_status` |
| `raw_assets` | immutable | audio + photo bytes | `id`, `event_id`, `kind`, `mime`, `size_bytes`, `data_base64`, `sha256`, `created_at` |
| `ai_analyses` | one doc per event, write-once | structured AI output | `id`, `event_id`, `transcript`, `language_detected`, `structured`, `evidence`, `model_versions`, `prompt_version_id`, `prompt_name`, `prompt_version`, `started_at`, `finished_at`, `error` |
| `corrections` | append-only | linked human corrections | `id`, `original_event_id`, `corrected_by_user_id`, `corrected_by_user_name`, `payload`, `created_at` |
| `prompt_versions` | append-only | every prompt version archived | `id`, `name`, `version`, `model`, `system_prompt`, `notes`, `created_at` |
| `ai_proposals` | append-only; decision recorded once | AI-suggested ops items | `id`, `event_id`, `site_id`, `category`, `title`, `description`, `suggested_priority`, `suggested_owner_role`, `confidence`, `decision`, `decided_by_*`, `operational_item_id`, `source_snippet`, `details`, `created_at` |
| `operational_events` | **append-only ledger** | every lifecycle / comment / blocker / edit / voice-update / assign event | `id`, `operational_item_id`, `kind`, `actor_user_id`, `actor_user_name`, `prev_status`, `new_status`, `payload`, `created_at` |
| `operational_items` | derived projection (rebuildable) | cheap current-state read | `id`, `category`, `title`, `description`, `site_id`, `project_id`, `origin_type`, `origin_reference_id`, `inherited_evidence_event_id`, `status`, `priority`, all `*_by_user_*` + `*_at` fields, `blocker`, `health`, `last_updated_at`, `last_derived_from_op_event_id`, `suggested_owner_role?`, `ai_details?`, `ai_confidence?`, `duplicate_of_item_id?` |
| `ai_feedback`* | reserved | future Learning Engine | — |
| `knowledge_items` | soft-archive + versioned | Construction Knowledge Core (V4) master data | `id`, `type`, `name`, `description`, `code`, `category_id?`, `phase_id?`, `tags[]`, `ai_keywords[]`, `default_duration_days?`, `checklist_items[]`, `document_kind?`, `relationships[]`, `version`, `archived_at?`, `created_by_*`, `updated_by_*`, `created_at`, `updated_at` |
| `knowledge_versions` | **append-only** | immutable pre-edit snapshots of `knowledge_items`, mirrors `corrections` pattern | `id`, `item_id`, `item_type`, `version`, `snapshot`, `changed_by_*`, `created_at` |

`*` = reserved, not yet written by any code path.

**Indexes** (declared in `backend/core/db.py`): primarily `id`-based lookups. Add domain
indexes (`events.site_id+server_created_at`, `operational_events.operational_item_id+created_at`,
`operational_items.site_id`, `ai_proposals.event_id+decision`) before scaling beyond pilot.

**Relationships**
* `sites.project_id → projects.id`
* `events.site_id → sites.id`, `events.user_id → users.id`
* `raw_assets.event_id → events.id`
* `ai_analyses.event_id → events.id` (1:1)
* `ai_proposals.event_id → events.id`, `ai_proposals.operational_item_id → operational_items.id`
* `operational_items.inherited_evidence_event_id → events.id`
* `operational_events.operational_item_id → operational_items.id`
* `operational_items.duplicate_of_item_id → operational_items.id` (V3.3)
* `corrections.original_event_id → events.id`

No `_id` is ever leaked over the API — everything is keyed on the string `id` field.

---

## 9. API documentation

All routes are prefixed `/api`. All endpoints except `POST /api/auth/login` require
`Authorization: Bearer <jwt>`. All responses are JSON.

### 9.1 Auth

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/auth/login` | `{phone, name, role}` | `{token, user}` |
| `GET` | `/api/me` | — | current `user` |

```bash
curl -X POST http://localhost:8001/api/auth/login \
  -H "content-type: application/json" \
  -d '{"phone":"9222222222","name":"Priya Coordinator","role":"coordinator"}'
# → {"token":"<jwt>","user":{"id":"…","phone":"9222222222","name":"…","role":"coordinator","created_at":"…"}}
```

### 9.2 Projects (V3.3)

| Method | Path | Body | Role gate |
|---|---|---|---|
| `GET` | `/api/projects` (+ `?include_archived=true`) | — | any |
| `POST` | `/api/projects` | `{name, code?, location?, image_url?}` | not supervisor |
| `PATCH` | `/api/projects/{id}` | partial | not supervisor |
| `POST` | `/api/projects/{id}/archive` | — | not supervisor |
| `POST` | `/api/projects/{id}/unarchive` | — | not supervisor |
| `POST` | `/api/projects/seed` | — | any (idempotent demo seed) |

### 9.3 Sites

| Method | Path |
|---|---|
| `GET` | `/api/sites` (+ `?project_id=…`) |
| `POST` | `/api/sites` (not supervisor) |

### 9.4 Events (Reality)

| Method | Path | Body |
|---|---|---|
| `POST` | `/api/events` | multipart: `site_id` (form), optional `text` / `gps` / `client_created_at` / `app_version` (form), optional `audio` (file), optional `photos[]` (files) |
| `GET` | `/api/events/{id}` | — |
| `POST` | `/api/events/{id}/corrections` | `{note, corrected_field?, new_value?, reason?}` |
| `POST` | `/api/events/{id}/regenerate-proposals` | — (coordinator/management) |

```bash
# capture a multi-intent text event
curl -X POST http://localhost:8001/api/events \
  -H "Authorization: Bearer $TK" \
  -F "site_id=$SITE" \
  -F "text=Kal 30 bags cement chahiye. Do electrician bhejna. Crane kharab hai."
# → {"id":"evt_…","ai_status":"pending", …}     (201, <300 ms)
```

### 9.5 Timeline

```
GET /api/timeline?site_id=<id>            # construction events only
GET /api/timeline?site_id=<id>&include=ops  # merged with operational events
```

### 9.6 Raw assets

```
GET /api/raw-assets/{asset_id}        # base64 photo/audio bytes
```

### 9.7 AI proposals

| Method | Path | Body |
|---|---|---|
| `GET` | `/api/ai-proposals` (+ `event_id` / `site_id` / `status` filters) | — |
| `POST` | `/api/ai-proposals/{id}/accept` | optional edits + `assigned_to_user_id` |
| `POST` | `/api/ai-proposals/{id}/reject` | `{reason?}` |

```bash
curl -X POST http://localhost:8001/api/ai-proposals/$PROP/accept \
  -H "Authorization: Bearer $TK" -H "content-type: application/json" \
  -d '{"assigned_to_user_id":"<userId>"}'
# → operational item doc (201)
```

### 9.8 Operational items (V3 + V3.3)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/operational-items` | manual create |
| `GET` | `/api/operational-items` (+ `site_id`, `status`, `priority`, `category`, `assigned_to_me=true`) | list |
| `GET` | `/api/operational-items/{id}` | returns `{item, history, evidence}` |
| `POST` | `/api/operational-items/{id}/transition` | `{to_status, note?}` |
| `POST` | `/api/operational-items/{id}/assign` | `{assigned_to_user_id, note?}` |
| `POST` | `/api/operational-items/{id}/comments` | `{text}` |
| `POST` | `/api/operational-items/{id}/blocker` | `{category, note?}` |
| `DELETE` | `/api/operational-items/{id}/blocker` | clears |
| `POST` | `/api/operational-items/{id}/due` | `{required_by}` |
| `POST` | `/api/operational-items/{id}/escalate` | `{reason}` |
| `PATCH` | `/api/operational-items/{id}` | **V3.3** — `{title?, description?, priority?, required_by?, quantity?, unit?, assigned_to_user_id?}` |
| `POST` | `/api/operational-items/{id}/voice-update` | **V3.3** — multipart `audio` |
| `POST` | `/api/operational-items/{id}/duplicate` | **V3.3** — `{duplicate_of_item_id, note?}` |
| `GET` | `/api/users` (+ `?role=…`) | for assignee pickers; phone stripped |

### 9.9 Dashboards

```
GET /api/operational-center            # buckets: open / overdue / high_priority / awaiting_verification / recently_completed / recently_updated + counts
GET /api/sites/{site_id}/requirements  # living checklist for requirement categories
```

### 9.9a Construction Knowledge Core (V4, admin-only mutations)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/knowledge-items` (+ `type`, `category_id`, `phase_id`, `tag`, `status`, `q`, `include_archived`) | list/search/filter; open to all roles |
| `POST` | `/api/knowledge-items` | create; **management role only**; `status` defaults to `draft` |
| `GET` | `/api/knowledge-items/{id}` | enriched with `category_name`/`phase_name`/`relationships[].target_name` |
| `PATCH` | `/api/knowledge-items/{id}` | update; bumps `version`, snapshots prior state; **management only**; `status` accepts `draft`/`active`/`deprecated` only — not `archived` (use the archive endpoint) |
| `POST` | `/api/knowledge-items/{id}/archive` / `/unarchive` | soft-archive; **management only**; also sets `status` to `archived`/`active` respectively |
| `GET` | `/api/knowledge-items/{id}/versions` | immutable pre-edit snapshots, newest first |
| `POST` | `/api/knowledge-items/{id}/relationships` | `{type, target_id, metadata?}`; generic typed edge; **management only** |
| `DELETE` | `/api/knowledge-items/{id}/relationships/{relationship_id}` | **management only** |
| `GET` | `/api/knowledge-meta` | `{types[], relationship_types[], statuses[]}` vocab for UI dropdowns |

`knowledge_items` also carries a reserved `applicability` dict (freeform — project types, building types, construction types, regions, ...) for future project-generation filtering. Not read by any filter logic in V4.

**V4.1 additions:** `PATCH /api/knowledge-items/{id}`, `POST .../relationships`, and `DELETE .../relationships/{id}` now use optimistic concurrency (atomic version-matched write) and return `409` on a genuine conflict instead of silently overwriting. "Item not found" now returns `404` (was `400`) on every mutation, distinct from a validation error.

### 9.9b Authentication & User Management (V4.1)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/auth/register` | Sign Up — `{phone, name}`; create-only, rejects an existing phone with 400; new account starts `approval_status=pending`, `is_active=true`, `assigned_project_ids=[]`. Separate from and does not affect `/api/auth/login`. |
| `PATCH` | `/api/me` | Self-service name edit — `{name}` only; never touches role/approval/projects. |
| `GET` | `/api/admin/users` (+ `approval_status`) | **management only**; list users, optionally filtered |
| `POST` | `/api/admin/users/{id}/approve` / `/reject` | **management only** |
| `POST` | `/api/admin/users/{id}/role` | `{role}`; **management only** |
| `POST` | `/api/admin/users/{id}/projects` | `{project_ids}`; **management only** |
| `POST` | `/api/admin/users/{id}/active` | `{is_active}`; **management only**; rejects deactivating your own account (400) |
| `DELETE` | `/api/projects/{id}` | Hard-delete only if zero sites (archived or active) reference it; 409 with blocking counts otherwise. Mirrors `DELETE /api/sites/{id}` exactly. **management/coordinator only.** |

### 9.9c System Information (V4.2)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/admin/system-info` | **management only**; read-only. Returns `{project_name, version, git_commit, build_date, server_started_at, uptime_seconds, backend_status, database_status, total_users, total_projects, total_sites, pending_approvals}`. `database_status` is a real `db.command("ping")`, not just "the process responded." |

### 9.10 Response shapes

Examples in the V3.2 test suite (`backend/tests/test_atlas_v3_2.py`) and in the existing
`/tmp/atlas_review.zip` export are the most accurate reference.

---

## 10. Authentication, roles & authorization matrix

### Auth
- Phone + name + role login (no OTP). First login auto-creates the user.
- JWT (HS256) signed with `JWT_SECRET`. `iat` claim only.
- All endpoints except `POST /api/auth/login` require `Authorization: Bearer <jwt>`.
- Phone numbers are stripped from `/api/users` to avoid pilot PII leakage.

### Roles
| Role | Description |
|---|---|
| `supervisor` | Field user. Captures events. Cannot accept proposals, cannot manage projects. |
| `coordinator` | Office user. Accepts/rejects proposals, assigns work, edits items, manages projects. |
| `management` | Senior user. Same as coordinator + can escalate / create from any origin. |
| `site_engineer` | Suggested owner role for site issues (no extra permissions yet). |
| `client_coordinator` | Suggested owner role for client approvals (no extra permissions yet). |
| `architect` / `qa` / `safety_officer` | Suggested owner roles for relevant categories. |

### Authorization matrix
| Action | supervisor | coordinator | management |
|---|---|---|---|
| Login + capture event | ✅ | ✅ | ✅ |
| View timeline / ops / proposals | ✅ | ✅ | ✅ |
| Create / edit / archive project | ❌ (403) | ✅ | ✅ |
| Accept / reject AI proposal | ❌ (403) | ✅ | ✅ |
| Assign / reassign operational item | ✅ | ✅ | ✅ |
| Edit operational item (V3.3) | ✅ | ✅ | ✅ |
| Voice-update operational item (V3.3) | ✅ | ✅ | ✅ |
| Regenerate proposals | ❌ (403) | ✅ | ✅ |
| Escalate | ✅ | ✅ | ✅ |
| Transition status (incl. archive/cancel) | ✅ | ✅ | ✅ |
| Read Construction Knowledge (V4) | ✅ | ✅ | ✅ |
| Create/edit/archive Construction Knowledge (V4) | ❌ (403) | ❌ (403) | ✅ |
| Delete project (V4.1, only if zero sites) | ❌ (403) | ✅ | ✅ |
| Sign Up (V4.1) | n/a — unauthenticated | n/a | n/a |
| Approve/reject/assign users (V4.1) | ❌ (403) | ❌ (403) | ✅ |
| Edit own name (`PATCH /api/me`, V4.1) | ✅ | ✅ | ✅ |
| Use the app at all, if `is_active=false` (V4.1) | ❌ (401, any role) | ❌ (401) | ❌ (401) |

### Frontend workspace routing (V4 cleanup)
Sprint 3 added four *view-role* workspaces (Client / Supervisor / PM / Admin) layered on top of the three backend roles, originally chosen via a manual picker on the login screen. That picker is gone. Login now auto-resolves the workspace: `frontend/src/roles.ts` caches the last-known backend role per phone number per device, sends that (or the same `supervisor` default the backend itself uses for a brand-new phone) to the unchanged `POST /api/auth/login`, then routes into the workspace matching the **authoritative** role returned in the response via a single canonical map — `supervisor→supervisor`, `coordinator→pm`, `management→admin`. No backend route, request/response shape, or JWT mechanics changed. `client` remains fully defined in the frontend's permission tables but is no longer reachable via login auto-routing, since no backend signal distinguishes a "client" coordinator from a "PM" coordinator. See `memory/DECISIONS.md` ADR-020.

### Sign Up / Pending Approval (V4.1)
`POST /api/auth/register` creates a new account with `approval_status=pending`; an Administrator must approve it via the new User Management screen (`app/users/index.tsx`, admin-only nav entry on Profile) before it's routed into a real workspace — until then, both the login flow and the app's boot check route it to `app/pending.tsx` instead. Only `is_active=false` is enforced at the backend (401 from `get_current_user`); `approval_status` is a frontend-only gate by design — see `memory/DECISIONS.md` ADR-022 for why, and its documented boundary (no per-project data scoping yet).

---

## 11. Business rules, state machines & lifecycles

### Permanent rules (from `PROJECT_CONSTITUTION.md`)
1. Construction comes first — operations continue even if AI is down.
2. AI never blocks workflows (<300 ms event capture).
3. Raw data is preserved permanently.
4. AI interpretations are stored separately from factual records.
5. Human corrections never overwrite original facts.
6. Every AI insight must be explainable through Evidence.
7. Every architectural component is independently replaceable.
8. Data quality > AI sophistication.
9. Platform architecture > feature expansion.
10. Human judgement is authoritative — AI proposes; humans decide.

### Event lifecycle (Construction Events)
`pending → analyzed | failed | skipped` (one-way; the event document itself never mutates).

### Proposal lifecycle (AI Proposals)
`pending → accepted | edited | rejected` (one-way, decision recorded once).

### Operational Item state machine (V3.3)

States: `open, assigned, acknowledged, in_progress, fulfilled, verified, closed, reopened, archived, cancelled, duplicate`.

Allowed transitions (`operations_engine.TRANSITIONS`):

```
open         → assigned, acknowledged, in_progress, closed, archived, cancelled, duplicate
assigned     → acknowledged, in_progress, open, closed, archived, cancelled, duplicate
acknowledged → in_progress, fulfilled, closed, archived, cancelled, duplicate
in_progress  → fulfilled, closed, archived, cancelled, duplicate
fulfilled    → verified, in_progress, closed, archived
verified     → closed, reopened, archived
closed       → reopened, archived
reopened     → assigned, in_progress, open, closed, archived, cancelled, duplicate
archived     → open, reopened
cancelled    → open, reopened
duplicate    → open, reopened
```

Every transition appends a ledger row with `kind` matching the new status
(`assigned`, `started`, `fulfilled`, `verified`, `closed`, `reopened`, `archived`, `cancelled`)
and updates the projection's `status` + relevant `*_at` time field.

### Health (derived live, separate from status)
`on_track | due_soon | overdue | blocked | waiting_external | completed`.
Computed by `derive_health(item)` from `(status, blocker, required_by, now)`.
External blocker categories flip to `waiting_external`; others to `blocked`.

### Time intelligence (computed on read, never stored)
`current_age_hours, time_remaining_hours, days_overdue, time_to_complete_hours, verification_delay_hours`.

---

## 12. Operational item categories & workflow

Twelve categories from `operations_engine.CATEGORIES`:

`material_requirement · labour_requirement · equipment_requirement · client_approval ·
drawing_request · site_issue · quality_observation · safety_observation · commitment ·
inspection · follow_up · general`

Origin types (`operations_engine.ORIGIN_TYPES`):
`ai_proposal · manual · coordinator · management · client · architect · future_integration`.

Each category gets a default suggested owner role from the Intelligence Engine's
proposal emitter (see `_emit_proposals_from_structured` in `intelligence_engine.py`),
e.g. material → `coordinator`, client_approval → `client_coordinator`,
site_issue → `site_engineer`, drawing_request → `architect`, safety → `safety_officer`,
inspection → `qa`.

The category-aware **primary-action** logic on the op detail screen
(`primaryFor()` in `frontend/app/op/[id].tsx`) maps `(category, status)` to a
single one-tap CTA — e.g. `material_requirement + in_progress → "MARK DELIVERED"`,
`drawing_request + in_progress → "MARK RECEIVED"`.

---

## 13. Timeline & immutable ledger rules

### Construction events
* `events` is append-only for facts. Only `ai_status`, `ai_analysis_id`,
  `proposals_status`, `proposals_error` lifecycle markers can change.
* `raw_assets` is fully immutable.
* `ai_analyses` is one doc per event; write-once.
* User corrections live in a separate `corrections` collection, append-only.
* Default `/api/timeline` returns only construction events to preserve V2 backward compat.
  Opt-in operational merge via `?include=ops`.

### Operational ledger (CQRS)
* `operational_events` is the **single source of truth** for an item's history.
  Append-only. No row is ever updated or deleted.
* `operational_items` is a **derived projection** with `last_derived_from_op_event_id`
  pointing at the most recent ledger row. The projection can be wiped and rebuilt from
  the ledger at any time without data loss.
* All mutating engine functions follow the pattern:
  1. fetch projection (`get_item`)
  2. compute new state
  3. `append_event(...)` (ledger)
  4. update projection in memory
  5. `_save_item(...)` (upsert projection)
* Ledger event kinds today: `created · assigned · reassigned · acknowledged · started ·
  fulfilled · verified · closed · reopened · archived · cancelled · duplicate_of ·
  blocker_set · blocker_cleared · due_set · escalated · comment · edited · voice_update`.

### Voice-update audio linkage
`voice_update` ledger rows carry `payload.audio_asset_id`, `payload.transcript`,
`payload.summary`, `payload.language`. The original audio asset is stored in
`raw_assets` with `event_id = "op:<item_id>"` so it stays addressable and immutable.

---

## 14. AI prompts in use

Prompts live inline in `backend/engines/intelligence_engine.py` (no separate prompt files).
Each is stored in `prompt_versions` on first use; every `ai_analyses` doc records
`prompt_version_id`, `prompt_name`, `prompt_version`.

### Prompt 1 — `atlas_event_structurer` v1.1 (`EVENT_SYSTEM_PROMPT`)
Multi-intent extractor for Hindi / Punjabi / Hinglish / English supervisor utterances.
Returns a strict JSON object with keys:
`type · title · summary · materials[] · labour[] · equipment[] · client_approvals[] ·
drawing_requests[] · inspections[] · safety_observations[] · quality_observations[] ·
commitments[] · follow_ups[] · issues[] · work_done[] · urgency · language_detected`.
Rules: never invent values, every entry must come from the speaker's actual words,
confidence ∈ {low, medium, high}, priority ∈ {low, normal, high, critical} (critical only
for explicit emergencies), output JSON only.

### Prompt 2 — voice-update summary (V3.3)
Used by `summarise_voice_update()` to produce a ≤20-word English summary of a
voice-update transcript, with `language_detected`. Receives item title + category +
status as context so the summary is contextually relevant.

### Whisper
`whisper-1` via `OpenAI` client (Emergent base URL). Mime sniffed from the upload
content-type with extension fallbacks for `wav / mp3 / webm / ogg / m4a`.

---

## 15. Seed scripts

* **Demo seed** — `POST /api/projects/seed` (in `backend/routes/projects.py`).
  Idempotent. Creates one demo project `Atlas Pilot Construction` (`ATL-01`) and three sites
  (Tower A, Metro Line Extension, Residency Block C) **only if** no projects exist.
* **Test credentials** — `/memory/test_credentials.md` documents the seed users used in
  pytest + dev. Auto-create on first login.
* **No DB migration scripts.** MongoDB collections create lazily. The Intelligence worker
  startup includes a **V3.2.2 recovery pass** that backfills proposals for any event in
  state `ai_status=analyzed` with missing/null `proposals_status` (idempotent — skips events
  that already have proposals).

---

## 16. Test suite

| File | Coverage |
|---|---|
| `backend/tests/test_atlas_v4_2.py` | Sprint 4.2 Admin Experience: system-info endpoint field presence, admin gating, live-count reflection, regression smoke on Sprint 1-4.1 endpoints and existing User Management routes. 11 cases. |
| `backend/tests/test_atlas_v4_1.py` | Sprint 4.1 stabilization: Sign Up/Pending Approval workflow, admin User Management (approve/reject/assign role/assign projects/activate-deactivate), self-service `PATCH /api/me`, project `DELETE` with dependency guard, Knowledge Core 404/400/409 distinction, phone validation, regression smoke on Sprint 1-4 endpoints. 20 cases. |
| `backend/tests/test_atlas_v4.py` | Construction Knowledge Core (V4): CRUD, search/filter, archive/versioning, generic relationships, lifecycle status, admin gating. |
| `backend/tests/test_atlas_v3_2.py` | Current authoritative V3 suite. 13 cases: multi-intent extraction (≥4 categories from Hinglish utterance), material/labour/equipment detail shape, user directory (no phone leak, role filter), assign+reassign ledger growth, accept-with-assign one-tap, supervisor 403 on accept, V3.1 backward-compat smoke. |
| `backend/tests/test_atlas_v2.py` | Legacy V2 regression. |
| `backend/tests/test_construction.py` | Legacy V1 smoke. |

```bash
# Run the V4.1 suite (20/20 expected)
cd /app && pytest backend/tests/test_atlas_v4_1.py -v

# Run everything
cd /app && pytest backend/tests -v
```

Notes:
* The Intelligence-Engine-dependent tests need `EMERGENT_LLM_KEY` to be funded; with a
  zero-balance key the LLM falls back gracefully but multi-intent tests will fail.
* The V3.3 endpoints (PATCH item, voice-update, duplicate, project CRUD) are exercised
  end-to-end with curl/python in the V3.3 sprint validation script — adding dedicated
  pytest coverage is on the deferred TODO list.

---

## 17. Known bugs & functional limitations

| ID | Description | Severity |
|---|---|---|
| KB-1 | `props.pointerEvents is deprecated. Use style.pointerEvents` — emitted by RN-Web internals. Cosmetic only. | low |
| KB-2 | Pre-existing ruff `E701` / `E741` warnings in `engines/*.py` style. No functional impact. | low |
| KB-3 | V3.3 activity kinds (`edited`, `voice_update`, `duplicate_of`, `archived`, `cancelled`) lack pytest coverage. Validated only via the V3.3 live curl harness. | low |
| KB-4 | Single-instance in-process `asyncio.Queue` worker. If the backend pod restarts mid-analysis the V3.2.2 recovery picks up missed proposals on next start; mid-Whisper failures are marked `ai_status="failed"`. Not horizontally scalable as-is. | medium |
| KB-5 | Raw assets stored as base64 inside `raw_assets` documents. Works for the pilot; will not scale beyond a few hundred MB per site. S3 / MinIO migration deferred. | medium |
| KB-6 | Browser-recorded audio on web (`webm/opus`) is mime-sniffed but Whisper occasionally returns short empty transcripts on very small clips. Native `m4a` from Expo apps works reliably. | low |
| KB-7 | `operational_items` projection can lag the ledger by one row if a crash happens between `append_event` and `_save_item`. Mitigation path documented in `SPRINTS.md` (rebuild from ledger) but not exposed in UI. | low |
| KB-8 | `EMERGENT_LLM_KEY` budget exhaustion silently degrades AI quality (Whisper / GPT-4o calls return empty structures); proposals_status will read `empty`. Not surfaced in UI. | medium |
| KB-9 | No MongoDB indexes beyond `_id`. Fine at pilot scale; needs explicit indexes before scaling (`events.site_id+server_created_at`, `operational_events.operational_item_id+created_at`, `operational_items.site_id`, `ai_proposals.event_id+decision`). | medium |

---

## 18. Open TODOs / deferred features

* ~~**Engine 6 — Knowledge Engine** (Construction Ontology).~~ Delivered in V4 (Sprint 4) as `knowledge_items`/`knowledge_versions`. See §9.9a and `memory/ARCHITECTURE.md`.
* **Engine 7 — Workflow Engine** (approvals automation).
* **Engine 8 — Learning Engine** (feedback loop). Reserved collection `ai_feedback`.
* **Knowledge graph cycle detection** — `depends_on` relationships have no cycle guard yet; needed before a future Scheduling/Baseline engine consumes the dependency graph for sequencing.
* **Multi-blocker stack** (only single active blocker today).
* **S3 / MinIO** for raw assets.
* **Pytest coverage for V3.3** (edit / voice-update / duplicate / archive / cancel paths,
  project CRUD).
* **Mongo indexes** as listed in KB-9.
* **Recompute projection** helper exposed via internal route (for ops drift recovery).
* **Re-analyze** AI on user-edited proposals before acceptance (currently trusts edits).
* **Push notifications** — *only on explicit user request*. Do not propose unsolicited.

---

## 19. Full changelog V1 → V3.3

> Source of truth: `/memory/SPRINTS.md`. Summarised here.

### V1 — Construction Site Assistant
* Voice + photo capture → AI structured events.
* Phone+name auth, three roles, Hindi/Punjabi/Hinglish/English support.
* Single-file backend.

### V2 — Construction Intelligence Platform
* Renamed ATLAS · Construction Intelligence.
* Engine-based architecture (Reality / Memory / Intelligence / Timeline).
* Golden Rule (AI never blocks; <300 ms event capture).
* Immutable events + raw_assets + ai_analyses.
* Evidence Model surfaced on Event Detail.
* Prompt Versioning.
* Project → Site hierarchy.
* Async asyncio.Queue worker via FastAPI lifespan.

### V3 — Operational Intelligence Layer
* New **Operations Engine** with append-only `operational_events` ledger + derived `operational_items` projection (CQRS).
* AI Proposal workflow (`ai_proposals`).
* 11 operational categories (material, labour, equipment, client_approval, drawing_request, site_issue, quality_observation, safety_observation, commitment, inspection, follow_up + `general`).
* Operational lifecycle: open → assigned → acknowledged → in_progress → fulfilled → verified → closed (+ escalated / reopened).
* Operational Health derived live; separate from status.
* Time Intelligence (computed on read).
* Blocker as first-class concept with external-vs-internal categorisation.
* Origin tracking + Evidence Inheritance (single hop to originating Construction Event).
* Operational Center dashboard endpoint + screen.
* Site Requirements workspace.
* Timeline opt-in merge (`?include=ops`).

### V3.1 — Canonical Proposal Pipeline
* Decoupled proposal generation from analysis; idempotent `generate_proposals_for_event(event_id)`.
* `events.proposals_status` lifecycle marker added.

### V3.2 — Operational Completion
* Multi-intent extraction from a single utterance (≥4 distinct categories proven by tests).
* Assignment workflow (assign / reassign / history; one-tap accept-with-assign).
* Smart Operational Cards (Why / What / Who / When / Blocker on every card).
* Category-aware primary action on detail (`MARK DELIVERED`, `MARK RECEIVED`, etc.).
* `/api/users` directory with phone stripped.
* `backend/tests/test_atlas_v3_2.py` — 13 cases.

### V3.2.1 — TZ hotfix
* Centralised `_parse_iso()` in `operations_engine.py`; eliminated naive-vs-aware datetime comparison bug across `derive_health` + `compute_metrics`.

### V3.2.2 — Pipeline recovery hotfix
* Intelligence worker startup now backfills events stuck in `ai_status=analyzed` with no `proposals_status` — closes the silent runtime gap where voice notes were producing no operational items.

### V3.3 — Operational UX Completion (current RC1)
* Project management UI: create / edit / archive / unarchive + project selector entrypoint from Timeline header.
* Per-card quick ASSIGN/REASSIGN on every OPS card with role-aware picker.
* PATCH editing of operational items (title / description / quantity / unit / priority / required_by / assigned user) — every edit appends an `edited` ledger row with full diff.
* Voice Update on operational items: Whisper transcript + GPT summary, original audio asset linked, `voice_update` ledger row.
* Archive / Cancel / Mark-Duplicate status transitions (history preserved, never hard-deleted).
* Unified Activity timeline (renames History) rendering edited diffs, voice cards with transcript + AI summary, assignments, duplicates, blockers.
* Smart cards continue to display Why / What / Who / When / Blocker without opening detail.

### V4 — Construction Knowledge Core (Sprint 4) — Architectural Milestone
Not a feature release: this establishes the **canonical knowledge layer** that Atlas's next phase of intelligence and automation is built on — **Project Generation, Baseline Engine, Reality Engine (Activity matching), Material Intelligence, Labour Intelligence, Variance Analysis, and Construction Intelligence** will all read from `knowledge_items` rather than each inventing their own vocabulary for what construction work *is*. None of those modules are built in V4 — this sprint is deliberately scoped to the data layer and extension points they will need.

**Construction Knowledge Core**
* New Engine 6 (`knowledge_engine.py`) — `knowledge_items` as the canonical repository, single collection using a `type` discriminator (category/phase/activity/checklist_template/required_document).
* CRUD, search, filtering, soft-archive, immutable versioning (`knowledge_versions` — every edit snapshots the prior state before applying changes, mirroring the Corrections pattern).

**Knowledge Relationships**
* Generic `relationships[]` edges (`{id, type, target_id, metadata, created_at}`). Current support for dependencies (`depends_on`); extensible without a schema change to `precedes`, `requires`, `references`, `uses`, `inspected_by`, `linked_document`, `linked_material`, `linked_equipment`.

**Lifecycle**
* `status`: `draft | active | deprecated | archived`, tracked alongside `archived_at` (which retains its existing soft-archive role). New items default to `draft`.

**Future extension points**
* `applicability` — reserved, freeform dict for future filtering by project types, building types, construction types, and regions. Not read by any filter logic in V4.

**API**
* 10 new Knowledge Core endpoints. Management-role write access; read access for all authenticated users.

**Frontend**
* Admin-only Construction Knowledge workspace: browse, search, create, edit, archive, restore, Dependency Viewer.

**Workspace Routing**
* Removed the temporary Sprint 3 workspace selector. Users are now automatically routed into the correct workspace through one centralized backend-role → workspace resolver (`frontend/src/roles.ts`). Current mapping: Supervisor → Supervisor Workspace, Coordinator → Project Manager Workspace, Management → Admin Workspace.

**Confirmed unchanged:** authentication mechanics, every V1–V3 API request/response contract, and every existing operational workflow (capture, timeline, operations, proposals, projects, sites).

**Known limitations carried forward to V5:** no dependency cycle detection; archive-only deletion model (no hard-delete); relationship types not server-enforced against a closed enum; Coordinator defaults to PM workspace (Client workspace un-auto-routable pending a future permission-driven resolver); `applicability` has no dedicated UI yet; Whisper/GPT-4o proposal generation requires live-preview verification (sandbox-only limitation, not a code gap).

### V4.1 — Stabilization & QA Pass
First stability audit + full remediation pass. Fixed every issue found (1 Critical, 5 High, 5 Medium, 7 Low — see `memory/SPRINTS.md` for the complete list), plus two founder-requested foundations.

**Critical:** Operations screen showed a permanent loading spinner for Supervisor and Client roles (render gate depended on data never fetched for those roles). Fixed.

**High:** Event Detail's infinite background polling (stale-closure bug) fixed with a ref. Home screen's Capture CTA and the Capture screen itself now respect role permissions (previously enforced only by hiding the tab icon). Silent load failures across Home/Ops/Projects/Knowledge now show a retry banner instead of an indistinguishable-from-empty state. New `frontend/src/http.ts` adds global 401 → auto-logout handling.

**Medium/Low:** Gallery permission feedback, empty-sites messaging, `canManageProjects` added to `VIEW_PERMS` (was reading the raw backend role in 3 places), self-service name edit (`PATCH /api/me`), phone format validation, Knowledge search debounce, batched Knowledge list enrichment, optimistic concurrency on Knowledge writes (409 on conflict), 404-vs-400 distinction on Knowledge "not found," consolidated HTTP client helpers.

**Project Lifecycle:** `DELETE /api/projects/{id}` added, mirroring the existing `DELETE /api/sites/{id}` dependency-guard pattern exactly. Sites already had full lifecycle management since Sprint 2.

**Authentication foundation:** New `POST /api/auth/register` (Sign Up) — separate, create-only path; `/api/auth/login` unchanged. New accounts start `approval_status=pending`, `is_active=true`, `assigned_project_ids=[]`. `is_active=false` hard-blocks at `get_current_user` (401); `approval_status` gating is frontend-only (routes to new `app/pending.tsx`). New admin-only `routes/admin_users.py` + `app/users/index.tsx` for approve/reject/assign-role/assign-projects/activate-deactivate.

**Confirmed unchanged:** `/api/auth/login`, every V1–V4 API request/response contract, every existing permission rule. The only change to a pre-existing code path is `get_current_user` gaining the `is_active` check — a no-op for every account created before V4.1.

**Deliberate scope boundaries:** no per-project data scoping by `assigned_project_ids` yet (nothing filters queries by it — that's the real "future expansion"); no notification on approval (manual "Check Again" button instead); no password (auth model unchanged per "do not redesign authentication").

### V4.2 — Admin Experience
Completes the Admin experience so no administrator needs Git Bash, curl, MongoDB, or browser DevTools to manage Atlas day-to-day.

**User Management completion:** Search (client-side over the already-fetched, filtered list — zero backend change), View user details (a modal surfacing every field, including a computed Workspace label), CSV export (`frontend/src/csv.ts` — `Blob`+download on web, the OS share sheet via React Native's built-in `Share` API on native, no new dependency added — see ADR-024). Approve/Reject/Assign Role/Assign Projects/Activate-Deactivate are unchanged from V4.1.

**Admin System Information:** new page (`app/system/index.tsx`) and one new, read-only, admin-only endpoint (`GET /api/admin/system-info`, `routes/admin_system.py`) returning Atlas version, git commit (best-effort, falls back gracefully), build date, backend status, a real database ping, server uptime, and live counts (total users/projects/sites, pending approvals).

**Confirmed unchanged:** every V1–V4.1 API request/response contract, every existing permission rule, `routes/admin_users.py`, `routes/auth.py`, `core/auth.py`. This sprint adds exactly one new backend endpoint; everything else is frontend-only or reuses existing APIs.

---

## 20. Canonical documents

Always defer to these under `/memory/` — they outrank this file when in conflict:

* `PROJECT_CONSTITUTION.md` — permanent principles.
* `ARCHITECTURE.md` — engine map + collections + diagrams.
* `PRD.md` — product requirements.
* `DECISIONS.md` — ADRs.
* `SPRINTS.md` — sprint log.
* `test_credentials.md` — seed users for local testing.

If you change any architectural rule, update the matching canonical doc in the same PR.
