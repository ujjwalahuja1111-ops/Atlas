"""AI Business Setup — Step 2 of the locked market-ready sequence.

STEP 2 BOUNDARY (per this sprint's own explicit instruction): understand
and RECOMMEND an operating configuration from a free-text business
description. Do NOT provision accounts, activate engines, or build
navigation here — that is Step 3's own job, consuming the APPROVED
configuration this module persists.

TRACED FIRST (no existing setup system found to reuse or duplicate):
- No "organization"/"business profile"/"business type"/"industry" field
  exists anywhere in the repository (confirmed by search).
- Atlas is effectively single-tenant per deployment: insert_project() has
  no org_id, and memory_engine.register_user()'s own "founding admin"
  rule (the first user on an empty database is auto-approved as
  management) only makes sense if one deployment = one business. This
  module's own configuration document is therefore a SINGLETON, matching
  that existing assumption rather than inventing multi-tenancy.
- Only 4 roles exist today (memory_engine.ROLES): management,
  project_manager, site_supervisor, client. This module recommends a
  subset of these by name; it does not invent new role names.
- CRE (reasoning_engine) and commercial_engine are both always active
  today, gated by nothing - a restaurant project would have construction-
  specific CRE rules evaluated against it right now. This module
  establishes the capability vocabulary Step 3 will eventually use to
  change that; it does not change CRE/commercial activation itself here.
- The existing structured-LLM-call convention (services.intent_service.
  _run_structuring_pass, engines.intelligence_engine._structure) is
  reused exactly: one LlmChat call, system_message carries the schema,
  JSON parsed defensively, total failure returns None rather than a
  guess. No second LLM gateway.

CAPABILITY REGISTRY (Section 5) — the real, traced existing
capabilities, not an invented list. A fixed, small, explicit set; not a
dynamically-discovered engine registry (none exists, and building one is
explicitly out of scope for this step).
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from core.db import db
from core.llm_compat import LlmChat, UserMessage
from core.settings import EMERGENT_LLM_KEY

LLM_MODEL = "gpt-4o"

# ---------------------------------------------------------------- registry

CAPABILITIES: dict[str, str] = {
    "capture": "Voice/photo/text field capture of operational events.",
    "memory": "Projects, sites, users, and the event ledger. Always required.",
    "intelligence": "AI structuring of captures into operational facts.",
    "operational_tracking": "Operational items: requirements, commitments, follow-ups, issues, status lifecycle.",
    "timeline": "Chronological event/evidence timeline per item or activity.",
    "context": "Minimum-sufficient context retrieval (Context Builder) beneath queries.",
    "notifications": "Alerting on operational events.",
    "history": "Change-history queries (what changed, who said it, what's current).",
    "commercial": "Formal contract/milestone/payment-request commercial tracking.",
    "construction_reasoning": "Construction-specific reasoning rules (CRE) - lead times, inspections, readiness.",
    "workflow": "Activity/milestone scheduling and dependency tracking.",
    "verification": "Independent human verification of completion claims, evidence presence.",
    "relationship_linking": "Supersession/duplicate/fulfillment relationships between items.",
}

# Capabilities that are universal infrastructure, never meaningfully
# "optional" or "not required" for ANY business - recommended REQUIRED
# unconditionally, never asked about, never construction-specific.
ALWAYS_REQUIRED = {"capture", "memory", "intelligence", "operational_tracking",
                   "timeline", "context", "notifications", "history"}

# Capabilities that are genuinely domain-specific and must never leak into
# a business description that gives no evidence for them.
CONSTRUCTION_ONLY = {"construction_reasoning"}

VALID_LEVELS = {"required", "optional", "not_required"}
ROLES = {"management", "project_manager", "site_supervisor", "client"}

CONFIG_DOC_ID = "business_config"  # singleton, matches system_state's own pattern


# ------------------------------------------------------------ AI structuring

BUSINESS_SETUP_SYSTEM_PROMPT = f"""You are the Business Setup assistant for Atlas, an operational memory
and intelligence platform used across many kinds of businesses - construction, restaurants, retail/shops,
warehouses, software teams, and others.

The person describes their business in their own words. Your job is to understand how they actually
operate and recommend the smallest sensible Atlas configuration - never to impose one.

CRITICAL RULES:
1. Never invent facts the description does not support. If the business says "we run a restaurant" with
   no further detail, do not assume a number of outlets, a staff count, a delivery model, or a commercial
   need - leave those as configuration_questions instead of guessing.
2. Recommend roles ONLY from this exact set: management, project_manager, site_supervisor, client. Do not
   invent new role names. Only recommend a role the description's own operating model actually supports -
   do not add "client" merely because the business deals with customers; only recommend it when the
   description says an external party needs to use Atlas directly.
3. For capabilities, you MUST use exactly these keys and exactly one of "required" / "optional" /
   "not_required" for each: {", ".join(sorted(CAPABILITIES))}.
4. "construction_reasoning" must be "required" or "optional" ONLY when the description is genuinely about
   a construction/building/contracting business. For every other business (restaurant, retail, software,
   warehouse, etc.) it must be "not_required" - never recommend construction-specific reasoning for a
   non-construction business, even if the business has projects, sites, or physical goods.
5. "commercial" should reflect whether the description mentions payments, invoices, accounts, or billing
   at all. If money/payments were not mentioned, prefer "optional" or "not_required" rather than assuming
   a formal commercial workflow is needed.
6. "client_access_required" is a plain boolean: true only when the description explicitly says an
   external client/customer needs to use Atlas directly (not merely that the business has clients).
7. Ask at most 3 configuration_questions, only for facts that would genuinely change the recommendation
   (e.g. number of locations, whether clients need access) - never a long questionnaire.
8. confidence is "high" only when the description gives enough detail to recommend without guessing;
   otherwise "medium" or "low".
9. explanation is 1-3 plain sentences a business owner would understand, naming what in their own
   description led to the recommendation. Never mention internal engine/table/schema names.

Return ONLY a JSON object with exactly these keys:
- business_profile: {{"industry": string, "business_type": string, "org_size": string or null,
  "location_count": integer or null, "operating_model": string}}
- recommended_roles: list of strings, each one of management/project_manager/site_supervisor/client
- capability_recommendations: object mapping every one of the {len(CAPABILITIES)} capability keys above to
  "required"/"optional"/"not_required"
- client_access_required: boolean
- configuration_questions: list of up to 3 strings
- assumptions: list of strings - anything you treated as true that the description did not state outright
  (keep this list honest; an empty list is correct when you made no assumptions)
- confidence: one of "high"/"medium"/"low"
- explanation: string
"""


def _validate_recommendation(raw: dict) -> Optional[dict]:
    """Defensive validation before ANY AI output is shown to a human or
    persisted (Section 12's own "validated before being shown" rule).
    Returns None on any structural problem - never a partially-trusted
    guess; the caller treats this identically to a total LLM failure."""
    if not isinstance(raw, dict):
        return None
    profile = raw.get("business_profile")
    if not isinstance(profile, dict):
        return None
    roles = raw.get("recommended_roles")
    if not isinstance(roles, list) or not all(r in ROLES for r in roles):
        return None
    caps = raw.get("capability_recommendations")
    if not isinstance(caps, dict):
        return None
    if set(caps.keys()) != set(CAPABILITIES):
        return None
    if not all(v in VALID_LEVELS for v in caps.values()):
        return None
    # Hard safety net, independent of prompt compliance: construction_
    # reasoning can never be forced "required"/"optional" past this
    # function silently - a genuinely construction business legitimately
    # gets "required"/"optional" here too, so this is not a ban, just a
    # structural check that the field exists and holds a valid level
    # (already covered above). The real leakage guard is the dedicated
    # test that exercises a restaurant/software description and asserts
    # "not_required" - validation alone cannot know the business type.
    if not isinstance(raw.get("client_access_required"), bool):
        return None
    questions = raw.get("configuration_questions")
    if not isinstance(questions, list) or len(questions) > 3 or not all(isinstance(q, str) for q in questions):
        return None
    assumptions = raw.get("assumptions")
    if not isinstance(assumptions, list) or not all(isinstance(a, str) for a in assumptions):
        return None
    if raw.get("confidence") not in ("high", "medium", "low"):
        return None
    if not isinstance(raw.get("explanation"), str):
        return None
    return raw


async def generate_recommendation(description: str) -> Optional[dict]:
    """The ONE LLM call this module makes. Total failure isolation,
    matching _run_structuring_pass's own documented behaviour exactly:
    any failure (no key, bad JSON, invalid shape) returns None, never a
    guess. The caller must treat None as "could not analyze" and say so
    plainly, not substitute a default configuration."""
    if not EMERGENT_LLM_KEY:
        return None
    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=str(uuid.uuid4()),
            system_message=BUSINESS_SETUP_SYSTEM_PROMPT,
        ).with_model("openai", LLM_MODEL)
        response = await chat.send_message(UserMessage(text=description + "\n\nReturn JSON only."))
        text = (response if isinstance(response, str) else str(response)).strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip().removesuffix("```").strip()
        raw = json.loads(text)
        return _validate_recommendation(raw)
    except Exception:
        return None


# ------------------------------------------------------------- persistence

async def get_configuration() -> Optional[dict]:
    return await db.business_configuration.find_one({"id": CONFIG_DOC_ID}, {"_id": 0})


async def save_draft_recommendation(*, description: str, recommendation: dict, actor: dict) -> dict:
    """Persists the AI's own recommendation as a DRAFT - never active,
    never consumed by anything else until approve_configuration() below
    is explicitly called by a human. Overwrites any prior draft (a new
    description analysis supersedes the old draft); never overwrites an
    already-approved configuration - re-analysis after approval must go
    through a fresh, explicit call that a route layer can gate, not
    silently here."""
    existing = await get_configuration()
    if existing and existing.get("status") == "approved":
        raise ValueError(
            "A business configuration is already approved. Re-running setup requires "
            "an explicit reset, not a silent overwrite.")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": CONFIG_DOC_ID,
        "status": "draft",
        "raw_description": description,
        "ai_recommendation": recommendation,
        "approved_capabilities": None,
        "approved_roles": None,
        "approved_client_access": None,
        "ai_recommended": True,
        "approved_by_user_id": None,
        "approved_by_user_name": None,
        "approved_at": None,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        "created_by_user_id": actor["id"],
    }
    await db.business_configuration.replace_one({"id": CONFIG_DOC_ID}, doc, upsert=True)
    return doc


async def approve_configuration(*, actor: dict, capability_overrides: Optional[dict] = None,
                                role_overrides: Optional[list[str]] = None,
                                client_access_override: Optional[bool] = None) -> dict:
    """The ONLY function that moves a configuration from draft to
    approved (Section 15's own "human approval" requirement). Human
    review may adjust the AI's own recommendation before approving -
    overrides are validated with the SAME rules the AI output itself
    was validated against, so a human cannot accidentally approve an
    invalid configuration either. Does NOT provision anything - no
    accounts created, no engines activated (Step 3's own job, confirmed
    out of scope here)."""
    existing = await get_configuration()
    if not existing:
        raise ValueError("No business setup recommendation exists yet - analyze a business description first.")
    if existing.get("status") == "approved":
        raise ValueError("This business configuration is already approved.")

    rec = existing["ai_recommendation"]
    capabilities = dict(rec["capability_recommendations"])
    if capability_overrides:
        for key, level in capability_overrides.items():
            if key not in CAPABILITIES:
                raise ValueError(f"Unknown capability '{key}'.")
            if level not in VALID_LEVELS:
                raise ValueError(f"Invalid level '{level}' for capability '{key}'.")
            capabilities[key] = level

    roles = list(role_overrides) if role_overrides is not None else list(rec["recommended_roles"])
    if not all(r in ROLES for r in roles):
        raise ValueError("Roles must be one of: " + ", ".join(sorted(ROLES)))

    client_access = client_access_override if client_access_override is not None else rec["client_access_required"]
    if not isinstance(client_access, bool):
        raise ValueError("client_access must be a boolean.")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    existing["status"] = "approved"
    existing["approved_capabilities"] = capabilities
    existing["approved_roles"] = roles
    existing["approved_client_access"] = client_access
    existing["approved_by_user_id"] = actor["id"]
    existing["approved_by_user_name"] = actor.get("name")
    existing["approved_at"] = now
    existing["updated_at"] = now
    await db.business_configuration.replace_one({"id": CONFIG_DOC_ID}, existing)
    return existing
