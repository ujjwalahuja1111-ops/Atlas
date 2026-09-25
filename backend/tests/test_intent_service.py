"""Atlas Intent & Orchestration Phase 1 — regression tests.

Follows tests/test_dev02_bootstrap_reliability.py's own established
mongomock_motor pattern exactly (see that file's own header comment
for why this convention is used across this suite).

The LLM structuring pass itself is mocked (via monkeypatching
intent_service._run_structuring_pass) rather than calling a real
model — this is what makes these tests deterministic, per this
phase's own explicit "add deterministic tests" instruction. What is
under test is the new code: project resolution, confidence handling,
deterministic engine dispatch, RBAC pass-through, and failure
isolation — not the LLM's own classification accuracy, which cannot
be deterministically tested at all.

Reference Portfolio projects (RP-001, RP-002) are used ONLY as
regression fixtures where explicitly noted, matching this phase's own
explicit "do not treat them as historical intelligence" instruction —
every other test builds its own minimal fixtures.

Run from backend/:  python -m pytest tests/test_intent_service.py -q
"""
import os
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

mongomock_motor = pytest.importorskip("mongomock_motor")

os.environ.setdefault("MONGO_URL", "mongodb://mongomock:27017")
os.environ.setdefault("DB_NAME", "atlas_intent_test")

import core.db as core_db  # noqa: E402

_mock_client = mongomock_motor.AsyncMongoMockClient()
_mock_db = _mock_client["atlas_intent_test"]
core_db.db = _mock_db
core_db.client = _mock_client

from engines import memory_engine, reasoning_engine, commercial_engine, operations_engine, workflow_engine, knowledge_engine  # noqa: E402
from services import intent_service, inbox_intelligence_service  # noqa: E402

for _mod in (memory_engine, reasoning_engine, commercial_engine, operations_engine,
             workflow_engine, knowledge_engine, inbox_intelligence_service):
    _mod.db = _mock_db

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


ADMIN = {"id": "u_intent_admin", "name": "Intent Admin", "role": "management"}


def _mock_structuring(return_value):
    """Patches the one LLM call site so every test is deterministic."""
    intent_service._run_structuring_pass = AsyncMock(return_value=return_value)


async def _make_project(name: str) -> dict:
    return await memory_engine.insert_project(name=name, code=name.replace(" ", "").upper()[:8])


# ==========================================================================
# Each supported intent
# ==========================================================================
async def test_query_health_intent_dispatches_to_explain_health():
    project = await _make_project("Intent Health Project")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert result["intent"] == "query_health"
    assert result["result"]["ok"] is True


async def test_query_schedule_impact_intent_dispatches_to_lookahead():
    project = await _make_project("Intent Schedule Project")
    _mock_structuring({"intents": [{"intent": "query_schedule_impact", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "does this affect handover?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert result["intent"] == "query_schedule_impact"
    assert result["result"]["ok"] is True


async def test_query_comparison_intent_dispatches_to_compare_projects():
    p1 = await _make_project("Intent Compare Project One")
    await _make_project("Intent Compare Project Two")
    _mock_structuring({"intents": [{"intent": "query_comparison", "confidence": "high"}], "project_reference": "Intent Compare Project One", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "compare this project with my other one", user=ADMIN, active_project_id=None)
    assert result["type"] == "result"
    assert result["intent"] == "query_comparison"
    assert result["result"]["ok"] is True


async def test_query_digest_intent_is_portfolio_wide_no_project_needed():
    _mock_structuring({"intents": [{"intent": "query_digest", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what's happening on my projects today?", user=ADMIN, active_project_id=None)
    assert result["type"] == "result"
    assert result["intent"] == "query_digest"
    assert result["result"]["ok"] is True
    assert "coordination" in result["result"]["data"] or "my_day" in result["result"]["data"]


async def test_unresolved_intent_from_llm_returns_unresolved_message():
    _mock_structuring({"intents": [{"intent": "unresolved", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "create a new variation for the kitchen", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


# ==========================================================================
# Entity extraction (comparison_scope, project_reference)
# ==========================================================================
async def test_comparison_scope_entity_triggers_named_gap_not_a_guess():
    """Spec Item 28/Flow 8's own named gap - project type isn't
    structured data, so a scoped comparison must say so, never guess
    which projects count as 'residential'."""
    project = await _make_project("Intent Scope Gap Project")
    _mock_structuring({"intents": [{"intent": "query_comparison", "confidence": "high"}], "project_reference": None, "comparison_scope": "residential"})
    result = await intent_service.handle_intent(
        "compare with our other residential projects", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert result["result"]["ok"] is False
    assert "project type isn't consistently recorded" in result["result"]["error"]


async def test_project_reference_entity_resolves_explicit_project():
    await _make_project("Sharma Residence")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": "Sharma Residence", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Sharma Residence at risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "result"
    assert result["project"]["name"] == "Sharma Residence"


# ==========================================================================
# Confidence handling
# ==========================================================================
async def test_low_confidence_is_treated_as_unresolved():
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "low"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "hmm maybe something about risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


async def test_medium_confidence_still_proceeds():
    project = await _make_project("Intent Medium Confidence Project")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "medium"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "is this project okay?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"


# ==========================================================================
# Unresolved input (LLM classifies as unresolved AND malformed/unusable output)
# ==========================================================================
async def test_malformed_llm_output_missing_intents_field_is_unresolved():
    _mock_structuring({"confidence": "high"})  # no "intents" key at all
    result = await intent_service.handle_intent(
        "gibberish that produces bad json", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


async def test_llm_output_with_unsupported_intent_value_is_unresolved():
    _mock_structuring({"intents": [{"intent": "create_project", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    # create_project is a real Item-4 intent from the full spec but NOT
    # part of Phase 1's own SUPPORTED_INTENTS - must not be dispatched.
    result = await intent_service.handle_intent(
        "make a new project", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


async def test_empty_input_is_unresolved_without_calling_the_llm():
    intent_service._run_structuring_pass = AsyncMock(side_effect=AssertionError("should not be called"))
    result = await intent_service.handle_intent("   ", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


# ==========================================================================
# Active project resolution
# ==========================================================================
async def test_active_project_context_resolves_when_no_explicit_mention():
    project = await _make_project("Intent Active Context Project")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert result["project"]["id"] == project["id"]


# ==========================================================================
# Explicit project resolution
# ==========================================================================
async def test_explicit_mention_overrides_active_context():
    active_project = await _make_project("Intent Active But Not Mentioned")
    named_project = await _make_project("Intent Explicitly Named Project")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": "Intent Explicitly Named Project", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Intent Explicitly Named Project at risk?",
        user=ADMIN, active_project_id=active_project["id"])
    assert result["type"] == "result"
    assert result["project"]["id"] == named_project["id"]


async def test_mentioned_project_not_found_asks_rather_than_falls_back():
    active_project = await _make_project("Intent Fallback Candidate")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": "Totally Nonexistent Project Name XYZ", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Totally Nonexistent Project Name XYZ at risk?",
        user=ADMIN, active_project_id=active_project["id"])
    assert result["type"] == "unresolved"


# ==========================================================================
# Ambiguous project resolution
# ==========================================================================
async def test_ambiguous_project_reference_asks_for_clarification():
    await _make_project("Ambiguous Villa Project Alpha")
    await _make_project("Ambiguous Villa Project Beta")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": "Ambiguous Villa", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Ambiguous Villa at risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "clarification_needed"
    assert len(result["candidates"]) == 2


async def test_no_context_and_multiple_projects_asks_for_clarification():
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    # ADMIN already has several projects from earlier tests in this
    # module (shared mongomock db) - reuse that visibility directly
    # rather than re-seed, since ADMIN is not project-scoped (role
    # management sees everything, per list_projects's own logic).
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "clarification_needed"
    assert "question" in result


async def test_confirmed_project_id_completes_the_clarification_round_trip():
    """Item 22 - the one-round clarification actually completing.
    Resubmitting the same ambiguous text with confirmed_project_id set
    must resolve directly, not hit the same ambiguity again."""
    p1 = await _make_project("Confirm Round Trip Villa Alpha")
    await _make_project("Confirm Round Trip Villa Beta")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": "Confirm Round Trip Villa", "comparison_scope": None})
    ambiguous = await intent_service.handle_intent(
        "why is Confirm Round Trip Villa at risk?", user=ADMIN, active_project_id=None)
    assert ambiguous["type"] == "clarification_needed"

    resolved = await intent_service.handle_intent(
        "why is Confirm Round Trip Villa at risk?", user=ADMIN,
        confirmed_project_id=p1["id"])
    assert resolved["type"] == "result"
    assert resolved["project"]["id"] == p1["id"]


# ==========================================================================
# RBAC enforcement
# ==========================================================================
async def test_project_scoped_user_cannot_resolve_a_project_they_are_not_assigned_to():
    unassigned_project = await _make_project("Intent RBAC Unassigned Project")
    scoped_pm = {"id": "u_intent_scoped_pm", "name": "Scoped PM", "role": "project_manager",
                 "scope_projects": True, "assigned_project_ids": []}  # explicitly assigned to nothing
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": "Intent RBAC Unassigned Project", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Intent RBAC Unassigned Project at risk?",
        user=scoped_pm, active_project_id=unassigned_project["id"])
    # list_projects(user=...) already RBAC-filters - a project-scoped
    # user with no assignments sees nothing, so this must resolve as
    # not-found, never as a successful health check on a project this
    # user cannot see. This is RBAC enforcement inherited from the
    # existing engine, not re-implemented in intent_service.
    assert result["type"] == "unresolved"


# ==========================================================================
# Engine failure isolation
# ==========================================================================
async def test_engine_failure_is_isolated_not_raised():
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id="prj_does_not_exist_at_all")
    # active_project_id that doesn't match any visible project falls
    # through to normal resolution (ambiguous, since ADMIN has other
    # real projects) rather than crashing on a bad id.
    assert result["type"] in ("clarification_needed", "unresolved")


async def test_query_digest_partial_engine_failure_still_returns_result(monkeypatch):
    async def _boom(*a, **kw):
        raise RuntimeError("simulated my_day failure")
    monkeypatch.setattr(operations_engine, "my_day", _boom)
    _mock_structuring({"intents": [{"intent": "query_digest", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what's happening today?", user=ADMIN, active_project_id=None)
    assert result["type"] == "result"
    assert result["result"]["ok"] is True
    assert "today's task summary unavailable" in (result["result"].get("partial_errors") or [])


# ==========================================================================
# LLM failure isolation
# ==========================================================================
async def test_llm_call_exception_fails_safely_to_unresolved():
    intent_service._run_structuring_pass = AsyncMock(side_effect=RuntimeError("simulated LLM outage"))
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


async def test_llm_returns_none_fails_safely_to_unresolved():
    _mock_structuring(None)
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


# ==========================================================================
# Workflow Refinement Pass — P0 fix. reasoning_engine.explain_health /
# project_lookahead_view / compare_projects and operations_engine.my_day
# are all restricted to non-Client roles at their own real HTTP routes
# (_forbid_client, confirmed by reading routes/reasoning.py and
# routes/operational_items.py directly). intent_service previously
# called these functions directly, bypassing that route-layer check
# entirely - a real Client user could get a genuine 200 with full
# health/schedule/comparison/task data through the intent API. Found by
# live-testing an actual Client login against the real endpoint, not
# assumed from reading code; these tests lock the fix in place.
CLIENT_USER = {"id": "u_intent_client", "name": "Intent Client", "role": "client"}


async def test_query_health_forbidden_for_client_even_though_engine_call_would_succeed():
    project = await _make_project("Client RBAC Health Project")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["type"] == "result"  # not a hard failure - a clear, honest refusal
    assert result["result"]["ok"] is False
    assert "available on your account" in result["result"]["error"].lower()


async def test_query_schedule_impact_forbidden_for_client():
    project = await _make_project("Client RBAC Schedule Project")
    _mock_structuring({"intents": [{"intent": "query_schedule_impact", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "does this affect handover?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "available on your account" in result["result"]["error"].lower()


async def test_query_comparison_forbidden_for_client():
    await _make_project("Client RBAC Alpha Project")
    await _make_project("Client RBAC Beta Project")
    _mock_structuring({"intents": [{"intent": "query_comparison", "confidence": "high"}], "project_reference": "Client RBAC Alpha Project", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "compare with my other project", user=CLIENT_USER, active_project_id=None)
    assert result["result"]["ok"] is False
    assert "available on your account" in result["result"]["error"].lower()


async def test_query_digest_omits_my_day_for_client_but_keeps_coordination():
    _mock_structuring({"intents": [{"intent": "query_digest", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what do I need to know today?", user=CLIENT_USER, active_project_id=None)
    assert result["type"] == "result"
    assert result["result"]["ok"] is True
    assert "my_day" not in result["result"]["data"]
    assert "coordination" in result["result"]["data"]


async def test_query_health_still_works_normally_for_non_client_roles():
    """The fix must not affect any role it wasn't meant to restrict."""
    project = await _make_project("Non Client RBAC Project")
    _mock_structuring({"intents": [{"intent": "query_health", "confidence": "high"}], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=project["id"])
    assert result["result"]["ok"] is True


# ==========================================================================
# Phase D — Multi-Intent Synthesis. The existing 28 tests above, all
# still passing unmodified, are themselves test case A/K (single-intent
# behavior unchanged, existing Phase 1 questions unaffected). These
# tests cover the new multi-intent dispatch path specifically.
# ==========================================================================

async def test_two_intents_both_handlers_execute_and_both_results_return():
    """Test case B."""
    project = await _make_project("Multi Intent Two Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_schedule_impact", "confidence": "high"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I be worried about?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    assert len(result["sections"]) == 2
    intents_returned = {s["intent"] for s in result["sections"]}
    assert intents_returned == {"query_health", "query_schedule_impact"}
    for s in result["sections"]:
        assert s["result"]["ok"] is True
        assert s["project"]["id"] == project["id"]


async def test_three_intents_all_relevant_results_returned():
    """Test case C."""
    project = await _make_project("Multi Intent Three Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_schedule_impact", "confidence": "high"},
        {"intent": "query_digest", "confidence": "medium"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I focus on today?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    assert len(result["sections"]) == 3
    intents_returned = {s["intent"] for s in result["sections"]}
    assert intents_returned == {"query_health", "query_schedule_impact", "query_digest"}
    # query_digest is portfolio-wide, not project-scoped - must not carry a project key
    digest_section = next(s for s in result["sections"] if s["intent"] == "query_digest")
    assert "project" not in digest_section


async def test_zero_intents_selected_is_safely_unresolved():
    """Test case D - every candidate intent filtered out (e.g. all below
    the confidence floor)."""
    project = await _make_project("Multi Intent Zero Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "low"},
        {"intent": "query_schedule_impact", "confidence": "low"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "vague uncertain question", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "unresolved"


async def test_duplicate_intent_is_deduplicated_not_rejected():
    """Test case E."""
    project = await _make_project("Multi Intent Dedup Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_health", "confidence": "medium"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk, really why?", user=ADMIN, active_project_id=project["id"])
    # A single surviving unique intent produces the backward-compatible
    # single-result shape, not a multi_result with one section.
    assert result["type"] == "result"
    assert result["intent"] == "query_health"


async def test_more_than_three_requested_is_bounded_to_max_intents():
    """Test case F."""
    project = await _make_project("Multi Intent Bound Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_schedule_impact", "confidence": "high"},
        {"intent": "query_digest", "confidence": "high"},
        {"intent": "query_comparison", "confidence": "high"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "everything about this project please", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    assert len(result["sections"]) == intent_service.MAX_INTENTS
    assert len(result["sections"]) == 3


async def test_one_selected_handler_failing_does_not_destroy_the_others():
    """Test case G."""
    project = await _make_project("Multi Intent Failure Isolation Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_schedule_impact", "confidence": "high"},
    ], "project_reference": None, "comparison_scope": None})

    async def _boom(*a, **kw):
        raise RuntimeError("simulated explain_health outage")
    with patch.object(reasoning_engine, "explain_health", _boom):
        result = await intent_service.handle_intent(
            "what should I worry about?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    assert len(result["sections"]) == 2
    health_section = next(s for s in result["sections"] if s["intent"] == "query_health")
    schedule_section = next(s for s in result["sections"] if s["intent"] == "query_schedule_impact")
    assert health_section["result"]["ok"] is False
    assert schedule_section["result"]["ok"] is True


async def test_client_mixed_domain_question_restricted_intent_stays_inaccessible():
    """Test case H — the RBAC leak this task's own brief explicitly
    warns against: a Client asking a mixed-domain question must not
    have restricted data leak through the new composition step."""
    project = await _make_project("Multi Intent Client Mixed Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_digest", "confidence": "high"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I worry about?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    health_section = next(s for s in result["sections"] if s["intent"] == "query_health")
    assert health_section["result"]["ok"] is False
    assert "available on your account" in health_section["result"]["error"].lower()
    # Confirm no health data leaked into the section at all
    assert "data" not in health_section["result"]


async def test_client_mixed_domain_question_permitted_intent_stays_useful():
    """Test case I — same mixed-domain request as above; the permitted
    section must still be genuinely useful, not collapsed just because
    another section in the same answer was restricted."""
    project = await _make_project("Multi Intent Client Mixed Project 2")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_digest", "confidence": "high"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I worry about?", user=CLIENT_USER, active_project_id=project["id"])
    digest_section = next(s for s in result["sections"] if s["intent"] == "query_digest")
    assert digest_section["result"]["ok"] is True
    assert "coordination" in digest_section["result"]["data"]


async def test_shared_project_resolution_remains_correct_across_multiple_intents():
    """Test case J — project resolved once, correctly shared, not
    re-resolved (and potentially re-diverging) per intent."""
    project = await _make_project("Shared Context Alpha Villa")
    await _make_project("Shared Context Beta Villa")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_schedule_impact", "confidence": "high"},
    ], "project_reference": "Shared Context Alpha Villa", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I worry about?", user=ADMIN, active_project_id=None)
    assert result["type"] == "multi_result"
    for s in result["sections"]:
        assert s["project"]["id"] == project["id"]


async def test_ambiguous_project_with_multiple_intents_asks_once_not_per_intent():
    """A genuinely new edge case worth covering: ambiguity in shared
    project resolution must short-circuit to one clarification request
    for the whole multi-intent question, not one per intent."""
    await _make_project("Multi Intent Ambiguous Alpha")
    await _make_project("Multi Intent Ambiguous Beta")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_schedule_impact", "confidence": "high"},
    ], "project_reference": "Multi Intent Ambiguous", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I worry about?", user=ADMIN, active_project_id=None)
    assert result["type"] == "clarification_needed"
    assert len(result["candidates"]) == 2


async def test_multi_result_lead_in_never_names_an_engine_or_route():
    """Section 11's own explicit requirement — the composed lead-in must
    use user-facing language only."""
    project = await _make_project("Multi Intent Lead In Project")
    _mock_structuring({"intents": [
        {"intent": "query_health", "confidence": "high"},
        {"intent": "query_schedule_impact", "confidence": "high"},
    ], "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what should I worry about?", user=ADMIN, active_project_id=project["id"])
    lead_in = result["lead_in"].lower()
    for forbidden in ("engine", "reasoning_engine", "explain_health", "route", "handler", "endpoint"):
        assert forbidden not in lead_in


# ==========================================================================
# Event & Provenance Retrieval — query_change_history.
# Read-only presentation over the event history that already exists
# (Source Foundation + Workflow Event Preservation) — no new event
# architecture, no reconciliation, no integration.
# ==========================================================================

async def _make_bare_activity_for_history(project_id, name="Electrical First Fix"):
    now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    import uuid as _uuid
    aid = f"wa_{_uuid.uuid4()}"
    await _mock_db.workflow_activities.insert_one({
        "id": aid, "project_id": project_id, "name": name, "trade": "Electrical",
        "status": "not_started", "depends_on_activity_ids": [], "order": 0,
        "default_duration_days": 4, "requires_inspection": False,
        "planned_start": None, "planned_finish": None, "actual_start": None, "actual_finish": None,
        "milestone_id": None, "created_at": now_iso, "updated_at": now_iso,
    })
    return aid


# 1. Native-only history: events render chronologically, no unnecessary source label.
async def test_change_history_native_only_no_source_label():
    project = await _make_project("Change History Native Only Project")
    aid = await _make_bare_activity_for_history(project["id"])
    actor = {"id": ADMIN["id"], "name": ADMIN["name"]}
    await workflow_engine.set_schedule(aid, {"planned_finish": "2026-09-15T00:00:00+00:00"}, actor=actor)
    await workflow_engine.set_status(aid, "blocked", actor=actor)

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Electrical First Fix"})
    result = await intent_service.handle_intent(
        "what changed on Electrical First Fix?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    data = result["result"]["data"]
    events = data["events"]
    assert len(events) == 2
    assert events[0]["when"] <= events[1]["when"]  # chronological
    assert all(e["source"] is None for e in events)


# 2. Imported-only history: external system shown when present.
async def test_change_history_imported_shows_external_system():
    project = await _make_project("Change History Imported Project")
    aid = await _make_bare_activity_for_history(project["id"])
    actor = {"id": ADMIN["id"], "name": ADMIN["name"]}
    await workflow_engine.set_schedule(
        aid, {"planned_finish": "2026-09-18T00:00:00+00:00"}, actor=actor,
        source={"origin": "imported", "external_system": "primavera_p6"})

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Electrical First Fix"})
    result = await intent_service.handle_intent(
        "what changed on Electrical First Fix?", user=ADMIN, active_project_id=project["id"])
    events = result["result"]["data"]["events"]
    assert len(events) == 1
    assert events[0]["source"] == "primavera_p6"


# 3. Mixed native/imported history: both claims visible, chronology preserved,
#    neither declared correct.
async def test_change_history_mixed_native_and_imported():
    project = await _make_project("Change History Mixed Project")
    aid = await _make_bare_activity_for_history(project["id"])
    actor = {"id": ADMIN["id"], "name": ADMIN["name"]}
    await workflow_engine.set_schedule(aid, {"planned_finish": "2026-09-15T00:00:00+00:00"}, actor=actor)
    await workflow_engine.set_schedule(
        aid, {"planned_finish": "2026-09-18T00:00:00+00:00"}, actor=actor,
        source={"origin": "imported", "external_system": "primavera_p6"})

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Electrical First Fix"})
    result = await intent_service.handle_intent(
        "what changed on Electrical First Fix?", user=ADMIN, active_project_id=project["id"])
    events = result["result"]["data"]["events"]
    assert len(events) == 2
    assert events[0]["source"] is None
    assert events[0]["to"] == "2026-09-15T00:00:00+00:00"
    assert events[1]["source"] == "primavera_p6"
    assert events[1]["to"] == "2026-09-18T00:00:00+00:00"
    # No reconciliation field, no "winner", no authority claim anywhere
    # in the response.
    assert "winner" not in str(result).lower()
    assert "authoritative" not in str(result).lower()


# 4. Empty history: honest no-history response, never fabricated.
async def test_change_history_empty_is_honest():
    project = await _make_project("Change History Empty Project")
    aid = await _make_bare_activity_for_history(project["id"], name="Plumbing First Fix")

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Plumbing First Fix"})
    result = await intent_service.handle_intent(
        "what changed on Plumbing First Fix?", user=ADMIN, active_project_id=project["id"])
    data = result["result"]["data"]
    assert data["events"] == []
    assert data["message"] == "No recorded changes found for this item."


# 5. Previous-value preservation: from/to values come from the actual events.
async def test_change_history_from_to_values_are_real():
    project = await _make_project("Change History From To Project")
    aid = await _make_bare_activity_for_history(project["id"])
    actor = {"id": ADMIN["id"], "name": ADMIN["name"]}
    await workflow_engine.set_status(aid, "in_progress", actor=actor)

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Electrical First Fix"})
    result = await intent_service.handle_intent(
        "when did this become in progress?", user=ADMIN, active_project_id=project["id"])
    events = result["result"]["data"]["events"]
    status_event = next(e for e in events if e["what"] == "status")
    assert status_event["from"] == "not_started"
    assert status_event["to"] == "in_progress"


# 6. Actor preservation: real actor surfaced when present.
async def test_change_history_actor_preserved():
    project = await _make_project("Change History Actor Project")
    aid = await _make_bare_activity_for_history(project["id"])
    real_actor = {"id": "u_ramesh", "name": "Ramesh Supervisor"}
    await workflow_engine.set_status(aid, "blocked", actor=real_actor)

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Electrical First Fix"})
    result = await intent_service.handle_intent(
        "who changed the status?", user=ADMIN, active_project_id=project["id"])
    events = result["result"]["data"]["events"]
    assert events[0]["who"] == "Ramesh Supervisor"


# 7. RBAC — milestone history restricted to management/PM, matching the
#    existing commercial-events route's own real restriction; activity
#    history follows the existing project-visibility-only rule.
async def test_change_history_milestone_restricted_to_management_pm():
    project = await _make_project("Change History Milestone RBAC Project")
    await commercial_engine.create_contract(
        actor=ADMIN, project_id=project["id"], client_id=None, original_contract_value=1000000,
        contract_date="2026-01-01", duration_days=90)
    await commercial_engine.create_milestone(
        actor=ADMIN, project_id=project["id"], name="MEP Completion", sequence=1,
        planned_percent=10, trigger="x")

    supervisor = {"id": "u_intent_sup", "name": "Intent Supervisor", "role": "site_supervisor"}
    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "MEP Completion"})
    result = await intent_service.handle_intent(
        "what changed on MEP Completion?", user=supervisor, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "account" in result["result"]["error"].lower()


async def test_change_history_activity_visible_to_client_matching_existing_route():
    """Not a new restriction invented for this phase — confirmed by
    inspection that get_activity_evidence() (the existing, unmodified
    function this reuses) has always been project-visibility-only,
    with no role gate, unlike the commercial-events route."""
    project = await _make_project("Change History Activity Client Project")
    aid = await _make_bare_activity_for_history(project["id"])
    actor = {"id": ADMIN["id"], "name": ADMIN["name"]}
    await workflow_engine.set_status(aid, "blocked", actor=actor)

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Electrical First Fix"})
    result = await intent_service.handle_intent(
        "what changed on Electrical First Fix?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["result"]["ok"] is True


# 8. Multi-intent: history + health/consequence coexist through the
#    existing Phase D composition.
async def test_change_history_multi_intent_with_health():
    project = await _make_project("Change History Multi Intent Project")
    aid = await _make_bare_activity_for_history(project["id"])
    actor = {"id": ADMIN["id"], "name": ADMIN["name"]}
    await workflow_engine.set_status(aid, "blocked", actor=actor)

    _mock_structuring({"intents": [
        {"intent": "query_change_history", "confidence": "high"},
        {"intent": "query_health", "confidence": "high"},
    ], "project_reference": None, "comparison_scope": None, "entity_reference": "Electrical First Fix"})
    result = await intent_service.handle_intent(
        "what changed and why is Electrical First Fix blocked?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "multi_result"
    intents_present = {s["intent"] for s in result["sections"]}
    assert intents_present == {"query_change_history", "query_health"}
    history_section = next(s for s in result["sections"] if s["intent"] == "query_change_history")
    assert history_section["result"]["ok"] is True


# No entity named at all - honest decline, never a fabricated project-wide answer.
async def test_change_history_no_entity_named_is_honest():
    project = await _make_project("Change History No Entity Project")
    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None, "entity_reference": None})
    result = await intent_service.handle_intent(
        "what changed?", user=ADMIN, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "which" in result["result"]["error"].lower()


# Ambiguous entity reference - honest decline, no guessing.
async def test_change_history_ambiguous_entity_is_honest():
    project = await _make_project("Change History Ambiguous Entity Project")
    await _make_bare_activity_for_history(project["id"], name="Electrical First Fix")
    await _make_bare_activity_for_history(project["id"], name="Electrical Second Fix")
    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Electrical"})
    result = await intent_service.handle_intent(
        "what changed on Electrical?", user=ADMIN, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "more than one" in result["result"]["error"].lower()


# 9. Regression: all existing intents behave exactly as before (covered
# by the full existing test suite in this file re-passing unmodified).


# ==========================================================================
# query_change_history completion — synthetic "created" entry for
# operational items. No new event, no new intent, no event-ledger
# change - purely a presentation-layer addition over already-persisted
# item fields.
# ==========================================================================

async def _make_item_with_fields(project_id, site_id, *, quantity=None, unit=None,
                                  required_by=None, attributed_to=None, title="Test Item"):
    item = await operations_engine.create_item(
        actor=ADMIN, site_id=site_id, category="material_requirement",
        title=title, required_by=required_by)
    extra = {}
    if quantity is not None:
        extra["quantity"] = quantity
    if unit:
        extra["unit"] = unit
    if attributed_to:
        extra["attributed_to"] = attributed_to
    if extra:
        await _mock_db.operational_items.update_one({"id": item["id"]}, {"$set": extra})
        item.update(extra)
    return item


# 1. Item with creation fields but no events - genuinely zero events
#    only happens for a record inserted directly, bypassing
#    create_item() (e.g. a legacy or externally-seeded item) - since a
#    real create_item() call always logs its own "created" event
#    (confirmed by reading the code directly: it already calls
#    append_event(kind="created", ...) with category/title/origin_type
#    - but never quantity/unit/required_by/attributed_to, which are
#    set later, separately, in accept_ai_proposal(), with no
#    corresponding event at all - confirming the real gap this feature
#    closes).
async def test_synthetic_entry_for_item_with_no_events():
    project = await _make_project("QCH Synthetic No Events Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc).isoformat()
    item_id = f"op_{uuid.uuid4()}"
    await _mock_db.operational_items.insert_one({
        "id": item_id, "category": "material_requirement", "title": "Procure 200 pieces tiles",
        "description": "", "site_id": site["id"], "project_id": project["id"],
        "origin_type": "manual", "origin_reference_id": None, "inherited_evidence_event_id": None,
        "status": "open", "priority": "normal",
        "created_by_user_id": ADMIN["id"], "created_by_user_name": ADMIN["name"],
        "assigned_to_user_id": None, "assigned_to_user_name": None,
        "created_at": now, "required_by": "2026-09-24T00:00:00+00:00", "target_start": None,
        "quantity": 200, "unit": "pieces", "attributed_to": "supplier",
        "blocker": None, "health": "on_track", "affected_activity_ids": [],
    })

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Procure 200 pieces tiles"})
    result = await intent_service.handle_intent(
        "what changed on Procure 200 pieces tiles?", user=ADMIN, active_project_id=project["id"])
    data = result["result"]["data"]
    assert len(data["events"]) == 1
    entry = data["events"][0]
    assert entry["synthetic"] is True
    assert entry["what"] == "created"
    assert entry["fields"] == {
        "quantity": 200, "unit": "pieces",
        "required_by": "2026-09-24T00:00:00+00:00", "attributed_to": "supplier",
    }
    assert entry["when"] == now
    assert entry["who"] == ADMIN["name"]


# 2. Item with creation fields plus later status events - chronological
#    ordering (also covers requirement 7).
async def test_synthetic_entry_plus_later_status_event_chronological():
    project = await _make_project("QCH Synthetic Plus Events Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await _make_item_with_fields(
        project["id"], site["id"], quantity=80, unit="kg", attributed_to="food supplier",
        title="Procure 80 kg chicken")
    await operations_engine.append_event(
        item_id=item["id"], kind="status_changed", actor=ADMIN,
        prev_status="open", new_status="fulfilled")

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": item["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {item['title']}?", user=ADMIN, active_project_id=project["id"])
    events = result["result"]["data"]["events"]
    assert len(events) == 3
    # The synthetic creation entry must sort first - it happened first.
    assert events[0]["synthetic"] is True
    assert events[0]["what"] == "created"
    # events[1] is the real "created" event's own status transition
    # (None -> open, logged by create_item() itself); events[2] is the
    # later status_changed event this test explicitly triggered.
    assert events[2].get("synthetic") is not True
    assert events[2]["to"] == "fulfilled"
    whens = [e["when"] for e in events]
    assert whens == sorted(whens)


# 3. Missing optional fields - only genuinely present fields appear.
async def test_synthetic_entry_omits_missing_fields():
    project = await _make_project("QCH Missing Fields Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await _make_item_with_fields(
        project["id"], site["id"], quantity=50, title="Procure 50 bags cement")
    # No unit, no required_by, no attributed_to set at all.

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": item["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {item['title']}?", user=ADMIN, active_project_id=project["id"])
    entry = result["result"]["data"]["events"][0]
    assert entry["fields"] == {"quantity": 50}  # only the genuinely present field


# 4. attributed_to present vs absent.
async def test_synthetic_entry_attributed_to_present_vs_absent():
    project = await _make_project("QCH Attribution Present Absent Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item_with = await _make_item_with_fields(
        project["id"], site["id"], quantity=10, attributed_to="client", title="Item With Attribution")
    item_without = await _make_item_with_fields(
        project["id"], site["id"], quantity=10, title="Item Without Attribution")

    for item, expect_present in [(item_with, True), (item_without, False)]:
        _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                            "project_reference": None, "comparison_scope": None,
                            "entity_reference": item["title"]})
        result = await intent_service.handle_intent(
            f"what changed on {item['title']}?", user=ADMIN, active_project_id=project["id"])
        fields = result["result"]["data"]["events"][0]["fields"]
        assert ("attributed_to" in fields) == expect_present


# 5. required_by present vs absent.
async def test_synthetic_entry_required_by_present_vs_absent():
    project = await _make_project("QCH Required By Present Absent Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item_with = await _make_item_with_fields(
        project["id"], site["id"], quantity=10, required_by="2026-10-01T00:00:00+00:00",
        title="Item With Due Date")
    item_without = await _make_item_with_fields(
        project["id"], site["id"], quantity=10, title="Item Without Due Date")

    for item, expect_present in [(item_with, True), (item_without, False)]:
        _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                            "project_reference": None, "comparison_scope": None,
                            "entity_reference": item["title"]})
        result = await intent_service.handle_intent(
            f"what changed on {item['title']}?", user=ADMIN, active_project_id=project["id"])
        fields = result["result"]["data"]["events"][0]["fields"]
        assert ("required_by" in fields) == expect_present


# 6. RBAC / Client restrictions unchanged - operational item history
#    remains project-visibility-only (not newly restricted, not newly
#    opened, by this change).
async def test_synthetic_entry_rbac_unchanged_for_client():
    project = await _make_project("QCH RBAC Unchanged Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await _make_item_with_fields(
        project["id"], site["id"], quantity=5, title="RBAC Test Item")

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": item["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {item['title']}?", user=CLIENT_USER, active_project_id=project["id"])
    # Same, pre-existing rule: activity/item history is project-
    # visibility-only, so Client is allowed here - confirming this
    # change did not alter that existing boundary either way.
    assert result["result"]["ok"] is True
    assert result["result"]["data"]["events"][0]["synthetic"] is True


# 7. Chronological ordering - covered directly by test #2 above, and
#    an additional case with the synthetic entry appearing correctly
#    positioned against TWO later events.
async def test_synthetic_entry_ordering_with_multiple_later_events():
    project = await _make_project("QCH Multi Event Ordering Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await _make_item_with_fields(
        project["id"], site["id"], quantity=20, title="Multi Event Item")
    await operations_engine.append_event(
        item_id=item["id"], kind="status_changed", actor=ADMIN,
        prev_status="open", new_status="assigned")
    await operations_engine.append_event(
        item_id=item["id"], kind="status_changed", actor=ADMIN,
        prev_status="assigned", new_status="fulfilled")

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": item["title"]})
    result = await intent_service.handle_intent(
        f"what changed on {item['title']}?", user=ADMIN, active_project_id=project["id"])
    events = result["result"]["data"]["events"]
    assert len(events) == 4  # synthetic + real "created" status row + 2 explicit status changes
    assert events[0]["synthetic"] is True  # creation always first
    whens = [e["when"] for e in events]
    assert whens == sorted(whens)


# 8. No new event written as a side effect of calling
#    query_change_history itself - confirmed against the real count,
#    whatever it genuinely is (create_item()'s own real "created"
#    event is already there before this feature is even exercised;
#    the point is that READING history adds nothing further).
async def test_synthetic_entry_writes_no_new_event():
    project = await _make_project("QCH No Side Effect Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    item = await _make_item_with_fields(
        project["id"], site["id"], quantity=15, required_by="2026-09-30T00:00:00+00:00",
        attributed_to="supplier", title="No Side Effect Item")

    before_count = len(await operations_engine.list_events_for_item(item["id"]))

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": item["title"]})
    # Call it twice - if the read itself were persisting anything, a
    # second identical call would show a growing count.
    await intent_service.handle_intent(
        f"what changed on {item['title']}?", user=ADMIN, active_project_id=project["id"])
    await intent_service.handle_intent(
        f"what changed on {item['title']}?", user=ADMIN, active_project_id=project["id"])

    after_count = len(await operations_engine.list_events_for_item(item["id"]))
    assert after_count == before_count


# No fields at all, and genuinely no events either (a directly-
# inserted record, matching test #1's own approach) - the "no
# recorded changes" message remains honest, not a misleading empty
# synthetic entry.
async def test_no_synthetic_entry_when_item_has_no_confirmable_fields():
    project = await _make_project("QCH No Confirmable Fields Project")
    site = await memory_engine.insert_site(project_id=project["id"], name="Site")
    now = datetime.now(timezone.utc).isoformat()
    item_id = f"op_{uuid.uuid4()}"
    await _mock_db.operational_items.insert_one({
        "id": item_id, "category": "general", "title": "Bare Item With Nothing",
        "description": "", "site_id": site["id"], "project_id": project["id"],
        "origin_type": "manual", "origin_reference_id": None, "inherited_evidence_event_id": None,
        "status": "open", "priority": "normal",
        "created_by_user_id": ADMIN["id"], "created_by_user_name": ADMIN["name"],
        "assigned_to_user_id": None, "assigned_to_user_name": None,
        "created_at": now, "required_by": None, "target_start": None,
        "blocker": None, "health": "on_track", "affected_activity_ids": [],
    })

    _mock_structuring({"intents": [{"intent": "query_change_history", "confidence": "high"}],
                        "project_reference": None, "comparison_scope": None,
                        "entity_reference": "Bare Item With Nothing"})
    result = await intent_service.handle_intent(
        "what changed on Bare Item With Nothing?", user=ADMIN, active_project_id=project["id"])
    data = result["result"]["data"]
    assert data["events"] == []
    assert data["message"] == "No recorded changes found for this item."
