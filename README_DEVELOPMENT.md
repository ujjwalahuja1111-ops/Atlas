# Atlas — Development Setup

## Fresh setup

```
git clone <repo>
cd Atlas/backend
pip install -r requirements.txt
python -m scripts.bootstrap --reset
uvicorn server:app --reload
```

That's it. No other seed commands, no hidden prerequisites, no manual ordering, no further documentation lookup required. After `bootstrap --reset` completes, the database contains: core users/roles/knowledge/workflow templates, the Atlas Demo Project, the full Reference Portfolio (RP-001 and RP-002, including real Commercial Foundation Engine data — Contracts, Milestones, Payment Requests, Payments, Variations, Budgets), and every collection the frontend and API surface expect to find populated.

Before running it, create `backend/.env` with at least:

```
MONGO_URL=mongodb://localhost:27017
DB_NAME=atlas_dev
```

(`JWT_SECRET` and `EMERGENT_LLM_KEY` are also read from here if you need auth/AI features locally — see `backend/core/settings.py` for the full list.)

## The bootstrap command

```
cd backend
python -m scripts.bootstrap            # seed only what's missing, safe to re-run
python -m scripts.bootstrap --reset    # drop everything, then seed from scratch
python -m scripts.bootstrap --verify   # check the current database, seed nothing
python -m scripts.bootstrap --portfolio  # rebuild only the Reference Portfolio
```

### What it does, in order

1. **Validate environment** — confirms `MONGO_URL`/`DB_NAME` are set and the database is actually reachable, before touching anything. Fails immediately with a clear stage/cause/resolution if not — never partially seeds.
2. **Reset** (only with `--reset`) — drops every Atlas collection. Dynamic discovery, never a hardcoded list; never touches a database other than the one `DB_NAME` names.
3. **Core seed** — users, roles, knowledge, workflow templates, sample project content.
4. **Atlas Demo Project** — the permanent "Atlas Demonstration Villa" showcase dataset. Skipped safely if it already exists.
5. **Reference Portfolio** — RP-001 (the Demo Project itself), RP-002 (a new commercial fit-out project), and real Commercial Foundation Engine data for both. This stage runs *only* after Stage 4 completes within the same invocation — the historical "RP-001 must be seeded first" failure is structurally impossible now, because bootstrap owns that ordering itself rather than relying on a developer running scripts in the right sequence.
6. **Verification** — confirms users/projects/RP-001/RP-002/Commercial collections/workflow/operations all exist, and that the real cross-project comparison (the same function the API itself calls) actually succeeds.
7. **Summary** — a clean report of what's in the database and a final `SUCCESS` / `COMPLETED WITH VERIFICATION FAILURES` status line.

### Idempotency

Running `bootstrap` (without `--reset`) repeatedly is always safe — every underlying seeder it calls (`db_seed`, `seed_demo_project`, `reference_portfolio`) does its own natural-key lookup before creating anything, so re-running produces identical counts, not duplicates. Verified directly: running the full pipeline twice against the same database produces byte-identical collection counts across users, projects, contracts, milestones, variations, budgets, and workflow activities.

### `--verify`

Checks an existing database without seeding anything — useful after pulling someone else's dump, or to confirm a deploy actually left the environment in a working state. Exits non-zero if any check fails.

### `--portfolio`

Rebuilds just the Reference Portfolio (Stage 5) without a full reset. If the Atlas Demo Project doesn't exist yet, it's seeded first automatically — this flag never fails with a prerequisite error either.

## Database reset only

If you want to wipe the database without immediately reseeding:

```
python -m scripts.db_reset --yes
```

`bootstrap --reset` calls this same function internally — there's no separate reset logic to keep in sync.

## Common troubleshooting

**"MONGO_URL is not set"** — create `backend/.env` (see Fresh Setup above); `bootstrap` reads it directly, the same way `core.settings` does everywhere else in the codebase.

**"Could not connect to MongoDB"** — confirm `mongod` is actually running and reachable at the URL in `.env`. `bootstrap` checks this with a real `ping` before doing anything else, specifically so a connection problem surfaces as one clear line instead of a confusing failure partway through seeding.

**A verification check fails after `bootstrap --reset`** — this means a stage completed but produced unexpected data; re-run with `--verify` alone to see exactly which check is failing, and check that stage's own script (`db_seed.py` / `seed_demo_project.py` / `reference_portfolio.py`) directly — `bootstrap.py` itself contains no seeding logic to have introduced the bug, so the fix belongs in whichever of those scripts owns the failing collection.

**I only want the Atlas Demo Project, not the full Reference Portfolio** — run `python -m scripts.seed_demo_project` directly; it's still a fully standalone script, unchanged.

**I need to start completely over** — `python -m scripts.bootstrap --reset` is always safe to run again; there is no state that can get stuck requiring manual database surgery.

## Architecture note

`scripts/bootstrap.py` is an orchestrator, not a second place business logic lives. Every stage above calls an existing, already-tested function from `db_reset.py`/`db_seed.py`/`seed_demo_project.py`/`reference_portfolio.py` exactly as it already exists. If a bug is found in what gets seeded, fix it in the owning script — `bootstrap.py` should only ever need changes to its own ordering, validation, or reporting, never to what data gets created.
