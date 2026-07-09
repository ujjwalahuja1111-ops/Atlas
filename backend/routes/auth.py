"""Auth routes."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal
from core.auth import create_token, get_current_user
from engines import memory_engine

router = APIRouter(prefix="/api", tags=["auth"])

Role = Literal["supervisor", "coordinator", "management"]


def _clean_phone(raw: str) -> str:
    """Sprint 4.1 fix (audit M5): basic format validation, not just length.
    Strips spaces/dashes/parens, requires an optional leading '+' followed
    by 6-15 digits. Deliberately lenient (no country-specific rules) since
    phone is a free-text identity key across regions, not a login secret.
    """
    phone = raw.strip()
    digits = phone.lstrip("+").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or not (6 <= len(digits) <= 15):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    return phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")


class LoginRequest(BaseModel):
    phone: str
    name: str
    role: Role = "supervisor"


@router.post("/auth/login")
async def login(req: LoginRequest):
    phone = _clean_phone(req.phone)
    user = await memory_engine.upsert_user(phone=phone, name=req.name.strip() or "Site User", role=req.role)
    return {"token": create_token(user["id"]), "user": user}


class RegisterRequest(BaseModel):
    phone: str
    name: str


@router.post("/auth/register")
async def register(req: RegisterRequest):
    """Sign Up (Sprint 4.1). Creates a NEW, pending, unassigned account —
    distinct from /auth/login's upsert-on-first-use behaviour. The person
    still gets a token back (so the app can identify them and show a
    Pending Approval screen with their name), but they have no role
    assignment or project access worth anything until an Administrator
    approves them via the User Management screen. See memory_engine.
    register_user for the full rationale.
    """
    phone = _clean_phone(req.phone)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        user = await memory_engine.register_user(phone=phone, name=req.name.strip())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"token": create_token(user["id"]), "user": user}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


class UpdateMeRequest(BaseModel):
    name: str


@router.patch("/me")
async def update_me(req: UpdateMeRequest, user: dict = Depends(get_current_user)):
    """Self-service name edit (Sprint 4.1, audit M4). Deliberately narrow —
    only the caller's own name, nothing else. Role/approval/project
    assignment stay Administrator-only via /api/admin/users."""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    updated = await memory_engine.update_own_name(user["id"], req.name.strip())
    return updated
