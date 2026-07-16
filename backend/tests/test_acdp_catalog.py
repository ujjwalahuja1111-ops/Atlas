"""Project Atlas — Atlas Canonical Demo Project (ACDP) catalog checks.

Fast, no-database tests for scripts/acdp_fixtures.py's phase/activity/
zone catalog - the generator's data foundation. Deliberately does NOT
run the full seed_demo_project.main() simulation here (it performs
several thousand real engine calls and takes a few minutes - entirely
appropriate for a one-time deterministic seed, not for a routine fast
test suite run). The full generator is verified end-to-end via a
dedicated mongomock-backed smoke test
(smoketest/test_acdp_seed_verification.py, 37 checks covering every
founder-testing dimension: auth, dashboards, project feed, capture, AI
proposals, operational items, client approvals, CRE endpoints,
construction memory, and workflow) and via direct determinism/
idempotency verification (two full runs compared byte-for-byte
identical; a same-process rerun against an already-seeded database
correctly detected and skipped).
"""
import sys
sys.path.insert(0, "/home/claude/Atlas/backend")
from scripts import acdp_fixtures as fx


def _total_activity_instances() -> int:
    return sum(len(p["activities"]) * len(p["zones"]) for p in fx.PHASES)


def test_zone_count():
    assert len(fx.ZONES) == 6
    assert len(set(fx.ZONE_CODES)) == 6, "zone codes must be unique"


def test_every_phase_zone_is_a_real_zone():
    for phase in fx.PHASES:
        for zone_code in phase["zones"]:
            assert zone_code in fx.ZONE_CODES, f"{phase['phase_label']} references unknown zone {zone_code}"


def test_activity_total_within_brief_target_range():
    total = _total_activity_instances()
    assert 350 <= total <= 500, f"expected 350-500 activity instances, got {total}"


def test_every_activity_tuple_is_well_formed():
    for phase in fx.PHASES:
        for entry in phase["activities"]:
            assert len(entry) == 5, f"malformed activity tuple in {phase['phase_label']}: {entry}"
            name, trade, unit, duration, requires_inspection = entry
            assert isinstance(name, str) and name
            assert isinstance(trade, str) and trade
            assert isinstance(unit, str) and unit
            assert isinstance(duration, int) and duration > 0
            assert isinstance(requires_inspection, bool)


def test_activity_names_no_duplicates_within_a_phase():
    """Duplicate activity names within the same phase would collide once
    zone-suffixed (two identical knowledge item names)."""
    for phase in fx.PHASES:
        names = [a[0] for a in phase["activities"]]
        assert len(names) == len(set(names)), f"duplicate activity name within {phase['phase_label']}"


def test_stage_keyword_alignment():
    """Every ACDP phase except Landscape (a deliberate, documented
    exception - see ACDP_TIMELINE.md) must contain at least one activity
    whose name matches the CRE's own, unmodified stage keyword
    vocabulary - otherwise CRE's stage inference would silently never
    classify anything from that phase, defeating the entire point of
    aligning names to it in the first place."""
    from engines.reasoning_projections import stage_of_activity

    unclassified_phases = []
    for phase in fx.PHASES:
        if phase["phase_label"] == "Landscape":
            continue  # documented exception
        matched = any(
            stage_of_activity({"name": name, "trade": trade}) is not None
            for name, trade, unit, duration, insp in phase["activities"]
        )
        if not matched:
            unclassified_phases.append(phase["phase_label"])
    assert not unclassified_phases, f"phases with zero CRE-classifiable activities: {unclassified_phases}"


def test_landscape_partially_classified_as_expected():
    """Not every Landscape activity is stage-unclassified - some
    genuinely ARE other trades (pool filtration is plumbing -> mep, pool
    tiling and lighting -> finishes/mep) and correctly classify as such.
    Only activities with no real trade-keyword overlap (pool shell
    construction, soft/hard-scaping, planting) are unclassified, because
    CRE's vocabulary has no "landscape"/"garden"/"turf" keyword - a real,
    documented gap in the classifier, not something this dataset should
    paper over. This pins the exact, current split so a future change to
    either the catalog or the CRE keyword vocabulary is caught here
    rather than silently drifting from what ACDP_TIMELINE.md documents."""
    from engines.reasoning_projections import stage_of_activity

    expected_unclassified = {
        "Swimming Pool Shell Construction", "Garden Soft-scaping & Turfing",
        "Garden Hardscaping & Pathways", "Boundary Planting & Hedging",
    }
    landscape = next(p for p in fx.PHASES if p["phase_label"] == "Landscape")
    actual_unclassified = {
        name for name, trade, unit, duration, insp in landscape["activities"]
        if stage_of_activity({"name": name, "trade": trade}) is None
    }
    assert actual_unclassified == expected_unclassified, (
        f"Landscape's unclassified-activity set changed: "
        f"expected {expected_unclassified}, got {actual_unclassified} - "
        f"update ACDP_TIMELINE.md's Landscape explanation if intentional"
    )


def test_material_and_topic_banks_non_empty():
    assert len(fx.MATERIAL_ITEMS) >= 10
    assert len(fx.CLIENT_APPROVAL_TOPICS) >= 10
    assert len(fx.VOICE_TEMPLATES) >= 5
    assert len(fx.TEXT_TEMPLATES) >= 3
    assert len(fx.SAFETY_OBSERVATIONS) >= 3
    assert len(fx.DELAY_REASONS) >= 5
