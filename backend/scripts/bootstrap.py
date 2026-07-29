"""Atlas Database Lifecycle & Unified Seed Pipeline (DEV-01).

One command, always leaves Atlas in a fully operational development
state:

    cd backend
    python -m scripts.bootstrap --reset

This file is deliberately an ORCHESTRATOR, not a second place business
logic lives. Every stage below calls an existing, already-tested
function from db_reset.py / db_seed.py / seed_demo_project.py /
reference_portfolio.py exactly as it already exists — nothing here
re-implements seeding, migration, or counting logic a moment of it.
Where a stage needed a genuinely new capability (environment
validation, cross-stage verification, the summary report), that
capability is written once, here, because no existing script owned it
— not because this file is meant to accumulate business logic over
time.

Previously, producing a working dev database required four
independently-run scripts in a specific, undocumented order
(db_reset -> db_seed -> seed_demo_project -> reference_portfolio),
and reference_portfolio's own Reference Portfolio / Commercial
Foundation Engine migrations would fail with "RP-001 must be seeded
first" if run before seed_demo_project — a real, previously-reported
failure mode. This orchestrator owns that ordering itself: Stage 5
(Reference Portfolio) only ever runs after Stage 4 (Atlas Demo
Project) has completed within the same bootstrap run, so the
prerequisite is always satisfied by construction, not by a developer
remembering the right order. No prerequisite error should ever
surface from a plain `bootstrap` invocation again.
"""
from __future__ import annotations
import argparse
import asyncio
import sys
import time

sys.path.insert(0, ".")  # allow `python -m scripts.bootstrap` from backend/


# ---------------------------------------------------------------------------
# Stage 1 — Environment validation. Deliberately does NOT import
# core.settings/core.db yet: core.settings does `os.environ["MONGO_URL"]`
# (a bare KeyError on a missing var, not a clear message) at IMPORT
# TIME, so this stage checks the raw environment directly first and
# gives a clear, actionable error before anything else in the process
# even attempts to import a module that would touch Mongo.
# ---------------------------------------------------------------------------

class BootstrapError(Exception):
    """Raised with a clear stage/cause/resolution — the shape every
    failure in this file is reported in, per the brief's own Error
    Handling requirement."""
    def __init__(self, stage: str, cause: str, resolution: str):
        self.stage, self.cause, self.resolution = stage, cause, resolution
        super().__init__(f"[{stage}] {cause}")


def _print_failure(e: BootstrapError) -> None:
    print()
    print("=" * 60)
    print("ATLAS BOOTSTRAP FAILED")
    print("=" * 60)
    print(f"Stage:      {e.stage}")
    print(f"Cause:      {e.cause}")
    print(f"Resolution: {e.resolution}")
    print("=" * 60)


async def validate_environment() -> None:
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    root_dir = Path(__file__).parent.parent.parent  # backend/scripts/ -> backend/ -> repo root
    load_dotenv(root_dir / "backend" / ".env")
    load_dotenv(root_dir / ".env")  # tolerate either location, same as core.settings' own search

    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")

    if not mongo_url:
        raise BootstrapError(
            "Stage 1 — Environment Validation",
            "MONGO_URL is not set.",
            "Set MONGO_URL in backend/.env (e.g. MONGO_URL=mongodb://localhost:27017) and retry.",
        )
    if not db_name:
        raise BootstrapError(
            "Stage 1 — Environment Validation",
            "DB_NAME is not set.",
            "Set DB_NAME in backend/.env (e.g. DB_NAME=atlas_dev) and retry.",
        )

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        test_client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=5000)
        await test_client.admin.command("ping")
        test_client.close()
    except Exception as e:
        raise BootstrapError(
            "Stage 1 — Environment Validation",
            f"Could not connect to MongoDB at the configured MONGO_URL ({e}).",
            "Confirm MongoDB is running and MONGO_URL is reachable from this machine, then retry.",
        )

    print(f"Stage 1 — Environment validated (DB_NAME='{db_name}').")


# ---------------------------------------------------------------------------
# Stage 2 — Reset (optional). Reuses db_reset.reset() exactly as it
# already exists — dynamic collection discovery, only ever touches the
# one configured database, never a hardcoded list to keep in sync.
# ---------------------------------------------------------------------------

async def stage_reset() -> None:
    from scripts import db_reset
    dropped = await db_reset.reset()
    print(f"Stage 2 — Reset complete: {len(dropped)} collection(s) dropped.")


async def ensure_indexes_recreated() -> None:
    from core.db import ensure_indexes
    await ensure_indexes()


# ---------------------------------------------------------------------------
# Stage 3 — Core Seed. Reuses db_seed.main() exactly as it exists
# (users, roles, knowledge, workflow templates, demo content) — that
# function already calls ensure_indexes() itself as its first step, so
# a --reset run gets its indexes recreated as a natural consequence of
# this stage, not a separate mechanism.
# ---------------------------------------------------------------------------

async def stage_core_seed() -> None:
    from scripts import db_seed
    await db_seed.main(close_when_done=False)
    print("Stage 3 — Core seed complete.")


# ---------------------------------------------------------------------------
# Stage 4 — Atlas Demo Project. Reuses seed_demo_project.main() exactly
# as it exists — its own natural-key lookup on ACDP's fixed project
# code already makes "skip safely if it exists" a no-op, not something
# this orchestrator needs to check itself.
# ---------------------------------------------------------------------------

async def stage_demo_project() -> None:
    from scripts import seed_demo_project
    await seed_demo_project.main(close_when_done=False)
    print("Stage 4 — Atlas Demo Project ready.")


# ---------------------------------------------------------------------------
# Stage 5 — Reference Portfolio. Reuses reference_portfolio.main()'s
# own constituent functions exactly as they exist (RP-002 seed,
# RP-001/RP-002 Commercial reference layer, RP-001/RP-002 real
# Commercial Foundation Engine migration) — only ever called AFTER
# stage_demo_project has run within this same invocation, so
# migrate_rp001_to_commercial_engine's own "ACDP must be seeded first"
# precondition is always satisfied by construction.
# ---------------------------------------------------------------------------

async def stage_reference_portfolio() -> None:
    from scripts import reference_portfolio
    await reference_portfolio.seed_rp002()
    await reference_portfolio.seed_rp001_commercial_reference()
    await reference_portfolio.migrate_rp001_to_commercial_engine()
    await reference_portfolio.migrate_rp002_to_commercial_engine()
    await reference_portfolio.complete_rp001_operations()
    await reference_portfolio.record_missing_rp001_inspections()
    print("Stage 5 — Reference Portfolio (RP-001, RP-002) and Commercial Foundation data ready.")


# ---------------------------------------------------------------------------
# Stage 6 — Verification. New capability (no existing script owned
# this) — reads directly from the database and, for the comparison
# check, calls reasoning_engine.compare_projects() directly (the exact
# function GET /api/portfolio/compare itself calls), so "the reference
# comparison succeeds" is a genuine exercise of the real comparison
# logic, not a hand-rolled second implementation of it.
# ---------------------------------------------------------------------------

class VerificationResult:
    def __init__(self):
        self.checks: list[tuple[str, bool, str]] = []  # (label, passed, detail)

    def check(self, label: str, passed: bool, detail: str = "") -> None:
        self.checks.append((label, passed, detail))

    @property
    def all_passed(self) -> bool:
        return all(passed for _, passed, _ in self.checks)


async def run_verification() -> VerificationResult:
    from core.db import db
    from engines import memory_engine, reasoning_engine, commercial_engine

    result = VerificationResult()

    user_count = await db.users.count_documents({})
    result.check("Users exist", user_count > 0, f"{user_count} users")

    project_count = await db.projects.count_documents({})
    result.check("Projects exist", project_count > 0, f"{project_count} projects")

    rp001 = await db.projects.find_one({"code": "ACDP-VILLA"}, {"_id": 0})
    result.check("RP-001 (ACDP Villa) exists", rp001 is not None)

    rp002 = await db.projects.find_one({"code": "RP-002-NEOTERIC"}, {"_id": 0})
    result.check("RP-002 (Neoteric Corporate Office) exists", rp002 is not None)

    contract_count = await db.contracts.count_documents({})
    result.check("Commercial collections populated (Contracts)", contract_count > 0, f"{contract_count} contracts")
    milestone_count = await db.milestones.count_documents({})
    result.check("Commercial collections populated (Milestones)", milestone_count > 0, f"{milestone_count} milestones")
    variation_count = await db.variations.count_documents({})
    result.check("Commercial collections populated (Variations)", variation_count > 0, f"{variation_count} variations")
    budget_count = await db.budgets.count_documents({})
    result.check("Commercial collections populated (Budgets)", budget_count > 0, f"{budget_count} budgets")

    workflow_count = await db.workflow_activities.count_documents({})
    result.check("Workflow data populated", workflow_count > 0, f"{workflow_count} activities")

    ops_count = await db.operational_items.count_documents({})
    result.check("Operations populated", ops_count > 0, f"{ops_count} operational items")

    if rp001 and rp002:
        summary1 = await commercial_engine.get_project_commercial_summary(rp001["id"])
        summary2 = await commercial_engine.get_project_commercial_summary(rp002["id"])
        result.check("Commercial summaries available (RP-001)", summary1 is not None)
        result.check("Commercial summaries available (RP-002)", summary2 is not None)

        try:
            admin = await memory_engine.get_user_by_phone("9800000001")
            if admin:
                comparison = await reasoning_engine.compare_projects([rp001["id"], rp002["id"]], user=admin)
                result.check("Reference comparison succeeds", len(comparison["projects"]) == 2)
            else:
                result.check("Reference comparison succeeds", False, "seeded admin user not found")
        except Exception as e:
            result.check("Reference comparison succeeds", False, str(e))
    else:
        result.check("Commercial summaries available", False, "RP-001/RP-002 missing")
        result.check("Reference comparison succeeds", False, "RP-001/RP-002 missing")

    return result


def print_verification(result: VerificationResult) -> None:
    print("\nStage 6 — Verification:")
    for label, passed, detail in result.checks:
        mark = "PASS" if passed else "FAIL"
        suffix = f" ({detail})" if detail else ""
        print(f"  [{mark}] {label}{suffix}")


# ---------------------------------------------------------------------------
# Stage 7 — Summary report.
# ---------------------------------------------------------------------------

async def print_summary() -> None:
    from core.db import db

    counts = {
        "Users": await db.users.count_documents({}),
        "Projects": await db.projects.count_documents({}),
        "Reference Portfolio": sum([
            1 if await db.projects.find_one({"code": "ACDP-VILLA"}) else 0,
            1 if await db.projects.find_one({"code": "RP-002-NEOTERIC"}) else 0,
        ]),
        "Commercial Contracts": await db.contracts.count_documents({}),
        "Milestones": await db.milestones.count_documents({}),
        "Variations": await db.variations.count_documents({}),
        "Budgets": await db.budgets.count_documents({}),
        "Knowledge": await db.knowledge_items.count_documents({}),
        "Workflow Activities": await db.workflow_activities.count_documents({}),
        "Operations": await db.operational_items.count_documents({}),
    }
    print("\nAtlas Bootstrap Complete\n")
    for label, count in counts.items():
        print(f"  {label:<22} {count}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_full_bootstrap(*, do_reset: bool) -> bool:
    started = time.monotonic()
    try:
        await validate_environment()

        if do_reset:
            await stage_reset()
        await ensure_indexes_recreated()

        await stage_core_seed()
        await stage_demo_project()
        await stage_reference_portfolio()

        result = await run_verification()
        print_verification(result)

        await print_summary()

        elapsed = time.monotonic() - started
        status = "SUCCESS" if result.all_passed else "COMPLETED WITH VERIFICATION FAILURES"
        print(f"\n  Status                 {status}")
        print(f"  Elapsed                {elapsed:.1f}s")
        return result.all_passed

    except BootstrapError as e:
        _print_failure(e)
        return False
    finally:
        from core.db import close_client
        await close_client()


async def run_verify_only() -> bool:
    try:
        await validate_environment()
        result = await run_verification()
        print_verification(result)
        print(f"\n  Status                 {'SUCCESS' if result.all_passed else 'FAILED'}")
        return result.all_passed
    except BootstrapError as e:
        _print_failure(e)
        return False
    finally:
        from core.db import close_client
        await close_client()


async def run_portfolio_only() -> bool:
    """--portfolio: rebuild the Reference Portfolio without a full
    reset/reseed. Still owns its own prerequisite (the Atlas Demo
    Project / ACDP, which RP-001 IS) rather than failing with an
    opaque "must be seeded first" error — per the brief's own explicit
    Error Handling requirement, that specific failure mode should
    never surface from this orchestrator, in any of its modes."""
    try:
        await validate_environment()
        from core.db import db
        if not await db.projects.find_one({"code": "ACDP-VILLA"}):
            print("Atlas Demo Project (RP-001's own prerequisite) not found — seeding it first.")
            await stage_demo_project()
        await stage_reference_portfolio()
        result = await run_verification()
        print_verification(result)
        await print_summary()
        print(f"\n  Status                 {'SUCCESS' if result.all_passed else 'COMPLETED WITH VERIFICATION FAILURES'}")
        return result.all_passed
    except BootstrapError as e:
        _print_failure(e)
        return False
    finally:
        from core.db import close_client
        await close_client()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Atlas unified database lifecycle — one command, always leaves Atlas "
                    "in a fully operational development state.",
    )
    parser.add_argument("--reset", action="store_true",
                       help="Drop all Atlas collections before seeding (Stage 2).")
    parser.add_argument("--verify", action="store_true",
                       help="Run verification only (Stage 6) — no seeding.")
    parser.add_argument("--portfolio", action="store_true",
                       help="Rebuild the Reference Portfolio only (Stage 5) — "
                            "seeds the Atlas Demo Project first if it doesn't exist yet.")
    args = parser.parse_args()

    if args.verify:
        ok = asyncio.run(run_verify_only())
    elif args.portfolio:
        ok = asyncio.run(run_portfolio_only())
    else:
        ok = asyncio.run(run_full_bootstrap(do_reset=args.reset))

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
