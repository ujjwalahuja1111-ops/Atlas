# Atlas Commercial Foundation Engine
### Architecture & Domain Specification

**Status:** Architecture only. No implementation, no frontend, no APIs, no database changes. Every recommendation below is written to be implementable confidently in focused, sequential sprints — not implemented here.

**Grounding:** this specification is written from how real construction projects are commercially managed — BOQs, RA bills, work packages, retention, variations, milestone billing, procurement packages — not from how generic project-management software models "budget" and "invoice." Where a generic-software concept (Payment Request, Client Agreement, Scope, Tax) does not correspond to a distinct real-world commercial artifact, this document says so and recommends against giving it independent existence, per the brief's own instruction not to assume every candidate deserves an entity.

**Continuity:** this document extends, and does not contradict, the Commercial Layer sketch in the Atlas Domain Model (§6) and the Future Vision framing in the Atlas Product Bible. Where this document reaches a more specific conclusion than that earlier sketch (Work Package's role, Retention's exact shape, Tax's placement), the more specific conclusion here supersedes the sketch — the sketch was written before this domain had been studied in depth; this document is that study.

---

## 1. Purpose

### What the Commercial Foundation Engine owns

The complete commercial lifecycle of a construction project, from priced scope to final settlement: the Contract itself, the Bill of Quantities that prices the work, Work Packages that bridge scope to execution, the internal Budget a company tracks against, Variation Orders that formally change scope or price after signing, Procurement Packages for vendor-facing purchasing, and the billing chain — RA Bills and milestone-based Invoices, Payments received against them, and the Retention withheld and eventually released. It is the single, authoritative place Atlas answers three questions for any project: what did we agree to build, for how much; what has actually been billed and paid against that; and what do we now expect the final cost and revenue to be, given everything that's happened since signing.

### What it deliberately does not own

- General ledger accounting — double-entry bookkeeping, chart of accounts, tax filing, bank reconciliation. Atlas's Commercial Foundation Engine produces the commercial facts (an invoice was raised for this amount, on this date, against this contract) that an accounting system consumes; it does not become a second accounting system.
- Payroll or vendor payment execution — Atlas tracks that a Procurement Package exists and what it commits the project to spend; it does not run the actual vendor payment process, which belongs to whatever finance system a company already uses.
- Construction execution itself — activities, dependencies, status, and schedule remain Workflow Engine's, unmodified. The Commercial Foundation Engine reads execution state; it never becomes a second place execution is tracked.
- Physical measurement capture — the record of a measurement (what quantity of an item was executed, verified) is a Commercial Foundation Engine concern because RA billing depends on it, but the tooling to capture a measurement in the field is properly a future Measurement Engine's concern (§11). This document defines the data shape Measurement will populate; it does not build the capture mechanism.

### How this differs from ERP and Accounting software

Generic ERP and accounting software start from the transaction — a journal entry, an invoice line — and construction has to be forced into that shape after the fact (a BOQ item becomes a generic "product," a Work Package becomes a generic "project code"). The Commercial Foundation Engine starts from the opposite direction: it models a construction contract's own real structure — priced scope broken into billable quantities, work grouped the way a site actually organizes and procures it, billing tied to measured progress or reached milestones, retention withheld and released against a defect liability period — and only produces accounting-shaped output (an invoice, a payment record) at the boundary where it hands data to a system that genuinely is an accounting system. Atlas is the source of truth for what was agreed and what has happened on the project; an accounting system remains the source of truth for the company's books. The two are related, never merged.

### Integration with existing engines

- Workflow Engine — the Commercial Foundation Engine reads Workflow Activity status and the already-established STAGE_ORDER construction-lifecycle vocabulary as the trigger source for progress-based billing (RA bills, milestone bills). It never writes to a Workflow Activity, and it never maintains its own, second copy of "how far along is this project."
- Knowledge Engine — a BOQ item referencing a Knowledge Activity inherits that activity's unit of measure, and — where a Production Model exists for that activity — can read the same parametric quantity (e.g., a project's actual wall area) the Production Model already calculates from, rather than the Commercial Foundation Engine maintaining a separate copy of project-scale data.
- Operations Engine — a cost-impact conversation that starts in the field (a supervisor flags something, a client raises a concern) originates as an Operational Item, exactly as it does today; the Commercial Foundation Engine consumes that as the natural starting point for a formal Variation Order, rather than requiring a second, parallel "raise a commercial concern" mechanism.
- Timeline Engine — commercial events (an invoice raised, a payment received, a variation approved) become entries in a project's composed chronological view, read by Timeline Engine exactly the way an Event or a Correction already is — the Commercial Foundation Engine publishes into that composition, it does not maintain a competing timeline.
- Client Experience — every client-facing financial view this engine will eventually make possible (contract value, amount paid, upcoming payment, pending variation) is a read over Commercial Foundation Engine data, translated into client language exactly the way today's Client Experience Dashboard already translates CRE's health data — never a second, independently maintained "client financial summary."

### Presentation Summary
- The Commercial Foundation Engine owns a project's complete commercial lifecycle: Contract, BOQ, Work Packages, Budget, Variations, Procurement, billing, and Retention.
- It deliberately does not become a second accounting system, does not run vendor payments, and does not duplicate Workflow Engine's execution tracking or a future Measurement Engine's capture tooling.
- Unlike generic ERP/accounting software, it is modeled from construction's own real commercial structure first — BOQs, RA bills, retention — producing accounting-shaped output only at the handoff boundary.
- Every existing engine relationship is a read, never a duplication — the same "no duplicate truth" discipline the rest of Atlas already holds.

---

## 2. Core Commercial Domain — Entity Evaluation

### 2.0 Ownership Matrix

Every entity recommended as independent in this specification has exactly one owner: the Commercial Foundation Engine itself. This is worth stating as its own explicit table, not left implicit across the sections that follow — the value of doing so is confirming plainly that no entity in this domain has an ambiguous or split owner, the same discipline the Atlas Domain Model already holds for every existing engine's entities.

| Entity | Owning Engine | Notes |
|---|---|---|
| Contract | Commercial Foundation Engine | Sole writer of contract state and lifecycle transitions |
| Work Package | Commercial Foundation Engine | References, never owns, Workflow Activities (§3) |
| BOQ (Section, Item) | Commercial Foundation Engine | Sections/Items have no identity independent of their owning BOQ |
| Cost Code | Commercial Foundation Engine | Shared classification vocabulary, reused by BOQ Items and Budget lines — owned once, referenced twice |
| Budget | Commercial Foundation Engine | Internal-only; never co-owned with, or derived from, Contract/BOQ (§6, §12) |
| Variation Order | Commercial Foundation Engine | Absorbs Change Request and Rate Revision as states/subtypes, not separate owners |
| Procurement Package | Commercial Foundation Engine | Vendor-facing; distinct ownership from BOQ despite both eventually referencing Cost Code |
| Invoice | Commercial Foundation Engine | Single entity for both RA Bill and Milestone Bill billing methods |
| Payment | Commercial Foundation Engine | Distinct from Invoice specifically so partial payment is representable |
| Commercial Snapshot | Commercial Foundation Engine | Immutable, point-in-time; append-only, matching Atlas's platform-wide permanence discipline |

No entity in this domain is owned by Workflow Engine, Knowledge Engine, Operations Engine, Timeline Engine, or CRE — every relationship those engines have to commercial data is a read or a publish-into, never ownership, confirmed exhaustively in the Integration Matrix (§9).

### 2.1 Entity Catalogue

Evaluated against the brief's candidate list. Each verdict states whether independent existence is warranted, and if not, what the concept actually is.

| Candidate | Verdict | Reasoning |
|---|---|---|
| Contract | Independent entity. | The commercial agreement itself — value, terms, retention policy, defect liability period. |
| Client Agreement | Not independent — absorbed into Contract. | In construction practice, the agreement with the client is the contract; there is no genuine second artifact. Modeling them separately would create two records of the same commitment that could disagree. |
| Scope | Not stored — derived. | "Current scope" is the BOQ plus every accepted Variation Order to date. Storing it separately would duplicate what BOQ + Variation history already represents, and risk drifting from it — the same reasoning that keeps Timeline and Milestone unstored elsewhere in Atlas. |
| Work Package | Independent entity. | Evaluated in full in §3 — a genuine construction-native grouping concept, distinct from both BOQ and Workflow Activity. |
| BOQ | Independent entity, with Sections and Items as owned sub-structures (not separate top-level entities). | The priced backbone of the contract. Sections/Items only ever exist inside a BOQ; they have no identity independent of it. |
| BOQ Item | Sub-structure of BOQ (see above). | |
| Cost Code | Independent entity. | Internal cost classification (labour/material/equipment/overhead), reused across Budget lines and BOQ items — genuinely a shared vocabulary, not owned by either. |
| Budget | Independent entity. | Internal cost planning, deliberately distinct from the client-facing Contract/BOQ value. See §6. |
| Variation Order | Independent entity. | A formal, approved change to contract scope or price. |
| Change Request | Not independent — absorbed into Variation Order as its draft/pending state. | A Change Request and an approved Variation Order are the same underlying thing at two different lifecycle stages, not two different entities. Modeling them separately would duplicate exactly what a state machine already exists to represent. |
| Procurement Package | Independent entity. | Vendor-facing purchasing, genuinely distinct from BOQ (client-facing pricing) — what a project buys is not the same record as what it charges. |
| Milestone | Not stored — reused from existing Workflow/STAGE_ORDER concepts. | A billing "milestone" is a reference to a Workflow Activity or a construction stage already tracked elsewhere — not a new stored entity, consistent with the Domain Model's existing position that Milestone is always derived. |
| Invoice | Independent entity, generalized to represent both of construction's two real billing methods (RA Bill and Milestone Bill) as one entity with a billing_method field — not two separate entities. | See §5 and §8 — an RA Bill and a milestone-triggered bill differ in what determines the amount, not in what they fundamentally are (a billing document raised against a contract). |
| Payment Request | Not independent. | The closest real analogue — an advance or milestone payment ask before formal billing — is adequately represented by an Invoice in an early lifecycle state (see §4's lifecycle), not a second entity. |
| Payment | Independent entity. | Money actually received — deliberately distinct from Invoice, since an invoice can be partially paid over time. |
| Retention | Not an independent top-level entity — modeled as a Contract-level policy plus a running ledger of withheld/released amounts tied to Invoices. | See §6.4 — retention is genuinely stateful (withheld per bill, released in tranches after the defect liability period) but that state is naturally a ledger of Invoice-linked entries, not a freestanding entity with its own top-level lifecycle independent of the bills it was withheld from. |
| Tax | Not independent — a computed component of Invoice (and, where rates vary by item, of BOQ Item). | Tax has no identity or lifecycle of its own; it is always a calculated attribute of something else. |
| Forecast | Not independent — a component of the Budget Model. | See §6 — Forecast Budget is one of Budget's own tracked values, not a competing calculation the way a separate Forecast entity would risk becoming. |
| Commercial Snapshot | Independent entity. | A point-in-time, immutable capture of a project's full commercial state — mirroring the same pattern Construction Reasoning already uses for its own historical runs. Genuinely useful for audit, reporting, and — critically — the AI training signal described in §10, which needs comparable snapshots over time, not just current state. |

### Presentation Summary
- Nine candidate concepts were evaluated and correctly not given independent existence: Client Agreement (= Contract), Scope (derived from BOQ + Variations), Change Request (= Variation Order's draft state), Milestone (reused from Workflow/STAGE_ORDER), Payment Request (= an early-state Invoice), Tax (a computed attribute), and Forecast (a Budget component).
- Nine concepts were confirmed as genuinely independent entities: Contract, Work Package, BOQ, Cost Code, Budget, Variation Order, Procurement Package, Invoice, Payment, plus Commercial Snapshot.
- Every "not independent" verdict follows the same principle already established elsewhere in Atlas: no duplicate truth, no two records of the same real-world fact.
- Invoice is deliberately generalized to cover both RA billing and milestone billing as one entity — they differ in how the amount is determined, not in what they fundamentally are.

---

## 3. Work Package Model

### Should Work Package become a first-class Atlas entity?

Yes — as a commercial-and-procurement aggregation layer, not as a replacement for Workflow Activity.

This is the most consequential judgment call in this document, so it is worth being precise about what is and is not being recommended. Real construction projects — particularly anything beyond a small residential build — are commercially organized around Work Packages: "Structural Work Package," "MEP Work Package," "Finishes Work Package," each bundling a portion of the BOQ, a group of vendors procured against it, and a subset of the project's activities, for the specific purpose of tracking cost and progress at a granularity a full BOQ (hundreds of line items) or a full activity list is too fine to report on directly. This is a genuine, distinct commercial-reporting need that neither Workflow Activity nor BOQ currently serves.

What Work Package should not become: the primary planning abstraction, replacing Workflow Activity as the thing a schedule is built from. Workflow Engine's activity-and-dependency model is a working, tested planning engine — introducing Work Package as a competing planning primitive would be exactly the kind of engine redesign this sprint's own principles forbid, and would risk two systems disagreeing about what a project's actual schedule is. Work Package instead references Workflow Activities (many-to-many: a Work Package typically groups several activities; a large activity could in principle span two work packages, though this should be rare in practice) — it aggregates and reports on execution, it does not schedule it.

### Purpose
A commercial-and-procurement grouping of BOQ items, referenced Workflow Activities, and Procurement Packages, existing specifically to let a project be reported on, budgeted, and procured at a coarser, more useful granularity than either the full BOQ or the full activity list individually provide.

### Ownership
Commercial Foundation Engine. Work Package is a genuinely commercial concept (it exists to answer "how is this piece of the project doing, cost-wise") — it should not be owned by Workflow Engine, which correctly stays focused on execution scheduling, not cost aggregation.

### Relationships

```mermaid
graph TD
    WorkPackage[Work Package] -->|contains| BOQItem[BOQ Items]
    WorkPackage -.->|references, does not own| WorkflowActivity[Workflow Activities]
    WorkPackage -->|sourced via| ProcurementPackage[Procurement Packages]
    WorkPackage -->|rolls up into| Budget
    BOQItem -->|references, for unit/quantity| KnowledgeActivity[Knowledge Activity]
    KnowledgeActivity -.->|optionally, quantity source| ProductionModel[Production Model]
    WorkPackage -->|measured progress from| Measurement[Measurement - Future Engine]
    WorkPackage -.->|referenced by| Document[Document - Future Domain]
    WorkPackage -->|commercial status informs| ClientDecision[Client Decisions and Variations]
```

This directly matches, and confirms, the brief's own worked diagram: Work Package -> BOQ -> Activities -> Production Models -> Resources -> Measurements -> Documents -> Commercial -> Client Decisions — with one clarification this document adds precisely: the Activities link is a reference, not ownership, and Resources (labour/material/equipment allocation) is itself a future capability (§11), represented here as Procurement Package for the purchasing side of "resources" that already has a clear place in this architecture today.

### Lifecycle

```mermaid
stateDiagram-v2
    [*] --> planned: defined at contract/BOQ setup
    planned --> active: linked Workflow Activities begin execution
    active --> substantially_complete: measured progress crosses threshold
    substantially_complete --> complete: final measurement/billing settled
    complete --> [*]
```

### Consumers
Budget (cost roll-up), Client Experience (a future "progress by work package" view, more digestible than either raw BOQ or raw activity list), Portfolio Intelligence (a future cross-project "which category of work typically overruns" signal — directly feeding §10's AI readiness goals), and Procurement (which vendors/packages are tied to which piece of scope).

### Presentation Summary
- Work Package is recommended as a genuine, independent entity — but as a commercial and procurement aggregation layer, not a replacement for Workflow Engine's planning model.
- It references Workflow Activities rather than owning or replacing them, preserving the existing, working execution engine unmodified.
- It bundles BOQ items and Procurement Packages at a granularity useful for cost reporting — finer-grained than "whole project," coarser than "every BOQ line."
- This directly confirms the brief's own Work Package diagram, with one precision added: the Activities relationship is explicitly a reference, never ownership.

---

## 4. Contract Lifecycle

```mermaid
stateDiagram-v2
    [*] --> draft: Contract created
    draft --> review: submitted for internal or legal review
    review --> draft: changes requested
    review --> approved: internally approved
    approved --> active: signed by client, execution may begin
    active --> variation: a Variation Order is raised
    variation --> active: variation resolved, contract continues
    active --> completed: all BOQ scope executed and billed
    completed --> closed: retention released, defect liability period ended
    closed --> [*]
```

draft — Contract terms and initial BOQ are being assembled; owned exclusively by whoever is preparing the commercial proposal (Management/PM, per Atlas's existing role model).

review — Internal sign-off before the contract is presented to the client; can cycle back to draft.

approved — Internally approved, not yet signed; the contract is not yet commercially binding within Atlas.

active — Signed and binding. This is the state a project's Workflow Engine schedule generation should be gated on (a project should not begin formal, billable execution against a contract that isn't active) — a boundary condition worth stating explicitly here even though implementing that gate is not part of this sprint.

variation is not a separate persistent state so much as a transient marker — a contract in active state with one or more Variation Orders currently pending; the diagram shows it as a distinct node because the brief's own example does, but the more precise model is: active remains the contract's actual state throughout a variation's lifecycle, and the variation itself carries its own state machine (§7). A contract does not leave active merely because a variation is being discussed.

completed — All BOQ scope (as amended by every accepted Variation Order) has been executed and fully billed. The contract's commercial obligations are substantively finished, but retention has not yet been released.

closed — Retention released (fully or per whatever partial-release policy the contract specifies) at the end of the defect liability period. This is the true terminal state — a closed contract remains a permanent historical record, never deleted, matching Atlas's platform-wide permanence discipline.

Ownership: Commercial Foundation Engine exclusively, for every state transition. Transitions requiring approval (draft->review->approved, and the accept/reject decision within a Variation Order's own lifecycle) should reuse Atlas's existing RBAC model (management/PM-level actions) rather than introducing a parallel permission system.

### Presentation Summary
- Contract lifecycle: draft -> review -> approved -> active -> completed -> closed, with Variation Orders as a state within active, not a detour out of it.
- Active is the state that should gate whether formal, billable execution is permitted to begin — a real boundary condition for future implementation.
- Closed (after retention release) is the true terminal state; contracts are never deleted, matching Atlas's platform-wide permanence principle.
- All transitions are Commercial Foundation Engine's exclusively, reusing Atlas's existing RBAC model rather than a parallel one.

---

## 5. BOQ Architecture

```mermaid
graph TD
    BOQ --> Section1[Section: e.g. Civil Works]
    BOQ --> Section2[Section: e.g. MEP]
    Section1 --> Item1[Item: Excavation]
    Section1 --> Item2[Item: RCC Structure]
    Item1 --> Unit1[Unit: cum]
    Item1 --> Quantity1[Quantity: 420]
    Item1 --> Rate1[Rate: per unit]
    Quantity1 -->|x| Rate1
    Rate1 --> Amount1[Amount]
    Item1 -.->|classified by| CostCode[Cost Code]
    Item1 -.->|optionally grouped into| WorkPackage[Work Package]
    Item1 -.->|optionally references| KnowledgeActivity[Knowledge Activity]
```

BOQ belongs to exactly one Contract. Section is a pure organizational grouping within a BOQ (matching how a real BOQ document is structured — Civil, MEP, Finishes, etc.) with no commercial meaning of its own beyond grouping. Item is the actual priced line: description, unit, quantity, rate, and the computed amount (quantity × rate) — the one place in this entire domain model where a number is genuinely calculated, and it should be calculated the same deterministic way every other calculated value in Atlas is (see the Production Model precedent — a plain, explicit, testable calculation, never a stored formula string).

Cost Code classifies a BOQ Item for internal reporting (labour/material/equipment/overhead) independently of which Section it's organizationally filed under — the same item can be "in the Civil Works section" and "classified as Material cost" simultaneously; these are two different groupings serving two different purposes (client-facing organization vs. internal cost analysis), and Cost Code is what makes Budget's cost-type breakdown (§6) possible at all.

### Integration with Production Models

This is where BOQ Architecture and Knowledge Base v2's parametric Production Models meet directly, and it is worth stating precisely because it is one of the clearest wins available once this layer is built: a BOQ Item for "Wall Masonry" can reference the same Knowledge Activity a project's Workflow Activity already references — which means its quantity does not need to be entered a second time. The Production Model already calculates (and stores, per-project-instance) the actual wall area a specific project needs; the BOQ Item reads that same value rather than a commercial team re-measuring or re-entering something Atlas already knows. This is a direct, concrete instance of "no duplicate truth" applied to the commercial layer specifically — the quantity a client is billed for and the quantity a Production Model calculated a duration from are, correctly, the exact same number, read once from one place.

### Integration with the future Measurement Engine

A BOQ Item's contracted quantity (what was agreed) and its executed quantity (what has actually been measured and verified as complete) are deliberately two different numbers, tracked separately — an RA Bill is computed from the executed quantity, never the contracted one. This document defines the shape that distinction requires (a BOQ Item must be able to carry both an original quantity and an accumulating measured-to-date quantity) without building the Measurement Engine itself; the measured-to-date figure is populated by whatever future capture mechanism that engine provides, and this architecture is designed so that populating it is additive — it does not require restructuring the BOQ Item itself.

### Presentation Summary
- BOQ -> Section (organizational grouping) -> Item (the actual priced line) -> Cost Code (independent internal cost classification, orthogonal to Section).
- Amount is always calculated deterministically (quantity x rate) — the same explicit-calculation discipline the Production Model registry already established.
- A BOQ Item can share its quantity directly with an existing Production Model calculation, rather than re-entering a number Atlas already knows — a direct, concrete "no duplicate truth" win.
- BOQ Items are designed to carry both contracted and measured-to-date quantities from day one, so a future Measurement Engine can populate the latter additively, without restructuring this layer.

---

## 6. Budget Model

Budget is deliberately internal-only — distinct from the client-facing Contract/BOQ value, and never exposed through Client Experience the way Contract, Invoice, and Payment eventually will be (Client Experience Sprint's own explicit reasoning for deferring a Financial Summary was that no real data existed yet to back one; this section is where that real data will come from, once implemented, but Budget itself remains an internal management concern, not a client-facing one — a client sees what they agreed to pay, not what it costs the contractor to deliver it).

| Value | Definition | Update rule |
|---|---|---|
| Original Budget | The internal cost plan at contract signing — what the company expects to spend to deliver the contracted scope. | Set once, at contract activation. Immutable thereafter — a historical baseline, never edited. |
| Approved Budget | Original Budget adjusted for every internally-approved budget revision (distinct from a client-facing Variation Order — an internal cost re-plan doesn't necessarily change what the client is billed). | Updated only by an explicit, approved Budget Revision — never silently. |
| Committed Cost | The sum of everything the project is contractually obligated to spend, whether or not it's been invoiced by a vendor yet — driven directly by Procurement Package commitments. | Increases the moment a Procurement Package is committed; does not wait for an invoice. |
| Current Cost | Actual, incurred cost to date — money genuinely spent, not merely committed. | Increases as vendor invoices/payments are recorded against Procurement Packages. |
| Forecast Budget | The project's own best current projection of final total cost, given Approved Budget, Committed Cost, Current Cost, and remaining scope. | Recomputed, not manually maintained — the same "computed, not stored as a second opinion" principle that governs Timeline and Milestone elsewhere in Atlas. This is why Forecast is a component of the Budget Model (§2) rather than an independent entity: it is one more field this model produces, not a competing calculation. |
| Remaining Budget | Approved Budget minus Current Cost. | Purely computed, always, from the two values above — never itself independently editable. |

### Why Budget and Contract are deliberately separate numbers

A construction company's internal cost to deliver a scope of work and the price it charges a client for that scope are never the same number, and conflating them would be a serious architectural error — it would mean a client-facing view (Contract value) and an internal management view (Budget) could only ever be read from the same underlying data, when in reality a company's margin is the difference between them. Keeping Budget and Contract as genuinely separate entities, related only through the BOQ/Work Package structure both reference, is what makes it possible to correctly answer "are we making money on this project" without that calculation ever touching, or risking exposure through, the client-facing side of the platform.

### Presentation Summary
- Budget is deliberately internal-only, structurally separate from client-facing Contract value — this is what makes margin analysis possible without any risk of exposing it to a client.
- Original Budget is an immutable baseline; Approved Budget only changes through an explicit, approved revision — never silently.
- Committed Cost and Current Cost are tracked as two genuinely different numbers (obligated vs. actually spent), both driven by Procurement Package activity.
- Forecast Budget and Remaining Budget are always computed, never independently stored — the same "no duplicate truth" discipline applied to internal cost tracking.

---

## 7. Commercial Change Management

```mermaid
graph TD
    OperationalItem[Operational Item - field-raised concern] -->|may originate| VariationOrder[Variation Order]
    ClientRequest[Client Request] -->|may originate| VariationOrder
    VariationOrder -->|if approved, updates| BOQ
    VariationOrder -->|if approved, updates| Budget
    VariationOrder -->|if cost-impacting, requires| CommercialApproval[Commercial Approval]
    RateRevision[Rate Revision] -->|updates| BOQ
    BudgetRevision[Budget Revision] -->|updates| Budget
    CommercialApproval -.->|same mechanism as| ClientApprovalCentre[Existing Client Approval Centre]
```

Variation Order is the single entity governing every commercial change to scope or price, whatever prompted it — it may originate from a field-raised Operational Item (a supervisor identifies unforeseen ground conditions), a direct client request (the client wants an additional room), or an internal re-plan. A Variation Order's own lifecycle (proposed -> under_review -> approved | rejected) governs whether and how it actually updates the BOQ and Budget — nothing about scope or price changes until a Variation Order reaches approved.

Rate Revision is a narrower kind of change — the unit rate for a BOQ Item changes (a material cost increase is passed through) without necessarily changing quantity or scope. This is modeled as a specific kind of Variation Order (a variation_type field distinguishing rate-only changes from scope-adding/removing ones), not a separate entity — the approval and history-tracking needs are identical, only the effect differs.

Budget Revision is Budget's own, purely internal analogue — an internal cost re-plan that does not necessarily correspond to any client-facing Variation Order at all (e.g., a company revises its own labour cost assumption). It updates Approved Budget directly and requires only internal approval, never Commercial Approval in the client-facing sense.

### Commercial Approvals

A cost-impacting Variation Order is precisely the trigger condition this document's own predecessor (the Domain Model) named for finally introducing a first-class Decision entity — recommended there as not yet warranted, with the explicit condition that Commercial Layer implementation would be the right moment. This document confirms that condition is now met by this specification's own existence, and gives the specific reason precisely: unlike a material or design approval (well served today by an Operational Item's client_approval category), a cost-impacting Variation Order genuinely needs properties client_approval doesn't have — a monetary magnitude, a potential multi-step approval chain (site -> PM -> client, for larger amounts), and an outcome that formally modifies a different entity (the BOQ/Budget) rather than simply closing itself out. Recommendation carried forward from the Domain Model, now made concrete: implement Decision as the Commercial Foundation Engine's own approval mechanism for Variation Orders specifically, in the same implementation phase as Variation Order itself — not a platform-wide generalization of client_approval, and not built ahead of this specific, now-real need.

### Presentation Summary
- Variation Order is the single entity for every commercial change, whatever originated it — field-raised, client-requested, or internal — with nothing taking effect until it's formally approved.
- Rate Revision is a Variation Order subtype, not a separate entity; Budget Revision is Budget's purely internal analogue, requiring only internal approval.
- This document confirms the exact trigger condition the Domain Model named for introducing a first-class Decision entity: a cost-impacting Variation Order, specifically.
- Recommendation: implement Decision alongside Variation Order in the same phase, scoped to commercial approvals — not as a platform-wide generalization of the existing, and still correctly separate, client_approval mechanism.

---

## 8. Commercial Timeline

Commercial events are not a separate timeline — they are entries in the same composed, chronological project narrative Timeline Engine already produces from Events, Analyses, and Corrections. A construction project's commercial story, told this way:

```mermaid
graph LR
    A[Contract Signed] --> B[Advance Payment Invoice Raised]
    B --> C[Foundation Complete - Workflow Stage]
    C --> D[Milestone Bill Raised]
    D --> E[RA Bill 1 - Measured Progress]
    E --> F[Variation Order Approved]
    F --> G[RA Bill 2 - Includes Variation]
    G --> H[Final Bill]
    H --> I[Retention Release]
    I --> J[Project Closeout]
```

Contract Signed transitions the Contract to active (§4) — the point from which formal billing becomes possible.

Advance Payment is an early-lifecycle Invoice (§2's resolution of "Payment Request") — typically a fixed percentage, not yet tied to any measured progress.

Milestone-triggered billing (Foundation Complete -> Milestone Bill) reads a Workflow Activity's status or a project's STAGE_ORDER position directly — exactly the mechanism the Client Experience Sprint's own Project Timeline already uses to translate internal stage data into client-facing milestones, now reused as a billing trigger rather than only a display one. This is the same derived-data principle applied a second time, to a second consumer, without inventing a second way to determine "has this stage been reached."

RA Bills are the recurring, measurement-driven billing method — each one computed from the BOQ Items' measured-to-date quantities (§5), cumulative, with the previous bill's amount deducted so each RA Bill represents only the new progress since the last one, and retention withheld per the Contract's policy (§6.4 below expands this).

Variation Orders, once approved, modify the BOQ that subsequent RA Bills are computed from — a variation approved between RA Bill 1 and RA Bill 2 is reflected automatically in RA Bill 2's calculation, because RA Bill always reads the BOQ's current state, never a snapshot frozen at contract signing.

Final Bill settles all remaining measured quantity once execution is complete. Retention Release follows the defect liability period, per Contract policy — the point the Contract itself reaches closed.

### §6.4 — Retention, precisely

Retention is withheld as a percentage of each RA Bill (and typically the Final Bill), not deducted once at the end — meaning the correct model is a running ledger: each Invoice of billing_method=ra_bill carries a retention_withheld amount (computed from the Contract's retention percentage), and the Contract's total retention balance is the sum of every such entry across every invoice raised, minus every release recorded against it. Release itself may happen in tranches (a partial release at practical completion, a final release at the end of the defect liability period) — modeled as its own small entry type (a Retention Release record, linked to the Contract, with an amount and a date) rather than a single "release" flag, because real contracts genuinely do release retention in more than one step.

### Presentation Summary
- Commercial events are entries in Atlas's existing composed Timeline, never a separate, competing project history.
- Milestone billing reuses the exact same Workflow-stage-derived mechanism the Client Experience Sprint's Project Timeline already established for display — now reused for billing, without a second way of determining "has this stage been reached."
- RA Bills always compute from the BOQ's current state, so an approved Variation Order is reflected automatically in the next bill, with no manual reconciliation step.
- Retention is modeled as a running ledger across every RA Bill withheld, with release itself supporting multiple tranches — matching how retention genuinely works on real contracts, not a single end-of-project flag.

---

## 9. Integration Matrix

| Engine | Consumes from Commercial Foundation Engine | Publishes to Commercial Foundation Engine | Dependency direction |
|---|---|---|---|
| Workflow Engine | Nothing. | Activity status, STAGE_ORDER position (billing triggers), Production Model quantities (BOQ quantity source). | Commercial depends on Workflow; Workflow has zero dependency on Commercial — preserves Workflow Engine's existing independence completely. |
| Knowledge Engine | Nothing. | Activity unit-of-measure, Production Model definitions and calculated quantities (BOQ Item quantity/unit source). | Commercial depends on Knowledge; one-directional, matching the precedent already set by Workflow Engine's own existing dependency on Knowledge Engine's calculation registry. |
| Operations Engine | Variation Order origination point (a cost-impacting Operational Item may become a Variation Order). | Nothing (Operations Engine does not read Commercial data). | Commercial depends on Operations for origination only; no reverse dependency. |
| Timeline Engine | Nothing (Timeline Engine is a pure composition layer with no entities of its own to publish). | Commercial events (invoice raised, payment received, variation approved) as timeline entries. | Timeline composes Commercial's published events, exactly as it already composes Events/Analyses/Corrections. |
| Construction Reasoning Engine (CRE) | Nothing today; future — cost-overrun and cash-flow findings could become new CRE finding types, reading Commercial data the same way CRE reads Workflow/Operations data today. | Nothing (CRE does not write). | A future, optional read dependency — CRE would depend on Commercial, never the reverse, preserving CRE's existing "reads everything, owns nothing but its own findings" boundary. |
| Client Experience | Contract value, Invoice/Payment history, pending Variation Orders (client-approval-relevant ones), retention position — everything the Client Experience Sprint's deferred Financial Summary and Payment Centre would need. | Nothing (Client Experience is a pure translation layer). | Client Experience depends on Commercial; one-directional, exactly matching how it already depends on CRE for health/progress data today. |

No duplicated responsibility was found or introduced across this matrix. Every dependency is one-directional; no engine both consumes from and publishes to the Commercial Foundation Engine in a way that could create a cycle.

### Presentation Summary
- Every integration in this matrix is one-directional — no engine both consumes from and publishes to Commercial Foundation Engine, so no circular dependency is possible.
- Workflow and Knowledge Engines remain completely independent of Commercial — Commercial depends on them, never the reverse, preserving their existing boundaries unmodified.
- Client Experience's dependency on Commercial exactly mirrors its existing dependency on CRE — a pure translation layer, reading, never maintaining its own copy.
- CRE's future relationship to Commercial (cost-overrun findings) would be additive and optional, preserving CRE's "reads everything, owns nothing but its findings" boundary unchanged.

---

## 10. AI Readiness — Future Training Signals

This section designs deterministic data, per the brief's own instruction — not an AI feature. Every signal below is a plain, auditable calculation over Commercial Foundation Engine data; none of them require AI to produce, and all of them become genuinely valuable training signal only once accumulated across many completed projects.

| Signal | Deterministic definition | Why it matters |
|---|---|---|
| Budget Accuracy | Final Current Cost divided by Original Budget, per project and per Cost Code, at project closure. | The clearest possible measure of whether the company's own cost estimation is improving over time — and, per Cost Code, exactly which kind of work is hardest to estimate accurately. |
| Variation Frequency | Count and cumulative value of approved Variation Orders as a percentage of original Contract value, per project. | A high-variation project is a specific, nameable risk pattern — this signal is what would eventually let Atlas flag "projects like this one tend to see significant scope growth" as an evidenced finding, not a guess. |
| Cash Flow Patterns | Time-series of Invoice raised vs. Payment received, per project, showing the actual lag between billing and collection. | Directly informs future cash-flow forecasting — a genuinely valuable capability, buildable only once this data exists to learn from. |
| Cost Overruns | Current Cost exceeding Approved Budget, by Cost Code and by Work Package, with the specific point in the project timeline it occurred. | The Work Package-level granularity here is exactly why Work Package was worth making a first-class entity (§3) — "structural work overruns more often than finishes work" is a pattern only visible at that granularity. |
| Payment Delays | Actual payment date minus Invoice due date, per client, per project. | A deterministic, evidenced basis for future risk-scoring of payment reliability — never a subjective assessment. |
| Scope Growth | Cumulative approved Variation value over time, as a project progresses through STAGE_ORDER. | Distinguishes "scope grew steadily throughout" from "scope grew suddenly near completion" — genuinely different risk patterns, both fully derivable from data this architecture already captures. |
| Productivity vs. Cost | Production Model's calculated duration (Knowledge Base v2) cross-referenced against that same Work Package's actual cost — the direct bridge between Atlas's existing parametric duration calculations and this document's new cost data. | This is the single clearest example of two previously separate parts of Atlas becoming more valuable together than either was alone — a capability this architecture makes possible but does not itself build. |

Design principle held throughout this section: every signal is defined as a calculation over data this architecture already captures for its own operational purposes (billing, budgeting, procurement) — nothing here proposes capturing new data solely for the sake of a future AI feature. This is deliberate: data captured only to feed a model, with no operational purpose of its own, tends to be low-quality, because no one is actually relying on it day to day. Every signal above is a byproduct of data that has to be correct anyway for the Commercial Foundation Engine to do its actual job.

### Presentation Summary
- Every AI-readiness signal is a plain, deterministic calculation over commercial data — no AI is designed or required to produce any of them.
- Every signal is a byproduct of data this engine needs to be correct anyway for its own operational purpose — nothing is captured solely to feed a future model.
- Work Package's existence as a first-class entity is what makes Cost Overrun signals meaningful at a genuinely useful granularity.
- Productivity vs. Cost is the clearest example of this architecture and Knowledge Base v2's existing Production Models becoming more valuable together than either is alone.

---

## 11. Future Integration

How the Commercial Foundation Engine should relate to capabilities that don't exist yet, and to external systems, without becoming tightly coupled to any of them:

Measurement Engine — the Commercial Foundation Engine defines the data shape (BOQ Item's contracted vs. measured-to-date quantity, §5) that a future Measurement Engine populates. The relationship is additive by design: Measurement Engine's job is to get a verified quantity into that field; it never needs to restructure BOQ itself to do so.

Decision Engine — as established in §7, the Commercial Foundation Engine is precisely the trigger condition the Domain Model named for finally building a first-class Decision entity, scoped specifically to commercial approvals (Variation Orders, and eventually Payment approvals) in the same implementation phase as this engine.

Document Engine — every Contract, Invoice, and Variation Order will eventually need to reference a real, uploaded document (the signed contract PDF, the invoice document, supporting photos for a variation). The Commercial Foundation Engine should reference Document Engine's future entities for file storage, never reimplement document storage itself — this specification's entities should carry a document_ids reference field where relevant, ready for that future engine to populate, rather than needing modification when Document Engine arrives.

Notification Engine — payments due, variations pending approval, and milestones reached are natural, high-value notification triggers, exactly the pattern the Domain Model's own Notification specification already describes: Commercial Foundation Engine publishes the state change; Notification Engine observes and decides how and to whom to alert; Commercial Foundation Engine never becomes a second place "should this person be notified" gets decided.

Business Intelligence — the AI-readiness signals in §10 are precisely Business Intelligence's future raw material — this section is written to be that future engine's direct input, without Business Intelligence needing its own copy of the same commercial data.

ERP Systems and Accounting Software — the correct integration boundary is a defined export/sync interface, not deep coupling: Atlas publishes commercial facts (invoices raised, payments recorded, budget positions) in a well-defined shape; an external accounting system consumes them into its own books. Atlas should never attempt to become an accounting system, and should never require an external ERP's data model to shape Atlas's own entities. The specific integration mechanism (API, scheduled export, webhook) is implementation detail for whichever future sprint builds this bridge — the architectural commitment made here is only the boundary: one-directional publication of facts outward, never a live, bidirectional dependency on an external system's own data model.

### Presentation Summary
- Every future integration point is designed as an additive, one-directional relationship — Commercial Foundation Engine publishes facts; other engines and systems consume, observe, or store against them.
- Measurement Engine populates a field this architecture already defines; Document Engine is referenced, never reimplemented; Notification Engine observes state changes without Commercial Foundation Engine deciding who gets notified.
- ERP/Accounting integration is explicitly scoped as fact-publication outward, never a live, bidirectional dependency on an external system's data model — Atlas never becomes, or is shaped by, an accounting system.
- This section confirms, concretely, that the Decision Engine's build trigger (named in the Domain Model) is met by this specification.

---

## 12. Architecture Review

Potential duplication — none introduced, one guarded against explicitly. The single highest-risk duplication this domain invites is a BOQ Item's quantity being entered independently of a Production Model's already-calculated quantity for the same real-world measurement. §5 addresses this directly by design, not as an afterthought: the architecture is written so that reading the Production Model's value is the natural, easier path, not a discipline someone has to remember to follow.

Scaling risks. RA Bill calculation reads a BOQ's full item list and its cumulative measured-to-date quantities on every bill generation — for a very large BOQ (hundreds of items) on a long-running project, this is a real computational cost worth flagging now, the same way the Domain Model already flagged CRE's uncached per-project snapshot computation as a future-scale concern rather than a current one. Not urgent at today's likely project sizes; worth designing the RA Bill calculation to be incremental (computing only the delta since the last bill, not re-deriving the full cumulative position from scratch every time) when it is actually built.

Missing abstractions. This document deliberately does not invent a generic "Commercial Approval" abstraction distinct from the Decision entity recommended in §7 — a second, parallel approval mechanism alongside Decision would itself be the kind of duplication this review is checking for. If a future need arises for an approval type that doesn't fit Decision's shape, the correct move is extending Decision, not inventing an alternative.

Recommended boundaries. The single boundary most worth stating explicitly, because it will be tempting to blur under implementation pressure: Budget must never be computed from Contract/BOQ, and Contract/BOQ must never be computed from Budget. They are related only through the Work Package and Cost Code structures both reference. The moment one starts being derived from the other, margin analysis becomes structurally impossible to trust — this is the single most important boundary in this entire specification to hold precisely.

Technical debt. None yet — this is a pure specification with no implementation behind it to accumulate debt. The one debt-shaped risk worth naming preemptively: if implementation proceeds in the "multiple focused sprints" the brief anticipates, the greatest risk is a later sprint quietly reintroducing one of the entities this document recommended against (a standalone Tax entity, a separate Payment Request) because the person implementing that sprint didn't have this document's reasoning in front of them. Recommendation: each implementation sprint should explicitly re-read §2's table before adding any new commercial entity, not just before adding the entities this document already named.

### Presentation Summary
- No duplication currently exists to find (this is architecture only) — the one duplication risk actively designed against is a BOQ quantity being re-entered instead of read from an existing Production Model calculation.
- RA Bill calculation cost at scale is flagged as a future concern, the same way CRE's uncached snapshot computation already was in the Domain Model — not urgent, worth designing for incrementally when built.
- The single most important boundary in this entire specification: Budget and Contract/BOQ must never be derived from each other, only related through shared structure — this is what makes margin analysis trustworthy.
- The main technical-debt risk is procedural, not architectural: future implementation sprints should re-check this document's entity table before adding anything new, so a "not independent" verdict here doesn't get silently reversed later.

---

## Executive Summary

The Atlas Commercial Foundation Engine is the architecture for how Atlas will become the authoritative source of truth for a construction project's complete commercial lifecycle — from a priced Bill of Quantities through Variation Orders, procurement, progress billing, and retention, to final settlement — without becoming, or depending on, an accounting system.

This specification is grounded in how construction projects are actually commercially run, not in how generic project-management or ERP software happens to model "budget" and "invoice." That grounding produces several conclusions that would not be obvious from a generic-software starting point: Invoice is deliberately one entity representing both of construction's two real billing methods — RA Bills, driven by measured progress, and Milestone Bills, driven by reaching a construction stage — because they differ only in how the amount is determined, not in what they fundamentally are. Retention is modeled as a running ledger tied to every bill it was withheld from, with release supporting multiple tranches, because that is how retention genuinely works on real contracts, not as a single end-of-project flag. Work Package is recommended as a genuine, new, first-class entity — but explicitly as a commercial and procurement reporting layer that references Workflow Engine's existing, working execution model, never as a competing planning abstraction that would require redesigning it.

Nine entities are recommended as genuinely independent — Contract, Work Package, BOQ, Cost Code, Budget, Variation Order, Procurement Package, Invoice, Payment, and Commercial Snapshot — while nine other candidate concepts from the brief's own list are recommended against independent existence, each with a specific reason: Client Agreement is the same thing as Contract; Scope is always derivable from BOQ plus accepted Variations, the same way Timeline and Milestone are already derived elsewhere in Atlas rather than stored; Change Request is a Variation Order's own draft state, not a second entity; Tax and Forecast are computed attributes of Invoice and Budget respectively, not entities with their own identity; and Payment Request is adequately represented by an Invoice in an early lifecycle state. Every one of these decisions follows the same principle already established across Atlas's existing domain: no fact is ever recorded in two places that could someday disagree.

Budget and Contract are held as deliberately, structurally separate numbers — what a company spends to deliver a project and what it charges a client for it are never the same figure, and the single most important architectural boundary in this specification is that neither is ever computed from the other. This is what makes it possible to answer "is this project profitable" with confidence, and it is the boundary most worth protecting carefully once implementation begins.

This architecture also resolves a question the Domain Model deliberately left open: whether Atlas should introduce a first-class Decision entity. The Domain Model's own recommendation was to wait for a specific, concrete trigger — Commercial Layer implementation, because cost-impacting approvals genuinely need properties the existing client-approval mechanism doesn't have. This specification confirms that trigger is now met, and scopes Decision precisely: implemented alongside Variation Order, for commercial approvals specifically, not as a platform-wide replacement for the approval mechanism that already works well for material and design decisions.

Every integration this architecture defines with Atlas's existing engines is one-directional: Commercial Foundation Engine reads Workflow and Knowledge Engine data, and never the reverse; Operations Engine remains the natural origination point for a cost-impacting concern without needing a second, parallel mechanism; Timeline Engine composes commercial events exactly as it already composes everything else; and Client Experience will eventually read Commercial data the same way it already reads Construction Reasoning data today — as a pure translation layer, never a second copy. No engine both publishes to and consumes from the Commercial Foundation Engine, so no circular dependency is possible anywhere in this design.

Looking outward, this specification defines every future integration point — Measurement Engine, Decision Engine, Document Engine, Notification Engine, Business Intelligence, and external ERP/accounting systems — as additive and one-directional, never a live, bidirectional dependency that would let an external system's data model shape Atlas's own. And it defines the deterministic data foundation — budget accuracy, variation frequency, cash flow patterns, cost overruns by Work Package, payment delays, scope growth, and the direct bridge between Knowledge Base v2's existing production-duration calculations and this document's new cost data — that a future, genuinely valuable Business Intelligence capability will eventually be built on, without designing that capability itself, and without capturing a single field of data that doesn't already need to be correct for the Commercial Foundation Engine's own operational purpose.

## Success Criteria

This sprint succeeds if, and only if, the following are true of the document above, checkable directly against it:

- Every commercial entity's existence is justified, not assumed — §2's table gives an explicit reasoned verdict for all eighteen candidates from the brief, including the nine recommended against independent existence.
- Every entity has exactly one owner — stated explicitly throughout §§3-8 and confirmed structurally in the Integration Matrix (§9), where no engine both consumes from and publishes to the Commercial Foundation Engine.
- Every entity relationship is diagrammed — Mermaid relationship diagrams appear in §§3, 5, 7, 8, and 9's matrix is itself a relationship specification in tabular form.
- Every entity with a real lifecycle has a state diagram — Contract (§4) and Work Package (§3); entities without a genuine multi-state lifecycle (Cost Code, Commercial Snapshot) are correctly not forced into one.
- The specification integrates with, and does not redesign, every existing Atlas engine — confirmed explicitly in §1 and exhaustively in §9's Integration Matrix.
- The Work Package question is answered directly, not deferred — §3 states plainly that it should exist, and precisely what it should and should not become.
- AI readiness is deterministic data, not a designed AI feature — every signal in §10 is a stated calculation, with the design principle (no data captured solely for AI) made explicit.
- Future integrations are scoped without coupling Atlas to systems that don't exist yet — §11 addresses all six named future integration points, each as an additive, one-directional relationship.
- The document is detailed enough to implement confidently in focused sprints — every entity's ownership, lifecycle, and relationships are specified precisely enough that "what does this sprint need to build" has a clear, unambiguous answer at every point in this document, without requiring the implementer to make a domain-modeling decision this document should have already made.

A future implementer reading only this document, with no other context, should be able to answer every one of the five questions this sprint set out to answer — what commercial entities exist, who owns them, how they relate, how they integrate with existing Atlas engines, and how future engines can build on this without architectural drift — directly from what is written above.
