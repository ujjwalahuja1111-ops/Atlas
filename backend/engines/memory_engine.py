"""Memory Engine — the only writer to MongoDB.

Enforces immutability on facts:
  - events: insert-only on create; ONLY ai_status / ai_analysis_id may be set later
  - raw_assets: insert-only, never updated
  - corrections: insert-only
  - ai_analyses: one doc per event, written once on finish

Every read excludes Mongo's _id.
"""
from __future__ import annotations
import uuid
import hashlib
import base64
from datetime import datetime, timezone
from typing import Optional, Literal
from core.db import db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4()}" if prefix else str(uuid.uuid4())


async def _insert(collection, doc: dict) -> dict:
    """Insert a copy so Motor's added _id does NOT pollute the returned doc."""
    await collection.insert_one({**doc})
    return doc


# ---------------- users ----------------
async def upsert_user(phone: str, name: str, role: str) -> dict:
    """Login upsert. For a brand-new phone number, creates the account
    with the given role (self-service — the same behaviour Atlas has
    always had for a first-ever login). For an EXISTING account, only
    `name` is updated — `role` is intentionally left untouched.

    Sprint 6 root-cause fix: role used to be overwritten on EVERY login
    with whatever the caller passed. The frontend (roles.ts,
    resolveLoginRole) has no reliable way to know an existing account's
    real role before its first login on a given device/browser, so it
    falls back to a guessed default ("supervisor") for any phone it
    hasn't locally cached a role for yet — including a seeded or
    admin-configured account logging in for the very first time from any
    device. Because this function used to apply that guess
    unconditionally, a correctly-seeded admin/coordinator account was
    silently downgraded to "supervisor" in the database on its first
    ever login — this was the confirmed root cause of "all seeded users
    persist as site_supervisor." Role changes for an existing account
    are — and since Sprint 4.1 already should have been — exclusively an
    admin action via set_user_role(), never a side effect of logging in.
    """
    existing = await db.users.find_one({"phone": phone}, {"_id": 0})
    if existing:
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {"name": name}},
        )
        existing["name"] = name
        return existing
    doc = {
        "id": _new_id(),
        "phone": phone,
        "name": name,
        "role": role,
        "created_at": _now(),
    }
    return await _insert(db.users, doc)


# ---------------- users: Sprint 4.1 registration + admin management ----------------
# `upsert_user` above is used by the existing /api/auth/login. As of Sprint 6
# it updates `name` only for an existing account — `role` is admin-only via
# set_user_role() (see the root-cause fix note on upsert_user itself). A
# brand-new phone is still auto-provisioned as an immediately-usable account,
# exactly as it always has been.
#
# Registration ("Sign Up" on the login screen) is a NEW, separate path with
# different semantics: it only ever creates a brand-new account, and that
# account starts locked out of real access (`approval_status="pending"`)
# until an Administrator explicitly approves it via the User Management
# screen. The two paths never overlap — register_user() refuses to touch an
# existing phone number rather than reusing upsert_user's merge behaviour,
# so "Sign Up" can never silently reactivate or reset someone else's account.
#
# Fields below are all NEW and OPTIONAL on the `users` document. Every read
# site defaults a missing field via `.get(key, <backward-compatible value>)`
# so every account created before this sprint (via plain login) is treated
# as already-approved and active — no migration script needed.
APPROVAL_STATUSES = {"pending", "approved", "rejected"}

# Sprint 4.3 — Identity & Access Foundation.
# `workspace` is the admin-assigned UI experience (client/supervisor/pm/
# admin) — a NEW, EXPLICIT field, distinct from the derived mapping
# frontend/src/roles.ts has always used (DEFAULT_VIEW_ROLE_FOR[role]).
# WORKSPACE_ROLE_MAP is the same conceptual pairing that mapping already
# encodes; a workspace can only be assigned if it's compatible with the
# account's current backend role, so it's never possible to end up with
# (e.g.) workspace="admin" on a non-management account, which would show
# Admin navigation while every admin-gated backend call still 403s.
WORKSPACES = {"client", "supervisor", "pm", "admin"}
WORKSPACE_ROLE_MAP: dict[str, set[str]] = {
    "supervisor": {"supervisor"},
    "coordinator": {"client", "pm"},
    "management": {"admin"},
}


async def register_user(phone: str, name: str, requested_workspace: Optional[str] = None) -> dict:
    """Sign Up. Creates a brand-new, pending, unassigned account. Raises
    ValueError if the phone number already has an account — registration
    is create-only, never a merge (that's what /api/auth/login is for).

    `requested_workspace` (Sprint 4.3 — "User Type" on the Sign Up form)
    is purely informational: it's shown to the Administrator to help them
    decide, but is NEVER auto-applied to the real `workspace` field, which
    starts unset. This is what makes "no workspace until assigned" literally
    true even though Sign Up now collects a workspace preference.

    `scope_projects=True` is what makes "no project access, no site access"
    literally true: list_projects()/list_sites() only apply this
    restriction to accounts with this flag set, so it can be introduced
    without touching any account that existed before this sprint (see
    _is_project_scoped's docstring).
    """
    existing = await db.users.find_one({"phone": phone}, {"_id": 0})
    if existing:
        raise ValueError("An account with this phone number already exists. Please log in instead.")
    if requested_workspace and requested_workspace not in WORKSPACES:
        raise ValueError(f"Invalid requested_workspace '{requested_workspace}'. Must be one of {sorted(WORKSPACES)}")
    doc = {
        "id": _new_id(),
        "phone": phone,
        "name": name,
        "role": "supervisor",  # placeholder only — irrelevant until approved; admin assigns the real role
        "approval_status": "pending",
        "is_active": True,
        "assigned_project_ids": [],
        "workspace": None,
        "requested_workspace": requested_workspace,
        "scope_projects": True,
        "created_at": _now(),
    }
    return await _insert(db.users, doc)


def _backfill_user_defaults(d: dict) -> dict:
    """Single place applying every Sprint 4.1/4.3 backward-compatible
    default, so list_users_admin/get_user can't drift out of sync with
    each other."""
    d.setdefault("approval_status", "approved")
    d.setdefault("is_active", True)
    d.setdefault("assigned_project_ids", [])
    d.setdefault("workspace", None)
    d.setdefault("requested_workspace", None)
    d.setdefault("scope_projects", False)
    return d


async def list_users_admin(approval_status: Optional[str] = None) -> list[dict]:
    q: dict = {}
    if approval_status:
        q["approval_status"] = approval_status
    docs = await db.users.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return [_backfill_user_defaults(d) for d in docs]


async def get_user(user_id: str) -> Optional[dict]:
    d = await db.users.find_one({"id": user_id}, {"_id": 0})
    return _backfill_user_defaults(d) if d else None


async def set_user_approval(user_id: str, approval_status: str) -> Optional[dict]:
    if approval_status not in APPROVAL_STATUSES:
        raise ValueError(f"Invalid approval_status '{approval_status}'. Must be one of {sorted(APPROVAL_STATUSES)}")
    await db.users.update_one({"id": user_id}, {"$set": {"approval_status": approval_status, "updated_at": _now()}})
    return await get_user(user_id)


async def set_user_role(user_id: str, role: str) -> Optional[dict]:
    upd = {"role": role, "updated_at": _now()}
    # Sprint 4.3: if the currently-stored workspace is no longer valid for
    # the new role (e.g. role changed away from management while
    # workspace="admin"), clear it rather than leave an inconsistent
    # combination in place — the admin must explicitly re-assign a
    # compatible workspace. Cheaper and safer than trying to guess a new one.
    current = await get_user(user_id)
    if current and current.get("workspace") and current["workspace"] not in WORKSPACE_ROLE_MAP.get(role, set()):
        upd["workspace"] = None
    await db.users.update_one({"id": user_id}, {"$set": upd})
    return await get_user(user_id)


async def set_user_workspace(user_id: str, workspace: str) -> Optional[dict]:
    """Admin-assigns the UI workspace (Sprint 4.3). Validated against the
    account's CURRENT role via WORKSPACE_ROLE_MAP — assign role first if
    the desired workspace isn't yet compatible."""
    if workspace not in WORKSPACES:
        raise ValueError(f"Invalid workspace '{workspace}'. Must be one of {sorted(WORKSPACES)}")
    current = await get_user(user_id)
    if not current:
        return None
    role = current.get("role")
    if workspace not in WORKSPACE_ROLE_MAP.get(role, set()):
        raise ValueError(
            f"Workspace '{workspace}' is not compatible with role '{role}'. "
            f"Compatible workspaces for this role: {sorted(WORKSPACE_ROLE_MAP.get(role, set()))}"
        )
    await db.users.update_one({"id": user_id}, {"$set": {"workspace": workspace, "updated_at": _now()}})
    return await get_user(user_id)


async def set_user_projects(user_id: str, project_ids: list[str]) -> Optional[dict]:
    await db.users.update_one({"id": user_id}, {"$set": {"assigned_project_ids": project_ids, "updated_at": _now()}})
    return await get_user(user_id)


async def set_user_active(user_id: str, is_active: bool) -> Optional[dict]:
    await db.users.update_one({"id": user_id}, {"$set": {"is_active": is_active, "updated_at": _now()}})
    return await get_user(user_id)


async def update_own_name(user_id: str, name: str) -> Optional[dict]:
    """Self-service name edit (Sprint 4.1 stabilization fix — audit M4: the
    old flow's only way to fix a typo'd name was re-logging in, which also
    silently re-applies whatever role was passed to /auth/login. This is a
    narrow, self-only update — no role/approval/project fields touched."""
    await db.users.update_one({"id": user_id}, {"$set": {"name": name, "updated_at": _now()}})
    return await get_user(user_id)


# ---------------- projects + sites ----------------
def _is_project_scoped(user: dict) -> bool:
    """True if this user's project/site visibility should be limited to
    their assigned_project_ids (Sprint 4.3 — Identity & Access Foundation).

    Admin (management role) is always unrestricted — "Admin has
    unrestricted access" is unconditional, independent of any stored flag.

    Every account that predates this feature has no `scope_projects` field
    at all and defaults to False (unrestricted) — a deliberate migration
    safeguard, not an oversight: retroactively scoping existing accounts
    would break Sprint 1-4.2 capture/timeline/ops workflows for every
    current user, none of whom have ever had project assignment as a
    concept. Only accounts created via register_user() from this sprint
    onward are scoped by default (see register_user below).
    """
    if user.get("role") == "management":
        return False
    return bool(user.get("scope_projects", False))


async def list_projects(include_archived: bool = False, *, user: Optional[dict] = None) -> list[dict]:
    q: dict = {} if include_archived else {"archived_at": None}
    if user and _is_project_scoped(user):
        q["id"] = {"$in": user.get("assigned_project_ids", [])}
    return await db.projects.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


async def get_project(project_id: str) -> Optional[dict]:
    return await db.projects.find_one({"id": project_id}, {"_id": 0})


async def update_project(project_id: str, *, name: Optional[str] = None,
                         code: Optional[str] = None,
                         location: Optional[str] = None,
                         image_url: Optional[str] = None) -> Optional[dict]:
    upd: dict = {}
    if name is not None:
        upd["name"] = name
    if code is not None:
        upd["code"] = code
    if location is not None:
        upd["location"] = location
    if image_url is not None:
        upd["image_url"] = image_url
    if not upd:
        return await get_project(project_id)
    upd["updated_at"] = _now()
    await db.projects.update_one({"id": project_id}, {"$set": upd})
    return await get_project(project_id)


async def archive_project(project_id: str) -> Optional[dict]:
    await db.projects.update_one(
        {"id": project_id},
        {"$set": {"archived_at": _now()}},
    )
    return await get_project(project_id)


async def unarchive_project(project_id: str) -> Optional[dict]:
    await db.projects.update_one(
        {"id": project_id},
        {"$set": {"archived_at": None}},
    )
    return await get_project(project_id)


async def project_reference_counts(project_id: str) -> dict:
    """Counts of dependent records — used to decide if a project can be
    hard-deleted. Mirrors site_reference_counts(): a project's only direct
    dependents are its sites (which themselves guard their own deletion
    against events/operational_items/ai_proposals), so a project is safe to
    delete only when it has zero sites left, archived or not — an archived
    site is still dependent data that must not be silently orphaned by
    deleting its parent project.
    """
    return {
        "sites": await db.sites.count_documents({"project_id": project_id}),
    }


async def delete_project(project_id: str) -> bool:
    """Hard delete a project. Caller MUST check project_reference_counts() first."""
    r = await db.projects.delete_one({"id": project_id})
    return r.deleted_count > 0


async def list_sites(project_id: Optional[str] = None,
                     include_archived: bool = False, *, user: Optional[dict] = None) -> list[dict]:
    q: dict = {"project_id": project_id} if project_id else {}
    if not include_archived:
        q["archived_at"] = None
    if user and _is_project_scoped(user):
        allowed = set(user.get("assigned_project_ids", []))
        if project_id:
            # Asked for a specific project's sites but not assigned to it —
            # same effect as the project not existing for this caller.
            if project_id not in allowed:
                return []
        else:
            q["project_id"] = {"$in": list(allowed)}
    return await db.sites.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


async def get_site(site_id: str) -> Optional[dict]:
    return await db.sites.find_one({"id": site_id}, {"_id": 0})


async def insert_project(name: str, code: str, location: str = "", image_url: str = "") -> dict:
    doc = {
        "id": _new_id("prj_"),
        "name": name,
        "code": code,
        "location": location,
        "image_url": image_url,
        "created_at": _now(),
    }
    return await _insert(db.projects, doc)


async def insert_site(project_id: str, name: str, location: str = "", image_url: str = "") -> dict:
    doc = {
        "id": _new_id("site_"),
        "project_id": project_id,
        "name": name,
        "location": location,
        "image_url": image_url,
        "created_at": _now(),
    }
    return await _insert(db.sites, doc)


async def update_site(site_id: str, *, name: Optional[str] = None,
                      location: Optional[str] = None,
                      image_url: Optional[str] = None) -> Optional[dict]:
    upd: dict = {}
    if name is not None:
        upd["name"] = name
    if location is not None:
        upd["location"] = location
    if image_url is not None:
        upd["image_url"] = image_url
    if not upd:
        return await get_site(site_id)
    upd["updated_at"] = _now()
    await db.sites.update_one({"id": site_id}, {"$set": upd})
    return await get_site(site_id)


async def archive_site(site_id: str) -> Optional[dict]:
    await db.sites.update_one({"id": site_id}, {"$set": {"archived_at": _now()}})
    return await get_site(site_id)


async def unarchive_site(site_id: str) -> Optional[dict]:
    await db.sites.update_one({"id": site_id}, {"$set": {"archived_at": None}})
    return await get_site(site_id)


async def site_reference_counts(site_id: str) -> dict:
    """Counts of dependent records — used to decide if a site can be hard-deleted."""
    return {
        "events": await db.events.count_documents({"site_id": site_id}),
        "operational_items": await db.operational_items.count_documents({"site_id": site_id}),
        "ai_proposals": await db.ai_proposals.count_documents({"site_id": site_id}),
    }


async def delete_site(site_id: str) -> bool:
    """Hard delete a site. Caller MUST check site_reference_counts() first."""
    r = await db.sites.delete_one({"id": site_id})
    return r.deleted_count > 0


# ---------------- raw_assets ----------------
async def put_asset(
    event_id: str,
    kind: Literal["audio", "photo"],
    mime: str,
    raw_bytes: bytes,
) -> dict:
    b64 = base64.b64encode(raw_bytes).decode()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    doc = {
        "id": _new_id("ast_"),
        "event_id": event_id,
        "kind": kind,
        "mime": mime,
        "size_bytes": len(raw_bytes),
        "data_base64": b64,
        "sha256": sha,
        "created_at": _now(),
    }
    await _insert(db.raw_assets, doc)
    # we return a slim ref (without huge data_base64)
    return {k: v for k, v in doc.items() if k != "data_base64"}


async def get_asset(asset_id: str) -> Optional[dict]:
    return await db.raw_assets.find_one({"id": asset_id}, {"_id": 0})


async def get_assets_for_event(event_id: str, kind: Optional[str] = None) -> list[dict]:
    q: dict = {"event_id": event_id}
    if kind:
        q["kind"] = kind
    return await db.raw_assets.find(q, {"_id": 0}).to_list(50)


async def asset_thumb(asset_id: str) -> Optional[str]:
    """Return base64 string for a photo asset (used inline in timeline)."""
    doc = await db.raw_assets.find_one({"id": asset_id, "kind": "photo"}, {"_id": 0, "data_base64": 1})
    return doc.get("data_base64") if doc else None


# ---------------- events ----------------
async def insert_event(doc: dict) -> dict:
    """Insert an immutable event fact. doc must already contain id + server_created_at."""
    return await _insert(db.events, doc)


async def set_event_ai_status(event_id: str, status: str, ai_analysis_id: Optional[str] = None) -> None:
    """The ONLY mutating operation allowed on an event document.

    Lifecycle marker only — does not touch any factual field.
    """
    update: dict = {"ai_status": status}
    if ai_analysis_id is not None:
        update["ai_analysis_id"] = ai_analysis_id
    await db.events.update_one({"id": event_id}, {"$set": update})


async def set_event_proposals_status(event_id: str, status: str,
                                     error: Optional[str] = None) -> None:
    """V3.1 lifecycle marker — does not touch any factual field."""
    upd: dict = {"proposals_status": status}
    if error is not None:
        upd["proposals_error"] = error
    else:
        upd["proposals_error"] = None
    await db.events.update_one({"id": event_id}, {"$set": upd})


async def get_event(event_id: str) -> Optional[dict]:
    return await db.events.find_one({"id": event_id}, {"_id": 0})


async def list_events_for_site(site_id: str, limit: int = 200) -> list[dict]:
    return (
        await db.events.find({"site_id": site_id}, {"_id": 0})
        .sort("server_created_at", -1)
        .to_list(limit)
    )


async def list_events_by_status(status: str, limit: int = 100) -> list[dict]:
    return await db.events.find({"ai_status": status}, {"_id": 0}).to_list(limit)


# ---------------- ai_analyses ----------------
async def put_ai_analysis(doc: dict) -> dict:
    return await _insert(db.ai_analyses, doc)


async def get_ai_analysis(event_id: str) -> Optional[dict]:
    return await db.ai_analyses.find_one({"event_id": event_id}, {"_id": 0})


async def get_ai_analyses(event_ids: list[str]) -> dict[str, dict]:
    docs = await db.ai_analyses.find({"event_id": {"$in": event_ids}}, {"_id": 0}).to_list(500)
    return {d["event_id"]: d for d in docs}


# ---------------- corrections ----------------
async def insert_correction(original_event_id: str, corrected_by: dict, payload: dict) -> dict:
    doc = {
        "id": _new_id("cor_"),
        "original_event_id": original_event_id,
        "corrected_by_user_id": corrected_by["id"],
        "corrected_by_user_name": corrected_by["name"],
        "payload": payload,
        "created_at": _now(),
    }
    return await _insert(db.corrections, doc)


async def list_corrections_for_events(event_ids: list[str]) -> dict[str, list[dict]]:
    docs = (
        await db.corrections.find({"original_event_id": {"$in": event_ids}}, {"_id": 0})
        .sort("created_at", 1)
        .to_list(500)
    )
    out: dict[str, list[dict]] = {}
    for d in docs:
        out.setdefault(d["original_event_id"], []).append(d)
    return out


# ---------------- prompt_versions ----------------
async def get_or_create_prompt_version(name: str, version: str, model: str, system_prompt: str, notes: str) -> dict:
    existing = await db.prompt_versions.find_one({"name": name, "version": version}, {"_id": 0})
    if existing:
        return existing
    doc = {
        "id": _new_id("pv_"),
        "name": name,
        "version": version,
        "model": model,
        "system_prompt": system_prompt,
        "notes": notes,
        "created_at": _now(),
    }
    return await _insert(db.prompt_versions, doc)
