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
import pytest
from unittest.mock import AsyncMock

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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert result["intent"] == "query_health"
    assert result["result"]["ok"] is True


async def test_query_schedule_impact_intent_dispatches_to_lookahead():
    project = await _make_project("Intent Schedule Project")
    _mock_structuring({"intent": "query_schedule_impact", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "does this affect handover?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert result["intent"] == "query_schedule_impact"
    assert result["result"]["ok"] is True


async def test_query_comparison_intent_dispatches_to_compare_projects():
    p1 = await _make_project("Intent Compare Project One")
    await _make_project("Intent Compare Project Two")
    _mock_structuring({"intent": "query_comparison", "confidence": "high",
                        "project_reference": "Intent Compare Project One", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "compare this project with my other one", user=ADMIN, active_project_id=None)
    assert result["type"] == "result"
    assert result["intent"] == "query_comparison"
    assert result["result"]["ok"] is True


async def test_query_digest_intent_is_portfolio_wide_no_project_needed():
    _mock_structuring({"intent": "query_digest", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what's happening on my projects today?", user=ADMIN, active_project_id=None)
    assert result["type"] == "result"
    assert result["intent"] == "query_digest"
    assert result["result"]["ok"] is True
    assert "coordination" in result["result"]["data"] or "my_day" in result["result"]["data"]


async def test_unresolved_intent_from_llm_returns_unresolved_message():
    _mock_structuring({"intent": "unresolved", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
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
    _mock_structuring({"intent": "query_comparison", "confidence": "high",
                        "project_reference": None, "comparison_scope": "residential"})
    result = await intent_service.handle_intent(
        "compare with our other residential projects", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"
    assert result["result"]["ok"] is False
    assert "project type isn't consistently recorded" in result["result"]["error"]


async def test_project_reference_entity_resolves_explicit_project():
    await _make_project("Sharma Residence")
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": "Sharma Residence", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Sharma Residence at risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "result"
    assert result["project"]["name"] == "Sharma Residence"


# ==========================================================================
# Confidence handling
# ==========================================================================
async def test_low_confidence_is_treated_as_unresolved():
    _mock_structuring({"intent": "query_health", "confidence": "low",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "hmm maybe something about risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


async def test_medium_confidence_still_proceeds():
    project = await _make_project("Intent Medium Confidence Project")
    _mock_structuring({"intent": "query_health", "confidence": "medium",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "is this project okay?", user=ADMIN, active_project_id=project["id"])
    assert result["type"] == "result"


# ==========================================================================
# Unresolved input (LLM classifies as unresolved AND malformed/unusable output)
# ==========================================================================
async def test_malformed_llm_output_missing_intent_field_is_unresolved():
    _mock_structuring({"confidence": "high"})  # no "intent" key at all
    result = await intent_service.handle_intent(
        "gibberish that produces bad json", user=ADMIN, active_project_id=None)
    assert result["type"] == "unresolved"


async def test_llm_output_with_unsupported_intent_value_is_unresolved():
    _mock_structuring({"intent": "create_project", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": "Intent Explicitly Named Project", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Intent Explicitly Named Project at risk?",
        user=ADMIN, active_project_id=active_project["id"])
    assert result["type"] == "result"
    assert result["project"]["id"] == named_project["id"]


async def test_mentioned_project_not_found_asks_rather_than_falls_back():
    active_project = await _make_project("Intent Fallback Candidate")
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": "Totally Nonexistent Project Name XYZ", "comparison_scope": None})
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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": "Ambiguous Villa", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is Ambiguous Villa at risk?", user=ADMIN, active_project_id=None)
    assert result["type"] == "clarification_needed"
    assert len(result["candidates"]) == 2


async def test_no_context_and_multiple_projects_asks_for_clarification():
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": "Confirm Round Trip Villa", "comparison_scope": None})
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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": "Intent RBAC Unassigned Project", "comparison_scope": None})
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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
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
    _mock_structuring({"intent": "query_digest", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
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
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["type"] == "result"  # not a hard failure - a clear, honest refusal
    assert result["result"]["ok"] is False
    assert "available on your account" in result["result"]["error"].lower()


async def test_query_schedule_impact_forbidden_for_client():
    project = await _make_project("Client RBAC Schedule Project")
    _mock_structuring({"intent": "query_schedule_impact", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "does this affect handover?", user=CLIENT_USER, active_project_id=project["id"])
    assert result["result"]["ok"] is False
    assert "available on your account" in result["result"]["error"].lower()


async def test_query_comparison_forbidden_for_client():
    await _make_project("Client RBAC Alpha Project")
    await _make_project("Client RBAC Beta Project")
    _mock_structuring({"intent": "query_comparison", "confidence": "high",
                        "project_reference": "Client RBAC Alpha Project", "comparison_scope": None})
    result = await intent_service.handle_intent(
        "compare with my other project", user=CLIENT_USER, active_project_id=None)
    assert result["result"]["ok"] is False
    assert "available on your account" in result["result"]["error"].lower()


async def test_query_digest_omits_my_day_for_client_but_keeps_coordination():
    _mock_structuring({"intent": "query_digest", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "what do I need to know today?", user=CLIENT_USER, active_project_id=None)
    assert result["type"] == "result"
    assert result["result"]["ok"] is True
    assert "my_day" not in result["result"]["data"]
    assert "coordination" in result["result"]["data"]


async def test_query_health_still_works_normally_for_non_client_roles():
    """The fix must not affect any role it wasn't meant to restrict."""
    project = await _make_project("Non Client RBAC Project")
    _mock_structuring({"intent": "query_health", "confidence": "high",
                        "project_reference": None, "comparison_scope": None})
    result = await intent_service.handle_intent(
        "why is this at risk?", user=ADMIN, active_project_id=project["id"])
    assert result["result"]["ok"] is True
