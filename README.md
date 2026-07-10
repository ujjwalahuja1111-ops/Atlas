# Project Atlas — Engineering Handoff Package (V3.3 RC1)

Open **HANDOFF.md** first. It is the single onboarding document.
Canonical product/architecture docs live in `memory/`.

## Local Development Database

Every developer should start from an identical, realistic dataset. Two
standalone scripts (`backend/scripts/db_reset.py` and
`backend/scripts/db_seed.py`) manage this — they are dev tooling only,
never imported by the running application, so they have zero effect on
production behaviour.

Run these from the `backend/` directory, with your `.env`
(`MONGO_URL`/`DB_NAME`) already configured:

```bash
# Reset Database — completely clears every collection
python -m scripts.dev reset

# Seed Database — populates users, projects, and realistic sample data
python -m scripts.dev seed

# Reset + Seed — the common one-liner for a clean slate
python -m scripts.dev reset-seed

# Add -y / --yes to skip the confirmation prompt, e.g. for scripting:
python -m scripts.dev reset-seed --yes
```

`scripts/dev.py` is a thin wrapper — it reuses `scripts/db_reset.py` and
`scripts/db_seed.py` internally, which remain available to run directly
if you only need one half (`python -m scripts.db_reset`, `python -m
scripts.db_seed`). Reset uses dynamic collection discovery, so it always
clears every current collection without needing to be updated when new
ones are added.

The seed is deterministic and idempotent — re-running it never creates
duplicates, so it's always safe to run again on an already-seeded
database. After seeding, it stores a small `seed_metadata` record
(`seed_version`, `atlas_version`, `created_at`) and prints a concise
summary of what was created.

It creates eight users (two per role), already approved and immediately
able to log in:

| Phone | Name | Role |
|---|---|---|
| 9000000001 | Atlas Admin 1 | Admin |
| 9000000002 | Atlas Admin 2 | Admin |
| 9000000011 | Project Manager 1 | Project Manager |
| 9000000012 | Project Manager 2 | Project Manager |
| 9000000021 | Site Supervisor 1 | Site Supervisor |
| 9000000022 | Site Supervisor 2 | Site Supervisor |
| 9000000031 | Client 1 | Client |
| 9000000032 | Client 2 | Client |

Log in with any name/phone pair above — no password (Atlas is
passwordless by design, see `HANDOFF.md`).

It also creates four projects — Luxury Villa, Commercial Office, and
Residential Apartment with light sample activity, plus **Atlas Demo
Site**, a fully populated showcase project with a realistic event
timeline (including photos and a voice-note-style entry), AI-generated
proposals (including a full material quantity takeoff), pending client
approvals, safety/quality observations, and a generated Construction
Workflow with real status history — everything a fresh install needs to
demonstrate the complete Atlas experience immediately after seeding.

