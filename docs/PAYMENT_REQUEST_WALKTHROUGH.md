# PAYMENT_REQUEST_WALKTHROUGH.md

Every step below was actually executed through the real API in this session, not narrated from reading the code. Two genuine route-path mistakes in the verification script itself were caught and fixed mid-walkthrough (the real payment-request-list route is /projects/{project_id}/commercial/payment-requests, not a bare /commercial/payment-requests) - a reminder that even a document meant to describe existing behavior benefits from actually running it.

## The Scenario

Project: "PR Walkthrough Project." Contract Rs 50,00,000. Milestone "Foundation," 30% (Rs 15,00,000).

## Step 1 — PM creates draft

POST /api/commercial/payment-requests -> PR-001, status draft, amount Rs 15,00,000.

## Step 2 — PM submits

POST .../status {"status": "under_review"} -> status becomes under_review.

Inbox state immediately after:
- PM: waiting_for_others = 1 (their own request, now pending someone else's action)
- Management: commercial_attention = 1

## Step 3 — Management reviews

Management's own coordination inbox shows: "Payment Request PR-001 submitted for review."

## Step 4 — Management approves

POST .../status {"status": "raised"} -> status becomes raised.

PM's own inbox immediately shows: "Payment Request Approved."

## Step 5 — Request sent to client

POST .../status {"status": "sent"} -> status becomes sent.

## Step 6 — Partial payment received

POST /api/commercial/payments {"amount": 800000, ...} - status automatically transitions to partially_paid (no separate manual step). Billing snapshot at this point, real output:

billed_to_date: Rs 15,00,000
received_to_date: Rs 8,00,000
outstanding_receivables: Rs 7,00,000
collection_efficiency: 53.33%

## Step 7 — Final payment received

POST /api/commercial/payments {"amount": 700000, ...} - status automatically transitions to paid. Billing snapshot:

billed_to_date: Rs 15,00,000
received_to_date: Rs 15,00,000
outstanding_receivables: Rs 0
collection_efficiency: 100%

## Step 8 — Request closed

A genuine finding, not glossed over: there is no separate manual "close" action in the current state machine (PAYMENT_REQUEST_TRANSITIONS["paid"] = set() - a terminal state with no further transitions at all, including to a distinct closed status). Atlas's existing behavior already treats paid as the terminal, closed state. This task's own brief names an explicit 8th step ("Request closed") as if distinct from paid - confirmed by testing that Atlas does not currently model this distinction. Not fixed this phase (would mean either adding a new terminal status or reinterpreting paid as already meaning "closed," a design decision better made deliberately than as a side effect of writing this document) - named directly as an open question for a future pass.

## Summary Table

| Step | Action | Resulting Status | Inbox Effect |
|---|---|---|---|
| 1 | PM creates draft | draft | none |
| 2 | PM submits | under_review | PM: Waiting For Others; Management: Commercial Attention |
| 3 | Management reviews | under_review (unchanged) | Management sees the card |
| 4 | Management approves | raised | PM: "Payment Request Approved" |
| 5 | Sent to client | sent | none new |
| 6 | Partial payment | partially_paid (automatic) | none new (no notification wired for partial receipt this phase) |
| 7 | Final payment | paid (automatic) | none new (same gap) |
| 8 | "Closed" | Not a distinct state - paid is already terminal | N/A |

A second honest gap, named directly: this task's own Section 10 asks for a Timeline event on "partial receipt recorded" and "full receipt confirmed" specifically. The existing record_payment() function already logs a payment_received commercial event on every call (confirmed, unmodified, pre-existing) - so the Timeline requirement is satisfied - but no Inbox notification fires for either receipt event this phase. A PM or Management user would see the payment reflected in the Bill phase's own numbers, but would not be proactively told via Inbox. Named as remaining scope, not implied complete.
