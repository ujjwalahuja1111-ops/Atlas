"""JWT auth helpers."""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Header, HTTPException
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
