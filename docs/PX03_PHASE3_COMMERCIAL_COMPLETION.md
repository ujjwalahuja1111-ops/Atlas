# PX03_PHASE3_COMMERCIAL_COMPLETION.md

## 1. What Was Audited

Every item this task's own Section 1 lists (A-M): the Payment Request lifecycle, payment recording, billing/collections, Commercial Health, Cash-Flow Timeline, commercial notifications, overdue handling, role-based visibility, date handling, project/archive isolation, navigation, existing tests, and the notification infrastructure. Each is classified below using exactly the required system: VERIFIED, FIXED, ALREADY CORRECT, BLOCKED, NOT ATTEMPTED.

## 2. What Was Already Correct

- Budget route gating (/commercial/budget) - already restricted to management/PM via _require_write_access, with a comment explicitly citing "the frozen spec's own section 6." Left unchanged.
- Summary route's budget stripping for Client - already correctly nulled budget for non-management/PM roles before this phase.
- Contract route's own fields (retention/advance/GST percentages) - confirmed these are terms the Client is already party to via the signed contract itself, not internal Atlas planning data. Not a leak; left unrestricted for Client.
- Payment request/payment/variation/milestone routes - confirmed these return data this task's own Section 6 explicitly names client-safe (payment requests, payments, variations) or reasonably operational (milestone progress). Left unrestricted.
- DatePicker usage across the Commercial Workspace - confirmed via the generic form-field renderer that every date field (raised_date, due_date, payment date, contract date) is already routed through DatePicker, not manual text entry.
- Home redirect logic (PX-02 Phase 2's own reversal) - confirmed still targets viewRole === 'admin' only, unchanged, with the stayHere escape hatch intact. No regression.
- No unexpected redirects into Commercial from any other route - the only path in is the Bill phase's own explicit embed.
- Timeline events for the payment state machine - append_commercial_event already logs payment_request_status_changed and payment_received on every relevant mutation, unmodified by this phase.

## 3. What Was Implemented

- Payment received / partial payment received notifications, targeted specifically at whoever raised the request (raised_by_user_id), differentiated by the real, post-transition outcome (full vs. partial) - see Section 4 for why this was a defect, not a clean gap.
- The 7-day overdue escalation rule, as a deterministic domain function (check_and_escalate_overdue_payment_requests) plus a callable route, given no scheduler exists in this environment (see Section 14 for the honest limitation).
- A require_active gate on assert_project_visible, applied to every core Payment Request mutation (create_payment_request, transition_payment_request_status, record_payment), closing the archive-isolation gap.

## 4. What Genuine Defects Were Found

1. The existing "payment received" notification fired before the payment's own outcome was determined, so it could never distinguish a partial payment from one that completed the request - and it only targeted the broad project PM/Management set, never the specific person who raised the request. This is not a "missing" notification (one already existed) but an incomplete one. Fixed by adding a second, targeted, outcome-aware notification alongside the existing one, which was left unmodified.
2. list_commercial_events had zero role gating - a genuine, serious security leak predating PX-03 entirely (from CP-01/RC1-HARDENING). Its own event payloads include exact internal figures (budget_revised's from/to values, actual_cost_recorded's deltas). Any Client or Supervisor with ordinary project access could retrieve this. Fixed by gating the route to management/PM.
3. The /commercial/summary route treated Supervisor identically to Client (both got everything except budget), when this task's own Section 7 gives Supervisor no safe-list exception the way Client's own Section 6 does. Fixed by blocking Supervisor entirely from this route.
4. record_payment() allowed a payment to be recorded against a request still in draft or the newly-added under_review state - only cancelled was ever blocked. This predates this phase (the draft gap existed even before Phase 3's own work). Fixed to require sent or later.
5. commercial_engine.py had no archive-awareness anywhere. A Payment Request could be created, submitted, approved, or paid against an archived project with no rejection at any layer.
6. create_payment_request() never called assert_project_visible internally at all - only the route did. This was caught specifically because a regression test called the engine function directly (bypassing the route), which is exactly the kind of caller a defense-in-depth check should protect against. Fixed at the engine layer, matching the pattern the other two mutation functions already used.

## 5. What Was Intentionally NOT Changed

- The Payment Request state machine's own transitions (PAYMENT_REQUEST_TRANSITIONS) - audited (Section 4 of this task's own brief) and confirmed correct; no defect found, so nothing was touched.
- The Billing & Collections formulas - audited against the edge cases this task's own Section 5 lists (no payment requests, draft/cancelled requests, partial payments, zero contract value) and confirmed correct via the existing PX-03 Phase 1 test suite, which already covers these cases.
- Commercial Health's own thresholds and independence from operational health - confirmed unchanged, still a single rendering location (Phase 2's own consolidation holds).
- The frontend was not touched this phase at all - this was a backend-focused audit and hardening pass, and no frontend defect was found that this phase's own scope required fixing.

## 6. Notification Matrix

| Event | Recipient | Status |
|---|---|---|
| Payment Request submitted for review | Management (project-assigned) | Preserved from Phase 1 |
| Payment Request approved | The PM who raised it | Preserved from Phase 1 |
| Payment Request returned for revision | The PM who raised it | Preserved from Phase 2 |
| Payment received (partial) | The PM who raised it, differentiated | Fixed this phase |
| Payment received (full) | The PM who raised it, differentiated | Fixed this phase |
| Payment Request becomes overdue (initial transition) | N/A - a status change, not itself notified | Deterministic transition only |
| 7-day overdue escalation | The PM who raised it + all project Management | Implemented this phase |

## 7. Payment State-Machine Verification

All items from this task's own Section 4 checklist:

- Invalid transitions rejected: VERIFIED (existing PAYMENT_REQUEST_TRANSITIONS dict, unchanged, already enforced).
- Payment cannot be recorded before sent: FIXED (Phase 2's own fix, re-confirmed still correct this phase).
- Payment cannot exceed remaining amount: NOT ENFORCED - confirmed by reading record_payment(): no ceiling check exists against the remaining balance. Named as a real, separate gap, not fixed this phase (out of this pass's own focus, and this task's own Section 4 only asks to "confirm," not mandating a fix if found).
- Partial/full payment transitions correctly: VERIFIED live.
- Duplicate payment recording: NOT PREVENTED - no idempotency key exists on record_payment; two identical calls would record two payments. Named as a real gap, not fixed this phase.
- Cancelled requests cannot receive payments: VERIFIED (existing check, unchanged).
- Returned-for-revision / approved notifications: VERIFIED live (Phase 2 and this phase respectively).
- Submit-for-review behavior: VERIFIED, unchanged.

## 8. Overdue / Escalation Behaviour

Implemented as described in Section 3 above. Explicit limitation, not glossed over: no scheduler, cron, or background-job mechanism exists anywhere in this backend (confirmed by searching the codebase before writing any code). check_and_escalate_overdue_payment_requests and its route (POST /projects/{project_id}/commercial/overdue-check) exist and are fully functional and idempotent when invoked - but nothing in Atlas currently invokes them automatically. An external scheduler would need to call this route periodically for the rule to actually run on its own; today it only runs when a user or script calls it.

## 9. Role-Based Commercial Access Matrix

| Endpoint | Management | PM | Supervisor | Client |
|---|---|---|---|---|
| profitability-panel | Full | Full | 403 | 403 |
| commercial/health | Full | Full | 403 | 403 |
| cash-flow-timeline | Full | Full | 403 | 403 |
| billing-collections | Full | Full | 403 | Full (explicitly client-safe) |
| client-safe-bill-summary | Accessible | Accessible | Not gated | The intended response |
| commercial/summary | Full | Full | 403 (fixed this phase) | Full, budget stripped |
| commercial/events | Full | Full | 403 (fixed this phase) | 403 (fixed this phase) |
| commercial/budget | Full | Full | 403 | 403 |
| commercial/contract, /payment-requests, /payments, /variations, /milestones | Full | Full | Full (not restricted - operational/client-safe data) | Full (explicitly client-safe) |

## 10. Archive Isolation Findings

Genuine gap found and fixed (Section 4 above). Verified live: a payment request cannot be created against an archived project (400, explicit message), while reading that project's existing commercial summary still succeeds - "archived != deleted" is honored. require_active=True was applied to the three core Payment Request mutation functions (create, transition, record payment). Not extended this phase, named directly: create_contract, create_budget, create_variation, revise_budget, and other commercial write functions were not audited/fixed for archive-awareness - a real, separate remaining scope item.

## 11. Navigation Findings

All ALREADY CORRECT, confirmed by re-inspection rather than assumed unchanged:
- Home's own redirect still targets Management only, unchanged since PX-02 Phase 2's own reversal.
- No route redirects unexpectedly into Commercial.
- The Commercial screen does not hijack any generic project route.

No frontend navigation code was touched this phase.

## 12. Test Results

- 9 new tests covering every genuine finding: partial/full payment notification targeting, overdue transition + escalation, escalation idempotency, the "recently overdue but not yet escalated" boundary case, the commercial-events leak fix, the summary route's Supervisor fix, archive isolation (with the engine-layer inconsistency it caught), and notification-failure isolation.
- Full backend regression suite: 203/203 passing (up from 194 at the start of this phase).
- npx tsc --noEmit: clean (no frontend files touched).
- npm run lint: 23 problems, unchanged from the prior phase's own improved baseline.

## 13. Live Verification Results

Every notification and state-transition finding above was verified through the real API in this session, not code-inspection-only - including the idempotency check (running the overdue-check endpoint twice and confirming exactly one notification exists, not two) and the security fixes (confirming actual 403 responses for Client/Supervisor against the real routes). UI/device verification remains unavailable in this environment, the same constraint stated in every prior phase's own validation document - nothing in this document claims a screen was manually tapped through.

## 14. Remaining Limitations

Stated directly, not implied solved:

- ~~No scheduler exists to invoke the overdue-escalation check automatically.~~ **RESOLVED in PX-03 Phase 4** — see docs/PX03_PHASE4_FINALIZATION.md Section 4. A genuine, live-verified background worker now invokes this automatically every 6 hours, following the exact pattern Atlas's own intelligence_engine worker already established.
- ~~Payment amount is not capped against the remaining balance, and duplicate payment recording is not prevented.~~ **RESOLVED in PX-03 Phase 4** — see Sections 1 and 2 of that document.
- ~~Archive-isolation (require_active) was only applied to the three core Payment Request mutations, not the full set of commercial write functions.~~ **RESOLVED in PX-03 Phase 4** — see Section 3 of that document; every commercial write function this task family names is now covered.
- Frontend was not touched this phase - no UI exists yet for triggering the overdue-check endpoint or seeing the new notification types beyond what the existing Inbox screen already renders generically. **PARTIALLY RESOLVED in PX-03 Phase 4**: the frontend now generates and sends the idempotency key described above, and the Inbox's own Escalations section was fixed to correctly surface commercial escalations. No dedicated UI for manually triggering the overdue-check endpoint was built (the automatic worker makes this less necessary), and this remains true.
