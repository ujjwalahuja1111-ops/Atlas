"""Project Atlas — Database Lifecycle & Unified Seed Pipeline (DEV-01).

Pure unit tests for bootstrap.py's own logic (VerificationResult,
BootstrapError) — the parts genuinely testable without a database
connection, matching Atlas Engineering Standards v1 Section 10's own
three-layer discipline (this is layer 1). The full pipeline
(Stages 2-7) was verified end-to-end against a live database during
development - see this sprint's own commit message for the exact
scenario run (full pipeline executed twice against the same database,
confirming byte-identical collection counts - genuine idempotency, not
assumed from each underlying seeder's own individual idempotency
guard). That full-pipeline scenario isn't re-encoded as an automated
test here because it takes several minutes to run (ACDP's own 18-month
simulated timeline) and requires a real MongoDB connection unavailable
in this sandbox's fast pure-unit test tier - exactly the kind of
scenario Atlas Engineering Standards v1's own Testing Standards names
as appropriately covered by manual verification during development
rather than a fast automated suite.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.bootstrap import VerificationResult, BootstrapError


def test_verification_result_all_passed_true_when_no_checks():
    r = VerificationResult()
    assert r.all_passed is True


def test_verification_result_all_passed_true_when_all_pass():
    r = VerificationResult()
    r.check("Users exist", True, "8 users")
    r.check("Projects exist", True, "6 projects")
    assert r.all_passed is True


def test_verification_result_all_passed_false_on_any_failure():
    r = VerificationResult()
    r.check("Users exist", True)
    r.check("RP-001 exists", False, "not found")
    assert r.all_passed is False


def test_verification_result_records_detail():
    r = VerificationResult()
    r.check("Commercial collections populated (Contracts)", True, "2 contracts")
    label, passed, detail = r.checks[0]
    assert label == "Commercial collections populated (Contracts)"
    assert passed is True
    assert detail == "2 contracts"


def test_bootstrap_error_carries_stage_cause_resolution():
    e = BootstrapError(
        stage="Stage 1 — Environment Validation",
        cause="MONGO_URL is not set.",
        resolution="Set MONGO_URL in backend/.env and retry.",
    )
    assert e.stage == "Stage 1 — Environment Validation"
    assert e.cause == "MONGO_URL is not set."
    assert "Set MONGO_URL" in e.resolution
    # Must never surface the historical prerequisite failure verbatim -
    # this exact string was the reported bug this sprint exists to fix.
    assert "must be seeded first" not in str(e)


def test_bootstrap_error_str_includes_stage_and_cause():
    e = BootstrapError("Stage 3", "seed failed", "retry")
    assert "Stage 3" in str(e)
    assert "seed failed" in str(e)
