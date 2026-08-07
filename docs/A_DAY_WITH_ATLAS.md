# A Day With Atlas — Studio Neoteric's First Monday

This is a product judgment document, not an engineering audit. No code was written. Every specific claim about screen behavior (what a button does, where a tap leads, what's shown when data is missing) was verified by reading the actual current code - including this session's own fresh findings, not just carried forward from UX-01/UX-02's earlier work, since CP-01, CP-02, PL-01, EX-01, and WF-01 have all shipped substantial new surface area since those audits. Where a claim is about how a real person would feel, it's stated as judgment, not dressed up as measurement.

---

## 1. Complete Experience Walkthrough

7:15 AM — Site Supervisor. Opens the app, lands on Capture. This is genuinely good: one screen, photo/voice/text all available without navigating away, site selection is the only real prerequisite. This hasn't changed since UX-01 called it out as already correct, and it's still true.

8:00 AM — Project Manager. Opens the app, lands on the Unified Workspace for whichever project they were last in. Sees Today's Mission, Project Pulse, and - new since PL-01 - a Stage Focus card. For a project still in Planning, the card reads "Setup in progress - Contract needed, Budget needed, 0 milestones defined." This is honest and clear. But the card itself doesn't tap through to fix any of it - the PM has to already know to scroll to Commercial themselves. Atlas told them exactly what's wrong and then didn't offer to take them there.

9:30 AM — A milestone gets marked achieved. WF-01's own orchestration fires here - genuinely well: within moments, "Raise payment request for 'Foundation'" appears in AI Suggestions with no manual refresh needed. This is a real, working example of Atlas behaving like an operating system rather than software. But tapping the suggestion doesn't take the PM to that milestone - it opens the general Commercial screen, and the PM has to scroll down, find Milestones, find Foundation again, and tap the same "Raise Payment Request" action a second time. Atlas did the hard part (noticing) and then handed the easy part (navigating) back to the human anyway.

11:00 AM — A variation needs raising. PM opens Commercial, taps Create Variation, fills a form, taps Submit, taps Send for Client Review - three separate taps across three separate screen states for what is, from the PM's own point of view, one decision ("this needs the client's sign-off"). Each step is individually clear; the sequence as a whole asks the PM to understand Atlas's own internal state machine (draft -> submitted -> client_review) rather than just "send this to the client."

1:00 PM — Client reviews the variation. Opens the Client Dashboard, sees the variation, approves it. This part is clean - the client-facing experience remains appropriately minimal and was not found to have new friction since UX-01.

3:00 PM — Management checks in. Opens Profile, taps Executive Hub (correctly the obvious first stop since UX-02's own fix). Sees portfolio-wide priorities and commercial intelligence. To check one specific project's day-to-day status, though, Management has no direct path from Executive Hub into that project's own Unified Workspace - they'd have to back out, go find the project another way, and open it there. Two different "the state of things" views exist (Executive Hub, Unified Workspace) with no bridge between them.

5:30 PM — PM closes the day. No single "day complete" moment exists - Daily Review is a separate destination the PM has to remember to visit, not something the Workspace itself surfaces as a closing ritual.

---

## 2. Pain-Point Heatmap

| Area | Severity | Why |
|---|---|---|
| AI Suggestions -> generic navigation, not deep-linked | High | Directly undercuts WF-01's own core achievement - the suggestion is smart, the landing is not |
| Stage Focus card not actionable | High | Tells the PM what's wrong, doesn't offer the fix |
| Variation lifecycle (create/submit/send-for-review) | Medium | Correct but exposes internal state machine as three taps |
| Executive Hub <-> Unified Workspace, no bridge | Medium | Two "state of things" views for Management with no path between them |
| No end-of-day closing moment | Low-Medium | Daily Review exists but isn't surfaced as part of the day's natural rhythm |
| Capture | None found | Already correct per UX-01, re-confirmed this session |
| Client experience | None found | Already correct per UX-01, re-confirmed this session |

---

## 3. Navigation Friction

The core four-tab structure (Home/Ops/Capture/Profile) plus the Unified Workspace remains sound - UX-02's own fixes here haven't regressed. The one new gap: the Unified Workspace and Executive Hub are both legitimate "how's everything going" destinations for Management, and nothing connects them. A management user checking portfolio health in Executive Hub who wants to drill into one specific project's day-to-day has to leave, find the project through a different path (Projects tab), and open its Workspace separately - the two screens don't know about each other.

---

## 4. Interaction Friction

The variation approval sequence is the clearest example in the product today of Atlas's own internal state machine leaking into the interaction. Create -> Submit -> Send for Client Review are three separate, deliberate taps, each on its own button, each requiring the PM to understand what state the variation is currently in before knowing which button applies. A PM's actual mental model is simpler: "I want the client to see this and decide." Atlas asks them to operate its own state machine to get there.

---

## 5. Approval Friction

Approvals themselves (client deciding on a variation, PM approving/rejecting) are clean, single-tap actions once reached - this was true in UX-01 and remains true. The friction isn't in the approval action itself; it's in reaching the thing needing approval, which is the same navigation gap named in Sections 1 and 2.

---

## 6. Commercial Friction

The Commercial Workspace has grown to over 1,000 lines and ten distinct modal forms since CP-01/CP-02's own additions - each individually well-scoped and correctly gated, but collectively this is now the single most complex screen in the product. UX-02's own reorganization (Cash Flow anchor, Billing merge, History behind a button) is still structurally sound and hasn't been undone - the growth since then is additional capability (real create/edit forms for Contract, Budget, Milestone, Variation, Payment Request, Payment), not a return of the density problem UX-01 originally found. The friction here is narrower and more specific: it's the AI-Suggestions-to-generic-navigation gap (Section 1), not the screen's own internal organization.

---

## 7. Capture Friction

None found, re-confirmed fresh this session. This remains the one workspace in Atlas that already matches the product's own stated philosophy - stated plainly again rather than manufacturing something to fill this section.

---

## 8. Management Friction

The Executive Hub / Unified Workspace gap (Sections 1-3) is Management's most concrete friction point. Beyond that, Management's own experience is otherwise well-served by existing capability (Portfolio Control Center, Commercial Intelligence, Cross-Project Intelligence) - no new gap was found in this pass beyond the navigation bridge.

---

## 9. Client Friction

None found. The client-facing product remains appropriately minimal, correctly restricted, and was not found to have accumulated new friction across CP-01, CP-02, PL-01, EX-01, or WF-01, since none of those packages touched client-facing screens.

---

## 10. The 20 Highest-ROI UX Improvements

Ranked by operational impact - time saved, coordination removed, training reduced, profit impact - not visual polish, per this task's own explicit instruction.

1. Deep-link AI Suggestions to the specific item. "Raise payment request for Foundation" should open that milestone's own raise-payment-request form directly, not the general Commercial screen. Time saved: real, every time a suggestion is acted on. This is the single highest-leverage fix in this document, because it directly completes WF-01's own unfinished promise.
2. Make the Stage Focus card tappable. "Contract needed" should open Contract creation directly. Same principle as #1, applied to PL-01's own work.
3. Collapse variation submission into one action for the PM. "Send to client for approval" as a single button that internally handles create->submit->send-for-review, keeping the granular states as a display concept, not a sequence of required taps.
4. Bridge Executive Hub and the Unified Workspace. A direct "open this project's workspace" action from any project row in Executive Hub/Portfolio Control Center.
5. Surface Daily Review as part of the Workspace's own closing rhythm, not a separately-remembered destination - e.g., a prompt near end-of-day.
6. Deep-link the Commercial History event feed's own entries to the record they describe (tap a "milestone_status_changed" event, land on that milestone), not just a text list.
7. Pre-fill the "Send for Client Review" step with a suggested message, since the PM has to communicate this outside Atlas today (WhatsApp) if there's no in-app way to add context for the client.
8. A visible "what changed since I last opened this" indicator on the Workspace, so a PM returning after hours away doesn't have to re-scan every section to find what's new.
9. One-tap "mark this suggestion as done" on AI Suggestions, distinct from acting on it, for suggestions a PM has already handled through a different path (e.g., raised the payment request from Commercial directly before seeing the suggestion).
10. Show which role suggested actions are assigned to directly in the suggestion row (already computed via suggested_responsible_role, not yet displayed) - a management-directed suggestion showing up identically to a PM-directed one invites the wrong person to act.
11. A visible retention/advance status indicator on Payment records, given CO-01's own finding that these fields exist but are entirely unused - even a "not tracked yet" label would be more honest than silence.
12. Client-visible "why this changed" note on Contract value updates - the PM-facing revision note (CP-02) has no client-facing counterpart, and a client seeing their contract value change with no explanation is exactly the moment they'd reach for WhatsApp to ask why.
13. A single "what's blocking me" filter across Operations and Commercial together, since today a PM checks blocked operational items and pending commercial decisions in two different places.
14. Batch "raise payment requests" for multiple achieved milestones at once, rather than one form per milestone, for projects with several milestones completing close together.
15. A lightweight "note to self" on any item, since Atlas has no informal scratchpad today - anything not yet worth a full operational item currently has nowhere to live except a person's own memory or WhatsApp.
16. Show projected cash flow, not just current, on Project Pulse - a PM's real question is often "will we be short next month," not just "are we short today."
17. A visible confirmation moment after Quick Capture submits, beyond the current status text, so a Supervisor walking away from spotty connectivity has clear confidence the capture actually saved.
18. Surface the CRE's own confidence level on AI Suggestions, not just the recommendation - a PM should be able to tell at a glance whether a suggestion is high-confidence (act now) or lower-confidence (worth a second look) without opening the full insight.
19. A "review contract" suggestion (WF-01) should link directly to the Contract section with the relevant variation highlighted, not just open Commercial generally - the same class of fix as #1, named separately because it's a distinct suggestion type.
20. An explicit "this project is ready to move to the next stage" nudge on the Workspace once a stage's own completion criteria (PL-01) are met, rather than requiring the PM to remember to change it themselves - PL-01 built the criteria; nothing currently tells the PM they've been met.

---

## Where Atlas Still Behaves Like Software Instead of an Operating System

The pattern across nearly every item above is the same one: Atlas has gotten very good at knowing what should happen next, and still asks the human to do the work of getting there. WF-01 proved Atlas can notice a milestone is ready to bill without anyone asking. PL-01 proved Atlas can tell a PM exactly what Planning still needs. What's missing isn't more intelligence - every fix in this document reuses computation that already exists. What's missing is the last step: turning "here's what should happen" into "tap here and it's already open." That gap - smart noticing, generic landing - is the throughline of this entire day, and closing it is the highest-leverage work available to Atlas today, ahead of any new capability.
