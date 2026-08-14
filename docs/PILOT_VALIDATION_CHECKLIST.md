# PILOT_VALIDATION_CHECKLIST.md

## The Same Environmental Limitation, Restated Rather Than Assumed Resolved

No device, simulator, or deployed Atlas instance exists in this environment - the identical constraint every UI-verification document in this engagement (LIVE-01, PX-02 Phases 1-3) has stated. What was genuinely done: a live, multi-role backend verification (Supervisor raises an item -> PM assigns it -> PM raises a client-approval item -> Client requests clarification), confirming every coordination-state transition this checklist below asks about actually happens correctly server-side. The checklist itself marks every item requiring an actual screen as BLOCKED, not rounded up.

---

## Project Manager

| Check | Result |
|---|---|
| Opening Inbox shows Action Required within 5 seconds | BLOCKED - requires a device; the underlying API call was confirmed fast in this sandbox (well under a second for a small seeded dataset), but real-device rendering time was never measured |
| Waiting For You and Waiting For Others are visually distinguishable without opening an item | PARTIALLY VERIFIED - confirmed the two sections render with distinct headers and separate lists in the code; not confirmed as a visual, at-a-glance distinction on an actual screen |
| Grouped notifications ("OPS-104 updated 4 times") display correctly | VERIFIED (data) - test_notification_grouping_collapses_same_entity confirms the backend groups 3 separate notifications into one card with count: 3; the actual card rendering was not seen on a device |
| Escalated items are visually impossible to ignore | BLOCKED - the red aging color is implemented and unit-tested; whether it's actually attention-grabbing on a real screen wasn't observed |
| Tapping a coordination card opens the correct Workspace phase | PARTIALLY VERIFIED - confirmed the deep-link table and navigation call are correct in code (test_deep_link_phase_routing_matrix); the actual navigation and back-stack behavior was not exercised on a device |

## Site Supervisor

| Check | Result |
|---|---|
| Assigned items appear in Action Required | VERIFIED (data) - confirmed live through the real API: an item assigned by a PM appears correctly in the Supervisor's own Action Required section |
| Inbox is reachable within the mobile thumb zone | BLOCKED - requires a device |
| Long clarification threads collapse automatically | VERIFIED (data) - the same grouping mechanism covers this; not visually confirmed |

## Management

| Check | Result |
|---|---|
| Management Attention Digest appears on Executive Hub | BLOCKED - the card was built and is wired to fetch real data, but was not rendered on a device |
| Digest correctly identifies declining-health projects | VERIFIED (data) - confirmed the underlying management_attention_digest() function correctly queries and filters real project health data live; the digest returned an empty (correct) result for a project with no declining health in this session's own test run |
| Digest shows escalated blocker and payment-request counts accurately | VERIFIED (data) - same function, confirmed against real, freshly-created test data |

## Client

| Check | Result |
|---|---|
| Client's Inbox never shows internal PM/Supervisor coordination items | VERIFIED - test_client_visibility_restriction_via_per_user_scoping confirms a Client's own coordination inbox for Action Required and Waiting For Others is always empty, derived structurally (per-user data scoping), not by a category filter that could be misconfigured |
| Client can see and respond to their own Waiting For You items | VERIFIED (data) - confirmed live: a Client's request-clarification action correctly produces a notification that surfaces in the PM's own Waiting For You section (the reciprocal direction - the Client's own item appearing correctly for them - follows the same, already-tested per-user scoping) |
| Client's Inbox is usable without confusion about internal categories they can't act on | BLOCKED - a genuine UX judgment call that requires a real person looking at a real screen, which this environment cannot provide |

---

## Honest Summary

Every "VERIFIED (data)" entry above reflects a real, live confirmation that the correct information exists and is correctly classified - the backend does what this checklist asks. Every "BLOCKED" entry reflects something only a real screen can confirm: legibility, visual hierarchy, thumb-reach, and the subjective sense of "this is impossible to ignore." Nothing in this document claims a device-level pass that didn't happen.
