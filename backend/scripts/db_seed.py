"""Deterministic development seed utility (Sprint DX-7).

Populates the database with a realistic, predictable dataset so every
developer starts from an identical baseline. Standalone script — not
imported by server.py, any route, or any engine, so it has zero effect on
production runtime behaviour; it only runs when a developer explicitly
invokes it.

Design principles:
  - Every document is created through the SAME engine functions production
    traffic uses (memory_engine, operations_engine, knowledge_engine,
    workflow_engine, intelligence_engine) — never a raw dict insert. This
    is the same "reuse existing architecture" rule every prior Atlas
    sprint has followed, and it means seeded data can never drift out of
    shape from what the real application actually produces.
  - Idempotent by construction: every top-level entity (user, project,
    site, knowledge item, workflow) is looked up by a natural key before
    creating it, and skipped if it already exists. Re-running this script
    against an already-seeded database is always safe and never produces
    duplicates.
  - The one exception is per-event content inside "Atlas Demo Site"
    (events/analyses/proposals aren't natural-keyed the way users/projects
    are) — those are guarded by a single top-level marker instead: if the
    demo project already has any events, the whole demo-content block is
    skipped, so re-running the script never doubles up the demo timeline.
  - After seeding, a single upserted record in `seed_metadata`
    (seed_version, atlas_version, created_at) lets future tooling detect
    what seeded a database and when, and a concise entity-count summary
    is printed at completion.

Usage:
    cd backend
    python -m scripts.db_seed
"""
from __future__ import annotations
import asyncio
import base64
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")  # allow `python -m scripts.db_seed` from backend/
from core.db import db, ensure_indexes, close_client  # noqa: E402
from core.settings import DB_NAME, APP_VERSION  # noqa: E402
from engines import memory_engine, operations_engine, knowledge_engine, workflow_engine, intelligence_engine  # noqa: E402

# Bumped whenever this script's seeded dataset changes in a way future
# tooling might care about (e.g. detecting "this DB was seeded by an
# older version of this script"). Independent of APP_VERSION.
SEED_VERSION = "1.0"

# A minimal, valid 1x1-pixel JPEG — used for seeded "photo" assets so any
# code that reads/decodes raw_assets.data_base64 gets real, valid image
# bytes rather than placeholder text. Deterministic, no network fetch.
_TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkI"
    "CQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/wAALCAABAAEBAREA/8QAFAABAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMR"
    "AD8AVN4A/9k="
)

_NOW = datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _days_ago(n: int) -> str:
    return _iso(_NOW - timedelta(days=n))


# ---------------------------------------------------------------------------
# Users — two per role, predictable phone numbers, immediately approved
# ---------------------------------------------------------------------------
USER_SEED = [
    # (phone, name, backend_role) — workspace is now purely derived from
    # role (FAC-04), so there is no separate override to specify here.
    ("9000000001", "Atlas Admin 1", "management"),
    ("9000000002", "Atlas Admin 2", "management"),
    ("9000000011", "Project Manager 1", "project_manager"),
    ("9000000012", "Project Manager 2", "project_manager"),
    ("9000000021", "Site Supervisor 1", "site_supervisor"),
    ("9000000022", "Site Supervisor 2", "site_supervisor"),
    ("9000000031", "Client 1", "client"),
    ("9000000032", "Client 2", "client"),
]


async def seed_users() -> dict[str, dict]:
    """Returns {name: user_doc}. upsert_user() is already idempotent by
    phone (updates name in place rather than duplicating — see Sprint 6.2
    Identity Security: role is NOT updated on a repeat upsert, matching
    login's own behaviour, so this also re-asserts the correct role via
    set_user_role() below, which is idempotent and safe to call every
    run), which is exactly the "no duplicate users after multiple runs"
    requirement — reused as-is, not reimplemented."""
    users: dict[str, dict] = {}
    for phone, name, role in USER_SEED:
        user = await memory_engine.upsert_user(phone=phone, name=name, role=role)
        if user["role"] != role:
            user = await memory_engine.set_user_role(user["id"], role)
        users[name] = user
    print(f"  users: {len(users)} ready (2 admin, 2 PM, 2 supervisor, 2 client)")
    return users


# ---------------------------------------------------------------------------
# Projects + sites
# ---------------------------------------------------------------------------
PROJECT_SEED = [
    # (code, name, location, site_name)
    ("VILLA-001", "Luxury Villa", "Whitefield, Bengaluru", "Villa Site"),
    ("OFFICE-001", "Commercial Office", "Cyber City, Gurugram", "Office Tower Site"),
    ("APT-001", "Residential Apartment", "Baner, Pune", "Apartment Block A"),
    ("DEMO-001", "Atlas Demo Site", "Model Town, Ludhiana", "Atlas Demo Site"),
]


async def _get_or_create_project(code: str, name: str, location: str) -> dict:
    existing = await db.projects.find_one({"code": code}, {"_id": 0})
    if existing:
        return existing
    return await memory_engine.insert_project(name=name, code=code, location=location)


async def _get_or_create_site(project_id: str, name: str, location: str) -> dict:
    existing = await db.sites.find_one({"project_id": project_id, "name": name}, {"_id": 0})
    if existing:
        return existing
    return await memory_engine.insert_site(project_id=project_id, name=name, location=location)


async def seed_projects() -> dict[str, dict]:
    """Returns {project_name: {"project": doc, "site": doc}}."""
    out = {}
    for code, name, location, site_name in PROJECT_SEED:
        project = await _get_or_create_project(code, name, location)
        site = await _get_or_create_site(project["id"], site_name, location)
        out[name] = {"project": project, "site": site}
    print(f"  projects: {len(out)} ready ({', '.join(out.keys())})")
    return out


# ---------------------------------------------------------------------------
# Knowledge Core — a small Activity Library + the five named templates
# ---------------------------------------------------------------------------
async def _get_or_create_knowledge(type_: str, name: str, **kwargs) -> dict:
    existing = await db.knowledge_items.find_one({"type": type_, "name": name}, {"_id": 0})
    if existing:
        return existing
    # actor: seeded knowledge is admin-authored, matching real usage (Knowledge
    # Core mutations are admin-only in every route that isn't this script).
    admin = kwargs.pop("actor")
    return await knowledge_engine.create_item(actor=admin, type_=type_, name=name, **kwargs)


async def seed_knowledge(admin: dict) -> dict:
    category = await _get_or_create_knowledge("category", "Structural Work", actor=admin, status="active")
    phase = await _get_or_create_knowledge("phase", "Foundation", actor=admin, status="active")

    excavation = await _get_or_create_knowledge(
        "activity", "Excavation", actor=admin, category_id=category["id"], phase_id=phase["id"],
        trade="Civil", unit="cum", default_duration_days=3, requires_inspection=False, status="active",
        description="Site excavation to design foundation depth.",
        applicability={"project_types": ["villa", "residential", "commercial"]},
    )
    shuttering = await _get_or_create_knowledge(
        "activity", "Shuttering & Reinforcement", actor=admin, category_id=category["id"], phase_id=phase["id"],
        trade="Civil", unit="sqm", default_duration_days=4, requires_inspection=True, status="active",
        description="Formwork and rebar placement ahead of concrete pour.",
    )
    concrete = await _get_or_create_knowledge(
        "activity", "Concrete Pour", actor=admin, category_id=category["id"], phase_id=phase["id"],
        trade="Civil", unit="cum", default_duration_days=2, requires_inspection=True, status="active",
        description="Foundation concrete pour and curing.",
    )

    async def _ensure_relationship(item, type_, target_id, metadata=None):
        if any(r["type"] == type_ and r["target_id"] == target_id for r in item.get("relationships", [])):
            return item
        return await knowledge_engine.add_relationship(item["id"], actor=admin, type_=type_, target_id=target_id, metadata=metadata or {})

    shuttering = await _ensure_relationship(shuttering, "depends_on", excavation["id"])
    concrete = await _ensure_relationship(concrete, "depends_on", shuttering["id"])

    checklist = await _get_or_create_knowledge(
        "checklist_template", "Pre-Pour Checklist", actor=admin, status="active",
        checklist_items=[
            {"id": "1", "text": "Rebar spacing verified against drawing"},
            {"id": "2", "text": "Formwork alignment checked"},
            {"id": "3", "text": "Site cleared of debris"},
        ],
    )
    concrete = await _ensure_relationship(concrete, "uses", checklist["id"])

    permit = await _get_or_create_knowledge(
        "required_document", "Excavation Permit", actor=admin, status="active",
        description="Local authority permit required before excavation begins.",
    )
    excavation = await _ensure_relationship(excavation, "linked_document", permit["id"])

    # The five named starter templates (Sprint 5's existing idempotent seed).
    seeded_templates = await workflow_engine.seed_default_templates(actor=admin)

    # Populate the "Villa" template with our three activities so
    # generate_workflow() has something real to produce for Atlas Demo Site.
    villa_template = await db.knowledge_items.find_one({"type": "workflow_template", "name": "Villa"}, {"_id": 0})
    if villa_template and not any(r["type"] == "includes_activity" for r in villa_template.get("relationships", [])):
        for order, act in enumerate([excavation, shuttering, concrete]):
            await knowledge_engine.add_relationship(
                villa_template["id"], actor=admin, type_="includes_activity",
                target_id=act["id"], metadata={"order": order},
            )
        villa_template = await knowledge_engine.get_item(villa_template["id"])

    print(f"  knowledge: 1 category, 1 phase, 3 activities, 1 checklist, 1 document, "
          f"5 workflow templates ({len(seeded_templates['created'])} newly created, "
          f"{len(seeded_templates['already_existed'])} already existed)")
    return {"category": category, "phase": phase, "excavation": excavation,
            "shuttering": shuttering, "concrete": concrete, "villa_template": villa_template}


# ---------------------------------------------------------------------------
# Per-project sample content (events, operational items)
# ---------------------------------------------------------------------------
async def _seed_event(site_id: str, project_id: str, user: dict, text: str, kind: str, days_ago: int,
                      photo: bool = False) -> dict:
    """Directly builds the same event shape reality_engine.capture() does —
    capture() itself expects FastAPI UploadFile objects (it's the HTTP-layer
    entrypoint), which don't apply to a standalone script, so this seeds
    the identical document shape without going through the multipart-upload
    plumbing. memory_engine.insert_event/put_asset — the actual persistence
    primitives capture() itself calls — are reused unchanged."""
    event_id = memory_engine._new_id("evt_")
    photo_ids = []
    if photo:
        asset = await memory_engine.put_asset(event_id, "photo", "image/jpeg", _TINY_JPEG)
        photo_ids.append(asset["id"])
    doc = {
        "id": event_id,
        "site_id": site_id,
        "project_id": project_id,
        "activity_id": None,
        "user_id": user["id"],
        "user_name": user["name"],
        "kind": kind,
        "text_input": text,
        "audio_asset_id": None,
        "photo_asset_ids": photo_ids,
        "gps": None,
        "client_created_at": _days_ago(days_ago),
        "server_created_at": _days_ago(days_ago),
        "app_version": "seed-script",
        "ai_status": "skipped",       # deterministic seed never calls Whisper/GPT-4o
        "ai_analysis_id": None,
        "proposals_status": "pending",
        "proposals_error": None,
    }
    await memory_engine.insert_event(doc)
    return doc


async def seed_light_project_content(project: dict, site: dict, users: dict[str, dict]) -> None:
    """A modest, realistic amount of activity for the three example
    projects — enough for each to look genuinely in-progress."""
    existing = await db.events.count_documents({"site_id": site["id"]})
    if existing:
        return  # already seeded in a prior run

    supervisor = users["Site Supervisor 1"]
    pm = users["Project Manager 1"]

    await _seed_event(site["id"], project["id"], supervisor, "Foundation excavation started on the north wing.",
                      kind="text", days_ago=6)
    await _seed_event(site["id"], project["id"], supervisor, "Excavation 70% complete, minor rock encountered on east side.",
                      kind="photo", days_ago=4, photo=True)
    await _seed_event(site["id"], project["id"], supervisor, "Excavation complete, ready for shuttering.",
                      kind="text", days_ago=2)

    await operations_engine.create_item(
        actor=pm, site_id=site["id"], category="material_requirement",
        title="Cement bags for foundation pour", description="OPC 53 grade, foundation mix.",
        priority="high",
    )
    await operations_engine.create_item(
        actor=supervisor, site_id=site["id"], category="labour_requirement",
        title="Mason team for shuttering", description="4-person shuttering crew needed next week.",
        priority="normal",
    )
    await operations_engine.create_item(
        actor=pm, site_id=site["id"], category="client_approval",
        title="Approve foundation design variation", description="Minor footing depth change pending client sign-off.",
        priority="high",
    )


# ---------------------------------------------------------------------------
# Atlas Demo Site — the fully populated showcase project
# ---------------------------------------------------------------------------
DEMO_STRUCTURED_ANALYSIS = {
    # Deliberately hand-authored, not generated by a live LLM call — a
    # deterministic seed must never depend on network access or an API key
    # (see Sprint 5.0.2). Shaped exactly like intelligence_engine's real
    # GPT-4o output schema (EVENT_SYSTEM_PROMPT) so it flows through the
    # unmodified, real generate_proposals_for_event() code path below —
    # this is what makes the resulting ai_proposals genuine "AI Proposal
    # Examples" rather than a separate, parallel fake data shape.
    "type": "voice_note",
    "title": "Foundation progress and material takeoff",
    "summary": "Supervisor reports foundation 60% complete and requests a full material quantity takeoff for the next pour.",
    "materials": [
        {"name": "OPC 53 cement", "quantity": 150, "unit": "bags", "required_date": None,
         "priority": "high", "trade": "Civil", "area": "Foundation", "reason": "Next pour",
         "confidence": "high"},
        {"name": "20mm aggregate", "quantity": 12, "unit": "cum", "required_date": None,
         "priority": "high", "trade": "Civil", "area": "Foundation", "reason": "Next pour",
         "confidence": "high"},
        {"name": "TMT rebar 12mm", "quantity": 800, "unit": "kg", "required_date": None,
         "priority": "normal", "trade": "Civil", "area": "Foundation", "reason": "Column starter bars",
         "confidence": "medium"},
    ],
    "labour": [
        {"trade": "Mason", "count": 6, "required_date": None, "priority": "high",
         "area": "Foundation", "reason": "Shuttering and pour crew", "confidence": "high"},
    ],
    "equipment": [
        {"name": "Concrete mixer", "quantity": 1, "required_date": None,
         "priority": "normal", "reason": "Foundation pour", "confidence": "high"},
    ],
    "client_approvals": [
        {"what": "Approve revised foundation waterproofing spec", "required_date": None,
         "priority": "high", "reason": "Site condition change", "confidence": "high"},
    ],
    "drawing_requests": [],
    "inspections": [
        {"what": "Pre-pour rebar inspection", "required_date": None, "priority": "high",
         "reason": "Required before concrete pour", "confidence": "high"},
    ],
    "safety_observations": [
        {"observation": "Excavation edge protection needs reinforcement on east side",
         "priority": "high", "area": "Foundation", "confidence": "high"},
    ],
    "quality_observations": [
        {"observation": "Formwork alignment within tolerance on north wing",
         "priority": "normal", "area": "Foundation", "confidence": "medium"},
    ],
    "commitments": [
        {"what": "Share updated foundation drawing", "owed_to": "Site Supervisor", "by_when": None,
         "confidence": "medium"},
    ],
    "follow_ups": [
        {"what": "Confirm cement delivery schedule", "when": None, "confidence": "medium"},
    ],
    "issues": ["Minor rock encountered during excavation on east side, may affect timeline."],
    "work_done": ["Foundation excavation completed.", "Shuttering started on north wing."],
    "urgency": "normal",
    "language_detected": "en",
}


async def seed_demo_project_content(project: dict, site: dict, users: dict[str, dict],
                                    knowledge: dict) -> None:
    existing = await db.events.count_documents({"site_id": site["id"]})
    if existing:
        print("  Atlas Demo Site: already fully seeded, skipping")
        return

    supervisor = users["Site Supervisor 1"]
    pm = users["Project Manager 1"]
    admin = users["Atlas Admin 1"]

    # --- Timeline: a realistic run of events, including photos ---
    await _seed_event(site["id"], project["id"], supervisor, "Site mobilization complete, boundary marked.",
                      kind="text", days_ago=14)
    await _seed_event(site["id"], project["id"], supervisor, "Excavation started.", kind="photo", days_ago=12, photo=True)
    await _seed_event(site["id"], project["id"], supervisor, "Excavation 60% complete.", kind="photo", days_ago=9, photo=True)
    voice_note_event = await _seed_event(
        site["id"], project["id"], supervisor,
        "Voice note: Foundation 60 percent complete, need full material takeoff for next pour, "
        "also flagging a safety issue on the east excavation edge.",
        kind="voice", days_ago=7,
    )
    await _seed_event(site["id"], project["id"], pm, "Progress update: on schedule, client walkthrough planned for next week.",
                      kind="text", days_ago=5)
    await _seed_event(site["id"], project["id"], supervisor, "Shuttering work started on north wing.",
                      kind="photo", days_ago=3, photo=True)

    # --- AI Analysis + Proposals — the real production code path, fed a
    #     hand-authored (not live-LLM) structured result. This is what
    #     produces both the "AI Proposal Examples" and the "AI-generated
    #     quantity takeoffs" (the materials list above) as genuine
    #     ai_proposals documents, not a separate fabricated shape. ---
    prompt_version = await memory_engine.get_or_create_prompt_version(
        name=intelligence_engine.PROMPT_NAME, version=intelligence_engine.PROMPT_VERSION,
        model=intelligence_engine.LLM_MODEL, system_prompt=intelligence_engine.EVENT_SYSTEM_PROMPT,
        notes="Seed-script registration — same prompt version real analyses use.",
    )
    analysis_doc = {
        "id": memory_engine._new_id("ana_"),
        "event_id": voice_note_event["id"],
        "transcript": voice_note_event["text_input"],
        "language_detected": "en",
        "structured": DEMO_STRUCTURED_ANALYSIS,
        "evidence": [{"kind": "text", "value": voice_note_event["text_input"]}],
        "model_versions": {"stt": None, "llm": intelligence_engine.LLM_MODEL},
        "prompt_version_id": prompt_version["id"],
        "prompt_name": intelligence_engine.PROMPT_NAME,
        "prompt_version": intelligence_engine.PROMPT_VERSION,
        "started_at": voice_note_event["server_created_at"],
        "finished_at": voice_note_event["server_created_at"],
        "error": None,
    }
    await memory_engine.put_ai_analysis(analysis_doc)
    await memory_engine.set_event_ai_status(voice_note_event["id"], "analyzed", analysis_doc["id"])
    result = await intelligence_engine.generate_proposals_for_event(voice_note_event["id"])
    print(f"  Atlas Demo Site: AI analysis seeded, {result.get('generated_count', 0)} proposals generated")

    # --- Operational items: progress/materials/labour/pending approvals,
    #     independent of the AI-generated ones above, so the project also
    #     has manually-raised items (matching real usage patterns). ---
    await operations_engine.create_item(
        actor=supervisor, site_id=site["id"], category="material_requirement",
        title="Waterproofing membrane for foundation", description="Required before backfill.",
        priority="high",
    )
    await operations_engine.create_item(
        actor=supervisor, site_id=site["id"], category="labour_requirement",
        title="Additional shuttering carpenters", description="2 more carpenters needed for north wing.",
        priority="normal",
    )
    await operations_engine.create_item(
        actor=pm, site_id=site["id"], category="client_approval",
        title="Approve client walkthrough date", description="Proposed for next Friday — needs client confirmation.",
        priority="high",
    )
    await operations_engine.create_item(
        actor=supervisor, site_id=site["id"], category="safety_observation",
        title="East excavation edge needs barricading", description="Flagged in voice note, not yet actioned.",
        priority="critical",
    )

    # --- Workflow: generate from the populated Villa template, then
    #     progress a couple of activities to produce real workflow
    #     history (status transitions, dependency-respecting cascade). ---
    generated = await workflow_engine.generate_workflow(project["id"], knowledge["villa_template"]["id"], actor=admin)
    by_name = {a["name"]: a for a in generated}
    excavation_activity = by_name.get("Excavation")
    if excavation_activity:
        await workflow_engine.set_status(excavation_activity["id"], "in_progress", actor=supervisor)
        await workflow_engine.set_status(excavation_activity["id"], "completed", actor=supervisor)
    print(f"  Atlas Demo Site: workflow generated ({len(generated)} activities), "
          f"excavation progressed to completed (unlocking Shuttering)")


# ---------------------------------------------------------------------------
# Seed metadata + completion summary
# ---------------------------------------------------------------------------
async def _write_seed_metadata() -> None:
    """Upserts a single record (never accumulates duplicates on repeat
    runs) so future tooling can detect what seeded this database and
    when, without needing to inspect the actual data."""
    await db.seed_metadata.update_one(
        {"_key": "current"},
        {"$set": {
            "_key": "current",
            "seed_version": SEED_VERSION,
            "atlas_version": APP_VERSION,
            "created_at": _iso(_NOW),
        }},
        upsert=True,
    )


async def _print_summary() -> None:
    counts = {
        "Users": await db.users.count_documents({}),
        "Projects": await db.projects.count_documents({}),
        "Sites": await db.sites.count_documents({}),
        "Events": await db.events.count_documents({}),
        "Knowledge items": await db.knowledge_items.count_documents({}),
        "Workflow activities": await db.workflow_activities.count_documents({}),
        "Operational items": await db.operational_items.count_documents({}),
        "AI proposals": await db.ai_proposals.count_documents({}),
    }
    print(f"\nSeed summary (seed_version={SEED_VERSION}, atlas_version={APP_VERSION}):")
    for label, count in counts.items():
        print(f"  {label:<22} {count}")


# ---------------------------------------------------------------------------
async def main(*, close_when_done: bool = True) -> None:
    print(f"Seeding database '{DB_NAME}'...")
    await ensure_indexes()

    print("Users:")
    users = await seed_users()

    print("Projects:")
    projects = await seed_projects()

    print("Knowledge Core:")
    admin = users["Atlas Admin 1"]
    knowledge = await seed_knowledge(admin)

    print("Sample project content:")
    for name in ("Luxury Villa", "Commercial Office", "Residential Apartment"):
        await seed_light_project_content(projects[name]["project"], projects[name]["site"], users)
    print("  seeded light content for 3 example projects")

    print("Atlas Demo Site (full showcase):")
    demo = projects["Atlas Demo Site"]
    await seed_demo_project_content(demo["project"], demo["site"], users, knowledge)

    await _write_seed_metadata()
    await _print_summary()

    print("\nLog in with any of:")
    for phone, name, role in USER_SEED:
        print(f"  {phone}  {name}  ({role})")

    if close_when_done:
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())
