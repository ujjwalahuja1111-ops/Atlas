# CO-01 — Commercial Operations Product Specification

This is a specification, not an audit. PX-01 and CX-01 are treated as accepted, prior fact - every "today, Atlas has X" claim in this document carries forward their verified findings rather than re-verifying them, except where this deeper design pass required checking something neither prior document covered (the AI proposal infrastructure, Section 8, and specific state-machine transition sets referenced throughout - each checked directly against the current backend before being relied on). Every design decision is labeled REUSE, EXTEND, or NEW, per this brief's own explicit instruction, so engineering can see at a glance what already exists correctly, what needs to grow, and what doesn't exist yet.

---

## 1. Commercial Product Vision

Commercial is not a bolt-on accounting module. It is project execution, denominated in money. A milestone completing on site and a payment request existing are not two facts that happen to correlate - in a well-run construction company, one is the reason the other exists. Atlas's own operational side already understands this instinct (an operational item's status change is the whole point of the screen, not a side effect); Commercial today does not, because the write path doesn't exist yet (CX-01). This specification's single organizing idea: every commercial screen lives inside a project, is reached from an operational trigger, and always makes clear why it exists, who caused it, and what changed as a result - the First Principle this brief states, applied as a literal, checkable requirement on every record type below, not an aspiration.

---

## 2. Commercial Domain Model

### Phase 1 — Pre-Construction (Client -> Proposal -> Estimate -> Negotiation -> Contract)

Decision: Lead/Proposal stay lightweight inside Atlas; Atlas does not become a CRM.

Reasoning: CX-01 confirmed no Lead/Proposal/Estimate concept exists today, backend or frontend - this is genuinely new ground, and new ground is exactly where scope discipline matters most. A construction company's sales process (site visits, relationship-building, competitive bidding) is a different discipline from project execution, with different cadence and different failure modes; building a full CRM (pipeline stages, activity logging, email integration) would pull Atlas away from its own stated identity as a construction operating system and into competing with dedicated CRM products, which is not this brief's objective. The concrete design: Lead is a light, informal record (company, contact, rough scope, estimated value) - closer to a note than a commercial object. Proposal is the first record that must answer this specification's First Principle (why/who/what changed), because a Proposal genuinely commits company time to producing an Estimate. Estimate is where BOQ-level detail first appears (Phase 4 defines this fully) - an Estimate is a draft BOQ with no commercial commitment yet. Negotiation is a state, not a new entity - a Proposal sits in negotiation while terms are discussed, and either converts (creates a Contract, reusing create_contract exactly as it exists today) or is marked lost.

Should Atlas integrate with external CRMs instead? Recommended as a future integration point (a webhook or API surface a company's existing CRM can push a "deal won" event into, auto-creating a Lead), not a Phase 1 requirement - this keeps the door open without making CRM integration a blocker to shipping the rest of this specification.

Classification: NEW. No part of Phase 1 exists today in any form.

### Phase 2 — Contract

Current state (CX-01, re-confirmed): create_contract and transition_contract_status exist and are well-designed. CONTRACT_STATUSES is strictly linear (draft -> review -> approved -> active -> completed -> closed) with no revise, suspend, terminate, or archive path. current_contract_value is correctly, automatically derived from approved variations - never stored, never manually edited.

Should contract revision overwrite, create versions, or clone? Create versions. A contract is the legal foundation of the relationship; overwriting its history is both a bad audit practice and a direct violation of this brief's own First Principle (a record that erases what it used to say cannot answer "what changed because of it"). Design: a contract_revisions collection, one row per revision, each carrying the full prior state plus what changed and why (reusing the exact shape commercial_events already uses for its own payload - {"from": ..., "to": ..., "reason": ...} - a pattern already proven correct across budget and milestone changes). The current contract document stays the single source of truth for "what's true now"; the revision log is the source of truth for "what used to be true and why it changed." This is the same pattern Atlas already uses successfully for budget_revised events - EXTEND, not a new pattern.

Suspend, Terminate, Archive: genuinely missing states, confirmed absent from CONTRACT_STATUSES in CX-01. Design: add suspended (reachable from active, returns to active) and terminated (reachable from active or suspended, terminal) as real states in the existing transition-map pattern - this is architecturally identical to how MILESTONE_TRANSITIONS and VARIATION states already work, just adding entries to an existing dictionary shape. EXTEND - same state-machine mechanism, new states within it.

Approvals: the existing draft -> review -> approved sequence is sufficient and correctly models a lightweight approval; no new mechanism needed. REUSE.

Signed PDFs: not addressed anywhere in the current backend (no document/attachment storage for contracts was found in CX-01 or this pass). Recommend a simple attachment reference (a URL/asset ID pointing at wherever the signed document lives, likely the same raw_assets pattern reality captures already use) rather than building a document management system - EXTEND of raw_assets, not a new subsystem.

Recovery/Exception handling: a terminated contract should remain fully readable (never deleted), consistent with this specification's later ruling on deletion (Section 10).

### Phase 3 — Budget

Current state (CX-01, re-confirmed): one budget model exists - original_budget, current_budget, committed_cost, actual_cost, with forecast_cost/variance/remaining_budget correctly derived on every read. revise_budget exists (a direct overwrite, logged as an event, not versioned). No lock/freeze mechanism, no distinction between an internal-cost budget and a client-facing budget.

Decision: one Budget object, not two. CX-01 flagged this as an open question; resolving it here. The Contract's own value (derived automatically from approved variations) already is the client-facing commitment. Building a second, separate "Client Budget" object would either duplicate the contract's own number or, worse, allow it to drift out of sync with the actual contract - a direct violation of this brief's own "commercial history should never contradict itself" instinct. The single Budget stays what it already is: the internal cost budget. This is a naming and documentation clarification, not new data modeling. REUSE, with a product-level renaming recommendation: present it to users as "Internal Cost Budget" or simply "Budget," and never as "Client Budget," so the UI itself doesn't invite the confusion CX-01 flagged.

Budget Freeze: genuinely missing. Design: a frozen: bool field plus a guard in revise_budget that rejects changes while frozen (an explicit unfreeze action required first, itself logged as an event). Small, additive. EXTEND.

Budget Revisions/History: exists today only as an event log (budget_revised events), not a queryable "version" list with before/after comparison. Recommend surfacing the existing event log as a comparison view rather than building new storage - the data already exists; only the presentation is missing. REUSE of underlying data, NEW presentation only.

Forecasting: forecast_cost (max of committed/actual) already exists and is correct for a simple forecast. A more sophisticated forecast (trend-based projection to completion) is a genuine future capability, not addressed by this specification's Phase 1 scope - named here as a deliberate deferral, not an oversight.

### Phase 4 — BOQ

Current state (CX-01): does not exist in any form, backend or frontend.

This is the largest genuinely new domain object in this specification, and deserves construction-specific design rather than a generic line-item table.

Structure: a BOQ is a versioned document belonging to a project, composed of line items (description, unit, quantity, rate, amount = quantity x rate), grouped into sections that mirror how a real BOQ is organized (e.g., "Civil Works," "Electrical," "Plumbing" - construction trade categories, not arbitrary folders). Import (Excel) vs. Manual: both are needed - Excel import for the common case (a BOQ prepared externally, e.g., by a quantity surveyor, arrives as a spreadsheet), manual entry for smaller projects or ad-hoc additions. Import should map columns to the same line-item schema manual entry produces, so downstream logic (revision, variation-linking) never needs to know which path created a given line.

Revision and version comparison: every BOQ revision is a new version (same reasoning as Contract versioning above - never overwrite); a comparison view shows quantity and rate deltas between any two versions, directly serving this brief's own "rate revision, quantity revision" requirement.

Variation generation: this is where BOQ becomes construction-specific rather than generic. A Variation (Phase 6) should be creatable from a BOQ line item - "this line's quantity changed" or "this is a new line not in the original BOQ" are the two most common real-world variation triggers, and the product should let a user start a variation from the BOQ line itself rather than typing a variation description from scratch. This directly serves the brief's own AI-integration instinct too (Section 8): given a BOQ line's original quantity/rate and a new quantity/rate, Atlas already knows the cost delta - it should compute and pre-fill it, not ask the user to calculate it by hand.

Linking to milestones and payments: a milestone's financial percentage (Phase 5) can reference specific BOQ sections (e.g., "Milestone 2 = Foundation section complete"), making milestone completion partially verifiable against BOQ progress rather than purely manual attestation - a genuine, construction-specific automation opportunity, not present in any generic project-management tool.

Linking to procurement: not addressed - Atlas has no procurement/material-ordering system today (confirmed absent from every engine reviewed across this engagement), and building one is out of this specification's own scope. Named as a real, deliberate boundary, not a silent gap.

Classification: NEW, entirely - no backend model exists, no UI, no partial implementation to extend.

### Phase 5 — Milestones

Current state (CX-01, re-confirmed): create_milestone and MILESTONE_TRANSITIONS (pending -> ready -> achieved -> payment_requested -> paid -> closed) exist and are well-designed. sequence, planned_percent, trigger (a text condition), planned_date are all captured. No dependency graph between milestones, no distinction between a "commercial milestone" (billing trigger) and a "construction milestone" (a physical progress marker with no direct billing tie).

Decision: milestones stay one object, with an optional financial_percent that can be zero. Building two parallel milestone systems (commercial vs. construction) would violate this specification's own founding idea - that commercial and operational execution are the same thing, expressed differently. A "construction milestone" is simply a milestone whose financial_percent is 0 or unset; a "commercial milestone" is one where it's populated. This is a REUSE of the existing schema with one EXTEND (making financial_percent genuinely optional, if it isn't already, and defaulting billing-linkage UI to hide for milestones without one).

Dependencies: genuinely missing (confirmed in CX-01). Design: an optional depends_on_milestone_id field, with a guard preventing a milestone from moving to ready until its dependency reaches achieved. EXTEND of the existing transition-guard pattern already used for status checks elsewhere in commercial_engine.py.

Automatic vs. manual vs. partial completion: today's model is fully manual (an explicit transition_milestone_status call). Automatic completion (e.g., "if BOQ section X reaches 100% via Phase 4's linkage, mark this milestone achieved") is a real, valuable automation - recommended as an optional trigger a PM can enable per-milestone, never a forced behavior, since construction reality (a milestone counted "done" pending final inspection, say) often needs a human's own judgment even when the underlying quantities are complete. Partial completion - billing 50% of a milestone's value - is not supported by the current binary achieved state and would require either splitting a milestone into sub-milestones (reusing existing structure) or adding a percent_complete field distinct from the binary status. Recommend the sub-milestone approach: it reuses everything that already exists rather than adding a second progress dimension to reconcile.

Retention linkage: addressed in Phase 8 (Payments), since retention is fundamentally a payment-time mechanism, not a milestone-time one.

### Phase 6 — Variations

Current state (CX-01, re-confirmed): the most complete commercial workflow already built - create_variation, submit_variation, send_variation_to_client_review, decide_variation form a genuine, correctly-gated multi-step flow, and this is the only commercial mutation with any UI at all today (client-facing approve/reject). Approved variations automatically flow into the contract's derived value.

Revision, Withdrawal, Cancellation: confirmed, by direct search, genuinely absent. The full status set is `("draft", "submitted", "client_review", "approved", "rejected", "implemented")` - a detail worth surfacing on its own: approval isn't the end of the line today, there's already a real `implemented` state after `approved`, which this specification's own design should build on rather than duplicate (a "variation is now reflected in the physical work" signal already exists and should stay the single source of truth for that fact). `rejected` and `implemented` are both dead ends in the current transition map - no path back to `draft`, no `withdrawn` state reachable from anywhere. Design: add `withdrawn` (PM-initiated, reachable from `draft` or `submitted`, before any client decision) and allow `rejected -> draft` as a genuine new transition (revise-and-resubmit, not an edit-in-place - consistent with this specification's own versioning principle, since the rejected version's own history should remain visible even after a revision supersedes it).

Time and Scope variations, not just Cost: today's model (confirmed in CX-01) tracks original_cost/proposed_cost only - no explicit schedule-impact field. A construction variation frequently changes the timeline as much as the cost (e.g., a scope addition extends the completion date). Recommend adding an optional schedule_impact_days field alongside cost - EXTEND, same object, new field, not a new concept.

Client communication: the existing send_variation_to_client_review step already represents this; no new mechanism needed beyond ensuring the client-facing UI (Phase 4's BOQ-origin variations, Section 8's AI-drafted variations) surfaces a clear reason and BOQ linkage when one exists, satisfying this specification's own First Principle for every variation a client sees.

### Phase 7 — Billing

Current state (CX-01, re-confirmed): create_payment_request exists, correctly gated to require an achieved milestone. outstanding_payments() (raised minus received) is correct and already used throughout the executive views. gst_percent exists on the contract but - confirmed by direct search in CX-01 - is written once and never read anywhere else in the codebase. No invoice numbering, no Credit/Debit Notes, no reminder workflow.

GST: the field exists; the calculation doesn't. Design: a Payment Request's own amount should be split into a base amount and a GST amount, computed from the contract's gst_percent at the moment the request is raised (not recalculated later if the rate changes, since a real GST rate is fixed at invoice time by law) - a straightforward calculation using data that already exists, currently sitting unused. EXTEND.

Invoices: today's Payment Request already functions as an informal invoice (amount, due date, status) - recommend not building a separate Invoice object, but formalizing the Payment Request itself with an invoice number (sequential, per-company or per-project, generated automatically on creation) and a formatted, GST-broken-down presentation. This avoids the CX-01-identified anti-pattern (Contract vs. Budget duplication) from recurring here. EXTEND, not a new object.

Credit Notes, Debit Notes: genuinely new - a Credit Note (reducing what's owed, e.g., for an overcharge) and Debit Note (increasing it, e.g., a late fee) are standard construction-billing instruments with no equivalent in the current schema. Recommend both as thin objects referencing a Payment Request (amount, reason, linked request) rather than a parallel billing system - NEW, but deliberately small.

Reminder workflow: genuinely missing (confirmed absent). This is Section 8's clearest AI-automation opportunity (an outstanding, overdue payment request is exactly the kind of pattern Atlas's existing intelligence layer should flag automatically) rather than a manually-triggered feature - designed fully in Section 8, not duplicated here.

### Phase 8 — Payments

Current state (CX-01, re-confirmed): record_payment exists, supports arbitrary (including partial) amounts, and has an is_adjustment boolean flag. advance_percent and retention_percent exist on the contract but - confirmed by direct search in CX-01 - are written once and never read anywhere else in the codebase.

Retention release: the single most construction-specific gap in this entire specification. Design: retention should not be a percentage sitting unused on the contract - it should be automatically withheld at the moment each payment is recorded (a payment of Rs 10L against a contract with 5% retention should record Rs 9.5L as received-and-available, Rs 50K as retained), tracked in a running retained_total on the project's commercial summary, and released via an explicit release_retention action (typically at project completion or a contractually-defined point) that itself becomes its own payment-like record for audit purposes. EXTEND of record_payment (the retention split is a calculation added to an existing, correct function) plus NEW (the release action and the retained-total tracking don't exist in any form today).

Advance payment: similarly inert today. Design: an advance is simply a payment recorded before any milestone is achieved - the constraint that create_payment_request requires an achieved milestone should have a deliberate, explicit exception for advances (flagged distinctly, payment_type: "advance", and correctly subtracted from the first milestone's payment request so the client is never double-billed for value they already paid in advance). EXTEND, same underlying record_payment/create_payment_request functions, new flag and one new guard exception.

Refund: not addressed anywhere today. Recommend modeling as a negative payment record (reusing record_payment with a negative amount and a required reason) rather than a new object - consistent with how is_adjustment already works. EXTEND.

Correction: is_adjustment exists but, confirmed in CX-01, has no explicit link from an adjustment back to the payment it corrects. Design: add corrects_payment_id (optional) to the payment record - a small, precise fix directly serving this specification's own First Principle ("what changed because of it" currently has no answer for an adjustment record). EXTEND.

Allocation: if a single payment should be splittable across multiple payment requests (a client pays one lump sum covering two outstanding milestones), this doesn't exist today - every payment ties to exactly one payment request. Recommend as a genuine, if smaller, new capability: an allocations list on the payment record instead of a single payment_request_id. NEW, but narrow in scope.

---

## 3. Commercial Workflow Specification

The complete lifecycle, stated as the single continuous sequence this brief's own "next logical screen" requirement implies, with every arrow naming what triggers it:

Lead created (manual) -> Proposal drafted (manual) -> Estimate/BOQ drafted within the Proposal (manual, becomes the project's first BOQ version on conversion) -> Negotiation (manual state) -> Contract created (converts the Proposal, reuses create_contract) -> Contract reviewed -> approved -> activated (manual approvals, existing state machine) -> Budget created (manual, immediately after activation - recommended as a required next step the Contract's own "activated" screen surfaces directly, not a separate destination to remember) -> Milestones created from the BOQ/contract terms (manual, ideally BOQ-linked per Phase 4) -> execution proceeds (operational side, already complete) -> Milestone reaches achieved (manual, or automatic via BOQ-linkage) -> AI suggests raising a Payment Request (Section 8) -> PM confirms -> Payment Request created, GST calculated -> Payment recorded (manual, retention automatically withheld) -> milestone marked paid -> closed -> repeat for each subsequent milestone -> Variation, if scope changes mid-project, branches off at any point after Contract activation, itself potentially triggering a Contract revision (Section 8) -> final milestone paid -> AI suggests retention release -> Contract marked completed -> closed.

Every step marked "manual" above is a genuine human decision point (this specification does not propose automating judgment calls); every step marked "AI suggests" is Section 8's proactive-not-passive instinct, applied to a specific, real trigger rather than a general dashboard.

---

## 4. Screen Specification

One representative screen per phase, in the format this brief requires. (Full coverage of every screen in this 8-phase lifecycle would run to dozens of entries; these are the highest-leverage ones - the first screen in each phase, since every subsequent screen in a phase follows the same pattern this one establishes.)

Contract Workspace (Phase 2)
- Purpose: answer "what are we contractually committed to, and is it current?"
- Primary user: Management, Project Manager
- Information shown: current terms, current derived value, status, revision history
- Primary action: Create Contract (if none exists) / Revise Contract (if active)
- Secondary actions: Suspend, Terminate, view Revision History, view Audit Trail
- Exit paths: back to Project Dashboard, forward to Budget (if no budget exists yet, this is the "next logical screen")
- AI recommendations: none at contract-creation time (nothing to infer yet); "This contract has been active 90 days with no Budget created" as a proactive nudge if the natural next step was skipped
- Next logical screen: Budget Workspace

Budget Workspace (Phase 3)
- Purpose: answer "are we going to make money on this project?"
- Primary user: Project Manager, Management
- Information shown: original/current/committed/actual, variance, forecast
- Primary action: Create Budget (if none) / Revise Budget
- Secondary actions: Freeze/Unfreeze, view revision comparison
- Exit paths: Project Dashboard, forward to Milestones
- AI recommendations: "Budget exceeded" -> suggest management review (Section 8)
- Next logical screen: Milestones

BOQ Workspace (Phase 4)
- Purpose: answer "exactly what are we building, and at what rate?"
- Primary user: Project Manager, Commercial responsibility-holder (Section 6)
- Information shown: sections and line items, current version, comparison to prior version if one exists
- Primary action: Import (Excel) or Add Line Item (manual)
- Secondary actions: Create Revision, Generate Variation from a line item, Link to Milestone
- Exit paths: Project Dashboard, forward to Milestones (BOQ-linked) or Variations (if generating one)
- AI recommendations: "This line's quantity changed materially from the original - start a Variation?" when a revision is saved
- Next logical screen: Milestones (if this is the first BOQ) or Variations (if editing mid-project)

Milestone Detail (Phase 5)
- Purpose: answer "is this piece of the project done, and does that mean we should get paid?"
- Primary user: Project Manager
- Information shown: sequence, trigger condition, financial percent, dependency (if any), current status
- Primary action: transition status (the existing, correct state machine)
- Secondary actions: view linked BOQ section, view linked Payment Request once one exists
- Exit paths: back to Milestones list, forward to Payment Request (once achieved)
- AI recommendations: "Milestone achieved - raise Payment Request?" - the clearest, single highest-value AI moment in this entire specification
- Next logical screen: Payment Request creation, pre-filled from this milestone

Variation Detail (Phase 6)
- Purpose: answer "what changed, why, and what does it cost us and the client?"
- Primary user: Project Manager (create/submit), Client (decide)
- Information shown: description, cost delta, schedule delta (new field), linked BOQ line (if BOQ-originated), status
- Primary action: role-dependent - PM: Submit/Send for Review; Client: Approve/Reject (the one workflow with real UI today)
- Secondary actions: Withdraw (PM), Revise-and-resubmit (PM, after rejection)
- Exit paths: Project Dashboard, forward to Contract (approved variations automatically update the derived value - no navigation needed, but the Contract screen should show a "recently updated by Variation X" note, satisfying the First Principle)
- AI recommendations: "Variation approved - the contract value has changed; review the updated Budget forecast" (Section 8)
- Next logical screen: Contract Workspace (to see the updated value) or back to Milestones (if the variation affects an upcoming one)

Payment Request / Payment Recording (Phases 7-8)
- Purpose: answer "what do we ask for, and what came in?"
- Primary user: Project Manager (request), Accounts/Commercial responsibility-holder (record)
- Information shown: amount, GST breakdown, due date, outstanding total, retention withheld
- Primary action: Create Payment Request (from an achieved milestone) / Record Payment (against an outstanding request)
- Secondary actions: Send Reminder (Section 8), Record Adjustment/Correction, view Allocation if split across requests
- Exit paths: Project Dashboard, Commercial Audit Trail (CX-01's own recommended unified view)
- AI recommendations: "Payment overdue by 14 days - send a reminder?"; "Final milestone paid - release retention?"
- Next logical screen: back to the originating Milestone (status auto-advances to paid)

---

## 5. Navigation Specification

Decision: Commercial is a workspace inside a Project, not a standalone top-level module. This directly follows the Construction Philosophy stated at the top of this brief ("everything starts from the project... build Commercial as another workspace inside a project"), and matches how every other project-scoped capability in Atlas already works (Workflow, Site Progress, Explain Health are all reached from the Project Dashboard, not a separate global "Workflow module" or "Health module"). The counter-argument - a global Commercial destination for someone who wants "all outstanding payments across every project" - is real, but is already correctly served by the executive layer (Commercial Intelligence, Portfolio Control Center), which composes across projects by design. Building a second, standalone Commercial module would duplicate that composition logic rather than reuse it. Recommendation: Commercial lives inside the Project (per this specification's own screens above), with the existing executive views remaining the cross-project lens - no new navigation-level concept required, only the missing screens themselves.

---

## 6. Role Specification

Decision: Commercial Manager and Accounts do not become new Atlas roles. Justification: CX-01 and this specification both confirm Atlas's existing four roles (management, project_manager, site_supervisor, client) map cleanly onto every responsibility this specification defines - "raise a payment request," "record a payment," "approve a variation" are all actions a Project Manager or Management account can take with the existing permission model (RC-02/Beta-06D's own extensive authorization work already established the pattern of assert_project_visible plus a role check for every commercial mutation). Introducing two new roles would mean re-deriving that entire authorization surface for two more identities, for a distinction ("who specifically does the accounting work") that is an internal company org-chart question, not a permission boundary Atlas itself needs to enforce. Recommendation: "Commercial Manager" and "Accounts" are responsibility labels a company assigns internally to specific project_manager (or management) accounts - Atlas doesn't need to know or enforce this distinction, the same way it doesn't need a distinct role for "the PM who happens to also do scheduling." If a specific company's workflow genuinely requires Accounts to be blocked from operational actions a PM can take (a real permission boundary, not just a label), that would justify a new role - but no evidence from this pass or CX-01 shows that requirement exists today, and this specification does not manufacture one.

Per-role summary, building directly on PX-01/CX-01's own journey work:
- Management: approves at contract/variation/budget-exceeded decision points; never enters transactional data.
- Project Manager: the primary operator of every Commercial screen in this specification - creates contracts, budgets, milestones, variations, payment requests; records payments if the company doesn't delegate that specifically.
- Site Supervisor: no direct Commercial interaction, consistent with PX-01's own finding that this role's world is capture and execution, not administration.
- Client: unchanged from today's correctly-scoped experience - approves/rejects variations, views investment/payment status, never sees internal cost data (Budget stays internal-only, per Section 2's own decision).

---

## 7. Automation Strategy

Per this brief's own instruction - never require repetitive manual work Atlas already has enough information to do safely:

- Generate: invoice numbers (Phase 7), retention withholding on every payment (Phase 8), GST calculation on every payment request (Phase 7).
- Suggest: raise a Payment Request when a milestone reaches achieved (Section 8's clearest case); start a Variation when a BOQ revision shows a material quantity/rate change (Phase 4); revise the Contract when a Variation is approved (today this already happens automatically for the derived value - the suggestion is for the explicit revision-history entry this specification's own Contract versioning design requires).
- Calculate: GST breakdown, retention amounts, forecast/variance (already exists, confirmed correct), BOQ line totals.
- Warn: budget exceeded (data exists - variance already goes negative correctly; the warning is new), a contract active 90+ days with no budget (a genuine gap-detection pattern, not existing data).
- Escalate: an overdue payment request past a configurable threshold escalating from "reminder suggested" to "flagged in Executive Hub / Priority Engine" - directly reusing the existing Priority Engine's own composition pattern (CX-01, Section 8 below) rather than building a second escalation mechanism.

---

## 8. AI Behaviour Specification

This is an EXTEND of Atlas's existing AI proposal infrastructure, not a new AI system. Verified directly for this specification: intelligence_engine.py already implements a complete "trigger -> generate proposal -> user accepts/rejects" pattern (generate_proposals_for_event, _emit_proposals_from_structured), currently wired only to Reality Capture events (a voice note or photo triggers an AI-suggested operational item). The ai_proposals collection and its accept/reject route (routes/ai_proposals.py) are trigger-agnostic in shape - nothing about the accept/reject mechanism is specific to reality events.

Design: add Commercial events as a second trigger source into this same pipeline, not a parallel AI system. Concretely:
- Trigger: milestone_status_changed -> achieved. Proposal: "Raise a Payment Request for [milestone name], Rs [amount]." Accept -> pre-fills and opens Payment Request creation (Section 4's screen). Reject -> dismissed, no action, logged.
- Trigger: variation_status_changed -> approved. Proposal: "Contract value changed by Rs [delta] - log this as a formal Contract revision." Accept -> creates a contract_revisions entry (Section 2). Reject -> the derived value still updates automatically (unaffected), only the explicit revision-log entry is skipped.
- Trigger: budget variance crosses zero (turns negative) on a read. Proposal: "This project's forecast now exceeds budget - flag for management review." Accept -> surfaces in the existing Priority Engine (reused, not rebuilt) as a management-facing item.
- Trigger: a payment request's due date passes with outstanding > 0. Proposal: "Payment overdue by [N] days - send a reminder?" Accept -> triggers Section 7's reminder mechanism.
- Trigger: final milestone reaches paid. Proposal: "Retention of Rs [amount] is available for release." Accept -> opens the retention-release action (Section 2, Phase 8).

Every one of these reuses the existing ai_proposals generate/accept/reject mechanism with a new trigger and a new proposal-text template - EXTEND, explicitly not NEW, because the hard part (a working, tested, already-adopted suggestion-and-confirmation UX pattern) already exists and this specification found no reason to replace it.

---

## 9. State Machine Specification

Consolidating every state machine this specification touches, marking each REUSE/EXTEND/NEW:

- Contract: draft -> review -> approved -> active -> completed -> closed, EXTEND to add active <-> suspended and {active, suspended} -> terminated.
- Budget: no formal state machine today (a single mutable document); EXTEND to add a frozen boolean gate, not a full state machine - freezing isn't a lifecycle stage, it's a toggle.
- BOQ: NEW - versioned document, no existing state machine to extend.
- Milestone: pending -> ready -> achieved -> payment_requested -> paid -> closed, REUSE as-is; dependency-gating is a guard condition added to the existing ready transition, not a new state.
- Variation: draft -> submitted -> client_review -> {approved -> implemented, rejected}, REUSE the core sequence (confirmed by direct search: this is the exact current state set, including the already-existing `implemented` post-approval state), EXTEND with withdrawn and a rejected->draft revision path, both confirmed absent today.
- Payment Request: existing states (achieved-gated creation through to paid), REUSE, with EXTEND for the advance-payment exception noted in Phase 8.
- Payment: not a state machine today (an append-only record); EXTEND with corrects_payment_id and allocation fields, still fundamentally append-only - consistent with Section 10's own ruling that payments are never deleted or edited in place.

---

## 10. Product Decisions Register

Each answered directly, with reasoning, per this brief's own requirement.

Should contract values be editable? No. The current design (value derived automatically from approved variations, never manually overwritten) is correct and should be preserved exactly. Direct editing would let a contract's value silently drift from the sum of what was actually approved - a First Principle violation. Other terms (duration, retention%) become editable only through the new versioned-revision mechanism (Section 2), never in place.

Should payments ever be deleted? No. Financial records are never deleted in this specification - corrections and refunds are new records that reference what they correct (Section 2, Phase 8), preserving a complete, honest history. This matches how Atlas already treats operational history (append-only event ledgers throughout commercial_events) and extends the same principle to payments specifically.

Should BOQ revisions overwrite? No. Versioned, per Section 2 - the same reasoning as Contract revisions: a BOQ used to justify a variation's cost delta needs to still exist in its original form even after being revised, or the variation's own justification becomes unverifiable.

Should milestones be immutable? Their sequence and terms should be editable while pending (before work has genuinely started against them) and locked once ready or later - editing a milestone's financial value after a client may have already seen and relied on it would violate this specification's own First Principle. Recommend: full edit while pending, append-only notes/comments after.

Should commercial history ever disappear? No, categorically. Every design decision in this specification (contract revisions, BOQ versions, payment corrections rather than edits, commercial_events as the audit backbone) is built around this single answer.

Should audit events be permanent? Yes - this is already how commercial_events behaves today (an append-only collection, confirmed throughout this engagement's own extensive Timeline verification work), and nothing in this specification proposes changing that. REUSE, unconditionally.

---

## 11. Engineering Readiness Matrix

| Capability | Classification | Basis |
|---|---|---|
| Contract create/review/approve/activate | REUSE | Existing, correct, verified backend function and state machine; needs UI only |
| Contract revise/suspend/terminate/archive | EXTEND | New states in an existing transition-map pattern; new contract_revisions collection using an existing event-payload shape |
| Budget create/revise | REUSE | Existing, correct backend |
| Budget freeze | EXTEND | One new field, one new guard |
| Budget comparison view | REUSE (data) / NEW (presentation) | Data exists via commercial_events; no view exists |
| BOQ (all of Phase 4) | NEW | No backend model exists at all |
| Milestone create/status | REUSE | Existing, correct backend |
| Milestone dependencies | EXTEND | One new field, one new guard, same pattern as existing transition guards |
| Variation create/submit/decide | REUSE | Existing, correct, already has partial UI |
| Variation withdrawal/schedule-impact/revise-after-rejection | EXTEND | Confirmed absent by direct search of VARIATION_TRANSITIONS; new field/states within the existing object |
| Payment Request create, GST calculation | EXTEND | Function exists; GST field exists but is unused - wiring, not new modeling |
| Invoice numbering | EXTEND | Formalizes the existing Payment Request object |
| Credit/Debit Notes | NEW | No equivalent exists |
| Payment record/partial | REUSE | Existing, correct backend |
| Retention withholding/release | EXTEND (withholding) / NEW (release action, tracking) | retention_percent exists unused; the split calculation extends record_payment, the release action and running total don't exist |
| Advance payment | EXTEND | advance_percent exists unused; needs a flag and one guard exception |
| Refund/Correction | EXTEND | Reuses record_payment/is_adjustment, adds one linking field |
| Payment allocation | NEW | No multi-request split capability exists |
| AI trigger integration (Section 8) | EXTEND | Reuses the entire existing ai_proposals generate/accept/reject pipeline with new triggers |
| Lead/Proposal/Estimate (Phase 1) | NEW | No concept exists in any form |

---

## 12. Phased Build Plan

Sequenced by the same readiness-first logic CX-01 established, refined here with this specification's own added detail.

Phase I - Reuse (fastest to real usability, zero new backend design): Contract create/review/approve/activate UI, Budget create/revise UI, Milestone create/status UI, Variation create/submit/decide UI (extending the one workflow with partial UI already), Payment Request creation UI, Payment recording UI. This phase alone, per CX-01's own finding, takes Atlas from "cannot run a commercial project" to "can run one." No new backend work.

Phase II - Extend (small, well-scoped backend additions, each directly closing a gap this specification found with hard evidence - GST, retention, and advance sitting unused; no correction-linking; no budget freeze): GST wiring, retention withholding + release, advance-payment flag, payment correction linking, budget freeze, milestone dependencies, contract revision/suspend/terminate states, variation withdrawal and schedule-impact field, invoice numbering. Also in this phase: Section 8's AI trigger integration - deliberately placed early rather than last, because it reuses fully-existing infrastructure and is disproportionately high-value (the milestone->payment-request suggestion in particular is this specification's single clearest "make Commercial feel proactive" moment) for its genuinely small implementation cost.

Phase III - New (genuinely new domain objects, correctly sequenced last): BOQ (Phase 4, the largest single item in this specification), Credit/Debit Notes, Payment allocation, Lead/Proposal/Estimate (Phase 1). Recommend BOQ first within this phase - it's the one new capability the rest of the specification actively depends on (variation-generation-from-BOQ, milestone-BOQ linkage), while Lead/Proposal/Estimate is the most independent of the four and can genuinely wait without blocking anything else in this specification from being useful.
