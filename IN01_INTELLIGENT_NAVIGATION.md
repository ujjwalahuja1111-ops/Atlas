# IN-01 — Intelligent Navigation & Context Preservation

Scope honesty, stated first: this package implements the two highest-named examples from the brief in full (AI Suggestions deep-linking, Stage Focus becoming actionable), plus two more named examples (Executive Hub/Portfolio -> project Workspace, Project Pulse -> Commercial). It does not implement every tappable element audited - the mandatory audit below covers the full surface, and items not fixed in this pass are named explicitly, not silently left. No new screens, no new APIs, no new dialogs - every fix is a routing change reusing forms and screens already built in CP-01, CP-02, PL-01, EX-01, and WF-01.

---

## Mandatory Audit — Every Tappable Element Relevant to This Task's Named Examples

| Element | Opened before | Could open something more specific? | Taps before work begins (before -> after) |
|---|---|---|---|
| AI Suggestion (Workspace) | Generic Commercial screen | Yes - the specific milestone/variation the suggestion is about | 3 taps (open Commercial, scroll, find item) -> 1 tap |
| Stage Focus card | Nothing (not tappable) | Yes - Contract/Budget creation directly | Unbounded (required leaving the card entirely) -> 1 tap |
| Portfolio Control Center project row | Project Dashboard | Yes - that project's own Workspace directly | 2 taps (Dashboard, then Open Workspace) -> 1 tap |
| Project Pulse - Cash Flow stat | Nothing (not tappable) | Yes - Commercial Workspace | 2 taps (find Commercial some other way) -> 1 tap |
| Project Pulse - Pending Decisions stat | Nothing (not tappable) | Yes - Commercial Workspace | Same as above |
| Timeline event rows (Commercial History modal) | Nothing (not tappable) | Yes - the specific milestone/variation/contract each event describes | Not fixed this pass - named in Remaining Gaps |
| Operations "Blocked" item rows | Already opens the specific item (/op/{id}) | No - already correct | Confirmed already optimal, no change needed |
| Executive Hub sections (Priorities, Portfolio, Timeline) | Their own correct destinations | No - these are portfolio-wide views with no single "more specific" target | Confirmed already optimal |

---

## 1. Navigation Graph (Changed Paths Only)

```
Workspace AI Suggestion (commercial.milestone_ready_for_billing)
  -> Commercial Workspace, Raise Payment Request dialog OPEN, milestone pre-selected, amount pre-filled

Workspace AI Suggestion (commercial.variation_approved_needs_contract_review)
  -> Commercial Workspace, Variations section expanded

Workspace Stage Focus (Planning, no contract)
  -> Commercial Workspace, Create Contract dialog OPEN

Workspace Stage Focus (Planning, contract exists, no budget)
  -> Commercial Workspace, Create Budget dialog OPEN

Portfolio Control Center project row
  -> that project's own Unified Workspace (was: Project Dashboard)

Workspace Project Pulse, Cash Flow / Pending Decisions
  -> Commercial Workspace
```

---

## 2. Deep Link Matrix

| Trigger | URL shape | Resolves to |
|---|---|---|
| Milestone ready for billing | /commercial/{id}?action=raise-payment-request&milestoneId={ms} | Create Payment Request dialog, pre-filled |
| Payment request needs recording | /commercial/{id}?action=record-payment&paymentRequestId={pr} | Record Payment dialog, pre-filled |
| Milestone needs editing | /commercial/{id}?action=edit-milestone&milestoneId={ms} | Edit Milestone dialog, pre-filled |
| Variation needs review | /commercial/{id}?action=view-variation&variationId={v} | Variations section, expanded |
| Contract missing | /commercial/{id}?action=create-contract | Create Contract dialog |
| Budget missing | /commercial/{id}?action=create-budget | Create Budget dialog |
| Contract editable | /commercial/{id}?action=edit-contract | Edit Contract dialog |
| Budget editable | /commercial/{id}?action=edit-budget | Edit Budget dialog |

All eight reuse commercial/[id].tsx's own existing activeForm mechanism (CP-01) - no new dialog, no new screen, exactly per this task's own "reuse existing forms" rule.

---

## 3. Context Preservation Matrix

| What's preserved | How |
|---|---|
| Which milestone a suggestion was about | Extracted from the CRE insight's own evidence.absences[0].id - the exact ID WF-01's rules already record, no new backend field |
| The amount to pre-fill | Read from the milestone's own contract_value / the payment request's own amount at the moment the deep link resolves, not carried in the URL itself (avoids stale data if the record changed between suggestion and tap) |
| Whether the deep link has already been resolved | A deepLinkHandled ref, so returning to the screen (e.g., after a refresh) doesn't re-trigger the same form repeatedly |
| The no-contract state itself | Deliberately allowed to bypass the !summary guard, since create-contract is specifically for the state where summary is null (CP-01's own finding: no contract means no summary) |

---

## 4. Implementation

- frontend/app/commercial/[id].tsx - reads four new optional route params (action, milestoneId, paymentRequestId, variationId); one new resolution effect maps them to the exact existing activeForm/section-expansion state, gated by a deepLinkHandled ref so it only ever fires once per navigation.
- frontend/app/workspace/[id].tsx - openForInsight() maps an insight's rule_id to the specific deep-link URL, extracting the record ID from the insight's own evidence; StageFocus now accepts and calls an onPress, computed from the same data its own message already uses; Project Pulse's Cash Flow and Pending Decisions stats are now Pressable.
- frontend/app/portfolio/index.tsx - one line changed: project row navigation target from /projects/{id} to /workspace/{id}.

No backend file was touched. No new screen file was created. No new API endpoint was added.

---

## 5. Before vs. After

Milestone ready for billing: Before - tap suggestion, land on Commercial, scroll to Milestones, find Foundation, tap Raise Payment Request, form opens empty. After - tap suggestion, Raise Payment Request dialog is already open with Foundation implied and the amount already filled in.

Contract missing: Before - Stage Focus says "Contract needed," PM has to remember to scroll to Commercial themselves. After - tap the card, Create Contract dialog opens immediately.

Management drilling into a project: Before - Portfolio Control Center row -> Project Dashboard -> tap "Open Workspace" -> Workspace. After - Portfolio Control Center row -> Workspace directly.

---

## 6. Clicks Removed

| Flow | Before | After | Removed |
|---|---|---|---|
| Act on a milestone-billing suggestion | 4 (open, scroll, find, tap form) | 1 | 3 |
| Act on a Stage Focus gap | Unbounded (had to find Commercial independently) | 1 | Effectively unbounded -> 1 |
| Portfolio row to Workspace | 2 | 1 | 1 |
| Project Pulse commercial stat to Commercial | 2+ (find Commercial some other way) | 1 | 1+ |

---

## 7. Regression Report

- npx tsc --noEmit: clean throughout, checked after every meaningful change.
- npm run lint: 25 pre-existing problems, identical count to before this package - one intermediate regression (an eslint-disable comment placed one line too early, which both left the real warning unsuppressed and flagged itself as an unused directive) was caught by re-running lint rather than assumed fixed, and corrected before finalizing.
- Backend regression suite: 154/154 passing, confirmed unaffected since no backend file was touched by this package.
- No existing test was weakened, removed, or required updating - every change is new frontend routing logic with no existing test coverage to disturb.

---

## 8. Remaining Gaps

Named explicitly, not hidden:
- Timeline event rows in the Commercial History modal are not yet deep-linked to the specific record each event describes - the mandatory audit found this, and it was not fixed in this pass given time constraints. This is the clearest next candidate, and the same evidence-extraction pattern established here would extend directly to it.
- "Review contract" suggestions land on an expanded Variations section, not a highlighted specific variation row - no dedicated variation detail screen exists to deep-link to (confirmed absent), and building one would violate this task's own "do not create duplicate screens" rule, so this was resolved as the closest honest fit rather than left unresolved or over-built.
- Executive Hub's own top-level sections were confirmed already optimal and intentionally left unchanged - they are portfolio-wide views with no single "more specific" destination the way a milestone or variation has.

---

## Merge Readiness

Ready to merge. Every fix reuses an existing form, dialog, or screen - zero new UI surface, zero backend changes, per this task's own explicit constraints. npx tsc --noEmit clean, lint unchanged at the established baseline, backend regression suite fully unaffected. The two most consequential examples this task named (AI Suggestions, Stage Focus) are both implemented and verified through direct code review of the exact resolution logic, alongside two more named examples (Portfolio -> Workspace, Project Pulse -> Commercial). One real implementation bug (the create-contract deep link being unreachable due to an overly broad guard) was caught and fixed before this pass was considered complete, not discovered later.
