# PX-01 — Atlas Product Experience & Workflow Simplification

This document is a product strategy analysis, not an engineering report. No code was written or changed. Every claim about what currently exists - which screens exist, what they let a user do, which API calls a screen actually makes - was verified directly against the current repository, not assumed from feature names or prior sprint reports. Where a claim is about a person's likely experience rather than a verifiable fact, it is presented as judgment, not evidence.

---

## 0. The Headline Finding — Read This First

Atlas cannot run a real commercial lifecycle today, in the UI, at all. Every commercial mutation capability that exists in the backend - create a contract, edit a contract, upload or edit a BOQ, manage a budget, create or edit a milestone, create a variation, request a payment, record a payment, edit a payment, view a financial audit trail - has zero UI surface. The entire frontend commercial API client (frontend/src/commercial_api.ts) contains exactly nine functions. Eight are reads. The ninth, apiDecideVariation, is the only commercial mutation reachable from any screen in the product, and it only lets a client approve or reject a variation someone else already created through a script or a direct API call.

This means: a real Project Manager, on a real Monday morning, cannot create a contract for a new project inside Atlas. Cannot raise a milestone. Cannot record that a client paid an invoice. The rich, realistic commercial data in the Reference Portfolio - the numbers Explain Health, Commercial Intelligence, and every executive dashboard confidently display - exists only because it was seeded by a script, not because a human could have entered it through the product. Commercial Intelligence is real and works. Commercial Operations does not exist. This is the single most important finding in this review, and it reframes everything else: no amount of navigation simplification matters if the thing being navigated to cannot actually be operated.

This is detailed fully in Section 6, but is stated here first because it should be read before anything else in this document.

---

## 1. Complete UX Audit — Current Issues

Verified directly against the current screen inventory (frontend/app/, 28 screens) and navigation code, not inferred from screen names.

### 1a. Navigation is deeply nested and engine-shaped, not workflow-shaped

The only direct entry points from the main navigation hub (the Profile tab, gated to management) are: Executive Hub, Portfolio Control Center, Knowledge, User Management, System Info - five links. Everything else - Priority Engine, Executive Timeline, Portfolio Search, Explain Health, Commercial Workspace, Daily Review, Site Progress, Workflow - is reachable only by first landing on one of those five and finding a header icon or a card that leads further in. A management user who wants to check "what needs my attention today" has no single, obvious first stop; they must already know that Executive Hub is a hub and Portfolio Control Center is something different, and guess which one answers their actual question.

This is architecturally consistent with the document's own diagnosis: every capability became its own destination (Priority Engine, Executive Timeline, Explain Health, Commercial Intelligence, Cross-Project Intelligence are each a distinct screen or distinct section of a screen), rather than the product organizing those same underlying computations around a person's actual question ("what needs a decision from me").

### 1b. Terminology leaks the underlying architecture into the UI

Screen and section names taken directly from the current navigation: "Executive Hub," "Executive Timeline," "Priority Engine," "Cross-Project Intelligence," "Explain Health," "Portfolio Control Center." These are engine names, not user-facing concepts a construction business owner uses in a sentence. Nobody runs a construction company and says "let me check Cross-Project Intelligence" - they say "are we seeing the same problem on more than one site." The names were not wrong when built (each sprint that built them documented exactly what they compose), but collectively they now read as a systems diagram, not a product.

### 1c. Genuinely duplicated information across screens, verified, not assumed

Confirmed by reading each screen's own data source: Executive Hub's own "Today's Priorities" panel and the standalone Priorities screen both call apiPriorityEngine() and render overlapping content - Executive Hub shows a 3-item summary of the same list the full Priorities screen shows in full. This is not necessarily wrong (a summary card that deep-links to its own full view is a defensible pattern), but as currently built there is no visual or textual cue on Executive Hub that this is "the same list, abbreviated" rather than a separate thing - a user has no way to know without opening both.

### 1d. The client experience is real and appropriately restrictive, with one contradiction worth flagging

The Client Dashboard (ClientDashboardScreen, rendered as the client's own home tab) is genuinely separate from the internal My Day frame - confirmed directly in (tabs)/index.tsx, where viewRole === 'client' returns an entirely different component tree. This is correct and matches the brief's own instruction that clients should never see internal operations. The one contradiction: the client-facing commercial/[id].tsx route is the same file as the internal Commercial Workspace, branching internally on viewRole === 'client' to show a restricted view. This works today, but it means client-facing and internal-facing commercial logic live in one file with one shared risk surface, rather than being cleanly separated - worth flagging as a latent risk even though no defect was found in the branching itself.

### 1e. The Operational Items screen is the most functionally complete screen in the product, and it is the least prominent

op/[id].tsx supports the full item lifecycle: assign, transition through every status, comment, request clarification, set/clear blockers, edit, voice-update, mark duplicate - this is the one place in Atlas where a real operational workflow, start to finish, actually works end-to-end in the UI. Yet it has no dedicated top-level navigation entry; it's reached only by tapping into an item from My Day, Daily Review, or the Ops tab. The most capable, most "does what a real user needs" screen in the product is also the most hidden. Commercial Operations, discussed in Section 6, is the inverse problem: highly visible read-only data with zero underlying capability.

---

## 2. User Journey Maps

Each map reflects the current product, verified against actual screens and API calls, followed by the friction it creates.

### Management / Business Owner

Current path to answer "what needs a decision from me today": Open app -> land on My Day (shared frame, admin widget set: PortfolioSummaryWidget, MyDaySection, ManagementCreCards) -> this shows operational signals, not commercial or executive ones -> go to Profile tab -> tap Executive Hub -> see a composed summary (Priority Engine top-3, Cross-Project Intelligence top patterns, Commercial Intelligence six stat lines) -> for anything specific, drill into Priorities, Commercial Intelligence detail, or Portfolio Control Center separately.

Friction: three different screens (My Day, Executive Hub, Portfolio Control Center) each partially answer "what needs my attention," none fully. Reaching Executive Hub takes two navigation actions from app launch even though it's arguably where this role should land first. Nothing in Commercial Intelligence links forward to action - if it flags a project as over budget, there is no next click that lets this person do anything about it (see Section 6).

### Project Manager

Current path through a working day, as the brief itself describes it (review -> assign -> answer clients -> resolve blockers -> approve -> monitor commercial -> close day):
- Review work: My Day (shared frame, PM widget set) - works well, this is a genuinely composed daily view.
- Assign work: from an operational item's own detail screen (op/[id].tsx) - works, but only reachable per-item, not as a batch "assign today's new items" action.
- Answer client questions: via comments on a client_approval item, from that item's own detail screen - works, and Beta-06G's own fix (an "AWAITING YOUR RESPONSE" badge) helps this specific case.
- Resolve blockers: via the same item detail screen's blocker controls - works.
- Approve requests: same pattern.
- Monitor commercial progress: Commercial Workspace (commercial/[id].tsx) - read-only. A PM can see that a milestone is overdue or a payment is outstanding, and can do nothing about it from here (see Section 6).
- Close the day: Daily Review - works, and correctly shows what finished today (after Beta-06E's fix).

Friction: the operational half of this day genuinely works and is reasonably well composed. The commercial half is a dead end - the PM can monitor but never act, which directly contradicts the brief's own description of this role's day.

### Site Supervisor

Current path: Capture tab (voice/photo) -> Ops tab (item list) -> tap into an item to update status/add a comment.

Friction: genuinely low, and this is worth stating plainly rather than manufacturing a problem - the capture flow is a dedicated tab with minimal navigation depth, matching the brief's own instruction ("large buttons, minimal text, almost no navigation"). This is the role whose current experience most closely already matches the brief's own target state.

### Client

Current path: Client Dashboard (home) -> Investment, Payment Journey, Variation Centre are queryable via the client-specific branch of commercial/[id].tsx.

Friction: the underlying data is genuinely appropriate (contract value, paid, outstanding, milestones, photos) and correctly restricted (confirmed: no path from any client screen reaches an internal/management screen). The one gap: approving or rejecting a variation is the only action a client can take anywhere in the product - requesting clarification and commenting exist at the API level (verified in routes/operational_items.py) but their presence in the client-facing UI was not independently re-confirmed in this pass and should be checked before treating this as fully resolved.

---

## 3. Workflow Simplification Plan — Before vs. After

This section proposes information-architecture changes only, per the brief's own instruction not to redesign visually or write code.

| Workflow | Before | After |
|---|---|---|
| "What needs my attention today" (Management) | Spread across My Day, Executive Hub, Portfolio Control Center - three screens, none complete | One landing view for this role, organized by decision type (financial decisions, operational risks, client-facing items), with Executive Hub's existing composition logic reused as the data source - not rebuilt, re-surfaced |
| "Monitor and act on commercial status" (PM) | Read-only Commercial Workspace with no path to action | The same screen, with the missing mutation actions from Section 6 added as the natural next click on each relevant card (e.g., a milestone card that's ready to be marked achieved shows that action inline) |
| "Which of my approvals need my input" (PM) | Discoverable only by opening each client_approval item individually, partially helped by the Beta-06G badge | A dedicated, filtered list surfaced directly from My Day - "Items awaiting your response" - reusing the existing awaiting_clarification_response flag as the filter, not a new computation |
| Executive terminology | "Executive Hub," "Priority Engine," "Cross-Project Intelligence" | Renamed to plain-language equivalents at the presentation layer only ("Today's Decisions," "What Needs Attention," "Recurring Issues") - the underlying engines and their names in code are unaffected; this is a labels-and-copy change, not an architecture change |

---

## 4. Navigation Redesign — Information Architecture

Organized around the brief's own five categories (Work, Decisions, Projects, Communication, Capture), mapped to what exists today rather than invented fresh.

Work - My Day (already exists, already role-branched), Daily Review, Site Progress. No change to the underlying screens; the case for consolidation is addressed in Section 5.

Decisions - Priority Engine, Executive Hub's own summary panels, pending client approvals, commercial items requiring action (once Section 6's gap is closed). Currently scattered across Executive Hub, Priorities, and individual item screens; the proposal is a single "Decisions" destination that composes all of these via their own existing data sources, not new computation.

Projects - Project Dashboard, Workflow, Explain Health, Commercial Workspace, Site Progress - all already exist as per-project destinations; currently reached inconsistently (some from Portfolio Control Center's row, some from Project Dashboard's own links). The proposal is consistent entry: every per-project destination reachable from the Project Dashboard, and only from there, rather than some being reachable from Portfolio Control Center directly and bypassing the project's own home screen.

Communication - Client approvals, comments, clarification requests. Currently embedded inside individual operational item screens with no aggregated view for a PM. The gap named in Section 3's "awaiting your response" proposal belongs here.

Capture - Already its own tab, already minimal. No change proposed.

Explicitly not reorganized under this scheme: Portfolio Search, Knowledge Base, User Management, System Info - these are utilities, not workflow destinations, and forcing them into one of the five categories above would be artificial. They remain accessible from the Profile/admin menu as they are today.

---

## 5. Screen Consolidation Plan

| Screen | Recommendation | Basis |
|---|---|---|
| Executive Hub + Priorities | Merge. Priorities' full list becomes Executive Hub's own expandable section rather than a separate destination, since Executive Hub already embeds a summary of the same data. | Verified duplication in Section 1c. |
| Executive Timeline | Keep separate, but link forward from Executive Hub explicitly (already does - confirmed in executive-hub.tsx). No change needed beyond what exists. | Distinct enough use case (chronological audit) to warrant its own screen; already correctly cross-linked. |
| Portfolio Control Center | Keep, but reposition as the entry point for "browse all my projects," distinct from Executive Hub's "what needs a decision." Currently both partially serve as a management landing screen with unclear differentiation. | Section 1a. |
| op/[id].tsx | Elevate, don't consolidate - its capability is correct and complete; the fix is discoverability (Section 4's "Decisions" and "Communication" categories both should surface it more directly), not merging it into something else. | Section 1e. |
| Daily Review + Site Progress | Keep separate. Different scopes (portfolio-wide "what finished today" vs. single-project "where are we") that were confirmed in Beta-06E to be genuinely non-duplicative once correctly scoped. | Verified in prior engagement work, re-confirmed here by reading both screens' own data sources. |
| Knowledge Base | Keep as a utility, not a workflow screen - correctly separate today. | No issue found. |

---

## 6. Commercial Operations Gap Analysis

This is the audit the brief made mandatory. Every item below was checked directly against frontend/src/commercial_api.ts (the complete list of commercial functions the frontend can call) and the screens that would need to call them.

| Workflow | Backend exists? | UI exists? | Verdict |
|---|---|---|---|
| Create Contract | Yes (POST /api/commercial/contracts, used extensively and verified throughout this engagement's own backend work) | No - no frontend function calls this endpoint anywhere | Operational blocker |
| Edit Contract | Yes (revise_contract in the backend engine) | No | Operational blocker |
| Terminate Contract | Confirmed absent — a direct search of `engines/commercial_engine.py` for "terminate" found zero matches | No | Genuine gap on both sides, not just unconfirmed |
| Upload BOQ | Confirmed absent — same search, zero matches for "BOQ" or "bill of quantities" anywhere in the commercial engine | No | Genuine gap on both sides, not just unconfirmed |
| Edit BOQ | Same as above | No | Same |
| Budget Management (create/update) | Yes (create_budget, budget update paths exist in the backend engine) | No | Operational blocker |
| Milestone Creation | Yes (POST /api/commercial/milestones) | No | Operational blocker |
| Milestone Editing/Status Transition | Yes (transition_milestone_status, hardened for authorization in RC-02) | No | Operational blocker |
| Variation Creation | Yes (POST /api/commercial/variations) | No | Operational blocker |
| Variation Approval | Yes | Yes - apiDecideVariation, client-facing only | The one commercial mutation that actually works end-to-end in the UI |
| Payment Requests (create) | Yes (POST /api/commercial/payment-requests) | No | Operational blocker |
| Payment Recording | Yes (record_payment) | No | Operational blocker |
| Payment Editing | Not identified as an existing backend capability (payments appear to be append-only once recorded, consistent with financial audit-trail practice) | No | Likely intentional on the backend side (correcting a payment via a reversing entry rather than editing history is standard financial practice) - but there is no UI for even that correction path either |
| Invoice History | Payment/payment-request history is queryable via the backend | Partially - Commercial Workspace displays this as a read-only list | Read path exists; no export or invoice-specific formatting confirmed |
| Commercial Corrections | Confirmed absent as a distinct capability — the only "correction" reference found anywhere in the commercial engine is a code comment explaining the `is_adjustment` flag on `record_payment`, not a dedicated correction workflow | No | Genuine gap, not just unconfirmed |
| Financial Audit Trail | Commercial events (commercial_events collection, confirmed extensively throughout this engagement's Timeline work) provide a real, append-only history | No dedicated UI - the raw event list is visible inside Commercial Workspace's own event feed, but not presented as a formatted audit trail | The data exists; the presentation does not |

Overall verdict, as the brief asks for explicitly: yes, this is real, and yes, it should be classified as an operational blocker. The task's own observation is confirmed, not merely suspected: the seeded Reference Portfolio's commercial richness exists because seed scripts called backend functions directly. No construction company could reproduce that data through the product itself. Commercial Intelligence - the executive-facing view of budgets, variance, and cash flow - is accurately described elsewhere in this engagement as fully functional and well-verified. But intelligence about commercial data that nobody can enter through the product is intelligence about a dataset the company can never actually build. This is not a polish item; it is the single highest-priority gap in the entire product.

---

## 7. Prioritized Implementation Roadmap

Ranked by the combination of business impact and how directly each item was verified in this pass (not estimated effort in engineering time, which is outside this document's own scope per the brief's "do not write code" instruction).

Tier 1 - Blocks real usage entirely, verified with direct evidence:
1. Commercial Operations UI (Section 6) - without this, Atlas cannot run a real project's commercial lifecycle. Every other improvement in this document is secondary to this one.

Tier 2 - Meaningfully reduces daily friction for the two highest-frequency roles, verified against real navigation code:
2. Elevate Operational Items / "awaiting your response" into a first-class, directly-navigable destination (Sections 1e, 3, 4) - the PM's own described daily workflow depends on this.
3. Consolidate Executive Hub and Priorities (Sections 1c, 5) - removes a confirmed duplication with no loss of capability.

Tier 3 - Improves clarity without changing what any role can do, lower urgency:
4. Plain-language relabeling of engine-named screens (Section 3) - a presentation-layer change with no functional risk, appropriate to schedule after Tiers 1-2 land, not before, since it changes nothing structural on its own.
5. Consistent per-project navigation entry (Section 4's "Projects" category) - worth doing, but nothing in this pass found it actively blocking anyone, only adding friction.

Explicitly deferred, not because they're unimportant but because they require new backend capability first: Terminate Contract, BOQ upload/edit, and Commercial Corrections as distinct capabilities were each confirmed absent from the backend itself (Section 6), not merely missing a UI. Building screens for these is a larger scope of work than Tier 1's gaps — it requires new backend design and implementation first, which is outside this document's own "do not write code" boundary and belongs in a dedicated follow-up engineering pass, not bundled into the Commercial Operations UI work in Tier 1.
