# WORKSPACE_LIFECYCLE_IMPLEMENTATION.md

## Files Added

- `frontend/app/projects/[id]/workspace/index.tsx` — the shell itself: header, lifecycle rail, phase switching, role-aware default phase, data loading.
- `frontend/app/projects/[id]/workspace/phases/SetupPhase.tsx` — new, lightweight.
- `frontend/app/projects/[id]/workspace/phases/PlanPhase.tsx` — new, lightweight.
- `frontend/app/projects/[id]/workspace/phases/ReviewPhase.tsx` — new, lightweight.
- `frontend/app/projects/[id]/workspace/phases/ClosePhase.tsx` — new, lightweight, mostly "Coming Soon."

**Execute and Bill have no new phase file** — they embed the existing `UnifiedWorkspace` (`workspace/[id].tsx`) and `CommercialWorkspaceScreen` (`commercial/[id].tsx`) components directly, unmodified. Both read their own `id` via `useLocalSearchParams()`, which resolves from the current route's dynamic segments regardless of which file defined the route — this let the shell reuse roughly 1,780 lines of existing, already-verified functionality with zero changes to either file, matching this task's own explicit "reuse existing screens and components" instruction as literally as possible.

## Files Modified

- `frontend/app/projects/index.tsx` — one line: the project list's own "tap a project" handler now navigates to `/projects/[id]/workspace` instead of `/projects/[id]`.
- `frontend/app/portfolio-search.tsx` — two lines: Projects and Sites search results now navigate into the new shell too, for the same reason.

No backend file was touched. No existing screen file (`workspace/[id].tsx`, `commercial/[id].tsx`, `projects/[id].tsx`) was modified.

## Phase-to-Component Mapping

| Phase | Source | Reuse level |
|---|---|---|
| Setup | New `SetupPhase.tsx` | Reuses existing `apiListProjects`/`apiListSites`/`apiGetCommercialSummary` data, new lightweight display |
| Plan | New `PlanPhase.tsx` | Reuses `summary.milestones`/`summary.variations` already fetched by the shell — zero new API calls |
| Execute | Existing `UnifiedWorkspace` component, embedded directly | Full reuse, zero modification |
| Review | New `ReviewPhase.tsx` | Reuses `apiExplainHealth`/`apiListInsights`/`apiGetSinceLastVisit` — all pre-existing engines (CRE, CM-01) |
| Bill | Existing `CommercialWorkspaceScreen` component, embedded directly | Full reuse, zero modification |
| Close | New `ClosePhase.tsx` | Reuses `apiArchiveProject` (the one real action); everything else is an honest placeholder |

## Temporary Placeholders

Stated explicitly, per this task's own instruction not to fabricate functionality:

- **Plan → Dependencies:** "Dependency tracking planned for a future phase" — the exact wording this task itself specifies, since no dependency engine exists in Atlas today.
- **Close → Snag/Punch List, Handover Checklist, Lessons Learned:** all three shown as "Coming Soon" cards. None of the three has any backing data model in Atlas — this was confirmed by searching the codebase before writing the placeholders, not assumed.
- **Setup → Client field:** shown as "Not set — no client field exists on Project today," rather than a blank or fabricated value. This is a real, pre-existing gap (first surfaced in PX-01B's own Wizard work, where "Client Name" is collected but never persisted) — repeated honestly here rather than hidden.

## Backward-Compatibility Decision

This task's own "preferred" approach was an automatic redirect from `/projects/[id]` to `/projects/[id]/workspace`. **This implementation deliberately does not do that**, and the reasoning is worth stating plainly: `projects/[id].tsx` is not just a legacy display screen — it is the actual, working host for the project **edit** modal (name/location/image, archive/unarchive, site management). Auto-redirecting away from it would have made that functionality unreachable, which would have meant either rebuilding edit inside the new shell (a "redesign," which this task explicitly says not to do for unrelated screens) or genuinely breaking a working feature. Instead: `/projects/[id]` is left completely untouched and fully reachable — the new shell's own Setup phase links directly to it via an "Edit Project" button — while every *new* navigation path into a project (the project list, search results) now goes straight to the new shell, which is what actually delivers this task's own success criterion of "one obvious workspace entry point" for anyone starting fresh. Existing deep links to `/projects/[id]`, `/workspace/[id]`, and `/commercial/[id]` all continue to work exactly as before, unmodified.
