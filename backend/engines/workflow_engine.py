"""Construction Workflow Engine (Sprint 5).

The first real consumer of the Construction Knowledge Core (Sprint 4) —
proves out exactly what that architecture was built for. This module owns
exactly two things, deliberately kept separate from `knowledge_engine.py`:

1. Generating a project's concrete workflow (a set of project-scoped
   *activity instances*) from an abstract Workflow Template + the Activity
   Library, denormalizing each activity's Knowledge Core fields at
   generation time.
2. Tracking each instance's status (not_started/ready/in_progress/blocked/
   completed) and *respecting dependencies* when transitioning it.

Why a new collection (`workflow_activities`) instead of reusing
`knowledge_items`: Knowledge Core is global, admin-curated, versioned
reference data — one canonical "Concrete Slab Pour" activity definition
shared across every project. A project's workflow needs many independent,
mutable, project-scoped *instances* of that concept, each with its own
status. Folding mutable per-project instance state into the same
collection as global reference data would be exactly the kind of
conflation Sprint 4's `applicability`/`status` design was careful to
avoid — so this stays a separate, purpose-built collection, the same way
`operational_items` is separate from `events` despite both describing
"things that happened on site."

Denormalization at generation time (not a live reference) is deliberate
and mirrors the `assigned_to_user_name`-alongside-`assigned_to_user_id`
pattern used throughout Atlas: a project's workflow must not silently
change shape if someone edits the Activity Library after the project
was generated. `knowledge_activity_id` is kept for traceability, but the
generated `name`/`trade`/`unit`/etc. are the project's own copy.

No scheduling: there is no date, no duration-as-calendar-time, no
critical path. "Duration" from the Activity Library is copied through as
informational data only. No AI, no resource/cost calculations,
no notifications — all explicitly out of scope for this sprint.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional
from core.db import db
from engines import knowledge_engine, memory_engine

STATUSES = {"not_started", "ready", "in_progress", "blocked", "completed"}

# Transitioning INTO these statuses requires every dependency to already be
# "completed" — this is the literal "Respect dependencies" requirement.
# blocked/not_started/ready have no such gate: blocked is an orthogonal
# "something's wrong" signal settable from any state, and reverting to
# not_started/ready is always safe (never destroys data, just resets intent).
_DEPENDENCY_GATED_STATUSES = {"in_progress", "completed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"wfa_{uuid.uuid4()}"


class WorkflowError(ValueError):
    """Base class for workflow-engine validation errors. Subclasses
    ValueError so routes can use the same broad `except ValueError` catch
    already established for knowledge_engine, while still allowing a
    specific `except WorkflowNotFoundError` first where routes want the
    404-vs-400 distinction (same pattern as KnowledgeNotFoundError)."""
    pass


class WorkflowNotFoundError(WorkflowError):
    pass


class DependencyNotSatisfiedError(WorkflowError):
    pass


async def _assert_project_visible(project_id: str, user: dict) -> dict:
    """Sprint 4.3's project-scoping foundation, reused (not duplicated) for
    workflow visibility: if a user can't see a project via
    GET /api/projects, they should not be able to see or generate its
    workflow either. Raises WorkflowNotFoundError (404) rather than 403 —
    same "acts as if it doesn't exist" behavior list_sites() already uses
    for an out-of-scope project_id query.
    """
    project = await memory_engine.get_project(project_id)
    if not project:
        raise WorkflowNotFoundError(f"Project '{project_id}' not found")
    if memory_engine._is_project_scoped(user):
        if project_id not in (user.get("assigned_project_ids") or []):
            raise WorkflowNotFoundError(f"Project '{project_id}' not found")
    return project


async def generate_workflow(project_id: str, template_id: str, *, actor: dict) -> list[dict]:
    """Generate a project's workflow from a Workflow Template. Refuses if
    the project already has a workflow (no accidental duplication —
    generation is a one-time bootstrap per project in V1; there is no
    "regenerate"/"merge" concept here, matching "no scheduling" simplicity).
    """
    await _assert_project_visible(project_id, actor)

    existing = await db.workflow_activities.count_documents({"project_id": project_id})
    if existing:
        raise WorkflowError(
            "This project already has a generated workflow. Delete/archive the project's "
            "existing activities before regenerating, or start a new project."
        )

    template = await knowledge_engine.get_item(template_id)
    if not template:
        raise WorkflowNotFoundError(f"Workflow template '{template_id}' not found")
    if template["type"] != "workflow_template":
        raise WorkflowError(f"'{template_id}' is a {template['type']}, expected workflow_template")

    # "Templates reference Activity Library items only" — enforced for free:
    # add_relationship() already guarantees every target_id is a real
    # knowledge item; here we additionally only include ones that are
    # type=activity and not archived (an archived activity is deliberately
    # retired from the library and shouldn't seed new projects).
    includes = [r for r in template.get("relationships", []) if r["type"] == "includes_activity"]
    includes.sort(key=lambda r: (r.get("metadata") or {}).get("order", 0))

    activities: list[dict] = []
    for rel in includes:
        act = await knowledge_engine.get_item(rel["target_id"])
        if not act or act["type"] != "activity" or act.get("archived_at"):
            continue
        activities.append(act)

    if not activities:
        raise WorkflowError(
            "This template has no active Activity Library items to generate from. "
            "Add activities to the template first."
        )

    # First pass: create one workflow_activity per template activity,
    # tracking the knowledge_activity_id -> new workflow_activity id mapping
    # so dependency links (second pass) can be translated into this
    # project's own instance ids.
    id_map: dict[str, str] = {}
    now = _now()
    docs = []
    for order, act in enumerate(activities):
        new_id = _new_id()
        id_map[act["id"]] = new_id
        docs.append({
            "id": new_id,
            "project_id": project_id,
            "knowledge_activity_id": act["id"],
            "template_id": template_id,
            "template_name": template["name"],
            "name": act["name"],
            "description": act.get("description", ""),
            "category_id": act.get("category_id"),
            "phase_id": act.get("phase_id"),
            "trade": act.get("trade"),
            "unit": act.get("unit"),
            "default_duration_days": act.get("default_duration_days"),
            "requires_inspection": bool(act.get("requires_inspection", False)),
            "order": order,
            "status": "not_started",   # provisional; corrected in the second pass below
            "depends_on_activity_ids": [],  # filled in the second pass below
            # Sprint 6.1 — execution targets. Pure data storage, no
            # validation or inference against status transitions (no
            # auto-populating actual_start when status becomes
            # in_progress, etc.) — deliberately deferred, this is the
            # foundation for future delay detection / schedule variance
            # reporting, not that reporting itself.
            "planned_start": None,
            "planned_finish": None,
            "actual_start": None,
            "actual_finish": None,
            # Activity Ownership Model (Execution Experience Sprint 02) —
            # explicit assignment, distinct from project visibility.
            # Visibility still controls who CAN see the activity;
            # assignment determines ownership within that visible set.
            # History embedded on the document (assignment_history) —
            # no new ledger collection, matching how e.g. an insight's
            # feedback_history is already embedded rather than given
            # its own collection.
            "assigned_to_user_id": None,
            "assigned_to_user_name": None,
            "assigned_at": None,
            "assignment_history": [],
            # Construction Knowledge Base v2 — Parametric Production
            # Models. Populated only when a user sets project-specific
            # input values (e.g. this project's actual wall area) via
            # set_production_inputs below; both stay None/empty
            # otherwise, and resolve_expected_duration falls back to
            # default_duration_days exactly as before this feature
            # existed — Preserve Existing Projects, unmodified.
            "production_model_inputs": {},
            "production_model_result": None,
            "created_at": now,
            "updated_at": now,
            "status_updated_by_user_id": actor["id"],
            "status_updated_by_user_name": actor["name"],
            "status_updated_at": now,
        })

    # Second pass: translate each source activity's depends_on relationships
    # into concrete sibling-instance ids within THIS project. A dependency
    # pointing at an activity outside this template's generated set is
    # skipped — it can't be resolved within this project, and silently
    # dropping it (rather than failing the whole generation) keeps
    # generation robust to partially-curated templates. Initial status:
    # zero resolvable dependencies -> ready; any dependency -> not_started.
    for act, doc in zip(activities, docs):
        depends_on = [r["target_id"] for r in act.get("relationships", []) if r["type"] == "depends_on"]
        resolved = [id_map[dep] for dep in depends_on if dep in id_map]
        doc["depends_on_activity_ids"] = resolved
        doc["status"] = "ready" if not resolved else "not_started"

    for doc in docs:
        await db.workflow_activities.insert_one({**doc})
        doc["expected_duration_days"] = resolve_expected_duration(doc)

    return docs


async def list_workflow(project_id: str, *, user: dict) -> list[dict]:
    await _assert_project_visible(project_id, user)
    items = await db.workflow_activities.find(
        {"project_id": project_id}, {"_id": 0},
    ).sort("order", 1).to_list(1000)
    return await _enrich_many(items)


async def get_workflow_activity(activity_id: str) -> Optional[dict]:
    doc = await db.workflow_activities.find_one({"id": activity_id}, {"_id": 0})
    if doc:
        doc["expected_duration_days"] = resolve_expected_duration(doc)
    return doc


async def _enrich_many(items: list[dict]) -> list[dict]:
    """Attach human-readable names for each activity's dependencies —
    mirrors knowledge_engine's enrich_many() batching convention (one
    query for the whole list, not one per item)."""
    if not items:
        return []
    by_id = {i["id"]: i for i in items}
    out = []
    for item in items:
        deps = [
            {"id": dep_id, "name": by_id[dep_id]["name"], "status": by_id[dep_id]["status"]}
            for dep_id in item.get("depends_on_activity_ids", [])
            if dep_id in by_id
        ]
        out.append({**item, "depends_on": deps, "expected_duration_days": resolve_expected_duration(item)})
    return out


def _dependencies_satisfied(activity: dict, siblings_by_id: dict[str, dict]) -> bool:
    return all(
        siblings_by_id.get(dep_id, {}).get("status") == "completed"
        for dep_id in activity.get("depends_on_activity_ids", [])
    )


SCHEDULE_FIELDS = {"planned_start", "planned_finish", "actual_start", "actual_finish"}


async def set_schedule(activity_id: str, updates: dict, *, actor: dict) -> dict:
    """Sprint 6.1 — store execution targets (Planned/Actual Start/Finish)
    on a workflow activity. Deliberately pure data storage: no validation
    against status, no cross-field validation (e.g. finish-after-start),
    no auto-population from status transitions. This is the foundation
    for future delay detection / schedule variance reporting — that
    analytics layer is explicitly not built here.

    `updates` may contain any subset of SCHEDULE_FIELDS; unrecognized
    keys are ignored (same filtering convention as
    knowledge_engine.update_item's UPDATABLE_FIELDS). A value of None
    clears that field.
    """
    activity = await db.workflow_activities.find_one({"id": activity_id}, {"_id": 0})
    if not activity:
        raise WorkflowNotFoundError(f"Workflow activity '{activity_id}' not found")

    await _assert_project_visible(activity["project_id"], actor)

    upd = {k: v for k, v in updates.items() if k in SCHEDULE_FIELDS}
    if not upd:
        return activity
    upd["updated_at"] = _now()
    await db.workflow_activities.update_one({"id": activity_id}, {"$set": upd})
    return await get_workflow_activity(activity_id)


async def assign_activity(activity_id: str, assignee: Optional[dict], *, actor: dict) -> dict:
    """Activity Ownership Model (Execution Experience Sprint 02) —
    explicit assignment of a workflow activity to a user, distinct from
    (and layered on top of) project visibility: visibility still gates
    who can see the activity at all; assignment determines ownership
    within that visible set, and becomes the source of truth for
    "assigned to me" views (see operations_engine.work_queue).

    assignee=None clears the assignment (unassign) — still recorded in
    assignment_history as a transition to no one, so the history stays
    a complete, honest record rather than silently losing the previous
    owner's tenure when someone unassigns.

    Reassignment is just calling this again with a different assignee —
    no separate "reassign" verb; the history array is what makes a
    reassignment distinguishable from a first assignment after the
    fact.
    """
    activity = await db.workflow_activities.find_one({"id": activity_id}, {"_id": 0})
    if not activity:
        raise WorkflowNotFoundError(f"Workflow activity '{activity_id}' not found")

    await _assert_project_visible(activity["project_id"], actor)

    now = _now()
    history_entry = {
        "assigned_to_user_id": assignee["id"] if assignee else None,
        "assigned_to_user_name": assignee["name"] if assignee else None,
        "previous_assignee_id": activity.get("assigned_to_user_id"),
        "previous_assignee_name": activity.get("assigned_to_user_name"),
        "assigned_by_user_id": actor["id"],
        "assigned_by_user_name": actor["name"],
        "assigned_at": now,
    }
    await db.workflow_activities.update_one(
        {"id": activity_id},
        {
            "$set": {
                "assigned_to_user_id": assignee["id"] if assignee else None,
                "assigned_to_user_name": assignee["name"] if assignee else None,
                "assigned_at": now if assignee else None,
                "updated_at": now,
            },
            "$push": {"assignment_history": history_entry},
        },
    )
    return await get_workflow_activity(activity_id)


# ---------------------------------------------------------------------------
# Construction Knowledge Base v2 — Parametric Production Models applied
# to a project-scoped workflow activity instance.
#
# The production model itself (calculation_method, input declarations,
# defaults) lives on the Activity knowledge item — see
# knowledge_engine's PRODUCTION_MODEL section. This module only stores
# this INSTANCE's specific input values (e.g. this project's actual
# wall area) and the resulting calculation, and resolves which duration
# a workflow activity should actually use.
# ---------------------------------------------------------------------------

def resolve_expected_duration(activity: dict) -> Optional[float]:
    """Preserve Existing Projects (item 8): if this activity has a
    computed production_model_result, its duration_days IS the expected
    duration. Otherwise — no production model was ever applied, exactly
    the situation for every activity that existed before this feature —
    fall back to the original default_duration_days, completely
    unmodified. Never raises: a missing/invalid production model result
    is treated the same as "no production model," not an error.
    """
    result = activity.get("production_model_result")
    if result and result.get("outputs", {}).get("duration_days") is not None:
        return result["outputs"]["duration_days"]
    return activity.get("default_duration_days")


async def set_production_inputs(activity_id: str, input_values: dict, *, actor: dict) -> dict:
    """Sets this workflow activity instance's production model input
    values (e.g. its actual wall area for THIS project) and immediately
    recalculates — "changing productivity should immediately affect
    derived duration" (item 4) holds here too: since the calculation
    always reads the activity template's CURRENT production_model
    (never a cached copy), editing the template's default productivity
    and then re-calling this (even with the same instance inputs)
    picks up the new default right away.

    Requires the underlying Activity knowledge item to actually have a
    production_model — raises ValueError otherwise, the same "explicit
    reason, never a silent wrong number" principle
    knowledge_engine.calculate_production_model itself follows.
    """
    activity = await db.workflow_activities.find_one({"id": activity_id}, {"_id": 0})
    if not activity:
        raise WorkflowNotFoundError(f"Workflow activity '{activity_id}' not found")
    await _assert_project_visible(activity["project_id"], actor)

    template_activity = await knowledge_engine.get_item(activity["knowledge_activity_id"])
    if not template_activity or not template_activity.get("production_model"):
        raise WorkflowError(
            f"Activity '{activity['name']}' has no production model — nothing to calculate.")

    merged_inputs = {**activity.get("production_model_inputs", {}), **input_values}
    result = knowledge_engine.calculate_production_model(
        template_activity["production_model"], merged_inputs)

    now = _now()
    upd = {
        "production_model_inputs": merged_inputs,
        "production_model_result": {**result, "calculated_at": now},
        "updated_at": now,
    }
    await db.workflow_activities.update_one({"id": activity_id}, {"$set": upd})
    return await get_workflow_activity(activity_id)


async def set_status(activity_id: str, new_status: str, *, actor: dict) -> dict:
    """Transition a workflow activity's status, respecting dependencies.

    - in_progress / completed: blocked unless every dependency is already
      completed (DependencyNotSatisfiedError -> 409, not 400: this is a
      state conflict, not a malformed request).
    - blocked: always allowed, from any status — an orthogonal "something
      external is wrong" signal, not a step in the dependency chain.
    - not_started / ready: always allowed (safe to revert).
    - Completing an activity cascades: every sibling in the same project
      that depends on it is re-evaluated, and any still sitting at
      "not_started" with ALL its dependencies now satisfied is
      auto-promoted to "ready". This is the project-level mirror of the
      Activity Library's "Unlocks" concept (knowledge_engine.compute_unlocks).

    Also enforces the same project-visibility rule as list_workflow() —
    a scoped user cannot change the status of an activity belonging to a
    project they can't see, even if they somehow know its activity id.
    """
    if new_status not in STATUSES:
        raise WorkflowError(f"Invalid status '{new_status}'. Must be one of {sorted(STATUSES)}")

    activity = await db.workflow_activities.find_one({"id": activity_id}, {"_id": 0})
    if not activity:
        raise WorkflowNotFoundError(f"Workflow activity '{activity_id}' not found")

    await _assert_project_visible(activity["project_id"], actor)

    siblings_by_id: Optional[dict[str, dict]] = None
    if new_status in _DEPENDENCY_GATED_STATUSES:
        siblings = await db.workflow_activities.find(
            {"project_id": activity["project_id"]}, {"_id": 0},
        ).to_list(1000)
        siblings_by_id = {s["id"]: s for s in siblings}
        if not _dependencies_satisfied(activity, siblings_by_id):
            raise DependencyNotSatisfiedError(
                f"Cannot set status to '{new_status}': one or more dependencies are not yet completed."
            )

    now = _now()
    updates: dict = {
        "status": new_status, "updated_at": now,
        "status_updated_by_user_id": actor["id"],
        "status_updated_by_user_name": actor["name"],
        "status_updated_at": now,
    }
    # Timeline Improvements — actual timestamps become the trusted
    # historical record automatically, on the matching transition, not
    # by anyone typing a date in. Never overwrites an already-set value
    # (e.g. one Management entered manually ahead of time) — this only
    # ever fills in what's still None.
    if new_status == "in_progress" and not activity.get("actual_start"):
        updates["actual_start"] = now
    if new_status == "completed" and not activity.get("actual_finish"):
        updates["actual_finish"] = now

    await db.workflow_activities.update_one(
        {"id": activity_id},
        {"$set": updates},
    )

    if new_status == "completed":
        # Reuse the siblings already fetched above (guaranteed present:
        # "completed" is always in _DEPENDENCY_GATED_STATUSES) instead of
        # re-querying the entire project's activities a second time.
        # The in-memory copy of THIS activity still shows its pre-update
        # status (the DB write above happened after the fetch) - corrected
        # here before use, since a stale status would make
        # _dependencies_satisfied wrongly conclude a dependent sibling
        # isn't unlockable yet.
        assert siblings_by_id is not None
        siblings_by_id[activity_id] = {**siblings_by_id[activity_id], "status": "completed"}
        await _promote_unlocked_siblings(activity["project_id"], activity_id, siblings_by_id)

    return await get_workflow_activity(activity_id)


async def _promote_unlocked_siblings(project_id: str, completed_activity_id: str,
                                     siblings_by_id: Optional[dict[str, dict]] = None) -> None:
    """After completing an activity, auto-promote any sibling sitting at
    not_started whose dependencies are now all satisfied.

    siblings_by_id, when provided by set_status (the common path), is
    reused directly rather than re-querying the project's full activity
    list a second time — a measured, genuine inefficiency (roughly 10
    workflow_activities round trips per activity across a full ACDP
    simulation) fixed here. Still independently callable with no
    siblings_by_id (fetches its own, unchanged) for any other caller."""
    if siblings_by_id is None:
        siblings = await db.workflow_activities.find({"project_id": project_id}, {"_id": 0}).to_list(1000)
        siblings_by_id = {s["id"]: s for s in siblings}
    now = _now()
    for s in siblings_by_id.values():
        if s["status"] != "not_started":
            continue
        if completed_activity_id not in s.get("depends_on_activity_ids", []):
            continue
        if _dependencies_satisfied(s, siblings_by_id):
            await db.workflow_activities.update_one(
                {"id": s["id"]},
                {"$set": {"status": "ready", "updated_at": now}},
            )


# Sprint 5's five named starter templates. Seeded as empty, named shells —
# deliberately NOT pre-populated with a fabricated activity list, since
# inventing a "realistic" construction sequence isn't something this
# engineering task should guess at; an admin populates each one with real
# Activity Library items via the existing, reused Dependency Viewer UI
# (POST .../relationships with type=includes_activity), the same
# mechanism this smoke-tested end to end. Mirrors the exact idempotent
# "already exists -> no-op" shape of the existing POST /api/projects/seed.
DEFAULT_TEMPLATE_NAMES = ["Villa", "Residential", "Commercial", "Interior", "Renovation"]


async def seed_default_templates(*, actor: dict) -> dict:
    created = []
    skipped = []
    for name in DEFAULT_TEMPLATE_NAMES:
        existing = await db.knowledge_items.find_one(
            {"type": "workflow_template", "name": name}, {"_id": 0, "id": 1},
        )
        if existing:
            skipped.append(name)
            continue
        item = await knowledge_engine.create_item(
            actor=actor, type_="workflow_template", name=name,
            description=f"{name} construction workflow template.",
            status="draft",  # admin promotes to active once populated with activities
        )
        created.append(item["name"])
    return {"created": created, "already_existed": skipped}
