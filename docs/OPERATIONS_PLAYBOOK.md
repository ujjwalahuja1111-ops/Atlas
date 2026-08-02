# Atlas Operations Playbook

Every command in this document was verified directly against the current repository — by reading the exact implementation it invokes, and in most cases by actually running it — not inferred from naming conventions or older documentation. Where two documents in this repository disagreed (`README.md` vs `README_DEVELOPMENT.md`), the discrepancy was resolved by checking which script is actually current, not by trusting either document blindly. Where a capability genuinely does not exist in this repository (frontend tests, a backup script, a combined start-both command), that is stated plainly rather than filled in with a plausible-sounding alternative.

All backend commands are run from the `backend/` directory. All frontend commands are run from the `frontend/` directory.

---

## 1. Daily Commands

### Start backend
```
cd backend
uvicorn server:app --reload
```
Verified: `server.py` defines `app = FastAPI(...)`; `uvicorn` is a pinned dependency (`uvicorn==0.25.0` in `requirements.txt`). No host/port override exists in this codebase, so uvicorn's own defaults apply (`127.0.0.1:8000`) unless overridden with `--host`/`--port` flags.

### Start frontend
```
cd frontend
npm start
```
Equivalent to `expo start` (the `start` script in `package.json` is exactly `expo start`).

### Start both
No combined command exists. There is no root-level `package.json`, no `concurrently` or `npm-run-all` dependency, and no script anywhere in the repository that launches both processes together. Run the two commands above in two separate terminals.

### Stop services
No formal stop command exists. There is no supervisor config, no `pm2` config, no systemd unit, and no `Procfile` anywhere in this repository. Stop each process with Ctrl+C in the terminal running it.

### Restart services
No formal restart command exists, for the same reason. Stop (Ctrl+C) and re-run the relevant start command above. The backend's `--reload` flag already restarts the server process automatically on file changes during development.

---

## 2. Database Commands

The canonical database lifecycle tool is `scripts/bootstrap.py`. See Section 6 for the full canonical-vs-legacy analysis.

### Reset database (wipe only, no reseed)
```
cd backend
python -m scripts.db_reset --yes
```
Drops every collection in the configured database via dynamic discovery (`list_collection_names()`), except MongoDB's own protected `system.*` namespaces. Omit `--yes` to be prompted for confirmation first. `bootstrap.py --reset` calls this exact function internally — there is no separate reset implementation to keep in sync.

### Drop database
There is no dedicated "drop the whole database" command (as distinct from dropping every collection inside it). `scripts/db_reset.py` drops all collections but leaves the database and the Mongo connection itself intact — this is the closest equivalent, and is what every workflow in this repository actually uses.

### Seed database
```
cd backend
python -m scripts.bootstrap
```
Seeds only what's missing (Stages 3–5: core seed, Atlas Demo Project, Reference Portfolio); safe to re-run repeatedly, since every underlying seeder does its own natural-key lookup before creating anything.

### Reset + Seed (the standard one-liner)
```
cd backend
python -m scripts.bootstrap --reset
```
This is the command documented in `README_DEVELOPMENT.md`'s own "Fresh setup" section and the one this repository's engineering history has used throughout. Full detail in Section 7.

### Verify seed
```
cd backend
python -m scripts.bootstrap --verify
```
Checks an existing database without seeding anything. Exits non-zero if any check fails.

### Verify expected record counts
Same command as above (`--verify`) prints a pass/fail line for each check, including record-existence checks. For the full numeric baseline after a clean reset+seed, see Section 8.

---

## 3. Test Commands

### Backend tests
```
cd backend
python -m pytest tests/test_acdp_catalog.py tests/test_acdp_dev_wiring.py tests/test_bootstrap.py tests/test_cre_architecture_guards.py tests/test_cre_projections.py tests/test_cre_rules.py tests/test_dev02_bootstrap_reliability.py -q
```
This is the exact, verified set of backend test files that run standalone (via `mongomock`, no live server or real MongoDB required) and pass cleanly today: 142 tests, 0 failures, confirmed by direct execution. There is no single `pytest tests/` invocation that works cleanly — see the notes below and Section 9 for why.

**Do not include `tests/test_cre_smoke_mongomock.py` in this set.** Despite its name, it fails — 7 real failures even run in complete isolation (e.g. it asserts on a `stages` key that `/api/reasoning-meta` no longer returns), confirmed by running it alone. This is a genuine, current mismatch between an old test and the live API, not a flake. See Section 9.

**35 of the ~40 files in `tests/` require a live, deployed backend server** (they `import requests` and hit real HTTP endpoints, e.g. `tests/test_rc01_commercial_visibility.py`). They cannot be run as pure unit tests against an in-memory database. To run them: start the backend (Section 1) against a real MongoDB instance, then run that specific file with `pytest`.

### Frontend tests
No frontend test command exists. There are no `.test.ts`/`.test.tsx`/`.spec.ts` files anywhere in `frontend/`, no Jest configuration, and no testing-library dependency in `package.json`. This capability is not implemented in this repository today.

### Full test suite
No single command runs "the full test suite" in one invocation, because the backend test files themselves require two different environments (mongomock-only vs. live-server) and there is no frontend test command at all. The closest thing to a full sweep is:
```
cd backend
python -m pytest tests/test_acdp_catalog.py tests/test_acdp_dev_wiring.py tests/test_bootstrap.py tests/test_cre_architecture_guards.py tests/test_cre_projections.py tests/test_cre_rules.py tests/test_dev02_bootstrap_reliability.py -q
```
plus, separately, running the live-server-dependent files against a running backend if a full integration pass is needed.

### TypeScript check
```
cd frontend
npx tsc --noEmit
```
Verified: runs clean (exit 0) against the current codebase.

### Lint
```
cd frontend
npm run lint
```
Equivalent to `expo lint`. Verified: runs today and reports 9 errors / 16 warnings against the current codebase (pre-existing issues, not something this inspection changed).

There is no backend lint command. No `flake8`, `ruff`, `pylint`, or similar tool is configured or listed in `requirements.txt`.

### Coverage
No coverage tooling exists on either side. `pytest-cov`/`coverage` are not installed and not listed in `requirements.txt`; no coverage-related package appears in `frontend/package.json`. This capability is not implemented in this repository today.

---

## 4. Production Commands

### Create first admin
```
POST /api/auth/register
Content-Type: application/json

{"phone": "<phone number>", "name": "<full name>"}
```
Verified directly in `engines/memory_engine.py`: the very first account ever registered on an empty database (checked via an atomic claim, hardened against concurrent registration) is automatically approved as `management`, unrestricted — the one deliberate exception to the normal pending-admin-approval flow. Every subsequent registration follows the standard pending-approval path. There is no separate CLI script for this; it is exclusively an API call.

### Backup database
No backup script exists anywhere in this repository. This is a standard MongoDB operational task outside Atlas's own tooling — use `mongodump` directly against the configured `MONGO_URL`/`DB_NAME`.

### Restore database
No restore script exists either, for the same reason — use `mongorestore` directly.

### Health check
```
GET /api/
```
Verified in `server.py`: returns `{"platform": ..., "version": ..., "status": "ok", "ai_enabled": <bool>}`. There is no dedicated `/health` or `/api/health` route — this root API path is the health-check surface that exists today.

### Verify deployment
```
cd backend
python -m scripts.bootstrap --verify
```
Same command as Section 2's "Verify seed" — checks an existing database (any environment, not just freshly-seeded ones) without modifying it, including a genuine exercise of `reasoning_engine.compare_projects()` (the same function the real comparison API endpoint calls), not a hand-rolled second implementation of that check.

---

## 5. Development Commands

### Install dependencies
Backend:
```
cd backend
pip install -r requirements.txt
```
Frontend:
```
cd frontend
npm install
```
Verified: `package-lock.json` is present, confirming npm (not yarn or bun) is this project's package manager.

### Update dependencies
```
cd frontend
npx expo install --check
npx expo install --fix
```
Verified via `npx expo install --help`: `--check` reports which installed packages need updating for the current Expo SDK; `--fix` automatically corrects invalid versions. This is the Expo-aware update path — a raw `npm update` risks breaking Expo SDK version alignment and is not what this project's own tooling is built around.

No backend dependency-update command exists beyond standard `pip install --upgrade -r requirements.txt`, which is not Atlas-specific tooling.

### Clean caches
```
cd frontend
npx expo start --clear
```
Verified via `npx expo start --help`: `-c`/`--clear` clears the Metro bundler cache. No separate, standalone "clean" command exists — clearing happens as a flag on the start command itself.

### Expo
```
cd frontend
npx expo start
```
(Equivalent to `npm start`.)

### Metro
Metro is Expo's bundler and has no separate standalone command in this project — it starts automatically as part of `expo start` / `npm start`.

### Android
```
cd frontend
npm run android
```
Equivalent to `expo start --android`.

### Web
```
cd frontend
npm run web
```
Equivalent to `expo start --web`.

(There is also `npm run ios`, equivalent to `expo start --ios`, not explicitly requested but present in `package.json` alongside `android`/`web`.)

---

## 6. Seeder — Canonical vs. Obsolete

Every seed-related script located in `backend/scripts/`:

| Script | Role |
|---|---|
| `bootstrap.py` | The canonical orchestrator. Calls the four scripts below in the correct order, adds environment validation, cross-stage verification, and a summary report. This is the command documented in the current (`README_DEVELOPMENT.md`) setup instructions. |
| `db_reset.py` | Underlying reset logic. Called internally by `bootstrap.py --reset`; also independently runnable. |
| `db_seed.py` | Underlying core seed logic (users, roles, knowledge, workflow templates, light sample project content). Called internally by `bootstrap.py` Stage 3; also independently runnable. |
| `seed_demo_project.py` | Underlying Atlas Canonical Demo Project (ACDP / "Atlas Demonstration Villa") seed logic — the large, realistic 18-month simulated dataset. Called internally by `bootstrap.py` Stage 4; also independently runnable. |
| `reference_portfolio.py` | Underlying Reference Portfolio logic (RP-001 commercial layer + RP-002 project, both migrated into the real Commercial Foundation Engine). Called internally by `bootstrap.py` Stage 5; also independently runnable, but requires the Atlas Demo Project (Stage 4 / ACDP) to already exist — this precondition is guaranteed automatically inside a `bootstrap` run, but not if this script is invoked completely on its own against an empty database. |
| `acdp_fixtures.py` | Pure data module (zone/phase/activity fixtures) imported by `seed_demo_project.py`. Not independently runnable — no CLI entry point, never touches the database itself. |
| `dev.py` | Legacy wrapper, still fully functional but superseded. Provides `reset` / `seed` / `reset-seed`, but its `seed` path only covers Stages 3–4 (core seed + Atlas Demo Project) — it never seeds the Reference Portfolio (Stage 5). Not mentioned anywhere in the current setup documentation (`README_DEVELOPMENT.md`); only described in the older `README.md`. |

**Which one is canonical:** `bootstrap.py`.

**Which ones are obsolete:** `dev.py` is legacy — it still runs correctly, but produces an incomplete database (missing the Reference Portfolio) compared to `bootstrap.py`, and is not the documented path in this repository's current setup instructions.

**Which command engineers should always use:**
```
cd backend
python -m scripts.bootstrap --reset
```

---

## 7. Reset — Exact Specification

**Command:**
```
cd backend
python -m scripts.bootstrap --reset
```

**File executed:** `backend/scripts/bootstrap.py`, which in turn calls `backend/scripts/db_reset.py` (Stage 2 — the reset itself), then `backend/scripts/db_seed.py` (Stage 3), `backend/scripts/seed_demo_project.py` (Stage 4), and `backend/scripts/reference_portfolio.py` (Stage 5).

**What it deletes:** Every collection in the configured database (`DB_NAME` from `backend/.env`), discovered dynamically via `list_collection_names()` — never a hardcoded list, so it always clears every current collection including ones added after this document was written. Only MongoDB's own protected `system.*` namespaces are left untouched.

**What it recreates, in order:**
1. Database indexes (`ensure_indexes()`).
2. Core seed: 8 users (2 per role: management, project_manager, site_supervisor, client), knowledge base, 5 workflow templates, light sample content for 3 example projects.
3. The Atlas Canonical Demo Project ("Atlas Demonstration Villa") — a fully populated, realistic 18-month simulated construction dataset across 6 zones/sites, with 5 additional users of its own.
4. The Reference Portfolio — RP-001 (the Demo Project, given a real commercial layer) and RP-002 (a new commercial fit-out project), both migrated into the real Commercial Foundation Engine (contracts, milestones, payment requests, payments, variations, budgets).
5. Automatic verification (Stage 6) and a summary report (Stage 7).

**Expected completion message:** the run prints a `Stage 6 — Verification:` block listing `[PASS]`/`[FAIL]` for each check, followed by an `Atlas Bootstrap Complete` summary with per-collection counts, and finally one of two status lines:
```
  Status                 SUCCESS
```
or, if any verification check failed:
```
  Status                 COMPLETED WITH VERIFICATION FAILURES
```
followed by an elapsed-time line.

---

## 8. Verification — Expected Record Counts After a Clean Reset

These counts were captured by actually executing the full reset+seed pipeline (Stages 2–5) against a clean database and querying every resulting collection directly — not estimated.

| Collection | Count |
|---|---|
| Users | 17 |
| Projects | 6 |
| Sites | 13 |
| Events | 799 |
| Operational Items | 352 |
| Operational Events | 1,643 |
| Workflow Activities | 377 |
| Knowledge Items | 412 |
| Knowledge Versions | 736 |
| Contracts | 2 |
| Milestones | 11 |
| Variations | 4 |
| Budgets | 2 |
| Payment Requests | 7 |
| Payments | 5 |
| Commercial Events | 95 |
| Commercial Reference records | 2 |
| AI Proposals | 68 |
| Corrections | 0 (none exist in a fresh seed until a correction is manually recorded) |
| Construction Memory | 358 |
| Reasoning Insights | 156 |
| Reasoning Runs | 16 |
| Raw Assets | 252 |
| Prompt Versions | 1 |
| Seed Metadata | 1 |

`bootstrap.py`'s own built-in summary (Stage 7) prints a shorter, curated subset of this table (Users, Projects, Reference Portfolio, Commercial Contracts, Milestones, Variations, Budgets, Knowledge, Workflow Activities, Operations) after every run — that is the quickest way to sanity-check a reset without querying every collection by hand.

---

## 9. Repository Cleanup — Every Operational Script

| Script | Classification | Basis |
|---|---|---|
| `backend/scripts/bootstrap.py` | ACTIVE | Canonical orchestrator; documented in the current setup guide; verified working end-to-end. |
| `backend/scripts/db_reset.py` | ACTIVE | Underlying reset logic, called by `bootstrap.py` and independently runnable; correctly implemented against the standard Motor API. |
| `backend/scripts/db_seed.py` | ACTIVE | Underlying core seed logic, called by `bootstrap.py` Stage 3 and independently runnable; verified working. |
| `backend/scripts/seed_demo_project.py` | ACTIVE | Underlying ACDP seed logic, called by `bootstrap.py` Stage 4 and independently runnable; verified working. |
| `backend/scripts/reference_portfolio.py` | ACTIVE | Underlying Reference Portfolio logic, called by `bootstrap.py` Stage 5 and independently runnable (with the ACDP precondition noted in Section 6); verified working. |
| `backend/scripts/acdp_fixtures.py` | ACTIVE (supporting module, not independently runnable) | Pure data required by `seed_demo_project.py`; no CLI of its own. |
| `backend/scripts/dev.py` | LEGACY | Still fully functional, but superseded by `bootstrap.py`; produces an incomplete database (no Reference Portfolio); absent from current setup documentation. |
| `backend/scripts/__init__.py` | Package marker, not an operational script. | — |
| `backend/scripts/DEV02_ROOT_CAUSE.md` | Documentation file, not a script. | — |
| `backend/tests/test_cre_smoke_mongomock.py` | DEPRECATED / BROKEN | Not a script in `scripts/`, but flagged here because Section 3 depends on this finding: fails with real assertion errors even run in complete isolation against the current API (asserts on response fields the API no longer returns). Should not be included in any "backend tests" invocation until someone updates it or removes it. |
| The 35 files in `backend/tests/` that `import requests` | ACTIVE, but environment-dependent | Not broken — genuinely require a live, deployed backend against real MongoDB to execute; cannot run as unit tests. Not evaluated individually for pass/fail in this pass, since doing so requires infrastructure (a running MongoDB server) not available for direct verification here. |

No script in this repository was found to be UNUSED in the sense of being completely dead code with zero references — every file in `backend/scripts/` is either directly invoked by `bootstrap.py`, independently documented as runnable, or (in `acdp_fixtures.py`'s case) imported by one of the others.
