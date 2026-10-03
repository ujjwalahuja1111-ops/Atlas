"""JWT auth helpers."""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Depends, Header, HTTPException
import jwt
from .settings import JWT_SECRET
from .db import db


def create_token(user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


async def _decode_and_load_user(authorization: Optional[str]) -> dict:
    """Shared by both dependencies below: decode the JWT, look up the
    user, and enforce the one check that's an absolute, no-exceptions
    block regardless of endpoint — a deactivated account. Approval
    status is intentionally NOT checked here; the two dependencies below
    each decide that differently.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # Sprint 4.1 — User Management foundation. Existing users predate these
    # fields entirely; .get(..., True) treats a MISSING is_active as active,
    # so every pre-Sprint-4.1 account keeps working with zero migration.
    # Deactivation is a hard, unbypassable block — unlike pending/rejected
    # (see get_current_user below), there is no legitimate reason a
    # deactivated account should reach ANY endpoint, including its own /me.
    if user.get("is_active", True) is False:
        raise HTTPException(status_code=401, detail="Account deactivated")
    return user


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Strict — the dependency every protected endpoint uses except
    GET /api/me (see get_current_user_any_status below).

    FAC-03 P0 fix: previously this only checked is_active, leaving
    approval_status entirely unenforced at the API layer — a pending or
    rejected account got a perfectly valid token from /auth/login (or,
    before this same fix, from /auth/register) and could call ANY
    endpoint successfully; the only thing standing between them and the
    full app was the frontend choosing not to navigate them into it. A
    pending user hitting the API directly (curl, Postman, a modified
    client) had complete, unrestricted access matching whatever role/
    workspace their account carried. "The frontend won't show them the
    button" was never real access control.
    """
    user = await _decode_and_load_user(authorization)
    status = user.get("approval_status", "approved")
    if status == "pending":
        raise HTTPException(status_code=403, detail="Account pending approval")
    if status == "rejected":
        raise HTTPException(status_code=403, detail="Account access denied")
    return user


async def require_commercial_capability(user: dict = Depends(get_current_user)) -> dict:
    """AI Engine / Role Configuration (Step 3) — Section 11's own explicit
    requirement: "the commercial engine should NOT become globally active
    simply because it exists." Applied at the ROUTER level in server.py
    (dependencies=[...] on app.include_router for the commercial routers),
    not per-route - commercial.py/commercial_workflow.py have 32 route
    handlers combined; a single, additive router-level dependency gates
    all of them without touching any individual route function, the
    smallest safe way to add this check.

    Fails OPEN (allows the request through) when no business
    configuration has been approved yet - an existing installation that
    predates Step 2/3 entirely (Section 20's own "do not blindly reset
    existing databases" / "do not destroy... commercial records") must
    keep working exactly as it always has. Once a configuration IS
    approved, this becomes the real, enforced gate: a business whose
    approved_capabilities marks "commercial" as "not_required" gets a
    403 on every commercial route, not merely a hidden navigation item -
    Section 19's own "backend authorization must remain authoritative."
    """
    from engines import business_setup_engine as bse
    cfg = await bse.get_configuration()
    if not cfg or cfg.get("status") != "approved":
        return user  # no approved configuration yet - fail open, see docstring
    if cfg["approved_capabilities"].get("commercial") == "not_required":
        raise HTTPException(status_code=403, detail=(
            "Commercial functionality is not part of this business's approved configuration."))
    return user


async def require_construction_reasoning_capability(user: dict = Depends(get_current_user)) -> dict:
    """Step 3 hardening — the same pattern as require_commercial_
    capability above, applied PER-ROUTE rather than at the router level:
    routes/reasoning.py mixes construction-CRE-derived routes with
    commercial-reference, client-facing, and genuinely universal ones
    (confirmed by reading each handler's own underlying engine call, not
    guessed from the router/file name) - a single router-level gate
    would incorrectly block universal functionality (e.g. portfolio
    search includes operational_items, which every business needs).

    Same fail-open discipline as the commercial gate: no approved
    configuration yet -> allow through, preserving existing installations'
    behaviour exactly.
    """
    from engines import business_setup_engine as bse
    cfg = await bse.get_configuration()
    if not cfg or cfg.get("status") != "approved":
        return user
    if cfg["approved_capabilities"].get("construction_reasoning") == "not_required":
        raise HTTPException(status_code=403, detail=(
            "Construction reasoning is not part of this business's approved configuration."))
    return user


async def get_current_user_any_status(authorization: Optional[str] = Header(None)) -> dict:
    """Lenient — used ONLY by GET /api/me. A pending or rejected account
    must still be able to check its OWN current status; that is exactly
    the mechanism the Pending Approval screen's "Check Again" button
    depends on (it polls GET /api/me and expects a 200 even while
    pending). Deliberately does not check approval_status at all — only
    the same hard is_active block every other endpoint enforces.
    Nothing else — no project, event, or operational data — is reachable
    through this dependency; it returns only the caller's own user
    document.
    """
    return await _decode_and_load_user(authorization)
