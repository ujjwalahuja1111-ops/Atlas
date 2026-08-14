# PX02_IMPLEMENTATION_ROADMAP.md

## 8. Click-Count Reduction Analysis

Every "Current" figure below is grounded in this engagement's own verified work (IN-01's own before/after tables, LIVE-01's own live-exercised flows), not estimated from scratch. Every "Proposed" figure reflects only the navigation changes this document's own Section 3/4 propose - not new capability.

### PM creates a new project
- **Current:** Projects tab → tap New Project → 4-step Wizard (already built, P2-04) → redirect to Workspace. **4 screens, ~12 taps** (Wizard's own fields), **1 decision point** (which team members).
- **Proposed:** unchanged - the Wizard itself is already the reduction this task's predecessor asked for; this roadmap's own navigation changes don't touch project creation further.
- **Expected reduction:** none further available here; already converged.

### Supervisor reports a blocker with photos
- **Current:** Capture tab (already the primary daily screen) → photo/voice/text → submit. **1 screen, ~3-4 taps.** Already optimal, confirmed repeatedly (UX-01 through this task's own Document A).
- **Proposed:** unchanged.
- **Expected reduction:** none available; this flow is already best-in-class against every competitor reviewed in Document A.

### PM responds to a client clarification
- **Current:** Inbox (via Profile → Inbox, 2 taps) → tap notification → navigate to item → respond. **~3 screens, ~6 taps.**
- **Proposed:** Inbox as a top-level tab (Section 3) removes the Profile hop. **~2 screens, ~4 taps.**
- **Expected reduction:** ~33% fewer taps, one fewer screen - the single most direct navigation win in this entire roadmap, since it requires no new engineering beyond a tab-bar change.

### Management identifies projects needing attention
- **Current:** Home (Executive Hub, already correct per IN-01) → Portfolio Control Center → project row → Workspace (IN-01's own fix). **~3 screens, ~4 taps** - already substantially optimized by IN-01.
- **Proposed:** unchanged - Section 3 confirms Executive Hub stays exactly where IN-01 already placed it.
- **Expected reduction:** none further; already converged by a prior package.

### Client approves a variation
- **Current:** Client Dashboard → Variation detail → Approve. **2 screens, ~2 taps.** Already minimal, confirmed correct throughout this engagement.
- **Proposed:** unchanged.
- **Expected reduction:** none available; already optimal.

### PM raises a payment request
- **Current (before IN-01):** Commercial Workspace → scroll to Milestones → find achieved milestone → tap Raise Payment Request → fill form. **~4 taps beyond navigation.**
- **Current (after IN-01, already shipped):** AI Suggestion → deep link directly into the pre-filled form. **1 tap from the Workspace's own AI Suggestions section.**
- **Proposed:** unchanged - this is IN-01's own already-delivered win, cited here for completeness against this task's own required scenario list, not re-claimed as new.
- **Expected reduction:** already achieved; 0% further reduction available from this roadmap.

**Honest summary of this section:** four of six named scenarios are already optimized by prior packages in this engagement (IN-01, UX-01/02). The one genuine, available win this roadmap identifies is promoting Inbox to a top-level tab - a small, low-risk, high-frequency change (clarifications happen often; this task's own Section 6 confirms Inbox is "the highest-value remaining verification gap"). This is stated directly rather than inflating the roadmap's own perceived scope.

---

## 9. Prioritized Implementation Roadmap

### Phase A — Navigation Convergence (2-3 days)
- **Scope:** 5-tab bar (Home/Projects/Capture/Inbox/More), Inbox promoted to a tab, OPS removed as a top-level tab, role-aware Home behavior (already substantially built in RC1-HARDENING/PX-01B - this phase is tab-bar restructuring, not new redirect logic).
- **Files/modules likely affected:** `app/(tabs)/_layout.tsx` (tab bar definition), `app/(tabs)/index.tsx` (Home's own existing redirect logic, unchanged in substance), removal of `app/(tabs)/ops.tsx` as a tab (content moves to More or stays reachable via Workspace).
- **Regression risk:** Low-Medium. Tab bar changes are visible to every user immediately; the risk is entirely in ensuring no existing deep link or `router.push('/(tabs)/ops')` call breaks - a direct grep-and-fix exercise, not a design risk.
- **Pilot impact:** High-visibility, low-engineering-cost - the click-count win in Section 8 (Inbox) ships in this phase.
- **Dependency order:** first - every later phase assumes this navigation shape exists.

### Phase B — Workspace Lifecycle Rail (3-5 days)
- **Scope:** Setup/Plan/Execute/Review/Bill/Close as an explicit visual rail inside the Workspace (built on PL-01's own existing `lifecycle_stage` field - no new state machine), consolidating `projects/[id].tsx`'s own remaining commercial tiles further (RC1-HARDENING's own H1 already did the first pass), extending the Project Feed to include Reality Capture events alongside Commercial events (EX-01's own named gap, closed here).
- **Files/modules likely affected:** `app/workspace/[id].tsx` (the Stage Focus section, extended into a full rail), `app/projects/[id].tsx` (further trim), the Project Feed composition logic (new query merging two existing event sources, no new storage).
- **Regression risk:** Medium. Touches the Workspace screen every internal role already depends on daily - requires the same careful, incremental verification discipline this engagement has used throughout (syntax check after every change, full regression suite before commit).
- **Pilot impact:** Medium - improves clarity of "what stage is this project in," doesn't change what's possible, only how it's organized.
- **Dependency order:** second - depends on Phase A's own navigation shape being settled first, since the Workspace is what Phase A routes PM/Supervisor into.

### Phase C — AI Operational Reporting (3-4 days)
- **Scope:** the Daily Site Report generator (Section 5), composed entirely from existing data - no new capture surface, no new AI engine. A new, small composition function (similar in shape to CM-01's own Since Last Visit composition) plus a export/share screen.
- **Files/modules likely affected:** new `backend/engines/daily_report_engine.py` (pure composition, matching CM-01/WF-01's own established pattern of reusing existing engines rather than duplicating logic), a new route, a new frontend screen for viewing/sharing the report.
- **Regression risk:** Low. This is new, additive surface area - it reads from existing engines but doesn't modify any of them, so the risk of breaking existing behavior is minimal; the main risk is scope creep into building new capture (explicitly out of bounds per this task's own "do not add features" framing for the surrounding sprints).
- **Pilot impact:** High, if built well - this is Atlas's own clearest opportunity to beat every competitor reviewed in Document A on a feature real construction teams already expect (a daily report), using data Atlas already has.
- **Dependency order:** third - benefits from Phase B's own lifecycle rail existing (the report can reference "what stage is this project in"), but doesn't strictly require it.

### Phase D — Collaboration Intelligence (4-6 days)
- **Scope:** Inbox prioritization (Action Required / Waiting For You / Waiting For Others / Escalations), notification grouping (Section 6), all built as read-time query changes over PX-01A's own existing `notifications` collection - no schema change.
- **Files/modules likely affected:** `backend/engines/notification_engine.py` (new grouping/prioritization query functions, additive), `frontend/app/notifications.tsx` (new sections, reusing the existing card component).
- **Regression risk:** Medium. Notification display logic is already live and depended on daily (PX-01A/B); grouping/collapsing behavior must be tested carefully to avoid ever hiding a genuinely new, actionable notification behind a collapsed group - the single most important thing to verify live before shipping this phase.
- **Pilot impact:** High for PM/Management specifically - this is the phase that most directly prevents notification fatigue as pilot usage scales past a handful of test scenarios into real daily volume.
- **Dependency order:** fourth, and the most independent of the four phases - could be sequenced before Phase C if collaboration fatigue proves to be the more urgent pilot risk once real usage begins.

### Cross-phase engineering discipline, stated once
Every phase above follows the same rule this entire engagement has enforced: no new backend engine, no new collection unless genuinely unavoidable (none of the four phases require one), full regression suite passing before any commit, and a live-API verification of the specific new behavior before considering a phase complete - matching LIVE-01's own established verification standard, not a lower bar for being "just a roadmap."
