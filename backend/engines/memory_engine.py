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
    existing = await db.users.find_one({"phone": phone}, {"_id": 0})
    if existing:
        await db.users.update_one(
            {"id": existing["id"]},
            {"$set": {"name": name, "role": role}},
        )
        existing["name"] = name
        existing["role"] = role
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
# `upsert_user` above (used by the existing /api/auth/login) is UNCHANGED and
# keeps its exact pre-Sprint-4.1 behaviour: an existing account's role/name
# are updated on every login, a brand-new phone is auto-provisioned as an
# immediately-usable account. That preserves every Sprint 1-4 login flow and
# test credential verbatim.
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


async def register_user(phone: str, name: str) -> dict:
    """Sign Up. Creates a brand-new, pending, unassigned account. Raises
    ValueError if the phone number already has an account — registration
    is create-only, never a merge (that's what /api/auth/login is for).
    """
    existing = await db.users.find_one({"phone": phone}, {"_id": 0})
    if existing:
        raise ValueError("An account with this phone number already exists. Please log in instead.")
    doc = {
        "id": _new_id(),
        "phone": phone,
        "name": name,
        "role": "supervisor",  # placeholder only — irrelevant until approved; admin assigns the real role
        "approval_status": "pending",
        "is_active": True,
        "assigned_project_ids": [],
        "created_at": _now(),
    }
    return await _insert(db.users, doc)


async def list_users_admin(approval_status: Optional[str] = None) -> list[dict]:
    q: dict = {}
    if approval_status:
        q["approval_status"] = approval_status
    docs = await db.users.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    # Backfill defaults for pre-Sprint-4.1 accounts so the admin UI always
    # sees a consistent shape without needing a migration.
    for d in docs:
        d.setdefault("approval_status", "approved")
        d.setdefault("is_active", True)
        d.setdefault("assigned_project_ids", [])
    return docs


async def get_user(user_id: str) -> Optional[dict]:
    d = await db.users.find_one({"id": user_id}, {"_id": 0})
    if d:
        d.setdefault("approval_status", "approved")
        d.setdefault("is_active", True)
        d.setdefault("assigned_project_ids", [])
    return d


async def set_user_approval(user_id: str, approval_status: str) -> Optional[dict]:
    if approval_status not in APPROVAL_STATUSES:
        raise ValueError(f"Invalid approval_status '{approval_status}'. Must be one of {sorted(APPROVAL_STATUSES)}")
    await db.users.update_one({"id": user_id}, {"$set": {"approval_status": approval_status, "updated_at": _now()}})
    return await get_user(user_id)


async def set_user_role(user_id: str, role: str) -> Optional[dict]:
    await db.users.update_one({"id": user_id}, {"$set": {"role": role, "updated_at": _now()}})
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
async def list_projects(include_archived: bool = False) -> list[dict]:
    q: dict = {} if include_archived else {"archived_at": None}
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
                     include_archived: bool = False) -> list[dict]:
    q: dict = {"project_id": project_id} if project_id else {}
    if not include_archived:
        q["archived_at"] = None
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
