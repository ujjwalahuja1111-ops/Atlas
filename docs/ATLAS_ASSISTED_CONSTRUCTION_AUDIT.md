# ATLAS ASSISTED CONSTRUCTION — PRODUCT & ARCHITECTURE AUDIT

**Status: audit only. No production code was modified to produce this document.**

This audit was built by reading the actual repository — every engine file, every route file, every frontend screen referenced below was opened and read, not inferred from documentation or naming conventions alone. Several findings below contradict what the engine and file *names* would suggest; those are called out explicitly, because the gap between what a system is named and what it actually does is exactly the kind of thing an audit exists to surface.

---

## A. Current System Map

Atlas's backend is organized as a set of independent engines (`backend/engines/`), each owning one collection or a small family of related collections, composed together by routes and by higher-level "reasoning" functions rather than by direct cross-engine writes. Sizes below are lines of code, as a rough signal of where the real weight of the system sits.

| Engine | Size | What It Actually Owns |
|---|---|---|
| `reasoning_engine.py` | 3,093 lines | The largest engine by far — portfolio views, health scoring, forecasting, priorities, executive Q&A (see Finding 1 below), client-facing views, cross-project pattern counting, commercial intelligence rollups. Composes data from every other engine; owns almost no raw data itself. |
| `operations_engine.py` | 1,528 lines | Operational Items — the single collection covering 11 work-item categories (material, labour, equipment, client_approval, drawing_request, inspection, site_issue, safety_observation, quality_observation, commitment, follow_up) plus AI Proposals, the queue of AI-suggested items awaiting human accept/reject. |
| `commercial_engine.py` | 1,193 lines | Contracts, budgets, milestones, variations, payment requests, payments, commercial health. The one deterministic source of financial truth. |
| `memory_engine.py` | 900 lines | Events (immutable capture records), AI analyses, corrections, users, projects, sites — the lowest-level, most foundational data layer. |
| `reasoning_projections.py` | 791 lines | Pure functions: health-score math, lookahead/dependency-graph logic, blocking-impact calculations. No I/O — reasoning_engine.py's own computational core, kept separately testable. |
| `knowledge_engine.py` | 684 lines | **Not** a learning or pattern-recognition system (see Finding 2 below) — a versioned taxonomy/master-data store: categories, phases, activity templates, checklist templates, required-document templates, workflow templates. Explicitly documented in its own header as containing "no AI behaviour." |
| `intelligence_engine.py` | 662 lines | The real AI pipeline: Whisper transcription, GPT-4o structuring of a captured event (text + up to 3 photos, multi-modal), and 11-intent proposal generation from that structured output. |
| `workflow_engine.py` | 554 lines | Workflow Activities — the schedule/dependency-graph layer (Construction Sequencing Engine). Powers the "lookahead" / next-likely-activity reasoning. |
| `knowledge_graph_engine.py` | 263 lines | **Not** a graph database or a cross-project pattern engine (see Finding 3 below) — a relationship-inference layer that traverses existing foreign keys within a single project (e.g. Variation → linked photo → originating Event) to answer "what led to this" / "what does this affect" queries. |
| `timeline_engine.py` | 179 lines | Read-side composition of the project's chronological event history. |
| `notification_engine.py` | 146 lines | The single notification-creation function every other engine calls; owns the `notifications` collection. |
| `reality_engine.py` | 151 lines | The `capture()` entry point — validates and persists a new Event (voice/photo/text) and queues it for AI analysis. |

**Finding 1 — There is no free-text, prompt-first interface anywhere in Atlas today.** The closest thing to it, `reasoning_engine.executive_answer()`, is explicitly documented in its own route as *"Not conversational AI: a fixed question vocabulary"* — seven hard-coded questions (`attention_today`, `greatest_risk`, `top_blocker`, `overdue_approvals`, `stalled_projects`, `tomorrow`, `supervisor_load`), each answered by 100% deterministic logic with zero LLM involvement. Passing any string outside that fixed set raises an error. The frontend doesn't even expose this as a question box — it renders as a static "Executive Briefing" card. This is the single most important finding in this audit: the brief's Section 4 vision ("Atlas should become prompt-first") describes something that does not exist in the product today, in any form.

**Finding 2 — Atlas's "Knowledge Engine" is not the institutional-memory system Section 11 of the brief envisions.** Its own module docstring states it explicitly: a taxonomy of categories/phases/activity templates/checklists, versioned, with "no AI behaviour, no scheduling, no project assignment." There is no vendor-performance tracking, no contractor-performance tracking, no "this material typically delays by N days" pattern, and no learning from historical project outcomes anywhere in the codebase.

**Finding 3 — Atlas's "Knowledge Graph" is not cross-project either.** It infers relationships from foreign keys that already exist *within* a single project's own records (a variation, the photo that justified it, the event that photo came from). It has no concept of "vendor X across four projects."

**Finding 4 — `cross_project_intelligence()` is real but narrow.** It is genuine cross-project aggregation — but it counts how many projects trigger the *same deterministic health-check rule ID*, nothing more. It is not learning, not a historical-outcome model, and not what Section 11's "Vendor Y has delivered on time on 5 of 6 comparable projects" example describes.

**Finding 5 (positive) — the two places Atlas *does* call an LLM already follow the architecture the brief asks for.** `intelligence_engine.py`'s event structuring and `reasoning_engine.py`'s optional `_ai_review()` insight-enhancement pass are both wrapped in total failure isolation: if the LLM call fails for any reason, the system falls back to deterministic output rather than breaking. `_ai_review()`'s own docstring states this outright: *"any exception returns [] and the deterministic findings stand alone."* This is precisely the "AI interprets ambiguity, deterministic systems establish facts" principle the brief asks to preserve — Atlas already has it, in exactly two places, and nowhere else. There is no third, fourth, or redundant AI call anywhere in the backend. Any new orchestration layer should extend this existing discipline, not invent a new one.

**Finding 6 (positive) — multi-modal input already exists, narrowly.** `intelligence_engine._structure()` already sends up to 3 photos to the LLM alongside the transcript/text, as real `ImageContent`. Image understanding is not a gap to build from zero — it is a capability that exists inside the Capture pipeline specifically and would need to be generalized, not invented.

---

## B. Current UX Map

Every user-facing screen in the Expo app (`frontend/app/`), grouped by what it actually does:

| Screen | Purpose |
|---|---|
| `(tabs)/index.tsx` | Home — role-branching: redirects Management to Executive Hub; shows Continue-Working + My Day for PM; shows the 4-action grid for Supervisor; shows progress + decisions for Client. |
| `(tabs)/executive-hub.tsx` | Management's own Home: Today's Priorities, Needs Attention Today digest, Portfolio Control Center. |
| `(tabs)/projects.tsx` | The list of accessible active projects. |
| `(tabs)/capture.tsx` | Voice / Photo / Text capture — the single entry point for Reality into Atlas. |
| `(tabs)/notifications.tsx` | The Inbox — coordination-state notification list (Action Required / Waiting For You / Waiting For Others / Escalations / Commercial Attention / Activity Feed). |
| `(tabs)/ops.tsx` | The full Operational Items list (hidden tab, reached contextually). |
| `(tabs)/profile.tsx` | "More" — profile, role switch (for demo/dev), settings, secondary destinations. |
| `event/[id].tsx` | Event detail — What Atlas Understood panel, AI Proposal review (accept/reject), corrections, approval requests. |
| `op/[id].tsx` / `op/create.tsx` | Operational item detail (assign, comment, transition, blocker, voice update) / manual creation form. |
| `projects/[id]/workspace/index.tsx` + 4 phase files | The Project Workspace — Setup / Plan / Execute / Review / Bill / Close, one canonical entry point per project. |
| `commercial/[id].tsx` | The Bill phase's own detailed screen: contract, budget, milestones, variations, payment requests, profitability. |
| `projects/new.tsx` | The 4-step manual project-creation wizard (Section F below covers this in detail). |
| `portfolio/index.tsx`, `portfolio-search.tsx`, `priorities.tsx`, `executive-timeline.tsx` | Management's portfolio-wide views. |
| `daily-review.tsx` | Daily Site Report generation and viewing. |
| `knowledge/index.tsx`, `knowledge/[id].tsx` | Browsing/editing the taxonomy master-data (Finding 2). |
| `workflow/[id].tsx` | Workflow Activity (schedule) detail. |
| `explain/[type]/[id].tsx`, `explain-health/[id].tsx` | "View Calculation" — the transparency screens showing exactly which figures produced a displayed number. |
| `site-progress/[id].tsx` | Site-level progress view. |
| `users/index.tsx`, `system/index.tsx` | Admin: user approval/role management, system diagnostics. |
| `login.tsx`, `pending.tsx` | Auth entry and pending-approval states. |

**~35 distinct screens.** Not excessive for the functional scope, but every one of them requires the user to already know *which* screen holds the answer to their question — there is no single entry point that resolves "what do I need to know" into the right destination automatically.

---

## C. Role Journey Map

| Role | Home Landing | Primary Screens | What They Cannot See |
|---|---|---|---|
| **Management** | Executive Hub | Portfolio Control Center, Priorities, Cross-Project Intelligence, Payment approvals | Nothing withheld within their own portfolio |
| **Project Manager** | Home (Continue Working + My Day) | Project Workspace (all 6 phases), Commercial/Bill phase, Ops, Inbox | Other PMs' unrelated projects |
| **Site Supervisor** | Home (4-action grid: Site Update / Report Issue / My Tasks / Messages) | Capture, My Tasks (Ops filtered to their own items), Inbox | Budget, cost, margin, any commercial figures |
| **Client** | Client Dashboard | Progress, Variations (approve/decline), Payment Requests (status only), client-safe Daily Site Reports | Internal budget, actual cost, margin, any Management/PM-only screen |

This role model is a genuine strength already in place: server-side RBAC (confirmed in `commercial_engine.py`'s own visibility checks and the route-level role decorators) — not merely UI-level hiding. Any new intent/orchestration layer must route through the same authorization checks the existing engines already enforce, not re-implement them.

---

## D. Existing Input Map

| Input Type | Where It Exists Today | Scope |
|---|---|---|
| Free-form text | Capture screen's "Text" option; every form field across the app | Per-event or per-field; never resolved into intent |
| Voice | Capture screen; Operational Item "Voice Update" | Transcribed (Whisper) → structured (GPT-4o) → proposals. The most mature input pathway in the product. |
| Photos | Capture screen (up to 3 analyzed per event, multi-modal) | Scoped entirely to the Capture pipeline — not available anywhere else (e.g. cannot attach a photo to a payment request or a variation) |
| Documents | **None found.** No document upload, no PDF/contract ingestion, anywhere in the codebase. | Full gap |
| Structured forms | The overwhelming majority of the product — project creation, commercial setup, milestone/variation entry, operational item creation | Manual, field-by-field, no assistance |
| Fixed-vocabulary Q&A | `executive_answer()` (Finding 1) | 7 pre-defined questions only |

The product's single most mature "understanding" pathway — voice/photo → transcription → structuring → proposals — is scoped narrowly to one screen (Capture) and one outcome type (Operational Item proposals). It does not yet reach project creation, commercial setup, or general Q&A. This is the foundation Phase 1–3 of any roadmap should extend, not replace.

---

## E. Orchestration Gap Analysis

For each major workflow: what the user does today, and what Atlas could take over.

| Workflow | User Does Today | Atlas Could Infer | Atlas Could Recommend | Atlas Could Execute | Requires Confirmation |
|---|---|---|---|---|---|
| Project creation | Fill a 4-step, ~12-field manual wizard | Contract value range, duration, likely phases, milestone split, team size, from a free-text description | A complete preliminary project model | Draft (not final) project + workflow activities via the *already-existing* `generate_workflow()` + template match | Yes — creating a project is a real, named entity other people will act on |
| Commercial setup (payment schedule) | Manually create each milestone one at a time in the Bill phase | The full milestone split from a sentence like "20% advance, 30% structure..." | The structured schedule for review | Draft milestones (not yet contract-binding) | Yes — financial structure |
| Site issue reporting | Already voice-capable (Capture) | Which operational category (material/labour/site_issue), likely schedule impact, who should be notified | "Notify PM", "This may affect [activity] by ~1 day" | The AI Proposal (already exists) + a **notification** (does not yet exist for this case — see Finding below) | No for the proposal (already how it works); yes for the notification's exact wording only if novel |
| "Why is this project at risk?" | Navigate to project → Review phase → read Explain Health screen | Nothing new to infer — `explain_health()` already answers this deterministically | N/A — it's already an explanation, not a recommendation | N/A | No |
| "What's happening today?" | Check Executive Hub / My Day separately per project | Nothing new — `since_last_visit()`, `daily_digest()`, `my_day()` already exist | Could synthesize across all three into one answer | N/A | No |
| Comparing projects | Navigate to Portfolio → Compare, select projects manually | Which projects are "comparable" (same type/scale) — **not built today**, would require project metadata Atlas doesn't yet infer at creation time | N/A | `compare_projects()` already exists once the IDs are known | No |
| Variation from a client request | PM manually opens Plan phase, fills a variation form | Cost/schedule impact estimate, whether it resembles a past variation type | "Send for client review" | Draft variation via `create_variation()` | Yes — becomes a contractual change once approved |

**The core gap is not missing engines. It is a missing layer that turns one free-text sentence into calls against the engines that already exist**, plus — separately and honestly — several genuine data gaps (vendor/contractor performance, historical outcome patterns, comparable-project detection) that no existing engine covers at all and that an intent layer cannot manufacture from data that was never captured.

---

## F. Engine Orchestration Map — 10 Representative Scenarios

Each scenario below is mapped against Atlas's **real, existing** engines and functions — not idealized or hypothetical ones. Where a genuine gap exists, it is named as a gap, not glossed over.

### 1. "Client wants quartz instead of granite."
- **Intent:** Variation request
- **Context:** Current project (from conversation context or explicit selection); the affected material/activity, if identifiable
- **Reality:** May already exist as a related Capture event
- **Commercial:** `commercial_engine.create_variation()` — cost impact
- **Workflow:** Possible activity resequencing if the affected work hasn't started
- **Timeline:** Recorded automatically as part of the variation's own history
- **Health:** May move the commercial-health dimension if the cost delta is material
- **Priority:** Surfaces in Management's Needs Attention if above a threshold
- **Memory:** Stored as the variation's own permanent record
- **Knowledge:** *Gap* — no existing mechanism to say "this resembles 3 prior finish-upgrade variations"
- **Recommendation:** "Send for client review" (an existing action: `send_variation_to_client_review()`)
- **Action:** Draft the variation; require PM confirmation before submission (financial/contractual consequence)

### 2. "Mistri nahi aaya, plaster ka kaam ruk gaya hai aur kal material bhi nahi aaya." (the brief's own example)
- **Intent:** Compound — labour shortage + material delay + activity blocked
- **Context:** Site, current activity (plaster)
- **Reality:** New Capture event (voice) — already the correct entry point
- **Commercial:** None directly
- **Workflow:** `workflow_engine` — the plaster `workflow_activity` may need a `blocked` status; `reasoning_projections.project_lookahead()` can estimate downstream impact via the existing dependency graph
- **Timeline:** Recorded
- **Health:** Schedule dimension may move
- **Priority:** New high-priority item for the PM
- **Memory:** Event + AI analysis (already how Capture works)
- **Knowledge:** *Gap* — no labour-availability or material-lead-time history exists to say "this vendor has been late 3 of 4 times"
- **Recommendation:** "Notify PM; ~1 day possible impact based on dependency graph"
- **Action:** Create the operational item (already how proposals work) + a notification (this specific outcome-driven notification does not yet exist and would be new, small orchestration logic, not a new engine)

### 3. "Create a new project for a 4,000 sq ft luxury residence in Chandigarh."
- **Intent:** Project creation
- **Context:** None yet — a new entity
- **Reality:** N/A
- **Commercial:** No existing benchmark data to propose a contract-value range — *gap*, unless historical comparable projects exist and are explicitly surfaced as "comparable, not certain"
- **Workflow:** **Already exists** — `workflow_engine.generate_workflow(project_id, template_id)` builds a full activity set from a `knowledge_engine` `workflow_template`. The gap is only in *selecting* the right template from a free-text description, not in generating the workflow itself.
- **Timeline:** New project record
- **Health:** Initializes at a neutral baseline
- **Priority:** N/A yet
- **Memory:** New project document
- **Knowledge:** The taxonomy templates (`phase`, `activity`, `workflow_template` types) are exactly the right existing tool for this — a genuinely strong fit already sitting unused for this purpose
- **Recommendation:** "Review the proposed structure" (explicitly labelled ASSUMED/SUGGESTED, per the brief's own trust model)
- **Action:** Draft-only project + draft workflow from template; explicit user confirmation required before the project is "live"

### 4. "Check whether this will affect the handover date."
- **Intent:** Schedule-impact query
- **Context:** Current project, most recent relevant event/variation
- **Workflow:** `reasoning_engine.project_lookahead_view()` / `reasoning_projections.project_lookahead()` — the real dependency graph, already built
- **Health:** Schedule dimension
- **Recommendation:** Derived directly from the existing dependency chain — no new computation needed, only new *phrasing* of an existing answer
- **Action:** None — informational

### 5. "Prepare the payment schedule." (20/30/30/20 split, the brief's own example)
- **Intent:** Commercial schedule setup
- **Commercial:** A sequence of `commercial_engine.create_milestone()` calls, each with a `planned_percent` derived from the stated split
- **Recommendation:** The structured schedule, shown before creation, explicitly labelled INFERRED
- **Action:** Draft milestones; requires confirmation (financial structure)

### 6. "Why is this project showing as high risk?"
- **Intent:** Explanation query
- **Health:** **Already fully answered** by `reasoning_engine.explain_health()` and the existing "View Calculation" screens (`explain-health/[id].tsx`)
- **Action:** None — this scenario requires zero new engine work, only a natural-language front door onto an existing, correct answer

### 7. "Tell the PM about this."
- **Intent:** Notification dispatch
- **Context:** The subject of "this" — resolved from conversation context (the real work here: correct pronoun/reference resolution, not a new notification mechanism)
- **Action:** `notification_engine.create_notification()` — already the single call site every other engine uses
- **Confirmation:** Low-risk; could be auto-sent, or shown for one-tap confirmation

### 8. "Compare this project with our previous residential projects."
- **Intent:** Comparison query
- **Reasoning:** `reasoning_engine.compare_projects()` **already exists** and does real comparison once given project IDs
- **Knowledge:** *Gap* — "previous residential projects" requires knowing project *type*, which is not consistently captured as structured metadata today; this is a real, specific, fixable gap (a single new field plus disciplined capture at creation time), not a missing engine
- **Action:** Resolve the IDs, then call the existing function — no new comparison logic needed

### 9. "Make a preliminary budget."
- **Intent:** Budget drafting
- **Commercial:** `commercial_engine.create_budget()` with categories inferred from project type/scale, cross-checked against the taxonomy's own category items
- **Recommendation:** Explicitly labelled ASSUMED, since a preliminary budget without a full BOQ is inherently a rough estimate
- **Action:** Draft only; requires confirmation

### 10. "What's happening on my projects today?"
- **Intent:** Daily digest query
- **Reasoning:** **Already exists in three separate forms** — `since_last_visit()`, `inbox_intelligence_service`'s daily digest, and `my_day()` — currently requiring the user to know which of three screens to open
- **Recommendation:** A single synthesized answer combining all three — pure orchestration of existing, correct outputs, no new computation
- **Action:** None — informational

**Pattern across all 10 scenarios:** in 7 of 10, the underlying deterministic capability already exists and is correct; the gap is exclusively the missing layer that resolves free text into the right existing function call(s). In the remaining 3 (vendor/labour history, comparable-project detection, benchmark contract values), the gap is a genuine, named data/capability gap that no orchestration layer can paper over — it requires new, disciplined data capture over time, honestly represented as a longer-term capability, not a Phase 1 deliverable.

---

## G. Screen Reduction Proposal

Applying the brief's own test — "if this screen disappeared, could Atlas still accomplish the user's goal through a simpler interaction?" — to each screen mapped in Section B:

| Screen | Disposition | Reasoning |
|---|---|---|
| `projects/new.tsx` (4-step wizard) | **Becomes secondary, not removed.** | Stays as the "review and correct Atlas's draft" surface, not the primary entry point. A free-text description becomes the primary path; the wizard becomes the confirmation/edit screen the brief's own Section 6 example shows. |
| `op/create.tsx` (manual operational item form) | **Becomes secondary.** | The AI Proposal pathway (already the dominant real-world path via Capture) should be the default; manual creation remains for the case where no capture prompted it. |
| `knowledge/index.tsx`, `knowledge/[id].tsx` | **Stays, but reframed as an admin/config surface, not a user-facing destination.** | This is genuinely master-data configuration (Finding 2) — correctly kept out of the main navigation already; no change needed beyond not conflating it with "AI knowledge" in any future messaging. |
| `explain/[type]/[id].tsx`, `explain-health/[id].tsx` | **Stays, unchanged, and becomes more important.** | These are exactly the brief's own "Level 5 — raw data for advanced users" layer, already built correctly. Any new recommendation surface should link here for evidence, not duplicate it. |
| `portfolio-search.tsx` | **Candidate to merge into the prompt-first entry point.** | A search box and an intent box solve overlapping problems; once free-text intent resolution exists, a separate search screen may be redundant. |
| Standalone `daily-review.tsx` | **Stays as the artifact viewer, but generation should be reachable from anywhere ("prepare today's report"), not only from within the Review phase.** | |
| `(tabs)/ops.tsx` (full Operational Items list) | **Stays, unchanged.** | This is the correct "Level 5" destination once someone has been given a next-action and wants full context; it should not be a primary navigation destination (already isn't — correctly hidden as a tab). |

**No screen in the current product is recommended for outright deletion.** Every one of them serves a real, correct function once reached. The proposal is about *primacy* — which screen a user is dropped into first — not about removing capability, matching the brief's own explicit instruction not to throw away existing engines or screens.

---

## H. New Information Architecture

Derived from the actual application (not assumed to be a fixed five-tab structure, per the brief's own instruction) — the existing tab structure (Home / Projects / Capture / Inbox / More) is **kept**, because it already maps cleanly onto real, distinct user needs (a personal landing point, a project list, a way to report reality, a coordination inbox, and everything else). The proposed change is not to the tab structure but to what sits **inside** Home:

**Home becomes the intent surface.** Instead of a fixed set of cards, Home leads with a single, prominent input — text or voice — that can resolve to any of: a capture, a query, a creation request, or a command. Everything currently on each role's own Home screen (Today's Priorities, Continue Working, the 4-action grid, Client's progress summary) remains, positioned *below* the intent box as the existing, already-correct "here's what's happening" layer — not replaced, but no longer the only way in.

This is deliberately conservative: it adds one new surface to an already-sound structure, rather than inventing a new navigation paradigm the brief did not ask for and the existing, working screens do not need.

---

## I. Intent Layer Architecture

Given Atlas's own established engine-composition pattern (routes are thin; engines own logic; `reasoning_engine.py` composes across engines already), the intent layer should be a **new, thin composition module** — following the exact discipline the codebase already uses for `reasoning_engine.py` and `services/event_intelligence_service.py` (built this year, see `docs/ATLAS_FREEHAND_EVOLUTION.md`) — not a new engine with its own storage.

**Proposed shape of one resolved interpretation:**

```
{
  "intent": "create_variation" | "capture_reality" | "query" | "create_project" | ...,
  "confidence": "high" | "medium" | "low",
  "context": {
    "project_id": "...",       // resolved from conversation state or explicit selection
    "resolved_from": "explicit" | "inferred_from_recent_activity" | "ambiguous"
  },
  "entities": {
    "material": "quartz",
    "affected_area": "kitchen counters",
    ...                        // intent-specific, extracted once
  },
  "required_engines": ["commercial_engine", "workflow_engine"],
  "assumptions": [
    {"field": "cost_impact", "value": null, "status": "requires_confirmation"}
  ],
  "confirmation_required": true
}
```

**Where this fits the existing pipeline:** `intelligence_engine._structure()` already produces exactly this kind of structured object from voice/text/photo input (transcript → JSON, single LLM call). The intent layer for text/voice **entry points outside Capture** should reuse this same `_structure()`-style single-pass extraction — one LLM call producing intent + entities + confidence + assumptions together — rather than a chain of separate LLM calls for intent, then entities, then confidence. This directly satisfies the brief's own Section 3 instruction ("do not create redundant AI calls when one structured analysis can be shared by multiple downstream engines").

**Confidence and ambiguity handling:** when `context.resolved_from` is `"ambiguous"` (e.g. the user has multiple active projects and none was named), Atlas asks one clarifying question rather than guessing — matching the brief's own Section 6 example ("It should ask only for information that materially changes the result").

---

## J. Orchestration Architecture

**One structured interpretation, many deterministic consumers.** The single LLM-produced object from Section I is never re-sent to another model for a second opinion on the same input. Instead, `required_engines` drives a fan-out of ordinary, already-existing async function calls — the same pattern `reasoning_engine.py` already uses internally when it calls into `commercial_engine`, `workflow_engine`, and `operations_engine` to build a portfolio digest.

```
Free-text / voice input
        ↓
  ONE structuring call (reused pattern from intelligence_engine._structure)
        ↓
  Structured interpretation (intent + entities + confidence + assumptions)
        ↓
  Deterministic dispatch to required_engines (no further AI calls)
    ├── commercial_engine   (facts: contract, budget, milestones)
    ├── workflow_engine     (facts: schedule, dependencies)
    ├── operations_engine   (facts: open items, blockers)
    ├── reasoning_engine    (composition: health, priority, forecast)
    └── memory/knowledge_graph (facts: history, related records)
        ↓
  Unified result assembled from real, deterministic outputs
        ↓
  Recommendation (Section K) — template-composed, evidence-linked
        ↓
  Confirmation gate (Section L) where required
        ↓
  Execution via existing engine write functions (create_variation, create_milestone, etc.)
        ↓
  Memory (the action itself becomes a new Event / audit record — no new mechanism needed, Events are already immutable and permanent)
```

This mirrors, almost exactly, the architecture `services/event_intelligence_service.py` already implements for the single case of "what does this captured event relate to" (see `docs/ATLAS_FREEHAND_EVOLUTION.md`) — one AI-derived summary, multiple deterministic lookups (milestone matching, activity matching), zero additional AI calls. The intent layer is this same pattern, generalized from "one captured event" to "any free-text input."

---

## K. Recommendation Architecture

Atlas already has one working recommendation format, in `reasoning_engine`'s insight generation: `observation` → `recommendation`, each insight carrying a `domain`, `severity`, and grounding evidence references. The intent-layer recommendation format should extend this existing shape rather than invent a new one:

| Field | Source |
|---|---|
| **What happened** | Deterministic fact from the relevant engine (e.g. `commercial_engine`'s own payment-request status) |
| **Why it matters** | Composed from the same evidence the existing `explain_health()` / `reasoning_insights` already reference — impact framed in terms the user already sees elsewhere (days, ₹, %) |
| **What should happen** | The recommendation text — template-composed from the deterministic facts, exactly like `daily_site_report_service.py`'s own "deterministic template composition, not LLM prose" (confirmed in that file's own comments) |
| **Who should act** | Resolved from the project's own role assignments (PM, Supervisor) — already known data |
| **Evidence** | A link into the existing "View Calculation" / `explain/[type]/[id].tsx` screens — reusing Section G's finding that this transparency layer is already correct and should not be duplicated |

**This deliberately keeps AI narrow.** The recommendation's *prose* can be template-composed deterministically (as Daily Site Reports already prove works well and avoids hallucination structurally); only the *initial intent resolution* needs an LLM call. This matches Finding 5 and the brief's own explicit instruction not to let AI replace deterministic reasoning.

---

## L. Trust / Confirmation Model

Directly extending the brief's own FACT / INFERRED / SUGGESTED / ASSUMED / REQUIRES CONFIRMATION vocabulary, mapped against what Atlas already does and does not enforce:

| Action Class | Example | Atlas Behavior |
|---|---|---|
| **Informs** | "Why is this at risk?", "What's happening today?" | No confirmation needed — purely reads existing, correct deterministic data (Section F, scenarios 4, 6, 10) |
| **Suggests** | "This may relate to the Bathroom Tiling Milestone" | Shown, never auto-applied — exactly how `event_intelligence_service.py` already works today (labelled "possibly related", requires 2+ keyword grounding, never asserted as certain) |
| **Prepares** | A draft project, a draft payment schedule, a draft variation | Created in a draft/unconfirmed state; visible for review; **not yet the system of record** until confirmed — this requires a genuine new state (`draft` project / `draft` milestone-set) that does not fully exist today and is a real, named piece of new work, not a reuse of an existing mechanism |
| **Asks confirmation** | Anything financial, contractual, or that another person will see (a variation sent to a client, a payment request submitted) | **Already enforced server-side** for the highest-stakes actions — e.g. a PM can never approve their own payment request (confirmed in `commercial_engine.py`); this discipline must extend to anything the intent layer proposes, not be weakened by it |
| **Executes automatically** | A notification whose content is low-risk and unambiguous (e.g. "tell the PM about this" where "this" is unambiguous) | Permitted only for actions with no financial, contractual, or audit-irreversible consequence — matches the brief's own explicit carve-out |

**The one new architectural requirement this surfaces:** Atlas's engines today are built around records that, once created, are immediately real (an Event is immediately permanent and immutable; a Variation is immediately a real variation in `pending` status). The "Prepares" tier requires a genuinely new concept — a draft/proposed state that a person must promote to real before it enters the deterministic system of record. This is the single largest new architectural primitive this vision requires; everything else in this audit reuses what already exists.

---

## M. Top 20 UX Opportunities (ranked by user impact)

1. A single, prominent text/voice entry point on Home, replacing the need to know which of ~35 screens holds an answer.
2. Surface `executive_answer()`'s 7 fixed questions as natural-language-resolvable, not a hidden fixed vocabulary.
3. Extend the Capture pipeline's already-working structuring to project creation (Section F, scenario 3).
4. Extend it to commercial setup / payment schedules (scenario 5).
5. Synthesize `since_last_visit()` + daily digest + `my_day()` into one answer (scenario 10) — zero new computation, pure UX consolidation.
6. Allow photo attachment outside the Capture flow (currently scoped only to new events) — e.g. attaching a photo directly to a variation.
7. Let "Tell the PM about this" work from any screen, not require navigating to a notification-composition flow.
8. Make `explain_health()` reachable from a plain-language question, not only by navigating into Review phase.
9. Reduce the 4-step project wizard to a review/edit step after an intelligent first draft (scenario 3), not the primary path.
10. Add project *type* as structured, captured metadata at creation — unlocks `compare_projects()`'s own "comparable projects" use case for free.
11. Surface "What's likely next" (already built via `event_intelligence_service.py`) more prominently — it currently only appears after opening a specific event.
12. Let Management ask "which project needs me today" in one sentence instead of reading the Portfolio Control Center row by row.
13. Give Site Supervisors a spoken/typed way to ask "what's my task list" rather than only navigating to My Tasks.
14. Reduce the payment-request creation form's own field count by inferring the milestone from context when only one is obviously relevant.
15. Let a Client ask "what's happening" in plain language instead of navigating their own dashboard's sections manually.
16. Make the "View Calculation" transparency screens reachable directly from any recommendation, not only from the number they explain.
17. Add a lightweight "draft" visual state (Section L) so a user can tell at a glance what Atlas prepared versus what is already real.
18. Let a PM correct a misresolved intent in place ("no, I meant the other project") rather than restarting the flow.
19. Surface confidence level plainly in the UI whenever Atlas infers something, not just internally in the data model.
20. Consolidate `portfolio-search.tsx` into the same entry point as the intent box once both exist, avoiding two competing "type something" surfaces.

## N. Top 20 Assisted-Construction Opportunities (ranked by manual effort eliminated)

1. Voice-to-structured-project-model (scenario 3) — eliminates ~12 manually-typed fields per project.
2. Voice-to-payment-schedule (scenario 5) — eliminates N manual milestone-creation round trips.
3. Compound Hindi/English voice → multi-issue structured reality (scenario 2, the brief's own example) — already 80% built via the existing Capture pipeline; the remaining 20% is impact-estimation and auto-notification.
4. Variation drafting from a described client request (scenario 1) — eliminates a manual form for the most common mid-project commercial event.
5. Auto-selecting the right `workflow_template` from a free-text project description — turns an existing but manually-triggered capability (`generate_workflow`) into an automatic one.
6. Auto-notification when a captured reality implies a clear next actor (scenario 2's "notify PM").
7. One-sentence budget drafting (scenario 9), grounded in the existing taxonomy's own category list.
8. Auto-linking a captured update to the milestone/activity it likely completes (already built — `event_intelligence_service.py` — but not yet extended beyond the Capture flow to, e.g., a typed note on the Bill phase).
9. Turning "compare with our previous residential projects" into a real, automatic query once project type is captured (Section M #10 is the prerequisite).
10. Auto-drafting a Daily Site Report on request from anywhere, not only from within Review phase.
11. Auto-resolving "which project" from recent activity when a user's intent doesn't name one explicitly.
12. Client-facing "what's happening" auto-summarized from the same data PM/Management already see, filtered to client-safe fields (the client-safe filtering logic already exists in the commercial engine for Daily Site Reports — reusable, not new).
13. Turning a described payment behaviour pattern ("client always pays late") into a flagged, visible pattern **once that data starts being captured** — named honestly as a data-capture prerequisite, not a Phase 1 deliverable.
14. Auto-drafting milestone status transitions when a captured update's own language strongly implies completion (with confirmation required, per Section L).
15. Reducing operational-item creation to "just describe it" for the common case, with the manual form remaining for the exception.
16. Auto-populating the "assumptions requiring confirmation" list for any drafted entity, rather than the user having to infer what Atlas guessed.
17. Turning a spoken schedule-impact concern into an automatic dependency-graph check (scenario 4) rather than a manual lookahead-screen visit.
18. Reducing the number of times a PM must leave their current screen to check something Atlas could answer inline.
19. Auto-suggesting the likely next operational item after one is completed, using the same dependency-graph logic that already powers "next likely activity."
20. Long-horizon: vendor/contractor performance surfacing (Section 11 of the brief) — named explicitly as requiring new, disciplined data capture over multiple projects before it can exist at all; this audit does not claim it is close to feasible today.

---

## O. Proposed Product Philosophy

Permanent principles, derived from what already works well in Atlas and what this audit found missing:

1. **One structured interpretation, many deterministic consumers.** Never call an LLM twice for the same piece of user input. This is already Atlas's practice in the two places it uses AI at all (Finding 5); the intent layer must not be the place this discipline breaks.
2. **AI resolves ambiguity; engines establish truth.** The moment a fact can be computed deterministically (health, forecast, commercial state, schedule impact), it must be — never re-derived by a language model. Atlas already does this everywhere except the still-unbuilt intent-resolution step.
3. **Nothing Atlas prepares becomes real without a clear, visible confirmation step**, proportional to the stakes of the action — informs and suggests need none; anything financial, contractual, or visible to another party needs one.
4. **Every recommendation must be traceable to evidence a user can actually open** — the existing "View Calculation" transparency layer is a genuine asset; new recommendation surfaces must link into it, not duplicate or bypass it.
5. **Existing engines are read, not rebuilt.** Every one of the 10 scenarios in Section F reused real, existing functions. New product surface should default to composing what exists before writing anything new.
6. **Screens are never deleted for their own sake** — only reordered by primacy, so a person can still reach full detail when they want it (the brief's own Level 5).
7. **Role-based visibility is enforced once, server-side, and never re-implemented in a new layer** — the intent/orchestration layer routes through existing authorization checks, it does not gain new powers of its own.
8. **A gap in data is not a gap the AI can talk its way around.** Where Atlas genuinely lacks the history to make a claim (vendor performance, comparable projects), it says so, rather than generating a plausible-sounding but ungrounded answer.

---

## Phased Roadmap

Ordered by dependency, not strictly by the brief's own suggested sequence — reordered where repository evidence changes what should come first.

| Phase | Scope | Why This Order |
|---|---|---|
| **1. Intent + Context architecture** | The structured-interpretation module (Section I), reusing `intelligence_engine._structure()`'s own pattern for a general text/voice entry point | Nothing else in this roadmap can start without this — it is the one genuinely new architectural piece everything else calls into |
| **2. Text input** | Wire Phase 1 into a Home-screen entry point for typed input first (simpler than audio infrastructure, proves the orchestration model end-to-end) | De-risks the harder audio path before adding it |
| **3. Multi-engine orchestration (read-only queries first)** | Scenarios 4, 6, 8, 10 — all pure queries against existing, correct deterministic engines, zero new write paths, zero new confirmation model needed | The lowest-risk, highest-confidence slice — proves the fan-out pattern (Section J) with no financial or contractual exposure |
| **4. Recommendation + explainability** | Section K's template-composed recommendation format, linked to existing "View Calculation" screens | Builds directly on Phase 3's read-only foundation before any write actions exist |
| **5. Trust / confirmation model + the draft-state primitive** | The one genuinely new architectural piece from Section L — draft projects, draft milestone sets | Must exist *before* any "Prepares" tier action is allowed to ship, not after |
| **6. Voice input** | Extend Phase 2's entry point to audio, reusing the existing Whisper pipeline already proven in Capture | Voice-specific work (the brief's own Hindi/English example) is now additive to an already-working text pipeline, not the first thing being debugged |
| **7. Assisted project creation** | Scenario 3 — reusing `generate_workflow()` + taxonomy templates, gated by the Phase 5 draft-state model | The single highest-effort-eliminated opportunity (Section N #1), but depends on Phases 1, 5, and 6 all being solid first |
| **8. Assisted commercial planning** | Scenario 5 — payment schedules, budgets | Financially consequential; explicitly sequenced after the confirmation model (Phase 5) is proven, not before |
| **9. Assisted site capture (extended)** | Generalizing the brief's own compound-issue example (scenario 2) beyond what Capture already does — auto-notification, impact estimation | Builds on Phases 1–6; the underlying transcription/structuring already exists, this phase is the orchestration and notification layer on top |
| **10. Role-specific intelligent Home / progressive disclosure convergence** | Section H's new information architecture, fully realized across all four roles | Deliberately last — it is the UX packaging of everything the prior nine phases actually built, not a phase with independent technical risk of its own |

**Explicitly out of scope for all 10 phases**, named directly rather than left implicit: vendor/contractor performance tracking, historical outcome learning, and comparable-project benchmarking (Section N #20) require new, disciplined data capture across many real projects over time. No phase above can deliver them — they are a data problem, not an orchestration problem, and claiming otherwise would violate this document's own trust model (Section L).



