# ROLE_NAVIGATION_MATRIX.md

| Role | Home | Projects | Capture | Inbox | More | Default Project Phase |
|---|---|---|---|---|---|---|
| Management | Redirects to Executive Hub (unchanged from RC1-HARDENING/PX-01B) | Full list, create allowed | Not shown (tab hidden - not a daily Management task) | Full inbox, all categories | Executive Hub, Portfolio Control Center, Knowledge, User Management, System Info, Reference Portfolio | Review |
| Project Manager | Real dashboard: My Day, blockers, "Continue Working" CTA into the last-viewed project's Workspace | Full list, create allowed | Shown, full capture flow | Full inbox, all categories | Knowledge, System Info (Executive Hub/User Management not shown - admin-gated) | Execute |
| Site Supervisor | Real dashboard: My Day, "Capture Site Update" CTA | List restricted to assigned projects only, create hidden (canManage gated) | Shown, primary daily screen | Full inbox, all categories | Knowledge, System Info only | Execute |
| Client | Client Dashboard (unchanged, separate component - never renders the internal tab-bar Home content) | Shown, but scoped to their own project(s) via existing Client visibility rules - not independently re-verified this phase | Not shown (tab hidden - clients don't capture site updates) | Shown; structurally restricted to their own notifications only (see the Implementation doc's note - no new category filter, existing per-user scoping) | Profile only | Review (the only phase tab a Client's Workspace shell renders - Setup/Plan/Execute/Bill/Close are never in the tab list at all, per Phase 1's own visiblePhases filter) |

## Intentionally restricted destinations, named explicitly

- Executive Hub, Portfolio Control Center, User Management: admin-only, gated in Profile/More by viewRole === 'admin' - unchanged from before this phase, re-confirmed still correct.
- Project creation (/projects/new): gated by canManage (derived from VIEW_PERMS[role].canManageProjects), which is false for Supervisor and Client - re-confirmed unchanged in the moved projects.tsx.
- Setup, Plan, Execute, Bill, Close phases (Workspace shell): never rendered for a Client - Phase 1's own visiblePhases filter removes every phase but Review before the rail even renders, and the phase-content switch below it has no code path that would render UnifiedWorkspace or CommercialWorkspaceScreen for a client role.
- Capture tab: hidden entirely for Management and Client, per TABS_FOR - neither role captures site updates as part of their own daily work.

## A note on what "Client -> Projects" actually means today

This task's own target model gives every role a Projects tab, including Client. Atlas's existing Client-facing experience is a separate, dedicated ClientDashboardScreen component (unchanged by this phase), which already surfaces project progress through its own screens rather than the internal projects.tsx list. Adding projects to the Client's own TABS_FOR entry makes the tab exist and reuses the same underlying /api/projects visibility scoping every other role gets (a Client only ever sees projects they're actually attached to) - but whether the internal projects.tsx list screen itself is the right UI for a Client to browse, versus something dedicated to their own experience, was not redesigned this phase and is named here as a real open question, not silently resolved.
