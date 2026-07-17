"""Atlas Canonical Demo Project (ACDP) seeder.

Builds ONE permanent, chronologically consistent 18-month construction
project - "Atlas Demonstration Villa" - exercising every Atlas engine
(reality/capture, intelligence/AI proposals, operations, workflow,
reasoning/CRE) through the SAME production code paths real traffic
uses. See memory/ACDP_TIMELINE.md for the full narrative this script
implements, and memory/ACDP_README.md for how to use the result.

Design principles (matching scripts/db_seed.py's established
conventions - see that file's own docstring):
  - Every document is created through the SAME engine functions
    production traffic uses (memory_engine, operations_engine,
    knowledge_engine, workflow_engine, intelligence_engine,
    reasoning_engine) - never a raw dict insert, except where an engine
    itself has no non-HTTP entry point for something a script can't
    supply anyway (e.g. reality_engine.capture() expects FastAPI
    UploadFile objects - this script builds the identical event
    document shape directly and calls memory_engine.insert_event(),
    exactly as db_seed.py's own _seed_event() already does).
  - Idempotent and deterministic: a single top-level marker (the ACDP
    project's existence, looked up by its fixed code) guards the whole
    run - if it already exists, this script does nothing. A fixed
    random seed (ACDP_SEED) means every field of the generated content
    (which activity gets which event on which day, which proposals get
    accepted vs rejected, etc.) is identical on every run.
  - A completely separate user/phone range from db_seed.py's seeded
    accounts (9000000xxx) - see USER_SEED below (9800000xxx) - so this
    can be seeded into the same database as the regular dev seed
    without ever colliding with it.
  - Reuses db_seed.py's exact `_TINY_JPEG` constant for photo assets
    (imported, not duplicated) and the exact same `_seed_event` idiom.

Usage:
    cd backend
    python -m scripts.seed_demo_project
"""
from __future__ import annotations
import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")  # allow `python -m scripts.seed_demo_project` from backend/
from core.db import db, ensure_indexes, close_client  # noqa: E402
from engines import (  # noqa: E402
    memory_engine, operations_engine, knowledge_engine, workflow_engine,
    intelligence_engine, reasoning_engine,
)
from scripts.db_seed import _TINY_JPEG  # noqa: E402 - reused, not duplicated
from scripts import acdp_fixtures as fx  # noqa: E402

ACDP_SEED = 20260718  # fixed -> deterministic output on every run
ACDP_PROJECT_CODE = "ACDP-VILLA"
PROJECT_DURATION_DAYS = 548          # ~18 months
CURRENT_DAY = 520                    # "today" within the story - ~95% through
_NOW = datetime.now(timezone.utc)


def _story_date(day_offset: int) -> str:
    """Maps a day offset (0 = project start) to an absolute ISO timestamp,
    anchored so CURRENT_DAY lands on "now" - i.e. the whole 548-day story
    ends approximately today, exactly like a real, still-active project
    would. Matches db_seed.py's `_days_ago` convention (relative-to-now
    backdating), just parameterised by story day instead of a flat offset."""
    delta_days = CURRENT_DAY - day_offset
    return (_NOW - timedelta(days=delta_days)).isoformat()


# ---------------------------------------------------------------------------
# Phase calendar - hand-tuned, realistic overlap (foundation starts before
# earthwork finishes everywhere, MEP starts while masonry is still wrapping
# up elsewhere, etc.), not a computed critical-path schedule (see
# ACDP_TIMELINE.md for why a hand-authored calendar was chosen over a
# scheduler for this seed script).
# ---------------------------------------------------------------------------
PHASE_WINDOWS = {
    "Earthwork": (0, 45),
    "Foundation": (30, 90),
    "RCC Structure": (70, 230),
    "Masonry": (160, 270),
    "Waterproofing": (210, 330),
    "MEP": (230, 410),
    "Flooring": (310, 430),
    "False Ceiling": (340, 430),
    "Painting": (390, 480),
    "Joinery": (360, 460),
    "Facade": (290, 410),
    "Landscape": (360, 505),
    "Testing": (445, 510),
    "Snagging": (475, 530),
    "Client Handover": (528, 548),
}

# Phases where a deliberate delay episode is injected on ~1 activity per
# zone (see ACDP_TIMELINE.md's "recovered schedule" story beat) -
# concentrated on the phases construction delays realistically cluster
# around: structure (steel/weather), MEP (vendor), finishes (drawing
# revisions/client decisions).
DELAY_PRONE_PHASES = {"RCC Structure", "MEP", "Flooring", "Facade"}

USER_SEED = [
    ("9800000001", "Ravinder Kapoor", "management"),
    ("9800000002", "Ananya Sharma", "project_manager"),
    ("9800000003", "Suresh Yadav", "site_supervisor"),
    ("9800000004", "Manpreet Singh", "site_supervisor"),
    ("9800000005", "Dr. Vikram Mehta", "client"),
]


async def seed_acdp_users() -> dict[str, dict]:
    users: dict[str, dict] = {}
    for phone, name, role in USER_SEED:
        user = await memory_engine.upsert_user(phone=phone, name=name, role=role)
        if user["role"] != role:
            user = await memory_engine.set_user_role(user["id"], role)
        users[name] = user
    return users


async def seed_acdp_project_and_sites(admin: dict) -> tuple[dict, dict[str, dict]]:
    project = await db.projects.find_one({"code": ACDP_PROJECT_CODE}, {"_id": 0})
    if not project:
        project = await memory_engine.insert_project(
            name="Atlas Demonstration Villa", code=ACDP_PROJECT_CODE,
            location="New Chandigarh",
        )
    sites: dict[str, dict] = {}
    for zone in fx.ZONES:
        existing = await db.sites.find_one(
            {"project_id": project["id"], "name": zone["name"]}, {"_id": 0})
        if not existing:
            existing = await memory_engine.insert_site(
                project_id=project["id"], name=zone["name"], location=zone["location"])
        sites[zone["code"]] = existing
    return project, sites


async def _get_or_create_category(admin: dict, name: str) -> dict:
    existing = await db.knowledge_items.find_one({"type": "category", "name": name}, {"_id": 0})
    if existing:
        return existing
    return await knowledge_engine.create_item(actor=admin, type_="category", name=name, status="active")


async def _get_or_create_phase(admin: dict, name: str) -> dict:
    existing = await db.knowledge_items.find_one({"type": "phase", "name": name}, {"_id": 0})
    if existing:
        return existing
    return await knowledge_engine.create_item(actor=admin, type_="phase", name=name, status="active")


async def seed_acdp_template(admin: dict) -> dict:
    """Builds the ACDP-specific Workflow Template + Activity Library
    entries (~360 activities across 15 phases x applicable zones).
    Guarded by natural-key lookup, exactly like db_seed.py's own
    _get_or_create_knowledge - never duplicated on rerun. Sets up
    depends_on relationships (sequential within each zone's phase, and
    phase-to-phase within the same zone) BEFORE generation, so
    workflow_engine.generate_workflow()'s existing, unmodified
    dependency-translation logic produces a real, reasoned dependency
    graph - not a flat list.
    """
    template = await db.knowledge_items.find_one(
        {"type": "workflow_template", "name": "ACDP Villa Master Template"}, {"_id": 0})
    if template and any(r["type"] == "includes_activity" for r in template.get("relationships", [])):
        return template  # already fully built

    if not template:
        template = await knowledge_engine.create_item(
            actor=admin, type_="workflow_template", name="ACDP Villa Master Template",
            description="Full activity sequence for the Atlas Demonstration Villa - "
                        "15 phases across 6 zones, ~360 activities.",
            status="active",
        )

    # last_activity_id_per_zone tracks the most recently created activity
    # in each zone (across ANY phase so far) so the next phase's first
    # zone-activity can depend on it - this is what produces cross-phase
    # dependency chains, not just within-phase ones.
    last_activity_id_per_zone: dict[str, str] = {}
    order = 0
    for phase in fx.PHASES:
        category = await _get_or_create_category(admin, phase["category"])
        phase_item = await _get_or_create_phase(admin, phase["phase_label"])
        for zone_code in phase["zones"]:
            zone = next(z for z in fx.ZONES if z["code"] == zone_code)
            prev_activity_id = last_activity_id_per_zone.get(zone_code)
            for name, trade, unit, duration, inspect in phase["activities"]:
                full_name = f"{name} — {zone['name']}"
                act = await db.knowledge_items.find_one(
                    {"type": "activity", "name": full_name}, {"_id": 0})
                if not act:
                    act = await knowledge_engine.create_item(
                        actor=admin, type_="activity", name=full_name,
                        category_id=category["id"], phase_id=phase_item["id"],
                        trade=trade, unit=unit, default_duration_days=duration,
                        requires_inspection=inspect, status="active",
                        description=f"{name} for {zone['name']}.",
                        applicability={"project_types": ["villa", "residential"]},
                    )
                    if prev_activity_id:
                        await knowledge_engine.add_relationship(
                            act["id"], actor=admin, type_="depends_on", target_id=prev_activity_id)
                    act = await knowledge_engine.get_item(act["id"])
                await knowledge_engine.add_relationship(
                    template["id"], actor=admin, type_="includes_activity",
                    target_id=act["id"], metadata={"order": order})
                order += 1
                prev_activity_id = act["id"]
            last_activity_id_per_zone[zone_code] = prev_activity_id

    return await knowledge_engine.get_item(template["id"])


def _activity_metadata_sequence():
    """Yields (phase_label, category, zone_code, zone_name, base_name, trade)
    in EXACTLY the same order seed_acdp_template() creates knowledge
    activities - so the Nth tuple this yields corresponds to the Nth
    workflow_activity generate_workflow() returns (same phase -> zone ->
    activity nesting, same iteration order, nothing re-sorted in between)."""
    for phase in fx.PHASES:
        for zone_code in phase["zones"]:
            zone = next(z for z in fx.ZONES if z["code"] == zone_code)
            for name, trade, unit, duration, inspect in phase["activities"]:
                yield phase["phase_label"], phase["category"], zone_code, zone["name"], name, trade


def _compute_placements(rng: random.Random) -> list[dict]:
    """One entry per activity instance (in generation order), each with a
    computed (start_day, end_day) inside its phase's calendar window,
    plus whether it's one of the deliberately delayed instances. Zones
    within a phase get an even slice of the phase window each (with a
    little jitter) so multiple zones progress visibly in parallel,
    exactly like real crews working different parts of the site at once.
    """
    placements = []
    # Group by (phase_label, zone_code) to give each group a contiguous slice
    groups: dict[tuple, list[int]] = {}
    meta_list = list(_activity_metadata_sequence())
    for idx, (phase_label, category, zone_code, zone_name, name, trade) in enumerate(meta_list):
        groups.setdefault((phase_label, zone_code), []).append(idx)

    for (phase_label, zone_code), indices in groups.items():
        window_start, window_end = PHASE_WINDOWS[phase_label]
        span = max(window_end - window_start, len(indices) * 2)
        # A little per-zone jitter so not every zone starts on day 0 of the window.
        zone_jitter = rng.randint(0, max(1, span // 6))
        cursor = window_start + zone_jitter
        for i, idx in enumerate(indices):
            phase_label_, category, zone_code_, zone_name, name, trade = meta_list[idx]
            duration = next(d for n, t, u, d, insp in
                            next(p for p in fx.PHASES if p["phase_label"] == phase_label)["activities"]
                            if n == name)
            is_delay = phase_label in DELAY_PRONE_PHASES and rng.random() < 0.08
            actual_duration = duration * (rng.uniform(2.0, 3.5) if is_delay else rng.uniform(0.8, 1.3))
            start = min(cursor, window_end - 1)
            end = min(start + max(1, round(actual_duration)), window_end + (15 if is_delay else 0))
            cursor = end
            placements.append({
                "index": idx, "phase_label": phase_label, "category": category,
                "zone_code": zone_code, "zone_name": zone_name, "name": name, "trade": trade,
                "start_day": start, "end_day": end, "delayed": is_delay,
            })
    placements.sort(key=lambda p: p["index"])
    return placements


async def _seed_event(site_id: str, project_id: str, user: dict, text: str, kind: str,
                      day_offset: int, photo: bool = False,
                      requires_client_approval: bool = False) -> dict:
    """Identical shape to db_seed.py's _seed_event, parameterised by
    absolute story day instead of days-ago, and extended with the
    Client Approval Workflow's requires_client_approval marker field."""
    event_id = memory_engine._new_id("evt_")
    photo_ids = []
    if photo:
        asset = await memory_engine.put_asset(event_id, "photo", "image/jpeg", _TINY_JPEG)
        photo_ids.append(asset["id"])
    when = _story_date(day_offset)
    doc = {
        "id": event_id, "site_id": site_id, "project_id": project_id, "activity_id": None,
        "user_id": user["id"], "user_name": user["name"], "kind": kind, "text_input": text,
        "audio_asset_id": None, "photo_asset_ids": photo_ids, "gps": None,
        "client_created_at": when, "server_created_at": when, "app_version": "acdp-seed",
        "ai_status": "skipped", "ai_analysis_id": None,
        "proposals_status": "pending", "proposals_error": None,
        "requires_client_approval": requires_client_approval,
    }
    await memory_engine.insert_event(doc)
    return doc


async def _maybe_generate_ai_proposals(rng: random.Random, event: dict, project: dict,
                                       actor: dict, phase_label: str, zone_name: str,
                                       activity_name: str, trade: str, outcome_cycle: list[str]) -> int:
    """Runs the REAL intelligence_engine proposal pipeline
    (generate_proposals_for_event) fed a hand-authored, phase-appropriate
    structured analysis - the same DEMO_STRUCTURED_ANALYSIS pattern
    db_seed.py's own seed_demo_project_content already established, just
    parameterised per call instead of one fixed example. Then applies one
    of accept / reject / modify-then-accept / leave-pending (ignored) to
    each generated proposal, cycling deterministically through
    outcome_cycle so all four outcomes genuinely exist in the dataset."""
    material_name, unit = rng.choice(fx.MATERIAL_ITEMS)
    structured = {
        "type": "voice_note", "title": f"{activity_name} update — {zone_name}",
        "summary": f"{activity_name} progress in {zone_name}; material and labour needs flagged.",
        "materials": [{"name": material_name, "quantity": rng.randint(10, 200), "unit": unit,
                       "required_date": None, "priority": rng.choice(["normal", "high"]),
                       "trade": trade, "area": zone_name, "reason": f"Needed for {activity_name}",
                       "confidence": "high"}],
        "labour": [{"trade": trade, "count": rng.randint(2, 8), "required_date": None,
                    "priority": "normal", "area": zone_name, "reason": f"{activity_name} crew",
                    "confidence": "medium"}],
        "equipment": [], "client_approvals": [], "drawing_requests": [], "inspections": [],
        "safety_observations": [], "quality_observations": [],
        "commitments": [], "follow_ups": [], "issues": [], "work_done": [activity_name],
        "urgency": "normal", "language_detected": "en",
    }
    prompt_version = await memory_engine.get_or_create_prompt_version(
        name=intelligence_engine.PROMPT_NAME, version=intelligence_engine.PROMPT_VERSION,
        model=intelligence_engine.LLM_MODEL, system_prompt=intelligence_engine.EVENT_SYSTEM_PROMPT,
        notes="ACDP seed registration — same prompt version real analyses use.",
    )
    analysis_doc = {
        "id": memory_engine._new_id("ana_"), "event_id": event["id"],
        "transcript": event["text_input"], "language_detected": "en", "structured": structured,
        "evidence": [{"kind": "text", "value": event["text_input"]}],
        "model_versions": {"stt": None, "llm": intelligence_engine.LLM_MODEL},
        "prompt_version_id": prompt_version["id"], "prompt_name": intelligence_engine.PROMPT_NAME,
        "prompt_version": intelligence_engine.PROMPT_VERSION,
        "started_at": event["server_created_at"], "finished_at": event["server_created_at"], "error": None,
    }
    await memory_engine.put_ai_analysis(analysis_doc)
    await memory_engine.set_event_ai_status(event["id"], "analyzed", analysis_doc["id"])
    result = await intelligence_engine.generate_proposals_for_event(event["id"])
    proposals = await operations_engine.list_ai_proposals(event_id=event["id"])
    for p in proposals:
        outcome = outcome_cycle[0]
        outcome_cycle.append(outcome_cycle.pop(0))  # rotate
        if outcome == "accepted":
            await operations_engine.accept_ai_proposal(proposal_id=p["id"], actor=actor)
        elif outcome == "rejected":
            await operations_engine.reject_ai_proposal(
                proposal_id=p["id"], actor=actor, reason="Not needed — already sourced locally.")
        elif outcome == "modified":
            await operations_engine.accept_ai_proposal(
                proposal_id=p["id"], actor=actor,
                edits={"priority": "high", "description": p.get("description", "") + " (quantity revised on-site)"})
        # "ignored": leave decision=pending, untouched — a real, common outcome.
    return result.get("generated_count", 0)


async def simulate_acdp_timeline(project: dict, sites: dict[str, dict], users: dict[str, dict],
                                 template: dict, admin: dict) -> dict:
    """The main chronological walk. Processes every generated workflow
    activity IN GENERATION ORDER (== dependency order, since each
    activity's only dependency is the previous one in its zone's chain -
    see seed_acdp_template) so workflow_engine.set_status()'s own,
    unmodified dependency check is always naturally satisfied without
    this script needing to duplicate that logic."""
    rng = random.Random(ACDP_SEED)
    pm, sup1, sup2, client = users["Ananya Sharma"], users["Suresh Yadav"], users["Manpreet Singh"], users["Dr. Vikram Mehta"]
    supervisors = [sup1, sup2]

    activities = await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)
    placements = _compute_placements(rng)
    assert len(activities) == len(placements), \
        f"activity/placement count mismatch: {len(activities)} vs {len(placements)} — catalog and generator drifted apart"

    counts = {"events": 0, "voice": 0, "photo": 0, "text": 0, "operational_items": 0,
             "client_approvals": 0, "ai_proposals": 0, "cre_runs": 0}
    ai_outcome_cycle = ["accepted", "rejected", "modified", "ignored"]
    ai_proposal_budget = 55  # spread across the timeline, see ACDP_TIMELINE.md
    ai_proposal_stride = max(1, len(activities) // ai_proposal_budget)
    reasoning_checkpoints = {round(PROJECT_DURATION_DAYS * m / 18) for m in range(1, 19)}

    for act_doc, placement in zip(activities, placements):
        site = sites[placement["zone_code"]]
        supervisor = supervisors[hash(placement["zone_code"]) % 2]
        start_day, end_day = placement["start_day"], min(placement["end_day"], CURRENT_DAY)
        activity_name, zone_name = placement["name"], placement["zone_name"]

        # ---- workflow status transition ----
        if placement["start_day"] <= CURRENT_DAY:
            await workflow_engine.set_status(act_doc["id"], "in_progress", actor=supervisor)
            if placement["delayed"]:
                await workflow_engine.set_status(act_doc["id"], "blocked", actor=supervisor)
                await operations_engine.create_item(
                    actor=supervisor, site_id=site["id"], category="site_issue",
                    title=f"{activity_name} blocked in {zone_name}",
                    description=f"Delayed due to {rng.choice(fx.DELAY_REASONS)}.",
                    priority="high",
                )
                counts["operational_items"] += 1
                await workflow_engine.set_status(act_doc["id"], "in_progress", actor=supervisor)
            if placement["end_day"] <= CURRENT_DAY:
                await workflow_engine.set_status(act_doc["id"], "completed", actor=supervisor)

        # ---- events across the activity's date span ----
        n_events = rng.choice([1, 2, 2, 2, 3, 3])
        last_event = None
        for i in range(n_events):
            day = min(start_day + rng.randint(0, max(1, end_day - start_day)), CURRENT_DAY)
            roll = rng.random()
            kind = "voice" if roll < 0.13 else ("photo" if roll < 0.45 else "text")
            template_bank = fx.VOICE_TEMPLATES if kind == "voice" else fx.TEXT_TEMPLATES
            text = rng.choice(template_bank).format(
                activity=activity_name, zone=zone_name, phase=placement["phase_label"])
            actor = supervisor if kind in ("voice", "photo") else pm
            wants_approval = (
                placement["phase_label"] in (
                    "Painting", "Facade", "Flooring", "Joinery", "False Ceiling", "Landscape",
                )
                and rng.random() < 0.22
            )
            evt = await _seed_event(
                site["id"], project["id"], actor, text, kind=kind, day_offset=day,
                photo=(kind == "photo"), requires_client_approval=wants_approval,
            )
            counts["events"] += 1
            counts[kind if kind != "photo" else "photo"] += 1
            last_event = evt

            if wants_approval:
                item = await operations_engine.find_open_item_for_event(evt["id"], category="client_approval")
                if not item:
                    topic = rng.choice(fx.CLIENT_APPROVAL_TOPICS)
                    item = await operations_engine.create_item(
                        actor=pm, site_id=site["id"], category="client_approval",
                        title=f"Approval needed: {topic}", description=f"Raised from site update on {activity_name}.",
                        origin_type="manual", inherited_evidence_event_id=evt["id"],
                    )
                counts["operational_items"] += 1
                counts["client_approvals"] += 1
                decision_roll = rng.random()
                if decision_roll < 0.55:
                    await operations_engine.transition_status(
                        item_id=item["id"], to_status="fulfilled", actor=client, note="Approved, please proceed.")
                elif decision_roll < 0.75:
                    await operations_engine.request_clarification(
                        item_id=item["id"], actor=client, note="Can you share more photos before I decide?")
                elif decision_roll < 0.90:
                    await operations_engine.transition_status(
                        item_id=item["id"], to_status="cancelled", actor=client, note="Please revise and resend.")
                # else: left pending — a real, common "not yet decided" state

        # ---- scattered operational items (material/labour/safety) ----
        if rng.random() < 0.22:
            category = rng.choice(["material_requirement", "labour_requirement", "safety_observation"])
            if category == "material_requirement":
                material_name, unit = rng.choice(fx.MATERIAL_ITEMS)
                await operations_engine.create_item(
                    actor=supervisor, site_id=site["id"], category=category,
                    title=f"{material_name} for {activity_name}", description=f"Needed in {zone_name}.",
                    priority=rng.choice(["normal", "high"]),
                )
            elif category == "labour_requirement":
                await operations_engine.create_item(
                    actor=supervisor, site_id=site["id"], category=category,
                    title=f"Additional {placement['trade']} crew — {zone_name}",
                    description=f"Needed to keep {activity_name} on schedule.", priority="normal",
                )
            else:
                await operations_engine.create_item(
                    actor=supervisor, site_id=site["id"], category=category,
                    title=rng.choice(fx.SAFETY_OBSERVATIONS).format(zone=zone_name, activity=activity_name),
                    description="Flagged during routine site walk.", priority=rng.choice(["normal", "high", "critical"]),
                )
            counts["operational_items"] += 1

        # ---- AI proposals (spread across the timeline) ----
        if last_event and placement["index"] % ai_proposal_stride == 0 and counts["ai_proposals"] < ai_proposal_budget:
            generated = await _maybe_generate_ai_proposals(
                rng, last_event, project, pm, placement["phase_label"], zone_name,
                activity_name, placement["trade"], ai_outcome_cycle)
            counts["ai_proposals"] += generated

        # ---- CRE reasoning run at each monthly checkpoint ----
        due = {c for c in reasoning_checkpoints if c <= end_day}
        if due:
            await reasoning_engine.run_reasoning(project["id"], actor=admin, include_ai=False)
            counts["cre_runs"] += 1
            reasoning_checkpoints -= due

    # Final reasoning pass over the completed state.
    await reasoning_engine.run_reasoning(project["id"], actor=admin, include_ai=False)
    counts["cre_runs"] += 1

    return counts


async def main(*, close_when_done: bool = True) -> None:
    await ensure_indexes()

    existing = await db.projects.find_one({"code": ACDP_PROJECT_CODE}, {"_id": 0})
    if existing:
        n_events = await db.events.count_documents({"project_id": existing["id"]})
        print(f"Atlas Demonstration Villa already seeded (project {existing['id']}, "
              f"{n_events} events) — nothing to do. Delete the project (or reset the "
              f"database) to reseed from scratch.")
        if close_when_done:
            await close_client()
        return

    print("Seeding Atlas Canonical Demo Project (ACDP) — this creates ~360 workflow "
         "activities and ~800 events across an 18-month simulated timeline; it will "
         "take a few minutes.\n")

    users = await seed_acdp_users()
    print(f"  users: {len(users)} ready (1 management, 1 PM, 2 supervisors, 1 client)")
    admin = users["Ravinder Kapoor"]

    project, sites = await seed_acdp_project_and_sites(admin)
    print(f"  project: {project['name']} ({len(sites)} sites/zones)")

    template = await seed_acdp_template(admin)
    n_activities = sum(1 for r in template.get("relationships", []) if r["type"] == "includes_activity")
    print(f"  knowledge: ACDP Villa Master Template ready ({n_activities} activities)")

    counts = await simulate_acdp_timeline(project, sites, users, template, admin)

    print("\nACDP seed complete:")
    print(f"  workflow activities : {n_activities}")
    print(f"  events              : {counts['events']} "
         f"(voice {counts['voice']}, photo {counts['photo']}, text {counts['text']})")
    print(f"  operational items   : {counts['operational_items']} "
         f"(client approvals: {counts['client_approvals']})")
    print(f"  AI proposals        : {counts['ai_proposals']}")
    print(f"  CRE reasoning runs  : {counts['cre_runs']}")
    print(f"\nLog in as the client to see the Client Dashboard: phone {USER_SEED[4][0]}, "
         f"role client.")
    print(f"Log in as management for the Executive Briefing: phone {USER_SEED[0][0]}, "
         f"role management.")

    if close_when_done:
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())



