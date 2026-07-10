"""Development database reset utility (Sprint DX-7).

Completely clears every collection from the configured database — using
dynamic discovery (list_collection_names()), not a hardcoded list, so it
never needs updating as new collections are added — while leaving the
database itself (and the Mongo server/connection) intact. Only MongoDB's
own protected system namespaces (system.*) are excluded. Standalone
script — not imported by server.py, any route, or any engine, so it has
zero effect on production runtime behaviour; it only runs when a
developer explicitly invokes it.

Usage:
    cd backend
    python -m scripts.db_reset
    python -m scripts.db_reset --yes        # skip the confirmation prompt

Safety: reads MONGO_URL/DB_NAME from the same core.settings every engine
uses, and always prints which database it's about to wipe before doing
anything, so a developer can't accidentally point this at the wrong
target without noticing.
"""
from __future__ import annotations
import argparse
import asyncio
import sys

sys.path.insert(0, ".")  # allow `python -m scripts.db_reset` from backend/
from core.db import client, db, close_client  # noqa: E402
from core.settings import DB_NAME  # noqa: E402

# MongoDB's own internal namespaces — never touched, regardless of what
# Atlas collections exist now or are added by future engines. Everything
# else returned by list_collection_names() is discovered and dropped
# dynamically, so this script never needs a code change when a new
# collection is introduced (previously a hardcoded list had to be kept in
# sync by hand).
_PROTECTED_PREFIXES = ("system.",)


async def reset(*, verbose: bool = True) -> list[str]:
    """Drops every collection currently in the database except MongoDB's
    own protected system namespaces. Returns the list of collections that
    were dropped. Fully dynamic: whatever exists gets dropped, whatever
    doesn't isn't touched — there is nothing here to keep in sync with the
    engines' actual collection names."""
    names = await db.list_collection_names()
    dropped = []
    for name in names:
        if name.startswith(_PROTECTED_PREFIXES):
            continue
        await db.drop_collection(name)
        dropped.append(name)
        if verbose:
            print(f"  dropped: {name}")
    if verbose and not dropped:
        print("  (database was already empty)")
    return dropped


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Reset the Atlas development database.")
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    print(f"This will permanently delete ALL data in database '{DB_NAME}'.")
    if not args.yes:
        reply = input("Type 'yes' to continue: ").strip().lower()
        if reply != "yes":
            print("Aborted — no changes made.")
            return

    dropped = await reset()
    remaining = await db.list_collection_names()
    print(f"\nReset complete. {len(dropped)} collection(s) dropped.")
    if remaining:
        print(f"Note: {len(remaining)} protected system collection(s) left untouched: {remaining}")
    else:
        print("Database is now empty.")
    await close_client()


if __name__ == "__main__":
    asyncio.run(_main())
