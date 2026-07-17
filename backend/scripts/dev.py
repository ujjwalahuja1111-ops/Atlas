"""Single developer entry point for the Atlas dev database (Sprint DX-7).

A thin wrapper — reuses db_reset.reset(), db_seed.main(), and (Atlas
Canonical Demo Project) seed_demo_project.main() exactly as they are,
adding nothing new of its own beyond argument parsing and combining
them for `seed` / `reset-seed`. Not imported by server.py, any route,
or any engine.

`seed` and `reset-seed` now ALSO seed the Atlas Canonical Demo Project
(the permanent "Atlas Demonstration Villa" dataset — see
memory/ACDP_README.md) immediately after the regular dev seed, on the
same database connection. Previously ACDP was only reachable via a
second, separate command (`python -m scripts.seed_demo_project`) that
this file had no knowledge of at all — anyone following the existing,
already-familiar `dev.py seed` workflow (which is what "the documented
setup" meant before this fix) would never have triggered it. ACDP's own
idempotency guard (a natural-key lookup on its fixed project code)
makes this a genuine no-op if ACDP has already been seeded, so running
`seed`/`reset-seed` repeatedly is exactly as safe as it always was.

`python -m scripts.seed_demo_project` on its own still works exactly as
before too, for anyone who wants to seed ONLY the ACDP dataset without
touching the regular dev seed.

Usage:
    cd backend
    python -m scripts.dev reset          # Reset Database
    python -m scripts.dev seed           # Seed Database (regular dev seed + ACDP)
    python -m scripts.dev reset-seed     # Reset + Seed
    python -m scripts.dev reset --yes    # skip the confirmation prompt
    python -m scripts.dev reset-seed -y  # same, short form
"""
from __future__ import annotations
import argparse
import asyncio
import sys

sys.path.insert(0, ".")  # allow `python -m scripts.dev` from backend/
from core.db import db, close_client  # noqa: E402
from core.settings import DB_NAME  # noqa: E402
from scripts import db_reset, db_seed, seed_demo_project  # noqa: E402


async def _confirm(skip: bool) -> bool:
    if skip:
        return True
    print(f"This will permanently delete ALL data in database '{DB_NAME}'.")
    reply = input("Type 'yes' to continue: ").strip().lower()
    if reply != "yes":
        print("Aborted — no changes made.")
        return False
    return True


async def _seed_all() -> None:
    """Regular dev seed, then the Atlas Canonical Demo Project, on the
    SAME connection - close_when_done=False on both so neither closes
    the client out from under the other; this function owns the one
    final close."""
    await db_seed.main(close_when_done=False)
    print()
    await seed_demo_project.main(close_when_done=False)
    await close_client()


async def run(command: str, *, skip_confirm: bool) -> None:
    if command == "reset":
        if await _confirm(skip_confirm):
            dropped = await db_reset.reset()
            print(f"\nReset complete. {len(dropped)} collection(s) dropped.")
        await close_client()

    elif command == "seed":
        await _seed_all()

    elif command == "reset-seed":
        if await _confirm(skip_confirm):
            dropped = await db_reset.reset()
            print(f"\nReset complete. {len(dropped)} collection(s) dropped.\n")
            await _seed_all()
        else:
            await close_client()


def main() -> None:
    parser = argparse.ArgumentParser(prog="dev.py", description="Atlas developer database commands.")
    parser.add_argument("command", choices=["reset", "seed", "reset-seed"])
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt (reset / reset-seed)")
    args = parser.parse_args()
    asyncio.run(run(args.command, skip_confirm=args.yes))


if __name__ == "__main__":
    main()
