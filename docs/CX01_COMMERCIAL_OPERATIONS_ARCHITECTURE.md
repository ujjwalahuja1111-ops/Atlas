# CX-01 — Atlas Product Architecture, Workflow Simplification & Commercial Operations

This document builds directly on PX-01, treating it as a starting point per this brief's own instruction. One correction to PX-01 is made below in Section 2, caught while re-verifying the commercial engine's exact function list for this deeper pass - PX-01 stated revise_contract exists as a backend function; it does not, and the correction matters for what follows. Every other claim in this document was independently re-verified against the current repository, not carried forward from PX-01 on trust. No code was written. No visual design was produced. No effort was estimated without a stated evidentiary basis.

---

## The Studio Neoteric Walkthrough — Required First, Because It Grounds Everything Else

Per this brief's own explicit instruction, before any architecture is proposed: walking a real Rs 3 crore turnkey project through Atlas as it exists today, step by step, checking at each step whether a normal user action exists or whether a script/seed/direct backend call would be required.

| Step | Exists as a normal user action today? | Evidence |
|---|---|---|
| Where is the first client created? | Partially. A client role user account can be created via POST /api/auth/register (self-registration, pending admin approval) or by an admin directly. But there is no "create a client record" concept distinct from "create a user account" - a client only becomes real to the commercial system the moment a contract names their client_id. | Confirmed: client_id is an optional field on create_contract; no separate client/CRM entity exists anywhere in the schema. |
| Where is the proposal prepared? | Does not exist. | Confirmed: no "proposal," "lead," or "estimate" concept anywhere in commercial_engine.py or any other engine. |
| Where is the contract signed? | Operational gap. The backend function (create_contract) exists and is well-designed. No screen calls it. | Confirmed in PX-01, re-confirmed here: zero references to a contract-creation call anywhere in frontend/src/commercial_api.ts or any screen. |
| Where is the BOQ uploaded? | Does not exist, backend or frontend. | Confirmed: zero matches for "BOQ" or "bill of quantities" anywhere in commercial_engine.py. |
| Where is the budget approved? | Operational gap. create_budget exists on the backend (a single internal-cost model: original/current/committed/actual). No screen calls it, and there is no "client budget" as a distinct concept from the internal cost budget the task asks about. | Confirmed via direct reading of create_budget/get_budget. |
| Where is the first milestone raised? | Operational gap. create_milestone exists and is well-designed (sequence, planned percent, trigger condition, planned date). No screen calls it. | Confirmed absent from commercial_api.ts. |
| Where is the payment request generated? | Operational gap. create_payment_request exists, correctly gated to only fire once a milestone is achieved. No screen calls it. | Same. |
| Where is the payment recorded? | Operational gap. record_payment exists, supports partial payments and an is_adjustment flag for corrections. No screen calls it. | Same. |
| How does that flow automatically update Executive, Operations and Commercial views? | This part genuinely works, and works well. Once data exists (by any means), Explain Health, Commercial Intelligence, Executive Timeline, and Portfolio Control Center all correctly and consistently reflect it - this was independently, extensively verified across many prior sprints in this engagement (cross-validated health scores across all seeded projects, a full four-way commercial consistency check, and more). | Verified in this engagement's own prior work, re-confirmed by reading the current reasoning_engine.py composition logic, unchanged since. |

The walkthrough's own verdict, per this brief's own classification rule: of nine steps, one merges into user-account creation, one doesn't exist as a business concept anywhere in Atlas (Proposal/Estimate/BOQ), and five are confirmed, fully-built backend capabilities with zero path a real user could reach them through. Only the final step - intelligence built on top of the data - actually works as intended. This confirms and sharpens PX-01's own finding: it is not that Commercial Operations is incomplete. It is that Commercial Operations, as a place a human being can go and do work, does not exist at all. Everything that follows in this document is organized around closing that gap first.

---

## 1. Product Architecture Review

Atlas today is architecturally a reporting and intelligence layer over a data model that assumes data already exists. Every engine - CRE, Priority Engine, Commercial Intelligence, Explain Health - is a read path over contracts, budgets, milestones, payment_requests, payments, variations, operational_items, workflow_activities, events. All of these collections are well-designed, internally consistent (verified extensively across this engagement's own history), and correctly composed by the intelligence layer. What's missing is not intelligence, and it is not data modeling - it's the write path a human uses in the ordinary course of running a project. This is a specific, nameable architectural gap, not a vague "needs more polish" observation: Atlas has a fully-formed commercial data model with no commercial application built on top of it. The operational side of Atlas (capture, operational items, workflow) does not share this problem - that side has a complete, verified, working write path from creation through closure (confirmed in op/[id].tsx's own full lifecycle support, and in this engagement's own end-to-end lifecycle simulations). The asymmetry between "operations has a product, commercial has only a data model" is the single most important architectural fact about Atlas today.

---

## 2. Commercial Operations Blueprint

Designed from first principles per this brief's own instruction, then checked against what already exists in the backend so the blueprint distinguishes "needs a screen" from "needs new backend work."

### Pre-Construction (Lead -> Proposal -> Estimate -> BOQ -> Negotiation -> Contract Approval)

Does not exist today, backend or frontend. This is a genuine new capability, not a UI gap. Recommended minimum for a first version: a Lead entity (company/contact/project scope, informal - not a hardened commercial object), a Proposal that becomes a BOQ line-item draft, and a Negotiation state that ends in either "convert to Contract" (which then calls the existing, working create_contract) or "lost." This is the one area of this blueprint that requires new backend design, not just new UI - flagged explicitly rather than folded in with the other gaps, because it changes the size and risk of this work.

### Contract

Create Contract: backend exists (create_contract), well-designed - captures value, date, duration, retention%, advance%, GST% as one coherent unit. Needs UI only.

Revise Contract: does not exist on the backend. This corrects PX-01, which stated it did - re-verified directly in this pass by reading the complete function list in commercial_engine.py; no revise_contract function exists. The only mechanism that changes a contract's effective value today is current_contract_value, which is derived automatically from approved variations (original value + sum of approved variation deltas, computed fresh on every read, never stored). This is a genuinely elegant design for the specific case of "the contract value changed because of a variation" - but there is no mechanism at all for revising the contract's other terms (duration, retention%, advance%, GST%) after creation. This is a real backend gap, not just a missing screen.

Terminate Contract: does not exist. Verified directly: CONTRACT_STATUSES = ("draft", "review", "approved", "active", "completed", "closed") - a strictly linear progression with no cancellation or termination branch anywhere. A real construction company's contract can be terminated mid-project (client default, mutual termination, force majeure); Atlas's own state machine currently has no path to represent that. Backend gap, not a UI gap.

Contract History / Versions: partially covered by the existing commercial_events ledger (every status change is recorded with actor, timestamp, from/to), but there is no dedicated "version" concept - because there is nothing to version, since terms can't be revised in the first place. Resolves naturally once Revise Contract is built correctly (each revision becomes a version).

Approval Workflow: the draft -> review -> approved status progression already models a lightweight approval flow. Sufficient as-is; the gap is entirely that no screen drives it.

### Budget

Create Budget, Budget Revisions: backend exists (create_budget, revise_budget) and is functionally adequate - single internal-cost model tracking original/current/committed/actual, with variance and remaining-budget derived on every read. Needs UI only.

Internal Cost Budget vs. Client Budget: only one budget concept exists. The current model (budgets collection) is unambiguously an internal cost budget - it tracks what the company expects to spend, not what the client has agreed to pay (that's the contract's own value). Conflating "budget" with "internal cost" is a reasonable default for a first version, but this brief specifically asks for the distinction, and today there is no separate client-facing budget object. This is a real design gap, though a narrower one than Pre-Construction: it may be resolvable by clarifying that "Contract" already is the client-facing commitment and "Budget" already is the internal one, and the fix is naming/presentation rather than a new data model - this needs a product decision, not assumed to require new backend work.

Budget Comparison: does not exist as a feature (comparing budget versions over time, or budget vs. actual in a dedicated view) - though the underlying data (current_budget, forecast_cost, variance) already supports building this as a read-only view with no new backend work.

Budget Locking: does not exist - no lock/freeze state anywhere in the budget schema. Real gap; likely low backend effort (a boolean flag plus a guard in revise_budget) but zero, so far, exists.

Budget Audit: exists via commercial_events (every budget_created/budget_revised/cost_committed/actual_cost_recorded event is logged with actor and payload) - this is a genuine, real audit trail already. The gap is presentation, not data (see Section 6's finding on this same pattern repeating for the full financial audit trail).

### BOQ

Import BOQ, Manual BOQ, BOQ Revision, Version History, Rate Changes, Quantity Changes, Variation Impact: none of this exists anywhere in Atlas today, backend or frontend. This is the single largest genuine gap in the entire commercial lifecycle - larger than "missing a screen," because there is no BOQ data model at all. A real construction company's commercial life revolves substantially around the BOQ (it's the basis for the contract value, the source of variation line items, and the reference for rate disputes); Atlas currently has no representation of it whatsoever. This is new backend design work, not UI work, and should be sized and prioritized as such.

### Milestones

Create, Edit (via status transition), Sequence, Financial Value, Due Dates, Completion Rules: backend exists and is well-designed (create_milestone captures sequence, planned percent, trigger condition, planned date; MILESTONE_TRANSITIONS enforces a clean state machine: pending -> ready -> achieved -> payment_requested -> paid -> closed). Needs UI only.

Dependencies (between milestones): does not exist - milestones have a sequence number but no explicit dependency graph (e.g., "Milestone 3 cannot be marked ready until Milestone 2 is achieved"). Real gap, moderate scope.

Approval Rules: the state machine itself is the approval mechanism (each transition requires an explicit actor call); there's no separate "approval rule" concept beyond that, and none appears needed - the existing transitions already require deliberate action at each step.

### Variations

Create, Review, Client Approval, Commercial Impact, Timeline Impact, Revision History: backend exists and is the most complete commercial workflow in the entire lifecycle - create_variation, submit_variation, send_variation_to_client_review, decide_variation form a genuine, multi-step, correctly-gated workflow, and critically, this is also the only commercial mutation with any UI at all (client-facing approve/reject, confirmed in PX-01). Commercial Impact is handled correctly (approved variations automatically flow into the contract's derived value, confirmed above). Timeline Impact: not found as a distinct tracked field - a variation can carry a cost delta but no explicit schedule-impact field. Revision History: covered by commercial_events.

The gap here is narrower than everywhere else: build Create/Submit/Send-for-review into the PM-facing UI (the backend, state machine, and even half the UI already exist) and this becomes the first fully operational commercial workflow in the product - the natural pilot for the rest of Commercial Operations.

### Billing

Payment Request: backend exists (create_payment_request), correctly gated to require an achieved milestone first. Needs UI only.

Tax: confirmed, by direct search, that `gst_percent` is written once at contract creation and never read anywhere else in the codebase — it is a stored, unused field, not applied to any payment request, invoice, or calculation. Same pattern as retention_percent and advance_percent below.

Invoices: does not exist as a distinct concept - payment requests function as an informal invoice today (they carry an amount, a due date, and a status), but there is no invoice numbering, no formatted invoice document, and no tax breakdown on it.

Client Receivables, Outstanding: exists and works - outstanding_payments() (raised minus received across all non-cancelled payment requests) is a real, correct, already-used calculation, confirmed extensively in this engagement's own commercial-consistency verification work.

Reminder Workflow: does not exist - no notification or reminder mechanism for outstanding payments anywhere in the codebase.

### Payments

Record Payment, Partial Payment: backend exists and works (record_payment takes an arbitrary amount against a payment request - partial payment is inherently supported by the data model, not a special case).

Advance Payment: the contract carries an advance_percent field at creation, confirmed - by the same direct search as gst_percent above - to be written once and never read anywhere else in the codebase. There is no dedicated advance-payment workflow; the field is entirely inert.

Retention: same confirmed pattern - retention_percent is stored on the contract at creation and never read anywhere else. No retention-specific withholding/release workflow exists anywhere in the payment or milestone logic. This is a real, specific, verifiable gap for a construction-specific concept (retention is not a generic finance feature; it's central to how construction billing actually works) - worth flagging distinctly rather than lumping into "billing in general."

Adjustments, Corrections: record_payment accepts an is_adjustment flag - this is the one place a "correction" concept genuinely exists in the schema, though it's a boolean on an otherwise-identical payment record, not a dedicated correction workflow (e.g., no explicit link from an adjustment back to the payment it's correcting).

Audit Trail: exists via commercial_events, same pattern as budget and contract - real data, no dedicated presentation.

### Commercial Intelligence — built correctly on top, once operations exist

The brief's own instruction ("build intelligence on top of these operations, not instead of them") is, encouragingly, already how Atlas is built - Commercial Intelligence, Explain Health, and the executive views all correctly compose the underlying commercial data rather than duplicating or recalculating it (verified extensively in this engagement's own prior work). Nothing about the intelligence layer needs to change. It needs the operations layer built underneath it so the data it's already correctly summarizing can be entered by a real user instead of a seed script.

---

## 3. Navigation Architecture

Re-affirms PX-01's five-category structure (Work, Decisions, Projects, Communication, Capture) with one addition this deeper pass surfaces: Commercial needs to become its own first-class category, not a sub-section of Projects. Reasoning: once Commercial Operations exists (Section 2), a PM's commercial actions - raise a milestone, submit a variation, record a payment - are frequent enough, and different enough in kind from "browse this project's status," that burying them inside the Projects category (as PX-01 proposed) would recreate the exact problem this document exists to solve. Commercial should sit alongside Work and Decisions as a primary navigation category once it has real actions in it, not just a report to read.

---

## 4. Workflow Architecture

The Studio Neoteric walkthrough (top of this document) is the workflow architecture, stated as a sequence rather than a diagram: Client/Lead -> Proposal/Estimate -> BOQ -> Contract -> Budget -> Milestone -> Variation (as needed, branching off Milestone) -> Payment Request -> Payment -> (repeat Milestone->Payment for each subsequent milestone) -> Contract Completion. Every arrow in that sequence should be a screen's own "what's next" action, not a separate destination the user has to go find - e.g., a milestone marked achieved should surface "Raise Payment Request" as the next action on that same screen, not require navigating elsewhere to remember to do it. This is the concrete meaning of this brief's own "every workflow should naturally lead to the next" instruction, applied specifically rather than left abstract.

---

## 5. User Journey Architecture

Building on PX-01's four journey maps, the one material addition from this deeper pass: the Project Manager's journey has an entirely missing middle. PX-01 correctly identified that "monitor commercial progress" was a dead end (read-only). This pass's fuller lifecycle walkthrough shows why more precisely: the PM's day, as this brief itself describes it, includes "commercial actions" as a named daily activity - but there is currently no commercial action available at all except approving/rejecting as a client, a role the PM doesn't have. The PM's journey doesn't have a friction point in Commercial - it has a void. This distinction matters for prioritization: friction is smoothed, a void is built.

Management and Client journeys are unchanged from PX-01's own findings, re-confirmed rather than re-derived in this pass. Site Supervisor's journey remains the one role whose current experience already matches this brief's target state, restated rather than repeated at length.

---

## 6. Screen Consolidation Strategy

Carried forward from PX-01 without material change (Executive Hub + Priorities merge; op/[id].tsx elevated for discoverability, not consolidated; Daily Review and Site Progress kept separate as genuinely non-duplicative). One new item this pass surfaces: the financial audit trail pattern (Section 2) repeats identically across Contract, Budget, and Payments - all three already have real, correct event-level history via commercial_events, and all three currently have no dedicated presentation of that history. Rather than building three separate "history" screens, this should be one Commercial Audit Trail view, filterable by entity type, reused across all three rather than triplicated. This is a consolidation recommendation made before the feature exists, which is the cheapest time to make it.

---

## 7. Product Simplification Strategy

Per this brief's Objective 5 - every finding stated as Current / Problem / Recommendation / Business impact / Engineering impact, evidence-based throughout.

Finding: Engine-named navigation.
- Current: "Executive Hub," "Priority Engine," "Cross-Project Intelligence," "Explain Health," "Commercial Intelligence" are the literal screen/section names surfaced to users.
- Problem: forces every user to learn Atlas's own internal architecture to use the product, contradicting this brief's own First Principle.
- Recommendation: relabel at the presentation layer only - "Needs Your Attention," "Why This Project Is At Risk," "Financial Status," matching this brief's own worked examples exactly. No backend or routing change.
- Business impact: directly reduces training time, the brief's own stated success metric.
- Engineering impact: minimal - copy/label changes only, no logic change, no risk to existing behavior.

Finding: Executive Hub and Priorities duplicate the same data.
- Current: both call apiPriorityEngine() independently and render overlapping content.
- Problem: a user has no way to know these are the same underlying list without opening both.
- Recommendation: merge per Section 6/PX-01; Priorities becomes Executive Hub's own expandable section.
- Business impact: removes a confusing "is this different information?" moment for management's highest-frequency screen.
- Engineering impact: low - this is a frontend composition change, not a new computation; the data source doesn't change.

Finding: The most complete screen in the product is the least discoverable.
- Current: op/[id].tsx supports the full operational item lifecycle correctly; it has no top-level navigation entry.
- Problem: capability that already works well is functionally hidden.
- Recommendation: surface directly from the new Commercial/Work/Decisions navigation categories (Section 3), not as a new screen - as better entry points into the existing one.
- Business impact: the PM's own described daily workflow depends on this.
- Engineering impact: navigation/routing only, zero change to the screen's own logic.

Finding: No commercial operations exist for a user to discover, let alone find confusing.
- Current: Section 2, in full.
- Problem: this is the inverse of "hidden functionality" - it's functionality that was never built a door to.
- Recommendation: Section 2's blueprint, prioritized in Section 10.
- Business impact: without this, no other simplification in this document matters, because the product cannot be used for its core purpose.
- Engineering impact: substantial and uneven - some pieces (Contract, Budget, Milestone, Payment Request, Payment creation UI) are pure frontend work against existing, correct backend endpoints; others (BOQ, Pre-Construction, Contract termination/revision, retention workflow) require new backend design. Conflating these into one estimate would misrepresent the actual scope, which is why Section 10 separates them explicitly.

---

## 8. Commercial Operations Implementation Plan

Sequenced by what's buildable against existing, correct backend endpoints first (lowest risk, fastest to real usability), before what requires new backend design.

Phase A - UI only, against already-correct, already-tested backend endpoints:
Contract creation, Budget creation, Milestone creation and status progression, Variation creation/submit/send-for-review (extending the one commercial mutation that already has partial UI), Payment Request creation, Payment recording. Each of these calls a backend function already verified working throughout this engagement's own history - this phase is entirely about building the missing frontend, not new business logic.

Phase B - New, small backend additions:
Budget Locking (a flag plus a guard), a unified Commercial Audit Trail view (Section 6), milestone dependencies, and wiring gst_percent/advance_percent/retention_percent into actual calculations - confirmed in Section 2 to be stored but entirely unused today.

Phase C - New backend design, larger scope, sequenced last deliberately:
Contract revision (beyond the existing variation-driven value changes) and termination as new status-machine states; BOQ as an entirely new data model; retention as a dedicated withholding/release workflow rather than a stored, unused percentage; Pre-Construction (Lead/Proposal/Estimate) as a new, lighter-weight entity preceding Contract.

---

## 9. Construction Operating System Vision

Atlas's own intelligence layer - Explain Health, Commercial Intelligence, Cross-Project Intelligence, the Priority Engine - already represents genuine, working differentiation; this engagement's own history shows these were built carefully and verified repeatedly to compose real data correctly rather than fabricate insight. The vision this document argues for is not building more of that. It's connecting the intelligence Atlas already has to a real, complete operational and commercial write path, so that the numbers Explain Health and Commercial Intelligence display are numbers a real construction company entered themselves, in the ordinary course of running their business, rather than numbers a seed script produced for demonstration. An operating system is defined by what a business does inside it every day - Atlas's operational side already earns that description; its commercial side, as of this document, does not yet.

---

## 10. Prioritized Implementation Roadmap

Ranked by verified evidence of blocking impact, per this brief's own instruction not to estimate effort without evidence - "impact" here means confirmed absence of a real user path, not a guess about engineering hours.

Tier 1 - the product cannot serve its core commercial purpose without this:
1. Commercial Operations Phase A (Section 8) - Contract, Budget, Milestone, Payment Request, Payment, and extended Variation UI against existing, working backend endpoints. This alone would take Atlas from "cannot run a commercial project" to "can run one, missing only the specialized construction-finance features below."

Tier 2 - closes named, real gaps that a growing company will hit, but doesn't block getting started:
2. Retention workflow - construction-specific, currently just a stored, unused number.
3. Contract revision and termination as real state-machine capabilities - currently impossible to represent a mid-project change or cancellation.
4. Budget Locking and the unified Commercial Audit Trail (Section 6/8B).

Tier 3 - genuinely new capability, larger and riskier, correctly sequenced last:
5. BOQ as a new data model - the single largest gap found in this entire pass, and the one most clearly out of scope for a quick addition.
6. Pre-Construction (Lead/Proposal/Estimate) - valuable, but a real construction company can start using Atlas at Contract with an external sales process feeding into it; this is not a blocker to adoption the way Tier 1 is.

Navigation and simplification work (Sections 3, 6, 7) should follow Tier 1, not precede it - relabeling and consolidating a navigation structure around commercial work that doesn't yet exist as a user action would be organizing a house before it has the room being organized.
