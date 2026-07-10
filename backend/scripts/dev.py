"""Single developer entry point for the Atlas dev database (Sprint DX-7).

A thin wrapper — reuses db_reset.reset() and db_seed.main() exactly as
they are, adding nothing new of its own beyond argument parsing and
combining the two for `reset-seed`. Not imported by server.py, any route,
or any engine.

Usage:
    cd backend
    python -m scripts.dev reset          # Reset Database
    python -m scripts.dev seed           # Seed Database
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
from scripts import db_reset, db_seed  # noqa: E402


async def _confirm(skip: bool) -> bool:
    if skip:
        return True
    print(f"This will permanently delete ALL data in database '{DB_NAME}'.")
    reply = input("Type 'yes' to continue: ").strip().lower()
    if reply != "yes":
        print("Aborted — no changes made.")
        return False
    return True


async def run(command: str, *, skip_confirm: bool) -> None:
    if command == "reset":
        if await _confirm(skip_confirm):
            dropped = await db_reset.reset()
            print(f"\nReset complete. {len(dropped)} collection(s) dropped.")
        await close_client()

    elif command == "seed":
        await db_seed.main()  # already closes the client itself

    elif command == "reset-seed":
        if await _confirm(skip_confirm):
            dropped = await db_reset.reset()
            print(f"\nReset complete. {len(dropped)} collection(s) dropped.\n")
            await db_seed.main()  # already closes the client itself
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
