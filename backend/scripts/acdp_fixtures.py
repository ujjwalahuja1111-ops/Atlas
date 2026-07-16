"""Atlas Canonical Demo Project (ACDP) — fixtures.

Pure data: the phase/activity catalog, zone (site) definitions, and
content templates the generator (scripts/seed_demo_project.py) turns
into a chronologically consistent 18-month construction story. Nothing
here talks to the database — this module is safe to import and inspect
standalone (e.g. from a notebook or a future test) without a running
Atlas backend.

Activity names are deliberately built from the SAME keyword vocabulary
engines/reasoning_projections.py's stage_of_activity() already
recognises (see ACDP_TIMELINE.md for the full mapping) — this is not a
new schema or a new engine rule, it's writing activity names the
existing, unmodified CRE stage-classifier already understands. A few
Landscape activities intentionally fall outside that vocabulary (the
real classifier has no "landscape" keyword) and are correctly
unclassified by CRE, exactly as any real out-of-vocabulary activity
would be today — not worked around here.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Zones (sites) — 6 zones under the one ACDP project, matching a real
# multi-structure villa plot. Every phase below declares which zones it
# applies to; not every phase touches every zone (a boundary wall has no
# RCC structure phase, the basement has no roof, etc.) — this is what
# gives the generated workflow a believable, non-uniform shape instead of
# the same activity list repeated identically 6 times.
# ---------------------------------------------------------------------------
ZONES = [
    {"code": "main", "name": "Main Residence", "location": "Plot A — New Chandigarh, Sector 20"},
    {"code": "guest", "name": "Guest House", "location": "Plot A (North Wing) — New Chandigarh, Sector 20"},
    {"code": "basement", "name": "Basement & Utility Block", "location": "Plot A (Sub-level) — New Chandigarh, Sector 20"},
    {"code": "boundary", "name": "Boundary Wall & Gate", "location": "Plot A Perimeter — New Chandigarh, Sector 20"},
    {"code": "landscape", "name": "Landscape & Pool", "location": "Plot A (Rear Garden) — New Chandigarh, Sector 20"},
    {"code": "servant", "name": "Servant Quarters", "location": "Plot A (South Wing) — New Chandigarh, Sector 20"},
]
ZONE_CODES = [z["code"] for z in ZONES]

# ---------------------------------------------------------------------------
# Phase catalog. Each phase: a category label, the zones it applies to,
# and a list of (name, trade, unit, default_duration_days,
# requires_inspection) tuples. The generator instantiates one Knowledge
# Activity + one workflow activity PER (activity, applicable zone) pair,
# which is what produces a natural, varying total (see
# seed_demo_project.py's ZONE_SCALE for the exact multiplier) rather than
# a hand-typed list of 400 unique strings.
# ---------------------------------------------------------------------------
PHASES = [
    {
        "category": "Earthwork", "phase_label": "Earthwork",
        "zones": ZONE_CODES,
        "activities": [
            ("Site Clearance & Layout Marking", "Civil", "sqm", 2, False),
            ("Temporary Site Office & Security Cabin Setup", "Civil", "unit", 2, False),
            ("Site Fencing & Access Control", "Civil", "rmt", 2, False),
            ("Earthwork Excavation", "Civil", "cum", 4, False),
            ("Soil Testing & Bearing Capacity Check", "Civil", "point", 1, True),
            ("Excavation Dewatering", "Civil", "day", 3, False),
            ("Backfilling & Compaction", "Civil", "cum", 3, False),
            ("Levelling & Grading", "Civil", "sqm", 2, False),
        ],
    },
    {
        "category": "Foundation", "phase_label": "Foundation",
        "zones": ["main", "guest", "basement", "boundary", "servant"],
        "activities": [
            ("PCC Bed", "Civil", "cum", 1, True),
            ("Footing Shuttering & Reinforcement", "Civil", "sqm", 3, True),
            ("Footing Concrete Pour", "Civil", "cum", 2, True),
            ("Footing Curing", "Civil", "day", 7, False),
            ("Grade Slab Casting", "Civil", "cum", 2, True),
            ("Plinth Beam Construction", "Civil", "rmt", 3, True),
            ("Plinth Backfilling", "Civil", "cum", 2, False),
            ("Anti-Termite Treatment", "Civil", "sqm", 1, False),
        ],
    },
    {
        "category": "RCC Structure", "phase_label": "RCC Structure",
        "zones": ["main", "guest", "basement", "servant"],
        "activities": [
            ("Column Shuttering & Reinforcement — Ground Floor", "Civil", "sqm", 3, True),
            ("Column Concrete Casting — Ground Floor", "Civil", "cum", 2, True),
            ("Beam & Slab Shuttering — Ground Floor", "Civil", "sqm", 4, True),
            ("Beam & Slab Reinforcement — Ground Floor", "Civil", "mt", 3, True),
            ("Slab Concrete Casting — Ground Floor", "Civil", "cum", 2, True),
            ("Column Shuttering & Reinforcement — First Floor", "Civil", "sqm", 3, True),
            ("Column Concrete Casting — First Floor", "Civil", "cum", 2, True),
            ("Beam & Slab Shuttering — First Floor", "Civil", "sqm", 4, True),
            ("Beam & Slab Reinforcement — First Floor", "Civil", "mt", 3, True),
            ("Slab Concrete Casting — First Floor", "Civil", "cum", 2, True),
            ("Staircase RCC Casting", "Civil", "cum", 2, True),
            ("Roof Slab Casting", "Civil", "cum", 3, True),
        ],
    },
    {
        "category": "Masonry", "phase_label": "Masonry",
        "zones": ["main", "guest", "boundary", "servant"],
        "activities": [
            ("Brickwork — Ground Floor", "Mason", "cum", 5, False),
            ("Brickwork — First Floor", "Mason", "cum", 5, False),
            ("Block Work — Internal Partitions", "Mason", "sqm", 3, False),
            ("Sill & Lintel Band Masonry", "Mason", "rmt", 2, False),
            ("Parapet & Chajja Masonry", "Mason", "rmt", 2, False),
            ("Jali & Lattice Screen Masonry", "Mason", "sqm", 3, False),
            ("Masonry Curing", "Mason", "day", 4, False),
            ("Cornice & Decorative Band Work", "Mason", "rmt", 2, False),
        ],
    },
    {
        "category": "Waterproofing", "phase_label": "Waterproofing",
        "zones": ["main", "guest", "basement", "landscape", "servant"],
        "activities": [
            ("Foundation Waterproofing Membrane", "Waterproofing", "sqm", 2, True),
            ("Terrace Waterproofing", "Waterproofing", "sqm", 3, True),
            ("Bathroom Damp Proofing", "Waterproofing", "sqm", 1, True),
            ("Basement Waterproofing Membrane", "Waterproofing", "sqm", 3, True),
            ("Parapet Waterproofing", "Waterproofing", "sqm", 1, True),
            ("Overhead Water Tank Waterproofing", "Waterproofing", "sqm", 2, True),
        ],
    },
    {
        "category": "MEP", "phase_label": "MEP",
        "zones": ["main", "guest", "basement", "landscape", "servant"],
        "activities": [
            ("Electrical Conduit & Wiring — First Fix", "Electrical", "point", 5, False),
            ("Plumbing Sanitary Line — First Fix", "Plumbing", "point", 5, False),
            ("Drainage & Sewerage Line", "Plumbing", "rmt", 4, True),
            ("HVAC Ducting", "HVAC", "rmt", 4, False),
            ("Fire Fighting Piping", "Fire Fighting", "rmt", 3, True),
            ("Electrical Wiring — Second Fix", "Electrical", "point", 4, False),
            ("Plumbing Fixtures — Second Fix", "Plumbing", "point", 3, False),
            ("DG Set Installation & Wiring", "Electrical", "unit", 2, True),
            ("Solar Panel Wiring", "Electrical", "point", 3, False),
            ("Intercom & CCTV Cabling", "Electrical", "point", 3, False),
            ("Water Softener & RO Plumbing", "Plumbing", "point", 2, False),
        ],
    },
    {
        "category": "Finishes", "phase_label": "Flooring",
        "zones": ["main", "guest", "servant"],
        "activities": [
            ("Internal Plastering", "Mason", "sqm", 5, False),
            ("External Plastering", "Mason", "sqm", 5, False),
            ("Flooring — Vitrified Tile", "Flooring", "sqm", 4, False),
            ("Flooring — Marble/Granite", "Flooring", "sqm", 5, False),
            ("Skirting Work", "Flooring", "rmt", 2, False),
            ("Staircase Flooring & Cladding", "Flooring", "sqm", 3, False),
        ],
    },
    {
        "category": "Finishes", "phase_label": "False Ceiling",
        "zones": ["main", "guest"],
        "activities": [
            ("False Ceiling — Gypsum Framing", "Carpentry", "sqm", 3, False),
            ("False Ceiling — Board & Finish", "Carpentry", "sqm", 3, False),
        ],
    },
    {
        "category": "Finishes", "phase_label": "Painting",
        "zones": ["main", "guest", "servant", "boundary"],
        "activities": [
            ("Putty & Primer", "Painting", "sqm", 3, False),
            ("Internal Painting", "Painting", "sqm", 4, False),
            ("External Painting", "Painting", "sqm", 4, False),
            ("Texture Paint — Feature Wall", "Painting", "sqm", 2, False),
            ("Exterior Waterproof Paint Touch-up", "Painting", "sqm", 2, False),
        ],
    },
    {
        "category": "Finishes", "phase_label": "Joinery",
        "zones": ["main", "guest", "servant"],
        "activities": [
            ("Door Frame & Shutter Fixing", "Carpentry", "nos", 4, False),
            ("Window Frame & Shutter Fixing", "Carpentry", "nos", 4, False),
            ("Wardrobe & Modular Carpentry", "Carpentry", "sqm", 5, False),
            ("Kitchen Shutter & Cabinet Carpentry", "Carpentry", "sqm", 5, False),
            ("Staircase Railing Woodwork", "Carpentry", "rmt", 3, False),
        ],
    },
    {
        "category": "Finishes", "phase_label": "Facade",
        "zones": ["main", "guest"],
        "activities": [
            ("Facade Stone Cladding", "Facade", "sqm", 5, True),
            ("Facade Grill & Railing Fixing", "Fabrication", "rmt", 3, False),
            ("Facade Glass Glazing", "Facade", "sqm", 4, True),
            ("Facade Lighting Installation", "Electrical", "point", 2, False),
            ("Portico Canopy Work", "Fabrication", "sqm", 3, False),
        ],
    },
    {
        "category": "Landscape", "phase_label": "Landscape",
        "zones": ["landscape"],
        "activities": [
            ("Swimming Pool Shell Construction", "Civil", "cum", 6, True),
            ("Swimming Pool Filtration Plumbing", "Plumbing", "point", 3, False),
            ("Swimming Pool Tiling", "Flooring", "sqm", 4, False),
            ("Garden Soft-scaping & Turfing", "Landscape", "sqm", 4, False),
            ("Garden Hardscaping & Pathways", "Landscape", "sqm", 4, False),
            ("Boundary Planting & Hedging", "Landscape", "rmt", 3, False),
            ("Outdoor Water Feature Construction", "Civil", "unit", 4, False),
            ("Outdoor Lighting Installation", "Electrical", "point", 3, False),
            ("Outdoor Furniture Placement", "Landscape", "nos", 1, False),
        ],
    },
    {
        "category": "Testing & Commissioning", "phase_label": "Testing",
        "zones": ["main", "guest", "basement", "servant"],
        "activities": [
            ("Electrical Testing & Commissioning", "Electrical", "point", 2, True),
            ("Plumbing Pressure Testing", "Plumbing", "point", 2, True),
            ("Fire Fighting System Testing", "Fire Fighting", "point", 2, True),
            ("HVAC System Testing", "HVAC", "point", 2, True),
            ("DG Set Load Testing", "Electrical", "unit", 1, True),
        ],
    },
    {
        "category": "Testing & Commissioning", "phase_label": "Snagging",
        "zones": ["main", "guest", "servant"],
        "activities": [
            ("Snagging Inspection Round 1", "QA", "checklist", 2, True),
            ("Snagging Rectification", "Multi-trade", "item", 5, False),
            ("Snagging Inspection Round 2", "QA", "checklist", 1, True),
        ],
    },
    {
        "category": "Handover", "phase_label": "Client Handover",
        "zones": ["main"],
        "activities": [
            ("Final Cleaning", "Housekeeping", "sqm", 2, False),
            ("Completion Certificate Documentation", "Admin", "document", 3, True),
            ("Client Walkthrough & Handover", "Admin", "session", 1, True),
        ],
    },
]

# ---------------------------------------------------------------------------
# Content templates — voice notes, text events, blockers, safety
# observations. Written the way a site supervisor would actually speak:
# short, plain, no fabricated transcription artefacts. {phase} / {zone} /
# {activity} are filled in by the generator from the phase/activity/zone
# actually active on that day, so every line stays tied to real timeline
# content instead of being generic filler.
# ---------------------------------------------------------------------------
VOICE_TEMPLATES = [
    "{activity} completed today in {zone}. Moving to next activity tomorrow.",
    "{activity} in progress, about halfway through in {zone}.",
    "Team started {activity} in {zone} this morning.",
    "{activity} delayed in {zone}, material not on site yet.",
    "Quality check done on {activity} in {zone}, looks good.",
    "{activity} finished ahead of schedule in {zone}.",
    "Rain today, {activity} in {zone} paused for the day.",
    "Client visited site, reviewed {activity} progress in {zone}.",
    "Labour shortage today, {activity} in {zone} running slow.",
    "{activity} in {zone} ready for inspection tomorrow.",
]

TEXT_TEMPLATES = [
    "Progress update: {activity} underway in {zone}.",
    "{activity} completed in {zone}, photos attached.",
    "Site visit note: {zone} looking good, {activity} on track.",
    "Weekly summary: {phase} phase progressing well across {zone}.",
    "Material delivery received for {activity} in {zone}.",
]

MATERIAL_ITEMS = [
    ("TMT Steel Bars (Fe 500D)", "MT"), ("OPC 53 Grade Cement", "bags"),
    ("River Sand", "cum"), ("20mm Coarse Aggregate", "cum"),
    ("AAC Blocks", "nos"), ("Red Bricks", "nos"),
    ("Vitrified Tiles 600x600", "sqm"), ("Italian Marble Slabs", "sqm"),
    ("Copper Electrical Cable", "rmt"), ("CPVC Plumbing Pipes", "rmt"),
    ("Waterproofing Membrane Sheets", "sqm"), ("Teak Wood Door Frames", "nos"),
    ("UPVC Window Profiles", "rmt"), ("Facade Stone Cladding Panels", "sqm"),
    ("Gypsum Board Sheets", "sheet"), ("Exterior Emulsion Paint", "litre"),
]

SAFETY_OBSERVATIONS = [
    "Scaffolding near {zone} needs additional bracing before next use.",
    "Workers observed without safety helmets near {activity} in {zone}.",
    "Excavation edge in {zone} needs barricading.",
    "Electrical panel in {zone} left uncovered overnight, corrected on site.",
    "Fire extinguisher missing from {zone} site office, replacement requested.",
    "Loose debris near {activity} area in {zone}, cleared same day.",
]

DELAY_REASONS = [
    "unseasonal rain", "cement delivery delay from vendor", "labour shortage after festival season",
    "steel price renegotiation with supplier", "drawing revision from architect",
    "client-requested design change", "monsoon waterlogging on access road",
    "shuttering material shortage", "electrician team unavailable this week",
]

CLIENT_APPROVAL_TOPICS = [
    "Kitchen countertop material — marble vs granite",
    "Master bedroom flooring pattern",
    "Facade stone cladding sample approval",
    "Swimming pool tile colour",
    "False ceiling design — living room",
    "Main gate design finalization",
    "Bathroom fittings brand selection",
    "Exterior paint shade approval",
    "Landscape layout revision",
    "Staircase railing design",
    "Modular kitchen layout",
    "Wardrobe finish selection",
    "Outdoor lighting fixture selection",
    "Boundary wall coping stone finish",
    "Guest house door hardware selection",
]
