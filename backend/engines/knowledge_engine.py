"""Knowledge Engine — Engine 6 (Sprint 4: Construction Knowledge Core;
extended Sprint 5: Construction Workflow Engine).

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
    | workflow_template (Sprint 5)
  A single collection avoids duplicating near-identical CRUD/search/archive/
  versioning logic five (now six) times (ADR precedent: operational_items is
  one collection covering 11 categories, not 11 collections). Sprint 5's
  Workflow Templates are exactly this pattern extended by one more type —
  see the Sprint 5 section below.
- Soft-archive via `archived_at`, exactly like projects/sites (ADR: no new
  archive paradigm).
- Versioning via immutable snapshots in `knowledge_versions`, mirroring the
  `corrections` pattern (ADR-004/012: facts are never overwritten in place;
  history is a linked, append-only record). The live document always holds
  current state + an incrementing `version` int for cheap reads.
- Relationships are a GENERIC, typed edge list embedded on the item:
    relationships: [{id, type, target_id, metadata, created_at}]
  Sprint 4 populated `depends_on` (Activity Dependencies); the shape was
  explicitly built to grow without a schema change, and Sprint 5 proves
  that out: `linked_material`, `linked_equipment`, `linked_document`, and
  the generic `uses` (for checklist templates) already existed and needed
  ZERO changes. Only two genuinely new edge type strings were needed —
  `linked_labour` (Labour was the one placeholder type Sprint 4 hadn't
  pre-declared) and `includes_activity` (a Workflow Template's ordered
  reference to Activity Library items — see below). No graph traversal /
  cycle detection is implemented (explicitly out of scope — this is a data
  shape, not a scheduling engine; project-level dependency *evaluation* is
  a separate, narrower concern owned by `workflow_engine.py`).
- Lifecycle `status` (draft | active | deprecated | archived) is tracked
  ALONGSIDE `archived_at`, not instead of it. `archived_at` remains the
  soft-archive timestamp that drives default list visibility (unchanged
  mechanic, matches projects/sites). `status` is the richer editorial state:
  new items default to `draft` so future consumers (e.g. Project Generation)
  can list only `active` items without seeing work-in-progress definitions.
  Sprint 5 reuses `status == "active"` directly as the Activity Library's
  "Active" flag — no separate boolean field, per "no duplicated logic."
  `archive_item`/`unarchive_item` keep both fields in sync (archive sets
  status="archived"; unarchive resets it to "active") so there is a single
  place — not two independent toggles — that owns the "is this archived"
  question.
- `applicability` is a deliberately unshaped, freeform dict reserved for
  future project-generation filtering (project types, building types,
  construction types, regions, ...). Sprint 4 stored and returned it
  verbatim with no filtering logic reading it yet; Sprint 5's Activity
  Library is the first real consumer this was reserved for — Activities
  carry `applicability` describing which project/building types they're
  relevant to (still not enforced/filtered automatically anywhere — that
  remains a documented future step, not built here).

Sprint 5 — Construction Workflow Engine additions to THIS file:
- Three new fields, meaningful only for `type="activity"` (mirroring how
  `document_kind` is only meaningful for `required_document` — same
  established pattern, not a new one): `trade` (string), `unit` (string,
  e.g. "sqm"/"each"/"lumpsum"), `requires_inspection` (bool).
- `workflow_template` added to `TYPES`. A template's ordered reference to
  Activity Library items is — deliberately — not a new field or
  mechanism, just more `includes_activity` relationships (see above),
  with the activity's position captured in `metadata.order`. "Templates
  reference Activity Library items only" falls out for free: `_assert_exists`
  already guarantees a relationship's `target_id` is a real knowledge item.
- `compute_unlocks()` — a read-only, computed (never stored) reverse-lookup
  of "which activities have a `depends_on` relationship pointing at me."
  This is the Activity Library's "Unlocks" concept. It is deliberately NOT
  a second stored relationship alongside `depends_on`, which would be two
  sources of truth for one fact and could drift — "no duplicated logic"
  applies to data, not just code.

None of the above required any change to CRUD, search, versioning,
archive, or relationship mechanics — Sprint 4's generic design absorbed
Sprint 5's requirements as pure data, exactly as intended.
"""
from __future__ import annotations
import uuid
import math
from datetime import datetime, timezone
from typing import Optional, Iterable, Callable
from core.db import db

# ----- vocab -----
TYPES = {"category", "phase", "activity", "checklist_template", "required_document", "workflow_template"}

# Lifecycle status. "archived" is intentionally NOT settable via the generic
# update path — it only ever gets set (in lockstep with archived_at) by
# archive_item(), and cleared by unarchive_item(). This keeps one owner for
# "is this archived" instead of two independently-mutable signals.
STATUSES = {"draft", "active", "deprecated", "archived"}
SETTABLE_STATUSES = {"draft", "active", "deprecated"}

# Curated for UI dropdowns / documentation. NOT strictly enforced server-side
# (see _validate_relationship_type) so future engines can introduce new edge
# types without a migration — extensibility over completeness, per brief.
# Sprint 5 adds `linked_labour` (Materials/Equipment/Documents already
# existed) and `includes_activity` (Workflow Template -> Activity Library).
KNOWN_RELATIONSHIP_TYPES = {
    "depends_on", "precedes", "requires", "references",
    "uses", "inspected_by", "linked_document", "linked_material", "linked_equipment",
    "linked_labour", "includes_activity",
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


class KnowledgeNotFoundError(ValueError):
    """Raised specifically when the PRIMARY item identified by a route's
    {item_id} path parameter doesn't exist, so routes can return 404
    instead of lumping every ValueError into 400 (Sprint 4.1 stabilization
    fix — audit finding L6). Subclasses ValueError so any existing `except
    ValueError` catch site keeps working unchanged; only routes that want
    the finer distinction need to catch this first.

    NOT raised when _assert_exists is used to validate a *referenced* id
    from the request body (category_id/phase_id/relationship target_id) —
    an invalid reference is a 400 (bad request body), not a 404 (the URL's
    resource not found), even though the underlying check is the same
    "does this id exist" lookup. See the `as_not_found` parameter below.
    """
    pass


async def _get_raw(item_id: str) -> Optional[dict]:
    return await db.knowledge_items.find_one({"id": item_id}, {"_id": 0})


async def _assert_exists(item_id: str, *, expected_type: Optional[str] = None, as_not_found: bool = False) -> dict:
    doc = await _get_raw(item_id)
    if not doc:
        msg = f"Referenced knowledge item '{item_id}' does not exist"
        raise KnowledgeNotFoundError(msg) if as_not_found else ValueError(msg)
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
    trade: Optional[str] = None,
    unit: Optional[str] = None,
    requires_inspection: bool = False,
    production_model: Optional[dict] = None,
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
        "trade": trade,                             # Sprint 5, only meaningful for activity
        "unit": unit,                               # Sprint 5, only meaningful for activity
        "requires_inspection": bool(requires_inspection),  # Sprint 5, only meaningful for activity
        # Knowledge Base v2 — Parametric Production Models. Only
        # meaningful for activity; None (the default) means "no
        # production model" — default_duration_days above continues to
        # be used unmodified, exactly as before this feature existed.
        # See knowledge_engine's PRODUCTION_MODEL section for shape and
        # workflow_engine.resolve_expected_duration for the fallback
        # logic this enables.
        "production_model": production_model,
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
    Single-item version — used by the single-item routes (get/create/update/
    archive/etc). For list responses, use enrich_many() instead: it batches
    all name lookups into ONE query regardless of list size (Sprint 4.1
    stabilization fix — audit finding L3, N+1 query pattern).
    """
    ref_ids = [item.get("category_id"), item.get("phase_id")]
    ref_ids += [r["target_id"] for r in item.get("relationships", [])]
    names = await resolve_names(ref_ids)
    out = _apply_names(item, names)
    if item.get("type") == "activity":
        out["unlocks"] = await compute_unlocks(item["id"])
    return out


async def enrich_many(items: list[dict]) -> list[dict]:
    """Batched version of enrich() — one resolve_names() query covering every
    category_id/phase_id/relationship target across the whole list, instead
    of one query per item.
    """
    if not items:
        return []
    ref_ids: list[str] = []
    for item in items:
        ref_ids.append(item.get("category_id"))
        ref_ids.append(item.get("phase_id"))
        ref_ids += [r["target_id"] for r in item.get("relationships", [])]
    names = await resolve_names(ref_ids)
    out = [_apply_names(item, names) for item in items]
    activity_ids = [item["id"] for item in items if item.get("type") == "activity"]
    if activity_ids:
        unlocks_map = await compute_unlocks_many(activity_ids)
        for o in out:
            if o.get("type") == "activity":
                o["unlocks"] = unlocks_map.get(o["id"], [])
    return out


async def compute_unlocks(activity_id: str) -> list[dict]:
    """Sprint 5 — the Activity Library's "Unlocks" concept: which OTHER
    activities have a `depends_on` relationship pointing at this one.
    Deliberately computed via reverse lookup, never stored — storing it
    as a second relationship alongside `depends_on` would be two sources
    of truth for one fact (see module docstring). Cheap at V1 scale (one
    indexed query on `relationships.target_id`, already indexed since
    Sprint 4 — see core/db.py).
    """
    docs = await db.knowledge_items.find(
        {"relationships": {"$elemMatch": {"type": "depends_on", "target_id": activity_id}}},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(200)
    return [{"id": d["id"], "name": d["name"]} for d in docs]


async def compute_unlocks_many(activity_ids: list[str]) -> dict[str, list[dict]]:
    """Batched compute_unlocks() — one query covering every activity in the
    list, mirroring enrich_many()'s N+1 fix for the same reason (Sprint 4.1
    audit finding L3)."""
    docs = await db.knowledge_items.find(
        {"relationships": {"$elemMatch": {"type": "depends_on", "target_id": {"$in": activity_ids}}}},
        {"_id": 0, "id": 1, "name": 1, "relationships": 1},
    ).to_list(500)
    out: dict[str, list[dict]] = {aid: [] for aid in activity_ids}
    for d in docs:
        for r in d.get("relationships", []):
            if r["type"] == "depends_on" and r["target_id"] in out:
                out[r["target_id"]].append({"id": d["id"], "name": d["name"]})
    return out


# ---------------------------------------------------------------------------
# Production Models (Construction Knowledge Base v2, Sprint 01).
#
# An Activity's `production_model` field, when set, has this shape:
#
#   {
#     "calculation_method": "wall_area_productivity_v1",
#     "inputs": [
#       {"key": "wall_area", "label": "Wall Area", "category": "project",
#        "unit": "sqm"},
#       {"key": "crew_size", "label": "Crew Size", "category": "execution",
#        "unit": "workers", "default_value": 4},
#       {"key": "productivity", "label": "Productivity",
#        "category": "execution", "unit": "sqm/day/worker",
#        "default_value": 70},
#     ],
#     "outputs": ["duration_days", "crew_recommendation"],
#   }
#
# `category` is one of PRODUCTION_PARAMETER_CATEGORIES below (project /
# execution / material) — purely descriptive grouping for UI display, not
# consumed by the calculation itself, so adding a new category later (or
# a new input with an existing category) never requires touching the
# calculation registry. This is the "future parameter types without
# redesign" requirement: a production model's `inputs` list and a
# calculation function's own **kwargs-free, dict-in/dict-out signature can
# both grow without changing this architecture.
#
# `calculation_method` is a REGISTRY KEY, not a stored formula string
# evaluated at runtime — deliberately. A formula string would need an
# expression evaluator (a real security/correctness surface) and would be
# much harder to unit-test or reason about than a plain, named Python
# function. This is what keeps calculation "deterministic," "separate
# from AI," and genuinely "explainable" in code, not just in principle:
# every registered function is source-controlled, independently testable,
# and returns its own worked calculation for display — never a black box.
#
# None (the default on every existing and new Activity) means "no
# production model" — see workflow_engine.resolve_expected_duration for
# the unmodified default_duration_days fallback this preserves.
# ---------------------------------------------------------------------------

PRODUCTION_PARAMETER_CATEGORIES = ("project", "execution", "material")


def _calc_wall_area_productivity_v1(inputs: dict) -> dict:
    """Wall Masonry — the first parametric activity (item 3). Duration
    is Wall Area divided by total daily output (crew size × per-worker
    productivity), rounded up to a whole day (partial-day durations
    aren't meaningful for scheduling). Crew Recommendation for this
    sprint is the crew size actually used in the calculation, i.e. "the
    crew size this duration assumes" — genuinely deriving a RECOMMENDED
    crew size from a target duration instead is a natural next output
    (see item 6 / the architecture doc's extension strategy), not built
    here.
    """
    wall_area = float(inputs["wall_area"])
    crew_size = float(inputs.get("crew_size") or 1)
    productivity = float(inputs["productivity"])
    if wall_area <= 0:
        raise ValueError("wall_area must be positive")
    if crew_size <= 0 or productivity <= 0:
        raise ValueError("crew_size and productivity must be positive")

    daily_output = crew_size * productivity
    duration_days = math.ceil(wall_area / daily_output)

    return {
        "outputs": {
            "duration_days": duration_days,
            "crew_recommendation": crew_size,
        },
        "explanation": {
            "duration_days": {
                "formula": "wall_area \u00f7 (crew_size \u00d7 productivity)",
                "values": {
                    "wall_area": wall_area, "crew_size": crew_size,
                    "productivity": productivity, "daily_output": daily_output,
                },
                "result": duration_days,
            },
        },
    }


CALCULATION_REGISTRY: dict[str, Callable[[dict], dict]] = {
    "wall_area_productivity_v1": _calc_wall_area_productivity_v1,
}


def calculate_production_model(production_model: dict, input_values: dict) -> dict:
    """Pure, deterministic calculation entrypoint — no I/O, no side
    effects, safe to call from a route, a test, or a future engine
    (Planning/CRE/Commercial Intelligence) alike.

    Resolves each declared input to either the caller-supplied value
    (a per-project-instance override, e.g. this project's actual wall
    area) or the production model's own stored default_value (e.g. the
    Knowledge Base's default productivity) — never silently invents a
    value. Raises ValueError for an unrecognized calculation_method or
    a required input with neither an override nor a default, so a
    caller always gets an explicit reason rather than a wrong number.

    Returns {resolved_inputs, outputs, explanation} — resolved_inputs
    makes it visible which values were overrides versus defaults,
    completing the explainability requirement (item 7): every
    calculated value is traceable to the exact inputs that produced it.
    """
    method = production_model.get("calculation_method")
    fn = CALCULATION_REGISTRY.get(method)
    if not fn:
        raise ValueError(f"Unknown production model calculation_method '{method}'")

    resolved: dict = {}
    for spec in production_model.get("inputs", []):
        key = spec["key"]
        if input_values.get(key) is not None:
            resolved[key] = input_values[key]
        elif spec.get("default_value") is not None:
            resolved[key] = spec["default_value"]
        else:
            raise ValueError(
                f"Missing required production model input '{key}' ({spec.get('label', key)})")

    result = fn(resolved)
    result["resolved_inputs"] = resolved
    return result


def _apply_names(item: dict, names: dict[str, str]) -> dict:
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


class KnowledgeConflictError(ValueError):
    """Raised when a write's optimistic-concurrency check fails — the item
    was modified by someone else between this caller's read and write
    (Sprint 4.1 stabilization fix — audit finding: no optimistic concurrency
    control). Subclasses ValueError for the same backward-compatible-catch
    reason as KnowledgeNotFoundError above.
    """
    pass


# ---------------- update ----------------
UPDATABLE_FIELDS = {
    "name", "description", "code", "category_id", "phase_id", "tags",
    "ai_keywords", "default_duration_days", "checklist_items", "document_kind",
    "status", "applicability", "trade", "unit", "requires_inspection",
    "production_model",
}


async def update_item(item_id: str, *, actor: dict, updates: dict) -> dict:
    item = await _assert_exists(item_id, as_not_found=True)
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

    upd["version"] = item["version"] + 1
    upd["updated_at"] = _now()
    upd["updated_by_user_id"] = actor["id"]
    upd["updated_by_user_name"] = actor["name"]
    # Optimistic concurrency, atomically: only apply if nobody else changed
    # the version we read, and only ever snapshot the pre-image we ACTUALLY
    # superseded (find_one_and_update returns the pre-update doc in the same
    # atomic op, so there's no window where a failed write still leaves an
    # orphaned "supersedes version N" snapshot behind).
    before = await db.knowledge_items.find_one_and_update(
        {"id": item_id, "version": item["version"]}, {"$set": upd},
        projection={"_id": 0},
    )
    if before is None:
        raise KnowledgeConflictError(
            "This item was modified by someone else since you loaded it. Please reload and try again."
        )
    await _snapshot_before_update(before, actor)
    return await _get_raw(item_id)


# ---------------- archive / restore ----------------
async def archive_item(item_id: str, *, actor: dict) -> dict:
    item = await _assert_exists(item_id, as_not_found=True)
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
    item = await _assert_exists(item_id, as_not_found=True)
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
    item = await _assert_exists(item_id, as_not_found=True)
    await _assert_exists(target_id)  # target must be a real knowledge item — 400 if not, not 404
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
    before = await db.knowledge_items.find_one_and_update(
        {"id": item_id, "version": item["version"]},
        {
            "$push": {"relationships": rel},
            "$set": {"version": item["version"] + 1, "updated_at": _now(),
                     "updated_by_user_id": actor["id"], "updated_by_user_name": actor["name"]},
        },
        projection={"_id": 0},
    )
    if before is None:
        raise KnowledgeConflictError(
            "This item was modified by someone else since you loaded it. Please reload and try again."
        )
    await _snapshot_before_update(before, actor)
    return await _get_raw(item_id)


async def remove_relationship(item_id: str, relationship_id: str, *, actor: dict) -> dict:
    item = await _assert_exists(item_id, as_not_found=True)
    if not any(r["id"] == relationship_id for r in item.get("relationships", [])):
        raise KnowledgeNotFoundError("Relationship not found")
    before = await db.knowledge_items.find_one_and_update(
        {"id": item_id, "version": item["version"]},
        {
            "$pull": {"relationships": {"id": relationship_id}},
            "$set": {"version": item["version"] + 1, "updated_at": _now(),
                     "updated_by_user_id": actor["id"], "updated_by_user_name": actor["name"]},
        },
        projection={"_id": 0},
    )
    if before is None:
        raise KnowledgeConflictError(
            "This item was modified by someone else since you loaded it. Please reload and try again."
        )
    await _snapshot_before_update(before, actor)
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
