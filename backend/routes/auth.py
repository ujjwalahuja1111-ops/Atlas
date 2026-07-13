"""Auth routes."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Literal, Optional
from core.auth import create_token, get_current_user, get_current_user_any_status
from engines import memory_engine

router = APIRouter(prefix="/api", tags=["auth"])

Role = Literal["management", "project_manager", "site_supervisor", "client"]
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
    role: Role = "site_supervisor"


@router.post("/auth/login")
async def login(req: LoginRequest):
    """Pure authentication. FAC-03 P0 fix: this used to upsert — silently
    CREATING a brand-new account for any never-before-seen phone number
    and logging that invented identity straight into a working session,
    using whatever role the request happened to carry (default
    "supervisor"). Any string of 6-15 digits — a typo, an unregistered
    number, "90000001" — was therefore a valid login: it passed format
    validation, found no existing account, and upsert_user() created one
    on the spot. That is a real authentication bypass, not a UX nicety.

    Login now ONLY authenticates an EXISTING account, looked up by phone
    and nothing else. An unrecognized phone is rejected outright (401) —
    it is never a signal to create anything. Creating a new account is
    exclusively /auth/register's job (Sign Up), which correctly starts
    every new account `approval_status="pending"`, locked out of real
    access until an Administrator approves it — self-service login-time
    account creation bypassed that gate entirely, which was the other
    half of the problem: even a deliberately-invented phone number
    landed directly in a fully-functional Site Supervisor session, no
    approval step in sight.

    A pending or rejected account still authenticates here (still gets a
    token) — core/auth.py's get_current_user is what blocks it from
    every real endpoint except GET /api/me, which is what the Pending
    Approval screen's own status check depends on to ever resolve.
    """
    phone = _clean_phone(req.phone)
    user = await memory_engine.get_user_by_phone(phone)
    if not user:
        raise HTTPException(status_code=401, detail="No account found for this phone number. Please sign up first.")
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
async def me(user: dict = Depends(get_current_user_any_status)):
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
