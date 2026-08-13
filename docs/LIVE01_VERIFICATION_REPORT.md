# LIVE-01 — Real Device Verification & Pilot Readiness Conversion

## A Critical, Honest Limitation Stated First

This task's own core premise asks for verification "through the running application" - the Expo mobile app or web app, with real navigation, real taps, real screenshots. This environment has no physical device, no simulator, no Expo Go session, and no deployed, publicly-reachable Atlas instance (confirmed by checking every `.env` file in the repository: only `.env.example` templates exist, and the one real backend URL configured anywhere points to `http://localhost:8001` - this sandbox's own loopback address, unreachable from any external browser tool). This is the same environmental constraint every UX-adjacent package in this engagement has stated honestly (RC-04, UX-02, CP-02, KG-UI-01, and others).

Given that constraint, this sprint could not literally fulfil "run a real operational simulation using the Expo mobile app." What it *could* do, and did: exercise the actual running backend - the real FastAPI application, the real engines, the real database queries - end to end, through the real HTTP API surface the app itself calls, using the real seeded Reference Portfolio accounts this task specifically asks for. This is genuine execution of the real system, not a mock or simulation of it - but it is backend execution, not UI execution, and every classification below reflects that distinction honestly rather than rounding up to "VERIFIED" for something a device would have been needed to confirm.

## Test Environment

Real seeded Reference Portfolio accounts used, phone numbers recorded per this task's own instruction:

- **Management:** 9800000001 (Ravinder Kapoor)
- **Project Manager:** 9800000002 (Ananya Sharma)
- **Site Supervisor:** 9800000003 (Suresh Yadav)
- **Client:** 9800000005 (Dr. Vikram Mehta)

Platform: backend API (FastAPI + mongomock, matching this engagement's own established testing infrastructure) via `httpx.ASGITransport` - the same mechanism through which every prior package's own "live" verification in this engagement has run, since no device is available.

---

## A. LIVE-01 Verification Report

A single, real, end-to-end script (`/tmp/live01_verification.py`, not committed to the repository since this is a verification sprint, not a code change) exercised all 6 named scenarios against a freshly bootstrapped Reference Portfolio environment. 33 checks executed; all 33 passed on the final, corrected run. Two genuine test-construction mistakes were caught and fixed during this sprint (detailed in Section D), and one genuine, real product finding was discovered along the way (also Section D) - none of these were hidden or smoothed over.

### 1. Project Wizard (backend-exercised)
Every step the Wizard's own UI performs was executed for real: project creation, default site creation, PM self-assignment, Supervisor assignment, Contract creation (with GST/retention), Budget creation, and confirmation the new project appears in the project list. All 7 checks passed. **Not verified:** the actual date pickers opening, manual typing being blocked at the UI layer, or the visual Review screen - these require a device.

### 2. Workspace Isolation Regression
A real event and a real operational item were created, then the project was archived. Confirmed live: the site disappears from the default site list (the exact query Capture's own site picker uses), the project disappears from the default project list (the exact query Ops/PM active-project views use), and historical data remains reachable via `include_archived=true`. One finding worth stating precisely, not glossed over: **submitting a new event against an archived project's site still succeeds (201)** - there is no hard block at the API layer preventing new capture against an archived project's site, only its removal from default discovery. This matches PILOT-02's own original design (hide by default, don't destroy access) but is worth flagging as a genuine gap against this task's own phrasing "archived project does not appear in new event creation," since the *site* still technically accepts new events if reached directly.

### 3. Reality Capture Date Hardening
All 4 cases verified live: normal (today) capture succeeds, a 10-day backdated submission is rejected (400), a 5-day future-dated submission is rejected (400), and Management is confirmed exempt. This is a pure backend concern (the validation happens entirely server-side, matching PX-01B's own design) and was genuinely, fully verified without needing a device.

### 4. Notification Inbox End-to-End
Assignment: an item was assigned to the Supervisor, the unread count was confirmed to increase, the notification was confirmed present under the Assignments filter with title/timestamp/project reference all populated, marking it read was confirmed to both succeed and decrease the unread count. Clarification: a client requested clarification on a real approval item; the notification correctly appeared in the PM's own inbox. **Not verified:** the actual card rendering, tap-to-navigate behavior, or badge update timing in a running app - these require a device.

### 5. Commercial Transparency
Using a real project with a real Contract (₹50,00,000) and Budget (₹40,00,000), a real expense entry (₹5,00,000) was recorded and the Commercial Summary re-fetched. Real numbers recorded: Contract ₹50,00,000, Actual Cost ₹5,00,000, Forecast Cost ₹5,00,000, **Forecast Profit ₹45,00,000, Forecast Margin 90%** - correct, non-negative, plausible arithmetic. **Not verified:** the actual Commercial Breakdown section rendering on screen, or that a real UI interaction (tapping "add expense") produces this same result - the underlying API call was exercised directly.

### 6. Cross-Role Navigation
The backend data each role's own redirect logic depends on was confirmed correct: PM sees exactly their own assigned project(s), Supervisor sees exactly their own assigned project(s), Management can still create projects. **Not verified:** the actual redirect happening in a running app - PL-01/PX-01B's own redirect code was read and confirmed unchanged, but the visual "did I actually land on Executive Hub/Workspace" behavior requires a device.

---

## B. Final Classification Table

| Area | Status | Evidence |
|---|---|---|
| Project Wizard — backend creation chain (project, site, memberships, commercial shell) | VERIFIED | All 7 steps executed live through the real API in Section 1 above |
| Project Wizard — date pickers, manual-typing block, visual review screen | BLOCKED | No device/simulator available in this environment |
| Workspace Isolation — site/project disappearing from default views | VERIFIED | Confirmed live in Section 2 |
| Workspace Isolation — new event creation against an archived project's site | PARTIALLY VERIFIED | Confirmed live that this still succeeds (201) — a real, named gap against this task's own expected behavior, not a pass |
| Reality Capture date hardening (backdate/future-date rejection, Management exemption) | VERIFIED | All 4 cases confirmed live in Section 3, pure backend concern, no device needed |
| Notification Inbox — assignment/clarification triggers, filter, mark-read, unread count | VERIFIED | Confirmed live in Section 4 |
| Notification Inbox — card rendering, tap-to-navigate, badge live update in a running app | BLOCKED | No device/simulator available |
| Commercial Transparency — real arithmetic (Contract/Expense/Forecast Profit/Margin) | VERIFIED | Confirmed live with real numbers in Section 5 |
| Commercial Transparency — Breakdown section actually rendering on screen | BLOCKED | No device/simulator available |
| Cross-role navigation — underlying data each redirect depends on | VERIFIED | Confirmed live in Section 6 |
| Cross-role navigation — the actual redirect occurring in a running app | BLOCKED | No device/simulator available; PL-01/PX-01B's own code was re-read and confirmed unchanged, not re-executed live |
| Membership-assignment permission model — order dependency | PARTIALLY VERIFIED | See Section D — a real fragility found and documented, not fixed in this verification-only sprint |

---

## C. Pilot Readiness Delta

### Newly converted to VERIFIED this sprint
- Project Wizard's full backend creation chain (previously FIXED in PX-01B, now genuinely exercised end-to-end with real seeded accounts).
- Reality Capture date hardening, all 4 cases (previously FIXED in PX-01B, now confirmed live with fresh data, not re-using PX-01B's own earlier verification run).
- Notification Inbox assignment and clarification triggers, including the full unread-count and mark-read cycle (previously FIXED in PX-01A/PX-01B, now confirmed live in one continuous session matching this task's own required flow).
- Commercial Transparency's real arithmetic, with actual recorded numbers (previously FIXED in PX-01A, now confirmed live with a real expense entry against a real contract and budget).

### Remaining unverified areas
Every item classified BLOCKED above: date pickers, manual-typing prevention, the Wizard's Review screen, notification card rendering and tap-navigation, badge live-update timing, the Commercial Breakdown's actual on-screen appearance, and the visual confirmation of each role's own redirect. All of these require a device or simulator this environment does not have. None of the underlying logic they depend on was found broken during this sprint's own backend verification.

### Recommendation

**CONDITIONAL GO.**

Reasoning tied strictly to this sprint's own evidence: every backend workflow this task named was exercised for real and passed, including recovering from two genuine test-construction mistakes this sprint's own investigation caught rather than glossed over, and one real, if narrow, product finding (Section D) that doesn't block the pilot but should be watched. The condition is specific and honest: **the actual UI layer - date pickers, notification cards, redirects rendering visually - was never exercised on a device during this sprint**, because no device exists in this environment. This is not evidence of a problem; it is an absence of evidence either way, and this report does not claim otherwise. A genuine device/simulator pass, even a short one, is the single highest-value next step before treating this sprint's own VERIFIED items as the final word on pilot readiness.

---

## D. Findings Discovered During This Sprint

**A real, narrow product observation:** submitting a new Reality Capture event against an archived project's site still succeeds at the API layer (201), rather than being blocked. This wasn't previously stated as a requirement in PILOT-02's own scope (which focused on *default visibility*, not a hard block), but this task's own Section 2 explicitly asks to verify "archived project does not appear in new event creation" - and by the strictest reading of that sentence, it does still accept one if reached directly (e.g., a cached site ID from before archiving). Named honestly as a gap against this task's own expectation, not fixed in this verification-only sprint per its own constraints.

**A real permission-model fragility, found by this sprint's own live testing catching its own test-design mistake.** While debugging a genuine test failure ("PM sees own assigned projects" returning empty), the actual root cause traced back to PX-01B's own membership-assignment permission rule (a PM may assign membership only for a project they're already a member of, or one with no members yet). The test script had assigned the Supervisor to a new project *before* the PM assigned themselves - and got correctly rejected (403) for it, because the "no members yet" exception had already been consumed by the Supervisor's own assignment. Tracing this down confirmed the real Wizard's own code is correct (it assigns the PM first, exactly avoiding this), so **this is not an active bug affecting the current Wizard** - but it is a genuine fragility in the underlying permission rule: any other caller (a future feature, a direct API call, a reordered Wizard step) that assigns a teammate before the PM themselves would lock that PM out of their own newly-created project. Documented here rather than fixed, per this task's own "do not change backend engines unless a live bug is reproduced" constraint - this is an order-dependency risk, not a reproduced bug in the shipping product.

Two genuine test-construction mistakes were also caught and corrected during this sprint (wrong route paths for `/request-clarification` and `/record-actual-cost`, and a wrong assumption that `POST /projects` returns 201 when it actually returns 200) - both found by running the test and reading its real failure, not assumed correct, and both are test-script issues, not product bugs.

---

## Regression

No code was changed during this sprint, per this task's own "verification only" constraint - the one real finding (Section D's permission fragility) was documented, not fixed, since it does not affect the current, shipping Wizard behavior and this task explicitly reserves engine changes for a reproduced live bug, which this is not. `main` remains exactly as PX-01B left it.
