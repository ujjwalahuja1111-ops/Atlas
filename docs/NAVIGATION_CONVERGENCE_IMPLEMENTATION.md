# NAVIGATION_CONVERGENCE_IMPLEMENTATION.md

## Files added

None — every screen this phase needed already existed; the work was relocation and reconfiguration, not new screen construction.

## Files moved (URL-preserving)

- `frontend/app/projects/index.tsx` → `frontend/app/(tabs)/projects.tsx`. Same `/projects` URL either way (Expo Router groups don't affect the path), now also registerable as a tab. Confirmed zero relative imports before moving, so nothing needed adjusting inside the file.
- `frontend/app/notifications.tsx` → `frontend/app/(tabs)/notifications.tsx`. Same `/notifications` URL, same reasoning. This preserves every existing deep link into it (PX-01A/B's own notification cards navigate here by `entity_id`, unaffected).

## Files modified

- `frontend/src/roles.ts` — `TabDef` and `TABS_FOR` rewritten to the target 5-tab model (Home/Projects/Capture/Inbox/More) per role. Ops removed from every role's visible tab list.
- `frontend/app/(tabs)/_layout.tsx` — registers `projects` and `notifications` as new `Tabs.Screen` entries; `ops` kept registered but permanently hidden (`href: null`) rather than removed, so its route stays reachable. Added a 30-second polling unread-count fetch for the Inbox tab's own badge (`tabBarBadge`).
- `frontend/app/(tabs)/index.tsx` — Home's own PM/Supervisor auto-redirect (built in RC1-HARDENING/PX-01B) removed; replaced with real dashboard content plus an explicit CTA (`ContinueWorkingCta` for PM, `CaptureSiteUpdateCta` for Supervisor), per this task's own Section 1 requiring dashboard content and a named button rather than an instant bounce. Management's own redirect to Executive Hub is unchanged.
- `frontend/app/commercial/[id].tsx` — added the legacy-route convergence banner ("Bill Phase • Open Full Workspace"), navigating to `/projects/[id]/workspace`.

## Old navigation structure

4 tabs: Home, Ops, Capture, Profile (varying by role — Client had only Home/Profile; Supervisor had Home/Capture/Ops/Profile). Notifications and Projects were both reachable only through Profile or Home, never as top-level destinations.

## New navigation structure

5 tabs for every role except Client (who gets 4 — no Capture, matching the original tab set's own reasoning that clients don't capture site updates): Home, Projects, Capture (non-client), Inbox, More (the renamed Profile tab — same file, same content, relabeled). Ops is no longer a visible tab for any role.

## Route redirects introduced

None new. Management's pre-existing Home → Executive Hub redirect (RC1-HARDENING/PX-01B) is unchanged. PM/Supervisor's pre-existing Home → Workspace auto-redirect was *removed* this phase (a deliberate behavior change, not a redirect addition — see below).

## A note on a deliberate behavior change, not just a rename

This task's own Section 1 asks for Home to show real dashboard content per role, with a named CTA button ("Continue Working," "Capture Site Update") — not an instant redirect. RC1-HARDENING/PX-01B had built exactly the opposite: Home immediately bounced PM/Supervisor away before they could see anything. Since this task explicitly specifies dashboard content and a button, the redirect was removed for PM/Supervisor (Management's redirect stays, since Section 1's own Management content list is already what Executive Hub shows). This is called out explicitly here because it reverses a prior package's own design decision — not silently changed without acknowledgment.

## Temporarily retained legacy entry points

- `/(tabs)/ops` — fully functional, just not tab-bar-visible. No banner was added here (see the note below on why).
- `/commercial/[id]` — fully functional, now carries the "Bill Phase • Open Full Workspace" banner.
- `/(tabs)/index` (Home's own per-project Timeline view, reached via "Timeline & Events" from the legacy `/projects/[id]` screen) — unchanged, no banner added this phase (time-constrained; named as remaining scope, not silently dropped).

## A genuine mismatch between this task's own example routes and Atlas's real ones, stated honestly

This task's Section 6 names `/projects/[id]/timeline`, `/projects/[id]/ops`, and `/projects/[id]/commercial` as legacy routes needing banners. None of these are Atlas's actual current routes — the real ones are `/(tabs)` (Home's own Timeline view, not project-scoped by URL), `/(tabs)/ops` (portfolio-wide, no single project in scope), and `/commercial/[id]` (genuinely project-scoped). The banner was only added where it could honestly apply: `/commercial/[id]`, which has a real `id` in scope. `/(tabs)/ops` was deliberately skipped rather than forced — it shows operational items across every project the user can see, with no single project context a banner could link to, and adding one would have required either fabricating a project context that doesn't exist or picking an arbitrary project, neither of which serves the user.

## Inbox category restriction for Client — a structural observation, not a new filter

This task's Section 8 asks that a Client "cannot see Inbox categories containing internal operational activity." No explicit category filter was added to the Inbox screen for this — none was needed, because the underlying `notification_engine.list_notifications(user_id)` is already scoped per-user, and a Client is structurally never the target of an assignment, status-change, or clarification-requested notification (those are always addressed to whoever is assigned an operational item, which a Client never is). This is a real, working restriction, but it comes from the existing per-user data model, not from a category allowlist built this phase — stated explicitly so it isn't mistaken for a new access-control mechanism that doesn't exist.
