"""Auth routes."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal, Optional
from core.auth import create_token, get_current_user
from engines import memory_engine

router = APIRouter(prefix="/api", tags=["auth"])

Role = Literal["supervisor", "coordinator", "management"]
Workspace = Literal["client", "supervisor", "pm", "admin"]


def _clean_phone(raw: str) -> str:
    """Sprint 4.1 fix (audit M5): basic format validation, not just length.
    Strips spaces/dashes/parens, requires an optional leading '+' followed
    by 6-15 digits. Deliberately lenient (no country-specific rules) since
    phone is a free-text identity key across regions, not a login secret.

    Sprint 6.2 Founder Verification fix: this used to VALIDATE against a
    fully-stripped `digits` string (spaces/dashes/parens AND a leading '+'
    all removed) but RETURN a less-stripped value that kept the '+' if the
    caller typed one. Two logins with the exact same phone number - one
    typed as "9876543210", the other as "+919876543210" - normalized to
    two DIFFERENT stored strings, so the second login silently created a
    brand-new account instead of matching the existing one. From the
    outside this looked exactly like "logging in overwrote my identity" -
    it didn't; a second account was created and the person was looking at
    it instead of their real one. Returning the same fully-stripped
    `digits` value used for validation makes every formatting variant of
    the same digit sequence collapse to one canonical stored key.
    """
    phone = raw.strip()
    digits = phone.lstrip("+").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or not (6 <= len(digits) <= 15):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    return digits


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
    # Sprint 4.3 — "User Type" on the Sign Up form. Purely informational
    # (shown to the Administrator to help them decide); never auto-applied
    # to the real, admin-controlled `workspace` field. See memory_engine.
    # register_user's docstring for why this doesn't contradict "no
    # workspace until assigned."
    requested_workspace: Optional[Workspace] = None


@router.post("/auth/register")
async def register(req: RegisterRequest):
    """Sign Up (Sprint 4.1, extended Sprint 4.3). Creates a NEW, pending,
    unassigned account — distinct from /auth/login's upsert-on-first-use
    behaviour. The person still gets a token back (so the app can identify
    them and show a Pending Approval screen with their name), but they have
    no role, workspace, or project access worth anything until an
    Administrator approves them via the User Management screen. See
    memory_engine.register_user for the full rationale.
    """
    phone = _clean_phone(req.phone)
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    try:
        user = await memory_engine.register_user(
            phone=phone, name=req.name.strip(), requested_workspace=req.requested_workspace,
        )
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
