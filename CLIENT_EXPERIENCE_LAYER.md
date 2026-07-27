# Client Experience Layer (CX-01)

A thin presentation layer over Atlas's existing engines, extending the existing Client Dashboard (app/(tabs)/index.tsx's ClientDashboardScreen) - no new screen, no new navigation, no /client-v2. Every number a client sees is read from an existing engine's own calculation; nothing here computes anything.

## Architecture

```
Client Dashboard (existing screen, extended)
  |-- Project Progress        - existing (CRE client_dashboard_view)
  |-- Your Investment          - NEW: client_investment_summary()   -> commercial_engine
  |-- Payment Journey          - NEW: client_payment_journey()      -> commercial_engine
  |-- Milestones               - existing (CRE lookahead / workflow)
  |-- Photos                   - existing (Reality Engine events)
  |-- Pending Approvals        - existing (Operations Engine, material/drawing approvals)
  |-- Variation Approvals      - NEW: client_variation_centre()     -> commercial_engine
  \-- Documents                - existing placeholder, unchanged
```

Three new functions in reasoning_engine.py, each doing nothing but reading and reshaping data commercial_engine already produces:

- client_investment_summary(project_id, user) - Contract Value, Paid, Outstanding, Current Variation Total, Upcoming Payment.
- client_payment_journey(project_id, user) - the Contract -> Milestone -> Payment sequence, built from real Commercial Foundation Engine Milestones and Payment Requests.
- client_variation_centre(project_id, user) - every Variation, each already carrying commercial_engine.calculate_variation_impact()'s output - the exact function decide_variation itself calls, never a second implementation.

## Why "Approval Centre" here means Variations, not the existing client_approval_centre

Atlas already had a client-facing approval system (client_approval_centre, app/op/[id].tsx) for material/drawing/design approvals raised as Operational Items - a different, already-working system, untouched by this sprint. This sprint's brief describes rich fields (Before/After, Cost Difference, Schedule Difference, Approval Impact via Cost/Schedule/Payment/Forecast) that map precisely to Commercial Foundation Engine's Variation entity, not to a generic Operational Item. client_variation_centre is that view - genuinely new, and deliberately separate from the existing approval system rather than a redesign of it.

## API Usage

| Endpoint | Function | Notes |
|---|---|---|
| GET /projects/{id}/client-investment | client_investment_summary | Returns null if no real Contract exists yet - frontend shows an honest empty state, never a fabricated number. |
| GET /projects/{id}/client-payment-journey | client_payment_journey | Same null convention. |
| GET /projects/{id}/client-variations | client_variation_centre | Returns {pending, history}, each Variation carrying its own impact. |
| POST /commercial/variations/{id}/decide | (existing, CF-01) | No new write endpoint - the client uses the same route already opened to the client role. |

Every read requires _assert_project_visible (the same engine-layer visibility check every other reasoning route uses) - a client cannot read another client's project's investment data.

## A real bug caught and fixed during development

The first version of client_investment_summary showed a partially-paid Payment Request's full original amount as "Upcoming Payment" - technically true of the request, but misleading to a client who has already paid part of it. Fixed to show the actual remaining balance (amount - sum(payments already recorded against this request)), verified against a live partial-payment scenario before being considered correct, and covered by a permanent regression test (test_upcoming_payment_shows_remaining_balance_not_full_amount).

## RBAC

Reads: client_investment_summary, client_payment_journey, client_variation_centre are all readable by any role with project visibility (management, PM, supervisor, client) - a client seeing their own project's real numbers is the point; there is nothing to hide from the client specifically about these three views, because they are already constructed to contain nothing internal.

Writes: unchanged from CF-01. Deciding a Variation (approved/rejected) is open to client/project_manager/management - a client may approve their own project's variation, matching the existing client_approval pattern's own precedent that this is fundamentally the client's decision.

What a client can never do: modify a Contract, Budget, Milestone status, or Payment Request status directly - every one of those routes requires management/project_manager (_require_write_access, unchanged from CF-01). The only client-writable action anywhere in the Commercial layer is deciding a Variation.

What a client can never see: Budget, Forecast, Committed Cost, Actual Cost, Variance, Remaining Budget - never present in any of the three new response shapes (not filtered at the edge; these fields are simply never read from commercial_engine.get_project_commercial_summary's own budget key in any of the three functions). Verified directly: test_client_investment_never_exposes_budget_fields asserts none of these terms appear anywhere in the response, not just that specific keys are absent - and commercial/budget's own route remains a hard 403 for client role, confirmed unchanged.

One deliberate exception, documented rather than silently present: GET /projects/{id}/commercial/summary (the full composed CF-01 endpoint) is technically readable by the client role and does include the internal budget object - this was CF-01's own RBAC design (read access for anyone with project visibility, matching Atlas's broader "clients see real data, translated per screen" philosophy) and is not changed here. client_investment_summary exists specifically so no client-facing screen ever needs to read that fuller, budget-inclusive endpoint directly - the safety boundary is enforced by which endpoint the frontend calls, and that choice is verified by test, not merely a convention.

## Component Hierarchy (frontend)

```
ClientDashboardScreen (app/(tabs)/index.tsx)
  |-- DashCard "PROJECT PROGRESS"       (existing)
  |-- DashCard "YOUR INVESTMENT"        (new) -> InvestmentTile x4, upcoming-payment banner
  |-- DashCard "PAYMENT JOURNEY"        (new) -> per-milestone row with connector line, status icon
  |-- DashCard "MILESTONES"             (existing)
  |-- DashCard "PHOTOS"                 (existing, unchanged)
  |-- DashCard "WEEKLY SUMMARY"         (existing placeholder, unchanged)
  |-- DashCard "PENDING APPROVALS"      (existing, material/drawing - unchanged)
  |-- DashCard "VARIATION APPROVALS"    (new) -> variation card (before/after, impact chips, approve/decline) + history list
  \-- DashCard "DOCUMENTS"              (existing placeholder, unchanged)
```

All new sections reuse the existing DashCard wrapper component and the existing dark, card-based visual language already established for this screen - no new design system introduced.

## What This Sprint Did Not Build - Named Explicitly

- Project Gallery reorganization (Progress/Drone/Milestone/Before-After grouping) - the existing "PHOTOS" card (a flat, chronological strip of recent photos) is unchanged. A real gap: photos aren't currently tagged by category anywhere in Atlas, so "Drone Photos" or "Before/After" grouping isn't derivable from existing data without a new capture-time classification this sprint didn't add.
- The single combined chronological feed (Commercial + Timeline + Photos + Approvals merged into one "Recent Updates" stream) - each category remains its own card, as it already was. Genuinely buildable from data that already exists (every source - commercial events, timeline events, approval decisions - already has a timestamp), but combining them into one properly-sorted, de-duplicated feed is real, non-trivial frontend composition work not attempted this sprint.
- Approval Detail view enrichment (Drawings/Photos/Quotations rendered inline when a client opens a specific variation) - client_variation_centre already returns linked_drawing_ids/linked_photo_ids/linked_quotation_ids for every Variation, so the data is present; a dedicated detail screen that resolves and displays those linked assets was not built.

## Future Roadmap

- Wire linked_drawing_ids/linked_photo_ids/linked_quotation_ids to actual asset resolution once a Document Engine (named as a future integration point in COMMERCIAL_FOUNDATION.md) exists - today these are id lists with no rendering.
- Photo categorization at capture time (progress / drone / milestone tags) would make Gallery reorganization derivable without inventing new frontend heuristics over uncategorized data.
- The combined chronological feed is the natural next UI investment once there are enough distinct event sources (commercial + timeline + approvals) that four separate cards start to feel like more scrolling than one unified story - worth revisiting once real client usage data shows whether that's actually the friction point.
