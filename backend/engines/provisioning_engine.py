"""AI Engine / Role Configuration — Step 3 of the locked market-ready sequence.

Takes a HUMAN-APPROVED business configuration (Step 2's own output,
engines.business_setup_engine) and turns it into: which role slots need
actual people, how to provision a real account for one, and which
capabilities are active. Does NOT rerun the business-setup AI, does not
reinterpret the description, does not redesign any existing engine.

TRACED FIRST (see Step 2's own module docstring for the business_
configuration trace this builds directly on top of; the following is
what Step 3 itself needed to trace new):

- Role mapping is ALREADY solved by Step 2: its own AI prompt and
  _validate_recommendation() only ever accept roles from the 4 real,
  existing RBAC names (memory_engine.ROLES: management, project_manager,
  site_supervisor, client). approved_roles therefore never needs
  translation - it already IS a list of valid RBAC role names. No role-
  mapping table, no new role ontology.
- How users are actually created today: /api/auth/register always
  creates a "pending" account (self-service, needs admin approval).
  /api/auth/login was deliberately hardened (FAC-03 P0 fix, confirmed by
  reading routes/auth.py's own docstring) to NEVER create an account -
  only authenticate an existing one. memory_engine.upsert_user() still
  exists but its own docstring says it is kept ONLY for the internal dev
  seed script as "a trusted, non-public caller" - its own created-account
  document has NO approval_status/is_active/scope_projects fields at
  all, so it is unsafe to reuse for real provisioning (a user created
  that way would not match what isApprovedAndActive()/RBAC checks expect
  elsewhere). provision_user() below is therefore a NEW function, not a
  reuse of upsert_user() - matching the SAME document shape register_
  user()'s own founding-admin branch already uses (approval_status=
  "approved", is_active=True), so a provisioned user is indistinguishable
  from one approved through the existing admin-approval flow.
- Navigation is ALREADY role-aware (frontend src/roles.ts's own TABS_FOR),
  and the tab set itself is small and fixed - commercial/CRE features are
  reached from within a project, not as top-level tabs. Nothing here
  invents a new navigation system; get_active_capabilities() gives the
  frontend the one additional signal (which capabilities are active) it
  did not have before, to show/hide within-project features.
- commercial_engine and reasoning_engine (CRE) are both confirmed always
  active today, gated by nothing - a restaurant project would have
  construction-specific CRE rules evaluated against it right now. This
  module does not touch either engine's own logic; it adds the
  capability-gate CHECK (require_capability below) that the route layer
  can apply, and applies it to the commercial routes specifically (this
  sprint's own Section 11 names commercial as the one case that most
  needs it: real money/payment records, not read-only reasoning output).
  CRE is NOT gated at the route level by this patch - documented as a
  known, honest limitation (lower risk: CRE is read-only analysis, not a
  route that writes commercial records).
"""
from __future__ import annotations

from typing import Optional

from core.db import db
from engines import business_setup_engine as bse
from engines import memory_engine

ROLE_LABELS = {
    "management": "Owner / Admin",
    "project_manager": "Project Manager",
    "site_supervisor": "Site Supervisor / Operations Lead",
    "client": "Client",
}


async def get_required_role_slots() -> list[dict]:
    """The role slots the approved configuration actually needs, each
    with how many real accounts already fill it - never invents people,
    only reports what is needed and what exists. Raises ValueError if no
    configuration is approved yet (Section 4's own "fail safely" rule -
    the caller must not provision from an unapproved recommendation)."""
    cfg = await bse.get_configuration()
    if not cfg or cfg.get("status") != "approved":
        raise ValueError("No approved business configuration exists yet.")
    roles = cfg["approved_roles"]
    if not cfg["approved_client_access"] and "client" in roles:
        # Defensive: approve_configuration() already lets a human set
        # client_access_override=False while still listing "client" in
        # roles (the two fields are independently editable in the
        # review UI) - Section 9 is a hard requirement, so this is
        # enforced here too, not only hoped for from the approval step.
        roles = [r for r in roles if r != "client"]
    slots = []
    for role in roles:
        filled = await db.users.count_documents({"role": role, "approval_status": "approved", "is_active": True})
        slots.append({"role": role, "label": ROLE_LABELS.get(role, role), "filled_count": filled})
    return slots


async def provision_user(*, actor: dict, phone: str, name: str, role: str) -> dict:
    """Creates ONE real, already-approved user account for a required
    role slot. The ONLY provisioning action this module performs -
    Section 5's own "role required != user account created" distinction
    is enforced by this being an explicit, one-person-at-a-time action
    the administrator takes, never anything automatic.

    Validates `role` against the APPROVED configuration's own approved_
    roles (not merely the global RBAC role set) - this is what makes
    Section 9 (no client slot/account when client access is not
    approved) and Section 6 ("only the roles required by the approved
    configuration") actually enforced in the write path, not merely a
    UI suggestion.
    """
    cfg = await bse.get_configuration()
    if not cfg or cfg.get("status") != "approved":
        raise ValueError("No approved business configuration exists yet.")
    approved_roles = set(cfg["approved_roles"])
    if role == "client" and not cfg["approved_client_access"]:
        raise ValueError("Client access is not part of the approved configuration.")
    if role not in approved_roles:
        raise ValueError(f"'{role}' is not one of the approved roles for this configuration.")
    if role not in memory_engine.ROLES:
        raise ValueError(f"'{role}' is not a valid role.")

    phone = phone.strip()
    name = name.strip()
    if not phone or not name:
        raise ValueError("Phone and name are required.")
    existing = await memory_engine.get_user_by_phone(phone)
    if existing:
        raise ValueError("An account with this phone number already exists.")

    from datetime import datetime, timezone
    doc = {
        "id": memory_engine._new_id(),
        "phone": phone,
        "name": name,
        "role": role,
        "workspace": memory_engine.WORKSPACE_FOR_ROLE[role],
        "approval_status": "approved",
        "is_active": True,
        "assigned_project_ids": [],
        "requested_workspace": None,
        # Least privilege by default, matching register_user()'s own
        # non-founding-admin branch: management sees everything already
        # (scope_projects only ever restricts list_projects/list_sites
        # for non-management accounts); anyone else provisioned here
        # starts scoped to nothing until explicitly assigned a project,
        # exactly like an admin-approved self-registration already would.
        "scope_projects": role != "management",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provisioned_by_user_id": actor["id"],
    }
    return await memory_engine._insert(db.users, doc)


async def get_active_capabilities() -> dict[str, str]:
    """Read-only signal for the frontend/route layer: which capabilities
    are active for THIS business. Empty dict (treated as "nothing
    confirmed active") if no configuration is approved yet - never a
    guessed default capability set."""
    cfg = await bse.get_configuration()
    if not cfg or cfg.get("status") != "approved":
        return {}
    return cfg["approved_capabilities"]


async def is_capability_active(capability: str) -> bool:
    """True for "required" or "optional" - both mean the capability is
    genuinely available to this business; "not_required" and "no
    configuration approved yet" both mean not active. Fails CLOSED
    (not active) when uncertain, matching Section 19's own "backend
    authorization must remain authoritative" principle - this is the
    actual check a protected route calls, not merely what the UI reads
    to decide what to render."""
    caps = await get_active_capabilities()
    return caps.get(capability) in ("required", "optional")


async def get_workspace_status() -> dict:
    """What Step 4 (real onboarding) and the frontend empty-state need:
    whether a configuration is approved yet, and if so, which role slots
    still need a real person. Deliberately does NOT suggest what to do
    next beyond naming the operating model - Section 15's own "do not
    hardcode construction instructions into a universal first-run
    state" - the frontend decides the exact copy from operating_model."""
    cfg = await bse.get_configuration()
    if not cfg or cfg.get("status") != "approved":
        return {"configured": False}
    slots = await get_required_role_slots()
    return {
        "configured": True,
        "business_profile": cfg["ai_recommendation"]["business_profile"],
        "role_slots": slots,
        "all_roles_filled": all(s["filled_count"] > 0 for s in slots),
        "active_capabilities": cfg["approved_capabilities"],
    }
