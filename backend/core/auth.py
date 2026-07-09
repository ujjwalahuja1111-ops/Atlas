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


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
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
    # Deactivation is the one status that must be a hard, unbypassable block
    # (unlike "pending approval", which is enforced by the frontend not
    # routing a pending user into the app shell — see ADR for rationale).
    if user.get("is_active", True) is False:
        raise HTTPException(status_code=401, detail="Account deactivated")
    return user
