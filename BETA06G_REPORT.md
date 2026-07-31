# Beta-06G — Multi-Role Experience & Production Readiness Validation Report

Per this sprint's own mandatory requirement, this report begins with the audit classification table.

---

## Role Validation Matrix

| Role / Workflow | Status | Evidence |
|---|---|---|
| Client - Dashboard, Investment, Payment Journey, Variation Centre | VERIFIED | Walked live against real ACDP data as the real seeded client account: all four endpoints return correct, internally-consistent figures (contract value, paid, outstanding, upcoming payment all present and coherent). |
| Client - full approval lifecycle (create -> request clarification -> PM responds -> client approves) | VERIFIED, functionally | Walked end-to-end through real API calls with a genuinely project-scoped client: every step succeeded, and the item's own history recorded all four events correctly and in order. |
| Client -> PM handoff: "clarification requested" visibility | BUG, found and fixed this pass | request_clarification's own docstring states its purpose is making client questions "clearly visible to the PM" - but no screen anywhere actually distinguished a client_approval item awaiting a PM response from an ordinary pending approval. See full account below. |
| Management - Executive Hub, Portfolio Control Center, Priority Engine, Explain Health, Commercial Intelligence | VERIFIED (carried forward) | Extensively cross-validated in Beta-06E's own pass across all 6 seeded projects and the full commercial chain; not independently re-walked this pass given that prior verification was thorough and recent. |
| Project Manager - Daily Review, priorities, assignment, tracking, commercial status | VERIFIED (carried forward from Beta-06E/F), EXTENDED this pass | Beta-06E's own end-to-end lifecycle simulation already confirmed create/assign/transition/verify/close all work correctly for a PM. This pass's own fix directly extends this role's daily experience with the clarification-visibility gap. |
| Site Supervisor - capture, operational items, comments, voice updates, blockers | VERIFIED (carried forward) | Core lifecycle actions confirmed working across Beta-06B through 06E's own testing; not independently re-walked this pass. |
| Site Engineer - assigned work, workflow progression, evidence, inspections | NOT INDEPENDENTLY WALKED this pass | Named explicitly rather than assumed covered by Supervisor's own testing, since this sprint names Site Engineer as a distinct role with its own section. |
| Cross-role workflow (Management -> PM -> Supervisor -> Engineer -> PM -> Client -> Management) | NOT WALKED AS ONE CONTINUOUS SEQUENCE this pass | Individual segments of this chain were verified in this and prior passes (PM<->Supervisor in Beta-06E, PM<->Client in this pass), but the full six-role sequence was not exercised as one continuous scenario. |
| Reference Portfolio qualitative assessment (#8) | NOT PERFORMED this pass | Named explicitly, not assumed adequate. |

---

## The Bug Found — Full Account

Walking a client's approval lifecycle exactly as a real client would use it - approve a tile selection, but first ask a question about the brand - surfaced something the code's own comments already flagged as an intended, not-yet-delivered outcome. request_clarification's own docstring reads: "Clarification keeps the item exactly where it is - open, still awaiting the client's real decision - while making it clearly visible to the PM that the client has questions before they can decide."

That second half was never actually true. A grep across the entire frontend for any reference to clarification beyond the request action itself returned nothing - no screen, badge, or list anywhere distinguished a client_approval item with an unanswered question from an ordinary pending approval. A Project Manager checking My Day's own "Pending Approvals" section had no way to tell which of their pending approvals were simply waiting on the client's own decision versus which ones the client was waiting on them to answer - without opening every single item individually to check its history.

This is exactly the kind of finding this sprint's own validation philosophy asks for: not a crash, not a data leak, but a real person doing their real daily job (triaging approvals) unable to do it efficiently because information the system already has was never surfaced. Per this sprint's own framing - "Would they require training simply because of the software?" - the honest answer here was yes: a PM would need someone to explain that they must open every approval individually to check for pending questions, which is exactly the kind of friction this sprint exists to eliminate.

Fixed by adding _flag_awaiting_clarification_response, a small, targeted helper that checks each pending approval's own last_derived_from_op_event_id (a field every mutation already sets, including request_clarification and add_comment) against a single batched query - if an item's most recent event is itself a clarification_requested, nothing has happened since, so it is genuinely still awaiting the PM's response. No new event kind, no new data model, no new API - this reuses the exact ledger and field the original feature already wrote, it was simply never read back out anywhere.

Verified three ways: a constructed scenario with three items in three distinct states (awaiting response, already answered, never questioned) confirmed the flag is True/False/False respectively - not just present, but correctly differentiated. Verified against the real ACDP portfolio: of the first five real pending approvals, two are genuinely awaiting a response that was never given, confirming this isn't a synthetic edge case but a real, current gap in the seeded reference data that a real PM using this exact portfolio would currently miss.

A small, visible frontend change accompanies the fix: My Day's pending-approval cards now show an "AWAITING YOUR RESPONSE" badge, using the same visual pattern already established for the existing "ASSIGNED TO YOU" badge, rather than inventing a new visual language.

---

## Client Assessment

The client-facing approval workflow itself - the part the client directly experiences - was confirmed to work correctly and feel natural: request clarification, receive an answer via comment, then approve, all in the same place, with no dead ends or confusing states. The gap found this pass was entirely on the receiving end (the PM's own visibility into an incoming question), not in anything the client themselves would encounter. This is a meaningful distinction for production readiness: the client half of this workflow does not need further work; the PM-facing half did, and now does.

---

## Testing

- 1 new regression test, reproducing the exact three-state scenario (awaiting/answered/never-asked) that confirms the fix distinguishes correctly, not merely that it doesn't crash.
- Full regression suite: 133/133 passing (up from 132).
- npx tsc --noEmit: zero errors, project-wide, after the frontend badge addition.
- Verified against real, live ACDP data - not only a constructed scenario.

---

## Files Changed

- backend/engines/operations_engine.py - new _flag_awaiting_clarification_response helper, wired into _my_day_pm's pending_approvals.
- backend/tests/test_dev02_bootstrap_reliability.py - 1 new regression test.
- frontend/src/MyDay.tsx - new "AWAITING YOUR RESPONSE" badge on pending-approval cards.

---

## Remaining Risks — Named Explicitly

1. Site Engineer's own primary workflows (assigned work, workflow progression, evidence upload, inspections, production inputs) were not independently walked this pass as their own distinct role - this sprint names Site Engineer separately from Site Supervisor, and that distinction was not honored with its own dedicated walkthrough.
2. The full six-role cross-workflow chain (Management -> PM -> Supervisor -> Engineer -> PM -> Client -> Management) was not exercised as one continuous sequence - individual adjacent handoffs were verified in this and prior passes, but not stitched into one end-to-end scenario.
3. Reference Portfolio qualitative assessment (naming realism, onboarding usefulness) was not performed.
4. The same "documented intent, never actually surfaced" pattern that produced this pass's own finding was found once, by chance, while walking one specific workflow. Given how directly this mirrors the pattern from Beta-06E and Beta-06F (a real capability existing in the data model but never actually wired into the screen meant to show it), a deliberate sweep for other "the docstring promises this but nothing displays it" cases across the codebase would be a reasonable, high-expected-value next step, not yet performed.

---

## Beta-06G Assessment

This sprint is not reporting Complete. Per its own Definition of Done, Site Engineer's own distinct workflows and the full cross-role chain were not independently exercised, and are named above rather than assumed adequate given other roles' own verification.

The finding this pass produced continues a pattern now visible across four consecutive sprints (Beta-06D through 06G): real defects surfaced specifically by using the product as a real person would, rather than by reading code or trusting that a feature's own documentation matched its actual behavior. In each case the underlying platform data was correct and complete; the gap was in what got shown, when, to whom. This is a meaningfully different - and arguably harder to catch - class of defect than the authorization bugs found earlier in this Beta-06 series, and this pass's own finding (a documented design intent that was simply never implemented in the UI layer) is exactly the kind of thing that would surface as real user confusion during an actual pilot, not as a system failure. Fixing it before that pilot, rather than during it, is the direct value of this sprint.
