# DUPLICATION_AUDIT.md

Audited projects/[id].tsx, workspace/[id].tsx, and commercial/[id].tsx for overlapping KPI blocks before adding any new UI, per this task's own explicit instruction.

## Duplicated Information Discovered

| Information | Where it appeared | Canonical owner selected | What was removed | What was intentionally retained |
|---|---|---|---|---|
| Commercial KPIs (Contract Value, Cash Flow) | projects/[id].tsx's own tile grid (already trimmed once by RC1-HARDENING's own H1, from 9 tiles to 2) and full detail in commercial/[id].tsx | Bill phase (embeds commercial/[id].tsx directly) | Nothing further removed from projects/[id].tsx this pass - it was already trimmed in RC1-HARDENING and touching it further risked exceeding this task's own "do not redesign unrelated screens" boundary | The 2-tile snapshot already in projects/[id].tsx, plus a new, separate read-only snapshot in Setup - see note below |
| Project Health | workspace/[id].tsx's own Health Strip | Review phase | Nothing removed - Health Strip stays inside the embedded Execute/UnifiedWorkspace component unmodified | A header-level health dot (green/amber/red) now shows in the shell's persistent header, matching this task's own "Header Indicator Only" rule for phases other than Review |
| Pending Approvals | workspace/[id].tsx's own Today's Mission section | Plan phase (new, lightweight) | Nothing removed from Execute - Today's Mission already surfaces approvals as part of daily operational triage, which is a different audience/purpose than Plan's own approval tracking | Execute's own Today's Mission stays as-is |
| Recent Events | workspace/[id].tsx's own Project Pulse / Since Last Visit card | Review phase (new "Recently Changed" section, reusing the same apiGetSinceLastVisit call) | Nothing removed from Execute | Execute's own recent-activity framing (operational, "what do I need to do today") stays distinct from Review's own framing ("what changed, what's at risk") |
| Blockers | workspace/[id].tsx's own Today's Mission | Execute (embedded, unchanged) | Nothing removed | A blocker/risk count could be surfaced in Review in a future pass - not built this phase, since Review's own AI Insights section already surfaces risk-relevant items without a dedicated duplicate counter |
| Team Assignments | No dedicated summary view exists anywhere today - confirmed by search, not assumed | Setup (new, lightweight - currently just a placeholder note, since no per-project "team" API exists) | N/A - there was nothing to remove | N/A |

## A Note on the One Genuine New Duplication This Phase Introduces

Setup's own "Commercial Baseline" section (Contract Value, Budget) is, strictly speaking, a second read-only snapshot alongside projects/[id].tsx's own existing 2-tile snapshot - both now show roughly the same two numbers. This was a deliberate choice, not an oversight: this task's own Section 2 explicitly asks Setup to display a "Commercial baseline summary (read-only snapshot only)," and Section 3's own duplication table explicitly allows "small read-only snapshot" as a permitted exception to the single-owner rule. Two small snapshots (Setup, and projects/[id].tsx's own pre-existing one) alongside one canonical detailed owner (Bill) is within the letter of this task's own rules - but it is named here explicitly rather than left for someone else to discover, since a future pass may reasonably decide projects/[id].tsx's own snapshot should be removed once the new shell is the only entry point anyone actually uses.

## What Was Not Touched, and Why

projects/[id].tsx itself was not further trimmed this phase, beyond what RC1-HARDENING already did. Reasoning: this task's own constraints explicitly forbid "redesign unrelated screens," and further trimming a screen that's about to become secondary (per the backward-compatibility decision in the Implementation doc) risked spending this phase's limited scope on a screen users will visit less often going forward, rather than on the new shell itself.
