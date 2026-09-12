"""Atlas Intent & Orchestration — Phase 1 + Phase D (Multi-Intent Synthesis).

Phase 1 implemented docs/ATLAS_INTENT_ORCHESTRATION_SPEC.md Items 1-11, 30:
one AI structuring pass, deterministic intent->engine dispatch,
read-only orchestration only.

Phase D removes the single-intent ceiling identified in the Construction
Intelligence Review: the SAME one structuring call now returns an
ORDERED LIST of up to 3 relevant intents instead of exactly one. Every
existing handler is completely unchanged; only the dispatch loop and a
small, deterministic composition step are new. A single selected
intent produces the exact same response shape Phase 1 always has
(Section 4's own explicit backward-compatibility requirement) — the
new "multi_result" shape only appears when 2+ intents are genuinely
selected.

Phase D explicitly does NOT implement: an engine capability registry,
cross-engine evidence/conflict reasoning, global confidence
aggregation, sentence-level provenance, or any new AI call beyond the
one structuring pass that already existed — per this phase's own
scope, and per the Construction Intelligence Review's own explicit
recommendation not to build those yet.

Phase 1 explicitly does NOT implement: voice (Item 3), write actions,
draft entities (Item 13), or persistent conversation memory beyond a
single clarification round (Item 19/22) — per this phase's own scope,
unaffected by Phase D.

The structuring call reuses the exact LLM-call pattern already
established in engines/intelligence_engine.py's own _structure() and
engines/reasoning_engine.py's own _ai_review() — same client, same
total-failure-isolation discipline (any exception -> unresolved,
never a guess), not a new pattern.
"""
from __future__ import annotations
import json
import logging
import uuid
from typing import Optional

from core.llm_compat import LlmChat, UserMessage
from core.settings import EMERGENT_LLM_KEY
from engines import memory_engine, reasoning_engine

logger = logging.getLogger(__name__)

LLM_MODEL = "gpt-4o"

# Item 4 — the closed intent taxonomy for Phase 1. Only the five intents
# named in this phase's own scope; every other intent in the full spec's
# taxonomy is deliberately absent here, not silently supported.
SUPPORTED_INTENTS = (
    "query_health", "query_digest", "query_schedule_impact",
    "query_comparison", "unresolved",
)

# Phase D — the maximum number of intents a single question can select.
# A plain, named constant (Section 3/6 of the Phase D brief), not a
# magic number buried in a conditional.
MAX_INTENTS = 3

# Item 8 — confidence floor: below this, treated as unresolved (Item 4)
# rather than acted on. Set to "medium" so only "low" confidence is
# rejected — "medium" and "high" both proceed. (A floor of "low" would
# be mathematically unreachable, since nothing sorts below the lowest
# value; this was caught by test_low_confidence_is_treated_as_unresolved
# actually failing, not assumed correct from the code alone.)
CONFIDENCE_FLOOR = "medium"
_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

# User-facing labels for each intent, used only in the multi-result
# composition lead-in (Section 9) — never exposes an engine or route
# name, per Section 11's own explicit instruction.
INTENT_LABEL = {
    "query_health": "health",
    "query_schedule_impact": "schedule",
    "query_comparison": "comparison",
    "query_digest": "recent activity",
}

INTENT_SYSTEM_PROMPT = """You are Atlas's intent-structuring pass for a construction \
management platform. Given a user's free-text request, select the RELEVANT intents \
from this list — select only what's genuinely relevant, up to 3, ordered by relevance:

- query_health: asking why a project is at risk, or about its overall health/status
- query_digest: asking what's happening today/recently across their projects
- query_schedule_impact: asking whether something affects the schedule/handover/a date
- query_comparison: asking to compare this project against other projects
- unresolved: the request does not clearly match any of the above, or is a write/\
action request (creating, changing, or approving something) — Phase 1 supports \
READ-ONLY QUERIES ONLY, so any request to create, change, approve, or take an action \
must be classified unresolved.

Rules for selecting intents:
- A simple, single-topic question (e.g. "what's the project health?") should select \
exactly ONE intent.
- A genuinely broad question (e.g. "what should I be worried about?", "what could \
affect handover?") may select 2-3 intents if more than one is truly relevant — but \
do NOT select extra intents just to fill the list. Select only what the question \
actually asks about.
- If nothing is sufficiently understood, or the request needs an action Phase 1 \
doesn't support, select only "unresolved" and nothing else.
- Never select "unresolved" alongside another intent.

Return JSON only, in exactly this shape:
{
  "intents": [
    {"intent": "<one of the four query intents, or 'unresolved' alone>", "confidence": "high" | "medium" | "low"}
  ],
  "project_reference": "<any project name/identifier literally mentioned, or null>",
  "comparison_scope": "<for query_comparison only: what kind of projects to compare \
against, e.g. 'residential', or null>",
  "reasoning": "<one short sentence explaining the selection>"
}
Do not include any text outside the JSON object."""


class IntentServiceError(Exception):
    pass


async def _run_structuring_pass(user_input: str) -> Optional[dict]:
    """The ONE LLM call (Item 4/7/8/9 combined into a single pass, per
    the spec's own explicit 'one structured interpretation' principle).

    Total failure isolation, matching reasoning_engine._ai_review()'s
    own documented behaviour exactly: any failure returns None, never
    a guess. The caller treats None identically to an 'unresolved'
    classification (Item 17 - fail safely, do not guess).
    """
    if not EMERGENT_LLM_KEY:
        return None
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=str(uuid.uuid4()),
            system_message=INTENT_SYSTEM_PROMPT,
        ).with_model("openai", LLM_MODEL)
        response = await chat.send_message(UserMessage(text=user_input + "\n\nReturn JSON only."))
        text = (response if isinstance(response, str) else str(response)).strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip().removesuffix("```").strip()
        raw = json.loads(text)
        if not isinstance(raw, dict):
            return None
        return raw
    except Exception:
        logger.exception("Intent structuring pass failed; treating as unresolved")
        return None


async def _resolve_project(structured: dict, user: dict, active_project_id: Optional[str]) -> dict:
    """Item 5/6 — Context Resolution, in the exact priority order the
    spec defines: (1) explicit mention in the input, (2) the existing
    getActiveSite() context passed in from the frontend, (3) most
    recent activity. Returns a dict describing the outcome rather than
    a bare project_id, so the caller can distinguish a clean resolution
    from an ambiguous one requiring a clarifying question (Item 22).
    """
    visible_projects = await memory_engine.list_projects(user=user)
    if not visible_projects:
        return {"status": "none_visible"}

    mention = (structured.get("project_reference") or "").strip().lower()
    if mention:
        matches = [p for p in visible_projects if mention in p["name"].lower()]
        if len(matches) == 1:
            return {"status": "resolved", "project": matches[0], "resolved_from": "explicit"}
        if len(matches) > 1:
            return {"status": "ambiguous", "candidates": matches}
        # Named but no match at all — do not silently fall through to
        # active project, since that would answer about the wrong
        # project. Ask, per Item 5's own "ask rather than guess" rule.
        return {"status": "not_found", "mention": structured.get("project_reference")}

    if active_project_id:
        active = next((p for p in visible_projects if p["id"] == active_project_id), None)
        if active:
            return {"status": "resolved", "project": active, "resolved_from": "active_context"}

    if len(visible_projects) == 1:
        return {"status": "resolved", "project": visible_projects[0], "resolved_from": "only_project"}

    return {"status": "ambiguous", "candidates": visible_projects}


# ---------------------------------------------------------------------------
# Item 10 — deterministic intent -> engine dispatch. Plain function
# lookup, no AI involved in this step, matching the spec's own explicit
# "plain dict lookup, no AI" description of this layer.
#
# P0 FIX — a real, serious RBAC leak found by live testing: these
# handlers call reasoning_engine.explain_health / project_lookahead_view
# / compare_projects directly, bypassing the _forbid_client(user) check
# that lives in the HTTP route layer (routes/reasoning.py) for these
# exact same functions. A Client user could get a real 200 with full
# health/schedule/comparison data through the intent API, while the
# equivalent direct route correctly returns 403 for the identical
# request - confirmed live before this fix, confirmed fixed after it.
# The check is replicated here rather than imported from routes/ (a
# services module should not depend on a routes module).
# ---------------------------------------------------------------------------

async def _handle_query_health(project: dict, user: dict) -> dict:
    if user.get("role") == "client":
        return {"ok": False, "error": "That level of project detail isn't available on your account — "
                                       "try asking about progress or what's happening instead."}
    try:
        result = await reasoning_engine.explain_health(project["id"], user=user)
        return {"ok": True, "data": result}
    except reasoning_engine.ReasoningError as e:
        return {"ok": False, "error": str(e)}


async def _handle_query_schedule_impact(project: dict, user: dict) -> dict:
    if user.get("role") == "client":
        return {"ok": False, "error": "That level of schedule detail isn't available on your account — "
                                       "try asking about progress or what's next instead."}
    try:
        result = await reasoning_engine.project_lookahead_view(project["id"], user=user)
        return {"ok": True, "data": result}
    except reasoning_engine.ReasoningError as e:
        return {"ok": False, "error": str(e)}


async def _handle_query_comparison(project: dict, user: dict, structured: dict) -> dict:
    if user.get("role") == "client":
        return {"ok": False, "error": "Comparing projects isn't available on your account — "
                                       "try asking about your own project's progress instead."}
    scope = (structured.get("comparison_scope") or "").strip()
    if scope:
        # Item 28/Flow 8 — named gap, not silently guessed: project
        # "type" is not structured, queryable data in Atlas today
        # (confirmed: memory_engine.insert_project has no type field).
        # Rather than guess which projects count as e.g. "residential",
        # say so plainly.
        return {
            "ok": False,
            "error": (
                f"I can't reliably tell which of your projects are '{scope}' yet — "
                "project type isn't consistently recorded. Try naming specific "
                "projects to compare instead."
            ),
        }
    try:
        all_projects = await memory_engine.list_projects(user=user)
        other_ids = [p["id"] for p in all_projects if p["id"] != project["id"]][:5]
        if not other_ids:
            return {"ok": False, "error": "You don't have any other projects to compare against yet."}
        result = await reasoning_engine.compare_projects([project["id"]] + other_ids, user=user)
        return {"ok": True, "data": result}
    except reasoning_engine.ReasoningError as e:
        return {"ok": False, "error": str(e)}


async def _handle_query_digest(user: dict) -> dict:
    """Portfolio-wide by nature (Item 11/Flow 10) — does not require a
    resolved project at all, matching the spec's own Flow 10."""
    from services import inbox_intelligence_service
    from engines import operations_engine
    results: dict = {}
    errors: list[str] = []
    # Item 17 — isolate each engine failure independently rather than
    # letting one failure blank the entire digest, matching the exact
    # pattern already established in event_intelligence_service.py.
    try:
        results["coordination"] = await inbox_intelligence_service.daily_coordination_digest(user)
    except Exception:
        logger.exception("query_digest: coordination digest failed")
        errors.append("coordination digest unavailable")
    # my_day() is Client-restricted at its own route (routes/operational_items.py's
    # own _forbid_client(user, "view My Day")) — confirmed, not assumed;
    # daily_coordination_digest and management_attention_digest have no
    # such restriction on their own real routes, so only this one
    # source is skipped for Client, not the whole digest.
    if user.get("role") != "client":
        try:
            results["my_day"] = await operations_engine.my_day(user=user)
        except Exception:
            logger.exception("query_digest: my_day failed")
            errors.append("today's task summary unavailable")
    if user.get("role") == "management":
        try:
            results["management_attention"] = await inbox_intelligence_service.management_attention_digest(user)
        except Exception:
            logger.exception("query_digest: management digest failed")
            errors.append("management attention digest unavailable")
    if not results:
        return {"ok": False, "error": "Could not retrieve today's summary right now."}
    return {"ok": True, "data": results, "partial_errors": errors or None}


PROJECT_SCOPED_INTENTS = {"query_health", "query_schedule_impact", "query_comparison"}


async def handle_intent(user_input: str, *, user: dict, active_project_id: Optional[str] = None,
                        confirmed_project_id: Optional[str] = None) -> dict:
    """The single entry point. Returns one of four response shapes:
      - {"type": "result", "intent": ..., "result": ...}                     (exactly 1 intent selected — unchanged from Phase 1)
      - {"type": "multi_result", "lead_in": ..., "sections": [...]}           (Phase D — 2-3 intents selected)
      - {"type": "clarification_needed", "question": ..., "candidates": [...]}
      - {"type": "unresolved", "message": ...}
    Never raises for a bad/ambiguous input — only for a genuine
    programming error, matching Item 17's fail-safely principle.

    confirmed_project_id (Item 22 — the one-round clarification
    completing) is the caller's own answer to a just-asked "which
    project?" question. When set, it bypasses the normal three-source
    resolution entirely — re-running resolution against the same
    original text would simply hit the same ambiguous mention again,
    since explicit mention takes priority over active_project_id in
    _resolve_project's own ordering. Still subject to the same RBAC
    visibility check every other path goes through.
    """
    if not user_input or not user_input.strip():
        return {"type": "unresolved", "message": "I didn't catch a question — try asking something like "
                                                   "\"why is this project at risk?\""}

    try:
        structured = await _run_structuring_pass(user_input.strip())
    except Exception:
        logger.exception("Intent structuring pass raised unexpectedly; treating as unresolved")
        structured = None
    if structured is None:
        return {"type": "unresolved", "message": "I couldn't understand that clearly. Try rephrasing, "
                                                   "or ask a specific question about a project."}

    # Phase D shape validation — the structured pass now returns an
    # ORDERED LIST of up to MAX_INTENTS candidate intents instead of
    # one. Validated here, not inside _run_structuring_pass, so it
    # always applies to whatever that function returns — whether from
    # a real LLM call or a test mock (same discipline Phase 1 already
    # established for the single-intent shape).
    raw_intents = structured.get("intents")
    if not isinstance(raw_intents, list) or not raw_intents:
        return {"type": "unresolved", "message": "I couldn't understand that clearly. Try rephrasing, "
                                                   "or ask a specific question about a project."}

    selected: list[dict] = []
    seen: set[str] = set()
    explicit_unresolved = False
    for item in raw_intents:
        if not isinstance(item, dict):
            continue
        candidate_intent = item.get("intent")
        candidate_confidence = item.get("confidence")
        if candidate_intent not in SUPPORTED_INTENTS or candidate_confidence not in _CONFIDENCE_ORDER:
            continue
        if candidate_intent == "unresolved":
            explicit_unresolved = True
            continue  # never mixed with real intents; handled below
        if _CONFIDENCE_ORDER[candidate_confidence] < _CONFIDENCE_ORDER[CONFIDENCE_FLOOR]:
            continue  # Item 8's own floor, applied per-intent — truth beats completeness (Section 15)
        if candidate_intent in seen:
            continue  # test case E — deduplicated, not rejected
        seen.add(candidate_intent)
        selected.append({"intent": candidate_intent, "confidence": candidate_confidence})
        if len(selected) >= MAX_INTENTS:
            break  # test case F — bounded to MAX_INTENTS, extras silently ignored

    if not selected:
        if explicit_unresolved:
            # Preserves Phase 1's own original, more accurate message —
            # the model understood the request and correctly identified
            # it as unsupported, which is a different situation from
            # "nothing survived confidence/validity filtering" below.
            return {"type": "unresolved", "message": "That's not something I can help with yet — "
                                                       "I can currently answer questions about project health, "
                                                       "schedule impact, comparisons, and daily summaries."}
        return {"type": "unresolved", "message": "I'm not confident I understood that correctly. "
                                                   "Could you rephrase your question, or ask a specific "
                                                   "question about a project?"}

    # Project resolution runs ONCE, shared across every selected
    # intent that needs it (Section 5) — never once per intent.
    project = None
    needs_project = any(s["intent"] in PROJECT_SCOPED_INTENTS for s in selected)
    if needs_project:
        if confirmed_project_id:
            visible_projects = await memory_engine.list_projects(user=user)
            confirmed = next((p for p in visible_projects if p["id"] == confirmed_project_id), None)
            resolution = {"status": "resolved", "project": confirmed} if confirmed else {"status": "not_found", "mention": "the selected project"}
        else:
            resolution = await _resolve_project(structured, user, active_project_id)

        if resolution["status"] == "none_visible":
            return {"type": "unresolved", "message": "You don't have any projects yet."}
        if resolution["status"] == "not_found":
            return {"type": "unresolved",
                    "message": f"I couldn't find a project matching \"{resolution['mention']}\"."}
        if resolution["status"] == "ambiguous":
            return {
                "type": "clarification_needed",
                "question": "Which project did you mean?",
                "candidates": [{"id": p["id"], "name": p["name"]} for p in resolution["candidates"][:8]],
            }
        project = resolution["project"]

    # Dispatch every selected intent to its own existing, unchanged
    # handler (Section 6) — RBAC stays inside each handler exactly as
    # in Phase 1 (Section 7's own explicit "never perform authorization
    # only once at the top"), and each handler's own failure is
    # isolated from the others (Section 8), matching the pattern
    # query_digest already established for its own multiple sources.
    sections: list[dict] = []
    for s in selected:
        try:
            outcome = await _dispatch_one(s["intent"], structured, user, project)
        except Exception:
            logger.exception(f"Phase D: handler for intent '{s['intent']}' raised unexpectedly")
            outcome = {"ok": False, "error": "This part of the answer wasn't available right now."}
        section = {"intent": s["intent"], "result": outcome}
        if project and s["intent"] in PROJECT_SCOPED_INTENTS:
            section["project"] = {"id": project["id"], "name": project["name"]}
        sections.append(section)

    # Backward compatibility (Section 4) — exactly one intent selected
    # produces the EXACT SAME shape Phase 1 has always returned, not a
    # single-item list wrapped in the new shape.
    if len(sections) == 1:
        only = sections[0]
        result = {"type": "result", "intent": only["intent"], "result": only["result"]}
        if "project" in only:
            result["project"] = only["project"]
        return result

    # Phase D — 2+ intents selected. A small, deterministic composition
    # (Section 9): a plain, template-composed lead-in naming what was
    # checked in user-facing language (never an engine/route name, per
    # Section 11), and the individual, unmodified section results for
    # the frontend to render — no LLM-written summary paragraph.
    labels = [INTENT_LABEL.get(s["intent"], s["intent"]) for s in sections]
    lead_in = "Here's what matters" + (f" — checked {', '.join(labels[:-1])} and {labels[-1]}" if len(labels) > 1 else f" — checked {labels[0]}") + "."
    return {"type": "multi_result", "lead_in": lead_in, "sections": sections}


async def _dispatch_one(intent: str, structured: dict, user: dict, project: Optional[dict]) -> dict:
    """Section 6 — the one place that routes a single selected intent
    to its own existing, completely unmodified handler. Not a new
    engine, not new business logic — a plain lookup, same discipline
    Phase 1 already used for its own single-intent dispatch."""
    if intent == "query_digest":
        return await _handle_query_digest(user)
    if intent == "query_health":
        return await _handle_query_health(project, user)
    if intent == "query_schedule_impact":
        return await _handle_query_schedule_impact(project, user)
    if intent == "query_comparison":
        return await _handle_query_comparison(project, user, structured)
    return {"ok": False, "error": "That's not something I can help with yet."}
