"""Knowledge Engine — Engine 6 (Sprint 4: Construction Knowledge Core).

Activates the slot reserved in ARCHITECTURE.md / PRD.md ("Knowledge — reserved
— Construction Ontology"). This is deliberately an *architecture* sprint: it
introduces reusable master-data objects that future engines (Scheduling,
BOQ, Baseline, Project Generation, AI Recommendations — none of which are
built here) will read from. No AI behaviour, no scheduling, no project
assignment lives in this module — only clean, versioned, searchable master
definitions and generic extension points for later engines to hang off.

Design (mirrors existing Atlas conventions):
- ONE collection `knowledge_items`, discriminated by `type`:
    category | phase | activity | checklist_template | required_document
  A single collection avoids duplicating near-identical CRUD/search/archive/
  versioning logic five times (ADR precedent: operational_items is one
  collection covering 11 categories, not 11 collections).
- Soft-archive via `archived_at`, exactly like projects/sites (ADR: no new
  archive paradigm).
- Versioning via immutable snapshots in `knowledge_versions`, mirroring the
  `corrections` pattern (ADR-004/012: facts are never overwritten in place;
  history is a linked, append-only record). The live document always holds
  current state + an incrementing `version` int for cheap reads.
- Relationships are a GENERIC, typed edge list embedded on the item:
    relationships: [{id, type, target_id, metadata, created_at}]
  V1 only *populates* `depends_on` (Activity Dependencies, per sprint scope),
  but the shape is intentionally generic so future sprints can add
  `precedes`, `requires`, `references`, `uses`, `inspected_by`,
  `linked_document`, `linked_material`, `linked_equipment` etc. WITHOUT any
  schema change. No graph traversal / cycle detection is implemented in V1
  (explicitly out of scope — this is a data shape, not a scheduling engine).
- Lifecycle `status` (draft | active | deprecated | archived) is tracked
  ALONGSIDE `archived_at`, not instead of it. `archived_at` remains the
  soft-archive timestamp that drives default list visibility (unchanged
  mechanic, matches projects/sites). `status` is the richer editorial state:
  new items default to `draft` so future consumers (e.g. Project Generation)
  can list only `active` items without seeing work-in-progress definitions.
  `archive_item`/`unarchive_item` keep both fields in sync (archive sets
  status="archived"; unarchive resets it to "active") so there is a single
  place — not two independent toggles — that owns the "is this archived"
  question.
- `applicability` is a deliberately unshaped, freeform dict reserved for
  future project-generation filtering (project types, building types,
  construction types, regions, ...). V1 stores and returns it verbatim; NO
  filtering logic reads it yet. Modelled as an open dict rather than
  hardcoded fields so new applicability axes never require a schema change.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional, Iterable
from core.db import db

# ----- vocab -----
TYPES = {"category", "phase", "activity", "checklist_template", "required_document"}

# Lifecycle status. "archived" is intentionally NOT settable via the generic
# update path — it only ever gets set (in lockstep with archived_at) by
# archive_item(), and cleared by unarchive_item(). This keeps one owner for
# "is this archived" instead of two independently-mutable signals.
STATUSES = {"draft", "active", "deprecated", "archived"}
SETTABLE_STATUSES = {"draft", "active", "deprecated"}

# Curated for UI dropdowns / documentation. NOT strictly enforced server-side
# (see _validate_relationship_type) so future engines can introduce new edge
# types without a migration — extensibility over completeness, per brief.
KNOWN_RELATIONSHIP_TYPES = {
    "depends_on", "precedes", "requires", "references",
    "uses", "inspected_by", "linked_document", "linked_material", "linked_equipment",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "kn_") -> str:
    return f"{prefix}{uuid.uuid4()}"


def _validate_type(type_: str) -> None:
    if type_ not in TYPES:
        raise ValueError(f"Unknown knowledge item type '{type_}'. Must be one of {sorted(TYPES)}")


def _validate_status(status: str) -> None:
    if status not in SETTABLE_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of {sorted(SETTABLE_STATUSES)} "
            f"('archived' is set via the archive/unarchive endpoints, not directly)."
        )


async def _get_raw(item_id: str) -> Optional[dict]:
    return await db.knowledge_items.find_one({"id": item_id}, {"_id": 0})


async def _assert_exists(item_id: str, *, expected_type: Optional[str] = None) -> dict:
    doc = await _get_raw(item_id)
    if not doc:
        raise ValueError(f"Referenced knowledge item '{item_id}' does not exist")
    if expected_type and doc["type"] != expected_type:
        raise ValueError(f"'{item_id}' is a {doc['type']}, expected {expected_type}")
    return doc


# ---------------- create ----------------
async def create_item(
    *, actor: dict, type_: str, name: str,
    description: str = "", code: str = "",
    category_id: Optional[str] = None,
    phase_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    ai_keywords: Optional[list[str]] = None,
    default_duration_days: Optional[float] = None,
    checklist_items: Optional[list[dict]] = None,
    document_kind: Optional[str] = None,
    status: str = "draft",
    applicability: Optional[dict] = None,
) -> dict:
    _validate_type(type_)
    _validate_status(status)
    if not name or not name.strip():
        raise ValueError("name is required")
    if category_id:
        await _assert_exists(category_id, expected_type="category")
    if phase_id:
        await _assert_exists(phase_id, expected_type="phase")

    now = _now()
    doc = {
        "id": _new_id(),
        "type": type_,
        "name": name.strip(),
        "description": description or "",
        "code": code or "",
        "category_id": category_id,
        "phase_id": phase_id,
        "tags": list(tags or []),
        "ai_keywords": list(ai_keywords or []),
        "default_duration_days": default_duration_days,
        "checklist_items": checklist_items or [],  # only meaningful for checklist_template
        "document_kind": document_kind,            # only meaningful for required_document
        "relationships": [],                        # generic typed edges — see module docstring
        "status": status,                            # draft | active | deprecated (archived via archive_item)
        "applicability": applicability or {},        # reserved, freeform — see module docstring
        "version": 1,
        "archived_at": None,
        "created_by_user_id": actor["id"],
        "created_by_user_name": actor["name"],
        "updated_by_user_id": actor["id"],
        "updated_by_user_name": actor["name"],
        "created_at": now,
        "updated_at": now,
    }
    await db.knowledge_items.insert_one({**doc})
    return doc


# ---------------- read / list / search ----------------
async def get_item(item_id: str) -> Optional[dict]:
    return await _get_raw(item_id)


async def list_items(
    *, type_: Optional[str] = None,
    category_id: Optional[str] = None,
    phase_id: Optional[str] = None,
    tag: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    include_archived: bool = False,
    limit: int = 500,
) -> list[dict]:
    query: dict = {}
    if type_:
        _validate_type(type_)
        query["type"] = type_
    if category_id:
        query["category_id"] = category_id
    if phase_id:
        query["phase_id"] = phase_id
    if tag:
        query["tags"] = tag
    if status:
        if status not in STATUSES:
            raise ValueError(f"Invalid status filter '{status}'. Must be one of {sorted(STATUSES)}")
        query["status"] = status
    if not include_archived:
        query["archived_at"] = None
    if q:
        # Lightweight case-insensitive search across name/description/tags/
        # ai_keywords/code. No $text index needed at V1 scale — keep it simple.
        pattern = {"$regex": q.strip(), "$options": "i"}
        query["$or"] = [
            {"name": pattern}, {"description": pattern},
            {"code": pattern}, {"tags": pattern}, {"ai_keywords": pattern},
        ]
    return (
        await db.knowledge_items.find(query, {"_id": 0})
        .sort("name", 1)
        .to_list(limit)
    )


async def resolve_names(ids: Iterable[str]) -> dict[str, str]:
    """Batch id -> name lookup, used to label relationships / category / phase refs."""
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    docs = await db.knowledge_items.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "type": 1}).to_list(len(ids))
    return {d["id"]: d["name"] for d in docs}


async def enrich(item: dict) -> dict:
    """Attach human-readable labels for category/phase/relationship targets.

    Read-only convenience for the frontend; does not mutate stored data.
    """
    ref_ids = [item.get("category_id"), item.get("phase_id")]
    ref_ids += [r["target_id"] for r in item.get("relationships", [])]
    names = await resolve_names(ref_ids)
    out = {**item}
    out["category_name"] = names.get(item.get("category_id"))
    out["phase_name"] = names.get(item.get("phase_id"))
    out["relationships"] = [
        {**r, "target_name": names.get(r["target_id"])}
        for r in item.get("relationships", [])
    ]
    return out


# ---------------- versioning ----------------
async def _snapshot_before_update(item: dict, actor: dict) -> None:
    """Immutable pre-edit snapshot, mirroring the `corrections` ADR pattern:
    facts are never overwritten in place; history is a linked append-only
    record. Stored once per edit, keyed by the version it superseded.
    """
    snap = {
        "id": _new_id("knv_"),
        "item_id": item["id"],
        "item_type": item["type"],
        "version": item["version"],
        "snapshot": item,
        "changed_by_user_id": actor["id"],
        "changed_by_user_name": actor["name"],
        "created_at": _now(),
    }
    await db.knowledge_versions.insert_one({**snap})


async def list_versions(item_id: str) -> list[dict]:
    return (
        await db.knowledge_versions.find({"item_id": item_id}, {"_id": 0})
        .sort("version", -1)
        .to_list(200)
    )


# ---------------- update ----------------
UPDATABLE_FIELDS = {
    "name", "description", "code", "category_id", "phase_id", "tags",
    "ai_keywords", "default_duration_days", "checklist_items", "document_kind",
    "status", "applicability",
}


async def update_item(item_id: str, *, actor: dict, updates: dict) -> dict:
    item = await _assert_exists(item_id)
    upd = {k: v for k, v in updates.items() if k in UPDATABLE_FIELDS and v is not None}
    if not upd:
        return item
    if "name" in upd and not upd["name"].strip():
        raise ValueError("name cannot be empty")
    if "status" in upd:
        _validate_status(upd["status"])
    if "category_id" in upd and upd["category_id"]:
        await _assert_exists(upd["category_id"], expected_type="category")
    if "phase_id" in upd and upd["phase_id"]:
        await _assert_exists(upd["phase_id"], expected_type="phase")

    await _snapshot_before_update(item, actor)
    upd["version"] = item["version"] + 1
    upd["updated_at"] = _now()
    upd["updated_by_user_id"] = actor["id"]
    upd["updated_by_user_name"] = actor["name"]
    await db.knowledge_items.update_one({"id": item_id}, {"$set": upd})
    return await _get_raw(item_id)


# ---------------- archive / restore ----------------
async def archive_item(item_id: str, *, actor: dict) -> dict:
    item = await _assert_exists(item_id)
    if item.get("archived_at"):
        return item
    await db.knowledge_items.update_one(
        {"id": item_id},
        {"$set": {"archived_at": _now(), "status": "archived",
                  "updated_by_user_id": actor["id"],
                  "updated_by_user_name": actor["name"], "updated_at": _now()}},
    )
    return await _get_raw(item_id)


async def unarchive_item(item_id: str, *, actor: dict) -> dict:
    item = await _assert_exists(item_id)
    if not item.get("archived_at"):
        return item
    await db.knowledge_items.update_one(
        {"id": item_id},
        {"$set": {"archived_at": None, "status": "active",
                  "updated_by_user_id": actor["id"],
                  "updated_by_user_name": actor["name"], "updated_at": _now()}},
    )
    return await _get_raw(item_id)


# ---------------- relationships (generic, typed edges) ----------------
def _validate_relationship_type(type_: str) -> None:
    if not type_ or not type_.strip():
        raise ValueError("relationship type is required")
    # Intentionally NOT restricted to KNOWN_RELATIONSHIP_TYPES: future engines
    # (Scheduling, Workflow, Learning) must be able to introduce new edge
    # kinds without touching this module. KNOWN_RELATIONSHIP_TYPES is only
    # the curated set surfaced in the UI dropdown.


async def add_relationship(
    item_id: str, *, actor: dict, type_: str, target_id: str, metadata: Optional[dict] = None,
) -> dict:
    _validate_relationship_type(type_)
    item = await _assert_exists(item_id)
    await _assert_exists(target_id)  # target must be a real knowledge item
    if target_id == item_id:
        raise ValueError("An item cannot have a relationship to itself")

    rel = {
        "id": _new_id("rel_"),
        "type": type_.strip(),
        "target_id": target_id,
        "metadata": metadata or {},
        "created_by_user_id": actor["id"],
        "created_by_user_name": actor["name"],
        "created_at": _now(),
    }
    await _snapshot_before_update(item, actor)
    await db.knowledge_items.update_one(
        {"id": item_id},
        {
            "$push": {"relationships": rel},
            "$set": {"version": item["version"] + 1, "updated_at": _now(),
                     "updated_by_user_id": actor["id"], "updated_by_user_name": actor["name"]},
        },
    )
    return await _get_raw(item_id)


async def remove_relationship(item_id: str, relationship_id: str, *, actor: dict) -> dict:
    item = await _assert_exists(item_id)
    if not any(r["id"] == relationship_id for r in item.get("relationships", [])):
        raise ValueError("Relationship not found")
    await _snapshot_before_update(item, actor)
    await db.knowledge_items.update_one(
        {"id": item_id},
        {
            "$pull": {"relationships": {"id": relationship_id}},
            "$set": {"version": item["version"] + 1, "updated_at": _now(),
                     "updated_by_user_id": actor["id"], "updated_by_user_name": actor["name"]},
        },
    )
    return await _get_raw(item_id)


# ---------------- reference integrity (used by hard-delete guards elsewhere, if ever added) ----------------
async def reference_counts(item_id: str) -> dict:
    """How many other knowledge items point at this one — informational only.
    V1 has no hard-delete for knowledge items (archive is the only removal
    path), but this is exposed as a clean extension point.
    """
    return {
        "as_category": await db.knowledge_items.count_documents({"category_id": item_id}),
        "as_phase": await db.knowledge_items.count_documents({"phase_id": item_id}),
        "as_relationship_target": await db.knowledge_items.count_documents({"relationships.target_id": item_id}),
    }
