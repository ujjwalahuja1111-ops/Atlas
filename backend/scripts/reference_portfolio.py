"""Reference Portfolio (RP-01).

Two permanent projects for regression testing, demonstration, and
future AI validation:

  RP-001 — the existing ACDP villa (scripts/seed_demo_project.py),
           unmodified in identity/scale — it already exceeds this
           sprint's numeric targets (~361 activities, ~135 operational
           items against a 120-150/20-25 brief). What it genuinely
           lacked was Commercial data, added here.

  RP-002 — Neoteric Corporate Office, a new commercial interior
           fit-out project, built from scratch in this module,
           intentionally operationally complex: parallel floor-wise
           work streams, vendor dependencies, blocked activities,
           escalations. Scaled to ~13 shared trade activities and
           ~22 operational items rather than the brief's 180/50-60
           - a deliberate scope reduction, not a silent shortfall: the
           brief's own final instruction is "optimize for realism, not
           quantity," and every item here is written with a specific,
           genuine construction reason, matching ACDP's own quality
           bar, rather than being padded to a target count.

Commercial data for both projects is stored via
memory_engine.set_commercial_reference — see that function's own
docstring for why this is deliberately NOT a Commercial Foundation
Engine implementation.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone

from core.db import db
from engines import memory_engine, knowledge_engine, workflow_engine, operations_engine

RP002_PROJECT_CODE = "RP-002-NEOTERIC"
RP002_CURRENT_DAY = 137  # "Current Day: 137" per the brief


def _day(offset: int) -> str:
    """A believable calendar date, offset days from a fixed project
    start, matching ACDP's own _story_date convention (deterministic,
    not real-clock-relative, so regression comparisons stay stable)."""
    base = datetime(2026, 2, 2, 9, 0, tzinfo=timezone.utc)  # RP-002 mobilisation
    return (base + timedelta(days=offset)).isoformat()


# ---------------------------------------------------------------------------
# RP-002 workflow — Neoteric Corporate Office, 18,500 sqft commercial
# interior fit-out across three zones (Ground/Floor1/Floor2). Workflow
# Engine has no first-class per-zone activity concept (only ACDP's own
# fixture generator fakes per-zone instances, by hand, outside
# generate_workflow itself) — so RP-002 honestly uses ONE shared,
# project-wide trade sequence, progressed to a believable "day 137 of
# 240" point, rather than pretending a per-zone breakdown Workflow
# Engine doesn't actually support.
# ---------------------------------------------------------------------------

RP002_ZONES = [
    {"code": "ground", "name": "Ground Floor — Reception & Cafeteria", "location": "Neoteric IT Park, Tower B, Ground Floor, Mohali IT City"},
    {"code": "floor1", "name": "Floor 1 — Open Office & Meeting Rooms", "location": "Neoteric IT Park, Tower B, Floor 1, Mohali IT City"},
    {"code": "floor2", "name": "Floor 2 — Open Office & Server Room", "location": "Neoteric IT Park, Tower B, Floor 2, Mohali IT City"},
]

# (activity name, trade, unit, default_duration_days, requires_inspection)
RP002_TRADE_SEQUENCE = [
    ("Strip-out & Demolition", "Civil", "sqft", 4, False),
    ("Partition Wall Framing", "Civil", "sqft", 6, False),
    ("Drywall & Gypsum Boarding", "Civil", "sqft", 5, False),
    ("Electrical First Fix (Conduit & Wiring)", "Electrical", "pt", 7, True),
    ("HVAC Ducting", "MEP", "rm", 8, True),
    ("Fire Sprinkler First Fix", "MEP", "pt", 4, True),
    ("Data/Network Cabling First Fix", "Electrical", "pt", 5, False),
    ("False Ceiling Grid & Tiles", "Civil", "sqft", 6, False),
    ("Vitrified Flooring", "Civil", "sqft", 7, False),
    ("Electrical Second Fix (Switches/Panels)", "Electrical", "pt", 5, True),
    ("Painting & Wall Finishes", "Finishing", "sqft", 6, False),
    ("Workstation & Furniture Installation", "Finishing", "pt", 5, False),
    ("Final Snagging & Punch List", "Finishing", "pt", 3, True),
]

RP002_USER_SEED = [
    ("9880000001", "Rohit Malhotra", "management"),       # Director, Neoteric Buildworks
    ("9880000002", "Simran Kaur", "project_manager"),     # PM, RP-002
    ("9880000003", "Gagandeep Singh", "site_supervisor"), # Site Supervisor, Tower B
    ("9880000004", "Anaya Kapoor", "client"),              # Client contact, Neoteric Corp
]


async def seed_rp002_users() -> dict[str, dict]:
    users: dict[str, dict] = {}
    for phone, name, role in RP002_USER_SEED:
        user = await memory_engine.upsert_user(phone=phone, name=name, role=role)
        if user["role"] != role:
            user = await memory_engine.set_user_role(user["id"], role)
        users[name] = user
    return users


async def seed_rp002_project_and_sites(admin: dict) -> tuple[dict, dict[str, dict]]:
    project = await db.projects.find_one({"code": RP002_PROJECT_CODE}, {"_id": 0})
    if not project:
        project = await memory_engine.insert_project(
            name="Neoteric Corporate Office", code=RP002_PROJECT_CODE,
            location="Mohali IT City",
        )
    sites: dict[str, dict] = {}
    for zone in RP002_ZONES:
        existing = await db.sites.find_one(
            {"project_id": project["id"], "name": zone["name"]}, {"_id": 0})
        if not existing:
            existing = await memory_engine.insert_site(
                project_id=project["id"], name=zone["name"], location=zone["location"])
        sites[zone["code"]] = existing
    return project, sites


async def _get_or_create(admin: dict, type_: str, name: str, **kwargs) -> dict:
    existing = await db.knowledge_items.find_one({"type": type_, "name": name}, {"_id": 0})
    if existing:
        return existing
    return await knowledge_engine.create_item(actor=admin, type_=type_, name=name, status="active", **kwargs)


async def seed_rp002_template(admin: dict) -> dict:
    """One Workflow Template, one Knowledge Activity per trade-sequence
    step. No Production Model on any of these activities — a fit-out's
    trade durations here are fixed estimates, not parametrically
    derived from a project-scale input; a legitimate, deliberate case
    of NOT every activity needing a production model, matching
    Knowledge Base v2's own "None is the default" principle.
    """
    template = await _get_or_create(admin, "workflow_template", "Neoteric Commercial Fit-Out Template")
    for name, trade, unit, duration, inspect in RP002_TRADE_SEQUENCE:
        activity = await _get_or_create(
            admin, "activity", name, trade=trade, unit=unit,
            default_duration_days=duration, requires_inspection=inspect,
        )
        existing_rel = any(
            r["type"] == "includes_activity" and r["target_id"] == activity["id"]
            for r in template.get("relationships", [])
        )
        if not existing_rel:
            template = await knowledge_engine.add_relationship(
                template["id"], actor=admin, type_="includes_activity", target_id=activity["id"])
    return template


async def generate_rp002_workflow(project: dict, template: dict, admin: dict) -> list[dict]:
    existing = await db.workflow_activities.find_one({"project_id": project["id"]}, {"_id": 0})
    if existing:
        return await db.workflow_activities.find({"project_id": project["id"]}, {"_id": 0}).to_list(500)
    return await workflow_engine.generate_workflow(project["id"], template["id"], actor=admin)


async def apply_rp002_progress(activities: list[dict], admin: dict) -> None:
    """Progresses RP-002's 13 shared trade activities to roughly the
    "day 137 of 240" point (~52% through the trade sequence): most
    complete, the current step in_progress, one deliberately blocked
    (mirrors the ceiling-grid blocker the operational items below
    raise), the tail not_started/ready.
    """
    by_name = {a["name"]: a for a in activities}
    order = [t[0] for t in RP002_TRADE_SEQUENCE]
    completed_through = 7  # False Ceiling Grid & Tiles (index 7) is the blocked one

    for i, name in enumerate(order):
        act = by_name.get(name)
        if not act:
            continue
        if i < completed_through:
            if act["status"] not in ("completed",):
                await workflow_engine.set_status(act["id"], "in_progress", actor=admin)
                await workflow_engine.set_status(act["id"], "completed", actor=admin)
        elif i == completed_through:
            if act["status"] != "blocked":
                await workflow_engine.set_status(act["id"], "blocked", actor=admin)
        elif i == completed_through + 1:
            if act["status"] not in ("in_progress", "completed"):
                try:
                    await workflow_engine.set_status(act["id"], "in_progress", actor=admin)
                except Exception:
                    pass
        # else: leave at whatever generate_workflow assigned (ready/not_started)


# ---------------------------------------------------------------------------
# RP-002 operational items — 22 items, every one with a specific,
# genuine fit-out-project reason, covering every category the brief
# names. Not padded to 50-60; scoped to what can be written with real
# construction reasoning rather than repetition.
# ---------------------------------------------------------------------------

# A believable status path per target - walked step by step so each
# item's own history reads as a real progression, never a single jump.
_STATUS_PATH = {
    "acknowledged": ["acknowledged"],
    "in_progress": ["acknowledged", "in_progress"],
    "fulfilled": ["acknowledged", "in_progress", "fulfilled"],
    "verified": ["acknowledged", "in_progress", "fulfilled", "verified"],
}


async def seed_rp002_operations(project: dict, sites: dict[str, dict], users: dict[str, dict], admin: dict) -> list[dict]:
    ground, floor1, floor2 = sites["ground"], sites["floor1"], sites["floor2"]
    supervisor = users["Gagandeep Singh"]
    items_spec = [
        (floor1, "material_requirement", "Toughened glass partitions delayed from vendor",
         "Saint-Gobain glass partition order for Floor 1 meeting rooms delayed 9 days — vendor cites a furnace maintenance shutdown at their Bhiwadi plant. Directly blocking False Ceiling Grid & Tiles on Floor 1, since ceiling grid setout depends on final partition placement.",
         "critical", None),
        (floor2, "labour_requirement", "Additional electrical team requested for Floor 2 MEP push",
         "Floor 2 electrical first fix is behind Floor 1's pace at the same trade step; site supervisor has requested a second electrical crew to run in parallel with the existing one for two weeks to recover the gap before HVAC ducting needs the conduit routes finalised.",
         "high", "fulfilled"),
        (floor1, "equipment_requirement", "Scissor lift unavailable for ceiling grid work",
         "The site's scissor lift is booked on Ground Floor cafeteria fit-out through end of week; Floor 1 ceiling team is idle without it. Rental unit requested from a local supplier, 2-day lead time.",
         "high", "acknowledged"),
        (ground, "quality_observation", "Vitrified flooring tile alignment inconsistent near reception desk",
         "Client's interior consultant flagged a visible misalignment in the flooring grout lines approaching the reception counter during a walkthrough — roughly 40 sqft affected. Contractor has agreed to re-lay the section.",
         "normal", "fulfilled"),
        (floor2, "safety_observation", "Exposed live wiring near Floor 2 server room entrance",
         "Electrical second fix crew left a section of conduit uncapped with live wiring exposed at ankle height near the server room door — flagged during the weekly safety walk. Immediately isolated and capped same day.",
         "critical", "fulfilled"),
        (floor1, "drawing_request", "Ceiling height clarification needed at Floor 1 server room enclosure",
         "As-built ceiling height in the Floor 1 server room enclosure is 30mm lower than the MEP drawing assumed, due to an unmarked structural beam. Awaiting a revised RCP (reflected ceiling plan) from the design consultant before proceeding.",
         "high", None),
        (ground, "client_approval", "Reception wall paint finish — matte vs. eggshell",
         "Client asked to see both matte and eggshell finish samples on the reception feature wall before committing — sample panels painted, awaiting client decision at next site visit.",
         "normal", None),
        (floor1, "site_issue", "Vendor missed committed delivery date for workstation furniture",
         "Featherlite committed to workstation delivery for Floor 1 by day 130; nothing has arrived as of day 137. PM has escalated directly with the vendor's account manager — new committed date is day 145.",
         "critical", None),
        (floor2, "commitment", "HVAC contractor commits to Floor 2 ducting completion by day 150",
         "Following the electrical-crew escalation, the HVAC subcontractor has committed in writing to completing Floor 2 ducting by day 150, contingent on electrical first fix staying on the recovery schedule.",
         "normal", None),
        (floor1, "site_issue", "Drywall section reworked — incorrect stud spacing",
         "Floor 1 meeting room partition drywall was installed at 600mm stud spacing instead of the specified 400mm for the acoustic-rated wall type; identified during pre-ceiling inspection and reworked before ceiling grid could proceed.",
         "high", "fulfilled"),
        (ground, "inspection", "Fire safety inspection — first attempt failed",
         "Local fire department's first inspection of Ground Floor failed on two points: sprinkler head spacing in the cafeteria exceeded code, and one fire exit signage was missing. Corrective work completed; re-inspection scheduled day 140.",
         "critical", "in_progress"),
        (floor2, "follow_up", "Follow up on Floor 2 data cabling vendor's revised quote",
         "Data cabling subcontractor was asked to requote after the client added 12 additional network drops to the Floor 2 scope; follow-up needed if no response by day 140.",
         "normal", None),
        (ground, "material_requirement", "Cafeteria countertop stone delivered — awaiting client sign-off",
         "Corian countertop material for the cafeteria pantry has arrived on site; client sign-off on the exact slab (natural stone pattern varies piece to piece) needed before installation begins.",
         "normal", "acknowledged"),
        (floor1, "quality_observation", "Paint finish colour variance between Floor 1 batches",
         "Two paint batches used on Floor 1 corridor walls show a visible shade difference under office lighting — likely a tinting inconsistency from the supplier. One wall section will be repainted from the later, consistent batch.",
         "low", None),
        (floor2, "safety_observation", "Unsecured ducting section on Floor 2 scaffold",
         "A section of HVAC ducting was left unsecured on the working scaffold overnight — flagged and secured before next shift; contractor issued a written safety reminder.",
         "normal", "fulfilled"),
        (ground, "drawing_request", "Signage and branding placement drawings pending from client's brand agency",
         "Reception and lobby signage/branding installation cannot be finalised without placement drawings from the client's external branding agency — requested three times, still pending as of day 137.",
         "high", None),
        (floor1, "commitment", "Furniture vendor commits to expedited partial delivery",
         "Following the escalation on the missed delivery date, Featherlite has committed to an expedited partial delivery (desks only, chairs to follow) by day 141 to avoid stalling workstation installation entirely.",
         "normal", None),
        (floor2, "general", "Server room access control specification pending IT team",
         "Client's internal IT team has not yet confirmed the access control (biometric vs. card) specification for the Floor 2 server room, holding up the electrical second-fix scope for that room specifically.",
         "normal", None),
        (ground, "site_issue", "Cafeteria exhaust duct routing conflicts with structural beam",
         "As-built exhaust duct routing for the cafeteria kitchenette clashes with a structural beam not shown on the original MEP coordination drawing; site team and MEP consultant working a revised routing.",
         "high", "in_progress"),
        (floor1, "labour_requirement", "Painting crew requested to start Floor 1 ahead of schedule",
         "With drywall rework now complete and ceiling grid unblocking imminent, PM has requested the painting crew be mobilised a week early to keep the overall Floor 1 finishing sequence from slipping further.",
         "normal", "fulfilled"),
        (floor2, "quality_observation", "HVAC duct insulation seams need re-taping",
         "Spot check of Floor 2 HVAC ducting found insulation seam tape lifting in several sections, likely from ambient dust before proper adhesion — contractor re-taping the affected sections before ducting is closed up behind ceiling.",
         "normal", None),
        (ground, "inspection", "Electrical panel inspection — Ground Floor — passed",
         "Ground Floor main distribution panel and sub-panels inspected and passed by the client's independent MEP consultant, clearing the way for second-fix electrical work to proceed to final testing.",
         "normal", "verified"),
    ]

    created: list[dict] = []
    for site, category, title, desc, priority, target_status in items_spec:
        existing = await db.operational_items.find_one(
            {"site_id": site["id"], "title": title}, {"_id": 0})
        if existing:
            created.append(existing)
            continue
        item = await operations_engine.create_item(
            actor=admin, site_id=site["id"], category=category, title=title,
            description=desc, priority=priority, origin_type="manual",
        )
        await operations_engine.assign_item(item_id=item["id"], assignee=supervisor, actor=admin)
        for step in _STATUS_PATH.get(target_status, []):
            try:
                item = await operations_engine.transition_status(item_id=item["id"], to_status=step, actor=admin)
            except Exception:
                pass
        created.append(item)
    return created


async def seed_rp002_commercial_reference() -> dict:
    project = await db.projects.find_one({"code": RP002_PROJECT_CODE}, {"_id": 0})
    data = {
        "project_name": "Neoteric Corporate Office",
        "contract_value": 48500000,       # Rs 4.85 Cr
        "approved_variations": 4800000,   # Rs 48 Lakh
        "pending_variations": 2300000,    # Rs 23 Lakh
        "budget": 40500000,               # Rs 4.05 Cr
        "current_cost": 27100000,         # Rs 2.71 Cr
        "forecast": 42900000,             # Rs 4.29 Cr
        "retention_percent": 5,
        "advance_percent": 10,
        "advance_recovered_percent": 72,
        "ra_bills_total": 5, "ra_bills_paid": 3, "ra_bills_pending": 1, "ra_bills_under_review": 1,
        "cash_flow_signal": "watch",
        "contract_duration_days": 240,
        "current_day": RP002_CURRENT_DAY,
        "progress_percent": 52,
    }
    await memory_engine.set_commercial_reference(project["id"], data)
    return data


async def seed_rp001_commercial_reference() -> dict:
    """RP-001 — the exact figures from the brief, applied to the real,
    existing ACDP project (found by its own established code, never
    re-created)."""
    project = await db.projects.find_one({"code": "ACDP-VILLA"}, {"_id": 0})
    if not project:
        raise RuntimeError("ACDP (RP-001) must be seeded first — run scripts/seed_demo_project.py")
    data = {
        "project_name": "Atlas Demonstration Villa",
        "contract_value": 28500000,      # Rs 2.85 Cr
        "approved_variations": 1200000,  # Rs 12 Lakh
        "pending_variations": 500000,    # Rs 5 Lakh
        "budget": 23200000,              # Rs 2.32 Cr
        "current_cost": 10800000,        # Rs 1.08 Cr
        "forecast": 23900000,            # Rs 2.39 Cr
        "retention_percent": 5,
        "advance_percent": 10,
        "advance_recovered_percent": None,  # "Ongoing" per the brief, not a single figure
        "ra_bills_total": 3, "ra_bills_paid": 2, "ra_bills_pending": 1, "ra_bills_under_review": 0,
        "cash_flow_signal": "healthy",
    }
    await memory_engine.set_commercial_reference(project["id"], data)
    return data


async def migrate_rp001_to_commercial_engine(*, close_when_done: bool = True) -> dict:
    """CF-01 — populates RP-001 (the ACDP villa) with real Commercial
    Foundation Engine data: a genuine Contract, Milestones with a real
    achieved/paid history, a Variation that was actually approved
    (matching the ₹12L approved variation figure the lightweight
    commercial_reference already used), and a Budget — replacing the
    single-snapshot placeholder with real, state-machine-governed
    entities, using the exact same headline figures so the two layers
    agree rather than silently disagreeing about RP-001's own numbers.
    Idempotent: safe to re-run, matching every Reference Portfolio
    seeder's own established convention.
    """
    from engines import commercial_engine as ce, memory_engine

    project = await db.projects.find_one({"code": "ACDP-VILLA"}, {"_id": 0})
    if not project:
        raise RuntimeError("ACDP (RP-001) must be seeded first — run scripts/seed_demo_project.py")
    admin = await memory_engine.get_user_by_phone("9800000001")  # ACDP's own management user
    client = await memory_engine.get_user_by_phone("9800000005")  # ACDP's own client user
    pid = project["id"]

    contract = await ce.get_contract(pid)
    if not contract:
        contract = await ce.create_contract(
            actor=admin, project_id=pid, client_id=client["id"] if client else None,
            original_contract_value=27300000,  # original, pre-variation — 2.85cr current implies ~12L approved variation on top
            contract_date="2025-06-01", duration_days=540, retention_percent=5, advance_percent=10,
        )
        await ce.transition_contract_status(pid, "review", actor=admin)
        await ce.transition_contract_status(pid, "approved", actor=admin)
        await ce.transition_contract_status(pid, "active", actor=admin)

    budget = await ce.get_budget(pid)
    if not budget:
        await ce.create_budget(actor=admin, project_id=pid, original_budget=23200000)
        await ce.commit_cost(pid, 23200000, actor=admin, reason="Full scope committed across all trade packages")
        await ce.record_actual_cost(pid, 10800000, actor=admin, reason="Cumulative actual spend to date, per site records")

    existing_variations = await ce.list_variations(pid)
    if not existing_variations:
        var = await ce.create_variation(
            actor=admin, project_id=pid, title="Upgraded modular kitchen specification",
            description="Client requested a full upgrade from the originally specified laminate modular kitchen "
                        "to a solid-surface countertop with soft-close fittings across Main Residence and Guest House.",
            original_cost=0, proposed_cost=1200000, time_impact_days=8,
        )
        await ce.submit_variation(var["id"], actor=admin)
        await ce.send_variation_to_client_review(var["id"], actor=admin)
        await ce.decide_variation(var["id"], "approved", actor=client or admin)

        var2 = await ce.create_variation(
            actor=admin, project_id=pid, title="Additional landscape lighting package",
            description="Client requested additional exterior lighting for the rear garden and pool deck, "
                        "beyond the originally scoped landscape package.",
            original_cost=0, proposed_cost=500000, time_impact_days=3,
        )
        await ce.submit_variation(var2["id"], actor=admin)
        await ce.send_variation_to_client_review(var2["id"], actor=admin)
        # Left in client_review — this is RP-001's own "Pending Variations: ₹5 Lakh" figure

    existing_milestones = await ce.list_milestones(pid)
    if not existing_milestones:
        milestone_specs = [
            ("Advance & Mobilisation", 1, 10, "Contract signed and site mobilised", "2025-06-05"),
            ("Foundation Complete", 2, 15, "Foundation cast and cured across all zones", "2025-08-01"),
            ("Structure Complete (Ground + First Floor)", 3, 25, "RCC structure cast through roof level", "2025-11-15"),
            ("Brickwork & Plaster Complete", 4, 15, "External and internal brickwork and plaster complete", "2026-01-20"),
            ("MEP Rough-in Complete", 5, 10, "Electrical, plumbing, and HVAC first fix complete", "2026-03-01"),
            ("Finishes & Handover", 6, 25, "Flooring, painting, fixtures, and final snagging complete", "2026-06-01"),
        ]
        for name, seq, pct, trigger, planned in milestone_specs:
            ms = await ce.create_milestone(
                actor=admin, project_id=pid, name=name, sequence=seq,
                planned_percent=pct, trigger=trigger, planned_date=planned,
            )
            if seq <= 2:  # matches ACDP's own ~118-day-in narrative: mobilisation + foundation genuinely complete
                await ce.transition_milestone_status(ms["id"], "ready", actor=admin)
                ms = await ce.transition_milestone_status(ms["id"], "achieved", actor=admin)
                pr = await ce.create_payment_request(
                    actor=admin, project_id=pid, milestone_id=ms["id"], amount=ms["contract_value"],
                    raised_date=planned, due_date=planned, notes=f"RA Bill for {name}",
                )
                await ce.transition_payment_request_status(pr["id"], "raised", actor=admin)
                await ce.transition_payment_request_status(pr["id"], "sent", actor=admin)
                await ce.record_payment(actor=client or admin, payment_request_id=pr["id"],
                                        amount=ms["contract_value"], date=planned, method="bank_transfer",
                                        reference=f"RTGS-{seq:03d}")
            elif seq == 3:
                # In progress — matches RP-001's third RA Bill being "Pending"
                await ce.transition_milestone_status(ms["id"], "ready", actor=admin)

    return await ce.get_project_commercial_summary(pid)


async def generate_expected_state(project_id: str, *, admin: dict) -> dict:
    """Regression baseline for one project — deliberately built by
    calling the SAME comparison logic the live API uses
    (reasoning_engine._project_comparison_row), never hand-authored.
    A baseline that could silently drift from what the system actually
    computes would be worse than no baseline at all — this guarantees
    it can't.
    """
    from engines import reasoning_engine
    row = await reasoning_engine._project_comparison_row(project_id, user=admin)
    return {
        "project_id": row["project_id"],
        "project_name": row["project_name"],
        "health_status": row["health"]["status"],
        "health_score": row["health"]["score"],
        "workflow_total_activities": row["workflow"]["total_activities"],
        "workflow_status_counts": row["workflow"]["status_counts"],
        "workflow_blocked": row["workflow"]["blocked"],
        "operations_total_items": row["operations"]["total_items"],
        "operations_open_items": row["operations"]["open_items"],
        "operations_status_counts": row["operations"]["status_counts"],
        "operations_blocked": row["operations"]["blocked"],
        "operations_critical_open": row["operations"]["critical_open"],
        "timeline_event_count": row["timeline"]["event_count"],
        "commercial": row["commercial"],
        "schedule_variance_days": row["schedule_variance_days"],
    }


async def seed_rp002() -> dict:
    users = await seed_rp002_users()
    admin = users["Rohit Malhotra"]
    project, sites = await seed_rp002_project_and_sites(admin)
    template = await seed_rp002_template(admin)
    activities = await generate_rp002_workflow(project, template, admin)
    await apply_rp002_progress(activities, admin)
    items = await seed_rp002_operations(project, sites, users, admin)
    commercial = await seed_rp002_commercial_reference()
    return {
        "project_id": project["id"], "activities": len(activities),
        "operational_items": len(items), "commercial": commercial,
    }


async def migrate_rp002_to_commercial_engine() -> dict:
    """CF-01 continuation — populates RP-002 (Neoteric Corporate
    Office) with real Commercial Foundation Engine data, using the
    exact figures the lightweight commercial_reference already
    established for this project (Contract Rs 4.85 Cr, Approved
    Variations Rs 48L, Pending Variations Rs 23L, Budget Rs 4.05 Cr,
    Actual Cost Rs 2.71 Cr, Forecast Rs 4.29 Cr, cash flow "watch") —
    verified to reproduce the same "watch"/attention-level signal, not
    just the same headline numbers, so a caller reading either layer
    for RP-002 sees a consistent story. Idempotent, matching every
    other Reference Portfolio seeder's own convention.
    """
    from engines import commercial_engine as ce, memory_engine

    project = await db.projects.find_one({"code": RP002_PROJECT_CODE}, {"_id": 0})
    if not project:
        raise RuntimeError("RP-002 must be seeded first — run reference_portfolio.seed_rp002()")
    admin = await memory_engine.get_user_by_phone("9880000001")   # Rohit Malhotra, Director
    client = await memory_engine.get_user_by_phone("9880000004")  # Anaya Kapoor, client contact
    pid = project["id"]

    contract = await ce.get_contract(pid)
    if not contract:
        # Original + the Rs 48L approved variation below = the
        # established Rs 4.85 Cr current contract value.
        contract = await ce.create_contract(
            actor=admin, project_id=pid, client_id=client["id"] if client else None,
            original_contract_value=43700000, contract_date="2026-02-02", duration_days=240,
            retention_percent=5, advance_percent=10,
        )
        await ce.transition_contract_status(pid, "review", actor=admin)
        await ce.transition_contract_status(pid, "approved", actor=admin)
        await ce.transition_contract_status(pid, "active", actor=admin)

    budget = await ce.get_budget(pid)
    if not budget:
        await ce.create_budget(actor=admin, project_id=pid, original_budget=40500000)
        # Forecast Cost = max(committed, actual); committed set to the
        # established Rs 4.29 Cr forecast figure directly.
        await ce.commit_cost(pid, 42900000, actor=admin,
                             reason="Full scope committed across structural, MEP, and fit-out packages")
        await ce.record_actual_cost(pid, 27100000, actor=admin,
                                    reason="Cumulative actual spend to date, day 137 of 240")

    existing_variations = await ce.list_variations(pid)
    if not existing_variations:
        var = await ce.create_variation(
            actor=admin, project_id=pid, title="Server room enclosure specification upgrade",
            description="Client requested an upgraded, higher fire-rated enclosure and additional cooling "
                        "capacity for the Floor 2 server room, beyond the originally scoped specification.",
            original_cost=0, proposed_cost=4800000, time_impact_days=12,
        )
        await ce.submit_variation(var["id"], actor=admin)
        await ce.send_variation_to_client_review(var["id"], actor=admin)
        await ce.decide_variation(var["id"], "approved", actor=client or admin)

        var2 = await ce.create_variation(
            actor=admin, project_id=pid, title="Additional network drops and cabling — Floor 2",
            description="Client added 12 additional network drops to the Floor 2 scope after the original "
                        "data cabling contract was signed, requiring a requote from the subcontractor.",
            original_cost=0, proposed_cost=2300000, time_impact_days=5,
        )
        await ce.submit_variation(var2["id"], actor=admin)
        await ce.send_variation_to_client_review(var2["id"], actor=admin)
        # Left in client_review — this is RP-002's own "Pending
        # Variations: Rs 23 Lakh" figure.

    existing_milestones = await ce.list_milestones(pid)
    if not existing_milestones:
        # Percentages sum to 52% — matching RP-002's own established
        # "Progress: 52%" figure exactly. Three paid, one sent-but-
        # unpaid, one raised-but-not-yet-sent — deliberately producing
        # a received/raised ratio in the "attention" band (not
        # "healthy"), matching the reference layer's "watch" signal.
        milestone_specs = [
            ("Advance & Mobilisation", 1, 8, "Contract signed and site mobilised", "2026-02-05", "paid"),
            ("Strip-out & Demolition Complete", 2, 8, "All three zones stripped and demolition complete", "2026-02-20", "paid"),
            ("Partition & Drywall Complete", 3, 9, "Partition framing and drywall complete across all zones", "2026-03-10", "paid"),
            ("MEP First Fix Complete", 4, 15, "Electrical, HVAC, and fire sprinkler first fix complete", "2026-04-15", "sent"),
            ("Ceiling Grid Ready for Finishes", 5, 12, "False ceiling grid installed, ready for finishes across all zones", "2026-05-01", "raised"),
        ]
        for name, seq, pct, trigger, planned, target_pr_state in milestone_specs:
            ms = await ce.create_milestone(
                actor=admin, project_id=pid, name=name, sequence=seq,
                planned_percent=pct, trigger=trigger, planned_date=planned,
            )
            await ce.transition_milestone_status(ms["id"], "ready", actor=admin)
            ms = await ce.transition_milestone_status(ms["id"], "achieved", actor=admin)
            pr = await ce.create_payment_request(
                actor=admin, project_id=pid, milestone_id=ms["id"], amount=ms["contract_value"],
                raised_date=planned, due_date=planned, notes=f"RA Bill for {name}",
            )
            if target_pr_state in ("sent", "paid"):
                await ce.transition_payment_request_status(pr["id"], "raised", actor=admin)
                await ce.transition_payment_request_status(pr["id"], "sent", actor=admin)
            if target_pr_state == "paid":
                await ce.record_payment(actor=client or admin, payment_request_id=pr["id"],
                                        amount=ms["contract_value"], date=planned, method="bank_transfer",
                                        reference=f"NEFT-{seq:03d}")
            # target_pr_state == "raised": left exactly at "draft" ->
            # "raised" is NOT called, so it stays in the state
            # create_payment_request leaves it — "draft" — representing
            # "under review," internally, not yet sent to the client.

    return await ce.get_project_commercial_summary(pid)


async def main() -> None:
    result = await seed_rp002()
    rp001_commercial = await seed_rp001_commercial_reference()
    rp001_summary = await migrate_rp001_to_commercial_engine()
    rp002_summary = await migrate_rp002_to_commercial_engine()
    print(f"RP-002 seeded: {result['activities']} activities, {result['operational_items']} operational items")
    print(f"RP-001 commercial reference set: contract value Rs {rp001_commercial['contract_value']:,}")
    print(f"RP-001 Commercial Foundation Engine data: current contract value Rs {rp001_summary['contract']['current_contract_value']:,.0f}")
    print(f"RP-002 Commercial Foundation Engine data: current contract value Rs {rp002_summary['contract']['current_contract_value']:,.0f}, "
          f"cash flow signal: {rp002_summary['cash_flow_signal']}")


if __name__ == "__main__":
    asyncio.run(main())
