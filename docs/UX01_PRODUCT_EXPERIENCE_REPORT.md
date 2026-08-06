# UX-01 — Atlas Product Experience Refactoring

This is a product audit, not an engineering document. No code was written or changed. Every specific claim about screen structure, section counts, and data sources was verified by reading the actual current code, not inferred from memory of building it - including my own prior work (CP-01's own additions to the Commercial Workspace are audited here with the same scrutiny as everything else, not exempted for having been built recently). Where a judgment is about how a real person would experience something, it's presented as judgment, grounded in the evidence beside it, not dressed up as a measured fact.

---

## 1. Current UX Audit — Every Workflow That Feels Unnecessarily Complex, and Why

The Home screen presents nine separate, stacked sections to a Project Manager on first launch, with a confirmed near-duplication between two of them. Verified directly: MyDaySection's PM branch renders four groups (Blocked, Pending Approvals, High Priority Work, Escalations), and PmCreCards - rendered directly beneath it on the same screen - adds five more (Today's Priorities, Look Ahead, Blockers, Delays, Suggested Actions). "Blocked" and "Blockers" are genuinely different data (the first reads from operational items, the second from a CRE-generated project briefing's blocked_activities), but nothing on screen tells a user that - they see two lists with near-identical names and no explanation of why they're separate. This is exactly the "why does this screen exist" question this task asks first: the honest answer for having both is "two different sprints, at two different times, each independently decided this information mattered," not "a person designing this screen from scratch decided nine stacked sections was the right amount."

The Commercial Workspace has grown to eight sections and 805 lines on one continuously-scrolling screen, confirmed directly by reading the current file (up from roughly 515 lines before CP-01's own additions). Contract, Budget, Cash Flow, Milestones, Payment Requests, Payments, Variations, and Commercial Timeline are all present simultaneously, distinguished only by collapse state. A PM opening this screen to do one specific thing - say, check if a milestone is ready to invoice - has to either already know which of eight collapsed sections to expand, or scroll past seven sections of things they didn't come here for.

The Operations tab exposes six sub-buckets (proposals, overview, overdue, high_priority, awaiting, mine), confirmed directly in the tab's own TABS constant. Two of these - overdue and high_priority - name concepts that also already appear on the Home screen (Due Today, High Priority Work). A PM has no way to know from the product itself whether "Operations -> High Priority" and "Home -> High Priority Work" show the same list, an overlapping list, or something different, without opening both and comparing.

None of this is a claim that the underlying capability is wrong. Every one of these sections represents something a prior sprint verified was real, useful data. The problem this task asks about is specifically that each was added as its own destination, independently, without anyone asking whether the screen as a whole still made sense once they accumulated - which is a different question than whether any individual piece was worth building.

---

## 2. Navigation Audit

Current: Four tabs (Home, Ops, Capture, Profile), with Profile's own admin menu providing five further links (Executive Hub, Portfolio Control Center, Knowledge, User Management, System Info) to management-only destinations, and every other screen (Priority Engine, Executive Timeline, Portfolio Search, Explain Health, Commercial Workspace, Daily Review, Site Progress, Workflow) reached only through secondary navigation from one of those.

Proposed: Retain the four-tab structure - it's genuinely correct for the two roles who live in it (Site Supervisor's world is Ops + Capture; a PM's is Home + Ops). The change is not to the tabs but to what Home and Ops each are responsible for showing, addressed in Sections 4 and 9 below, and to giving management a single, primary landing destination from Profile rather than five equally-weighted links with no indication which one to start with.

Reasoning: The tab structure itself was not found to be a problem in this pass - the actual friction identified in Section 1 is within screens (too much stacked on Home and Commercial), not in how screens are reached. Redesigning navigation architecture to fix a within-screen density problem would be solving the wrong layer.

---

## 3. Workspace Audit

- Home: 975 lines, serves three structurally different experiences (Client dashboard, and a shared My Day frame for admin/pm/supervisor with role-specific widget sets) from one file. The Client branch is confirmed cleanly separate (a distinct component, not a role-conditional maze within one render tree) - this part of Home is correctly scoped. The admin/pm/supervisor branch is where Section 1's nine-section stacking lives.
- Projects: Not deeply re-audited in this pass beyond confirming it exists as the correct entry point to per-project destinations (Section 5 of CX-01 already covers this ground); no new finding here.
- Capture: Confirmed to be one unified screen (not separate Voice/Photo/Text destinations) - genuinely well-scoped already, detailed in Section 7.
- Timeline: Not independently re-walked in this pass; Executive Timeline specifically was audited extensively in prior sprints (Beta-06F) and confirmed correct in composition, though its own screen-level information density was not re-examined here.
- Operations: Six sub-buckets on one tab, detailed in Sections 1 and 6.
- Commercial: Eight sections on one screen, detailed in Sections 1 and 5.
- Profile: Correctly minimal for non-admin roles; for management, five equally-weighted links with no indicated starting point (Section 2).

---

## 4. Information Hierarchy

Applied consistently: Primary = what a returning user needs without thinking; Secondary = relevant but not urgent, one tap away; Hidden = exists, rarely needed, behind an explicit action; Advanced = exists for a narrow case, should not appear in normal use.

Home (PM): Primary should be exactly one thing - "what needs your action right now," which today is spread across four-plus sections that could genuinely collapse into one, since Pending Approvals, Blocked, Escalations, and Blockers are all different flavors of the same underlying question. Secondary: Today's Priorities, Look Ahead (genuinely different in kind - forward-looking, not action-required). Hidden: Delays, Suggested Actions (useful, but not what a PM checks first thing). Advanced: none identified - nothing on this screen was found to be genuinely advanced-only content; everything present is either primary or should be one tap away, which is itself a finding (there's no "advanced" tier being abused here, the problem is entirely too much crammed into primary).

Commercial Workspace: Primary should be Contract status and Cash Flow (the two things that answer "is this project financially healthy right now"). Secondary: Milestones, Variations (things a PM actively works with). Hidden: Payment Requests, Payments (useful when specifically needed, not on every visit). Advanced: Commercial Timeline (a genuine audit trail - valuable, rarely the reason someone opened this screen).

---

## 5. Commercial Workspace — Specific Review of CP-01

Directly answering this task's own question: the information hierarchy is not correct as currently structured, and this finding applies equally to the sections CP-01 itself added - the create/edit buttons for Contract, Budget, and Milestones were wired into the existing eight-section, flat layout without asking whether that layout was still right once real create/edit actions existed on it, which is precisely the kind of unexamined accumulation this task exists to catch, including in my own recent work.

Cards, sections, and actions should be reorganized, specifically: Cash Flow (currently mid-screen, noCollapse, always expanded) is arguably the single most important piece of information on this screen and should anchor the top, not sit third. Payment Requests and Payments (currently two separate, always-visible sections) are the same underlying financial event from two angles (money owed, money received) and could be one section with two tabs rather than two full sections. Commercial Timeline, containing the full event audit trail, is genuinely valuable but was confirmed to be the least time-sensitive information on the screen and belongs behind an explicit "View History" action, not stacked at the bottom of every visit.

No implementation is proposed here, per this task's own instruction - this is the recommendation, not the change.

---

## 6. Operations Workspace — Can a PM Immediately Answer "What Needs Attention Today"?

No, not immediately, and the reason is measurable rather than a vague impression: a PM has to choose among six sub-buckets (proposals/overview/overdue/high_priority/awaiting/mine) on the Ops tab, none of which is labeled as "the one to check first," while the Home screen's own My Day section already surfaces overlapping categories (Blocked, High Priority Work) without any stated relationship to the Ops tab's own overdue/high_priority buckets. A new PM has no way to determine, from the product itself, whether checking Home is sufficient or whether Ops has additional information Home doesn't show - confirmed by reading both screens' own data sources, which pull from different underlying calls (my_day versus the Ops tab's own OperationalCenter query) rather than one shared, single source of truth being presented two ways.

---

## 7. Capture Workflow — Site Supervisor

This is the one workspace in Atlas that already matches this task's own target state, and that should be stated plainly rather than manufacturing a problem to fill out the audit. Confirmed directly: Capture is a single, unified screen - not separate Voice/Photo/Text destinations - with photo capture, an optional text note, and (based on the file's own ref-based recording state) voice capture all available without navigating away. Site selection is required before capture, which is a genuine, necessary constraint (an observation has to belong to a site), not unnecessary friction. No reduction is recommended here - this screen was built correctly the first time, and this audit's job is to say so, not to invent a change for the sake of having one in every section.

---

## 8. Click Audit

| Workflow | Current clicks (verified against the actual screen/route) | Recommended | Reasoning |
|---|---|---|---|
| Create Contract | 1 (empty-state button) -> fill form -> save = 2 real actions | Unchanged | Already minimal; CP-01 built this correctly - the empty state is the call to action, not a separate destination. |
| Edit Milestone | Open Commercial -> expand Milestones section (if collapsed) -> tap edit icon -> edit -> save = up to 4 actions depending on section state | Reduce to 2-3 by making Milestones default-expanded (already is) and ensuring the edit icon is reachable without an extra scroll past 3 other sections above it (Section 5's reordering addresses this) | The click count itself is fine; the distance (how much unrelated content sits between landing on the screen and reaching the action) is the real friction, not the number of taps. |
| Capture Observation | Open Capture tab (already active tab in most sessions) -> select site (if not already set) -> capture -> optional note -> submit = 2-4 actions | Unchanged | Already close to minimal; site selection is a real requirement, not overhead. |
| Assign Task | Open item -> tap Assign -> select user -> confirm = 3 actions | Unchanged | Not found to be a problem in this pass; this is a focused, single-purpose flow already. |
| View Timeline | From Project Dashboard -> tap Timeline = 1 action | Unchanged | Already correctly minimal. |

The pattern across this audit is not that individual click counts are high - most flows are already lean. The actual cost is cognitive distance: how much unrelated, simultaneously-visible information sits between opening a screen and finding the thing you came for. That is Section 9's subject directly.

---

## 9. Progressive Disclosure

Always visible (Home): one unified "needs your action" list, replacing the current four-plus separate sections that each partially answer the same question.

Always visible (Commercial): Cash Flow status and Contract status only.

Appear only when needed: Payment Requests/Payments (behind a single "Billing" toggle showing both), Delays/Suggested Actions (genuinely useful, not first-glance material).

Behind "View Details" / "View History": Commercial Timeline's full event audit trail - the data and the capability CP-01 and earlier sprints built are exactly right; only the always-visible placement is the issue.

Move into contextual actions: the distinction between "Blocked" and "Blockers" (Section 1) should not be two lists a user has to reconcile themselves - either merge them into one, clearly-sourced list, or if the underlying data genuinely serves different purposes, label them distinctly enough that no explanation is needed ("Blocked Tasks" versus "Blocked Workflow Steps," for instance) rather than two near-identical words.

This is explicitly about reducing what's shown simultaneously, not removing capability - every data source named above continues to exist and remains reachable; the recommendation is entirely about default visibility, consistent with this task's own instruction.

---

## 10. Cross-Workspace Consistency

Terminology inconsistency, confirmed directly: "Blocked" (Home) versus "Blockers" (Home, same screen, different card) versus "high_priority" (Ops tab's own internal bucket name, user-facing label not independently confirmed to differ) all describe overlapping concepts with different words in different places, sometimes on the same screen.

Section/card pattern inconsistency: the Commercial Workspace uses collapsible Section components throughout; the Home screen uses a mix of MyDayGroup and Card components from two different source files (MyDay.tsx and CreDashboard.tsx) for what a user experiences as the same kind of thing - a titled list of items. This was not found to cause a functional problem, but it means two visually and behaviorally slightly different list patterns exist for the same underlying UI concept, which is exactly the kind of accumulated inconsistency this task's own Section 10 asks to be named.

Filter/bucket naming: Ops tab's buckets (overdue, high_priority, awaiting, mine) and Commercial's own filters (confirmed in the Commercial Workspace screen: a variationFilter with all/pending/approved/rejected/implemented, and a prFilter with all/unpaid/paid/overdue) use overdue as a filter value in two different screens for two different underlying record types, with no shared visual treatment confirmed between them.

---

## Prioritized Improvement Backlog

Ranked by the same principle as every prior document in this engagement's own history - confirmed evidence of user confusion or friction, not aesthetic preference:

1. Reconcile "Blocked" vs. "Blockers" on the Home screen - the clearest, most concrete duplication found, on the single screen every user sees most often.
2. Reorder the Commercial Workspace so Cash Flow leads and Commercial Timeline moves behind an explicit action - directly addresses this task's own Section 5 requirement, no new capability needed, pure reordering of what already exists.
3. Clarify the relationship between Home's "What needs attention" sections and the Ops tab's own overlapping buckets - either through consistent labeling or an explicit statement of what each destination is for, addressing Section 6's core finding.
4. Consolidate Payment Requests and Payments into one Commercial section with two views of the same underlying financial relationship, rather than two separate always-visible sections.
5. Give management a single, clearly-primary landing destination from Profile, rather than five equally-weighted links.

Deliberately not on this list: anything touching Capture (Section 7's own finding is that it doesn't need changing) and anything that would add a new screen, filter, or visual element - consistent with this task's own instruction to reject recommendations that increase complexity even if they improve appearance.

---

## Product Experience Roadmap

This backlog should be sequenced before any further Commercial Phase II work (Section 8's own build plan in CO-01), not interleaved with it - adding GST, retention, and the other Phase II capabilities to a Commercial Workspace that already has an acknowledged information-hierarchy problem would mean building on an already-strained screen rather than a corrected one. The five items above are also, not incidentally, small in engineering scope (reordering, relabeling, consolidating two existing sections into one) - this task's own instruction not to estimate effort without evidence is honored by noting that every item on this list is a rearrangement or a merge of components that already exist and already work, not new capability, which is itself the evidence for why this can and should happen first.
