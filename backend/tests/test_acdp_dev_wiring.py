"""Project Atlas — ACDP visibility audit regression test.

Root cause of "the Atlas Canonical Demo Project is not visible after
the merge": the seeder (scripts/seed_demo_project.py) was correctly
implemented and worked correctly on its own, but was never wired into
scripts/dev.py's `seed` / `reset-seed` commands - the ONLY seed
commands that existed and were documented BEFORE this audit. Anyone
following that already-familiar setup (`python -m scripts.dev seed`)
would never have triggered ACDP at all; the database-level data,
project scoping, and every permission check were all already correct
(confirmed directly against raw collections and against
memory_engine.list_projects/_is_project_scoped during this audit) - the
project simply never existed because nothing had ever run its seeder.

This file is a fast, no-database structural test confirming the fix:
scripts/dev.py's seed orchestration genuinely calls
seed_demo_project.main(), and both seed mains' close_when_done
parameter (the mechanism that lets them safely chain on one database
connection) exists with the correct default. The full, real behaviour
(chained seeding actually populates ACDP; idempotent across repeated
calls in any order; standalone invocation unaffected) was exercised
directly against a real running application (see the audit report) -
not repeated here, since actually running the full ~3-minute seed is
correctly out of scope for the routine fast test suite (see
test_acdp_catalog.py's own docstring for the same reasoning).
"""
import inspect
import sys
sys.path.insert(0, "/home/claude/Atlas/backend")
from scripts import dev, db_seed, seed_demo_project


def test_dev_seed_command_invokes_acdp():
    """The actual regression: scripts.dev's `seed` command must reach
    seed_demo_project.main - not just db_seed.main - or "the documented
    setup" never seeds ACDP at all, which is exactly what happened."""
    source = inspect.getsource(dev)
    assert "seed_demo_project" in source, \
        "scripts/dev.py no longer references seed_demo_project - ACDP would silently stop being seeded by `python -m scripts.dev seed` again"
    assert "seed_demo_project.main(" in source, \
        "scripts/dev.py imports seed_demo_project but never calls its main() - ACDP still wouldn't actually get seeded"


def test_dev_seed_all_calls_both_seeders_in_one_flow():
    source = inspect.getsource(dev._seed_all)
    assert "db_seed.main(" in source
    assert "seed_demo_project.main(" in source


def test_both_seed_mains_support_chaining_without_premature_close():
    """The wrinkle the fix has to get right: both db_seed.main() and
    seed_demo_project.main() close the shared Mongo connection
    themselves when run standalone (`python -m scripts.db_seed` /
    `python -m scripts.seed_demo_project`) - chaining them naively would
    have the first one close the connection out from under the second.
    Both must expose a close_when_done parameter, defaulting to True (so
    standalone invocation is completely unaffected), that dev.py can set
    to False when it owns the connection lifecycle itself."""
    for mod in (db_seed, seed_demo_project):
        sig = inspect.signature(mod.main)
        assert "close_when_done" in sig.parameters, \
            f"{mod.__name__}.main() lost its close_when_done parameter - chaining from dev.py would break"
        assert sig.parameters["close_when_done"].default is True, \
            f"{mod.__name__}.main()'s close_when_done must default to True - standalone invocation must keep closing the connection exactly as before"


def test_standalone_acdp_command_still_documented_and_callable():
    """Backward compatibility: `python -m scripts.seed_demo_project` on
    its own must keep working exactly as it did before this audit."""
    assert hasattr(seed_demo_project, "main")
    assert callable(seed_demo_project.main)
    assert hasattr(seed_demo_project, "USER_SEED")
    assert len(seed_demo_project.USER_SEED) == 5


def test_acdp_project_code_used_consistently_for_idempotency():
    """The idempotency guard (both when reached via dev.py and
    standalone) keys off this exact constant - it must stay a single
    source of truth, not get duplicated/hardcoded a second time
    somewhere that could drift."""
    source = inspect.getsource(seed_demo_project.main)
    assert "ACDP_PROJECT_CODE" in source
