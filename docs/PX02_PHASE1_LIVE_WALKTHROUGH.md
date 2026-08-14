# LIVE WALKTHROUGH NOTES

## The Same Honest Limitation as LIVE-01, Stated First

This environment has no physical device, simulator, or deployed Atlas instance reachable by a browser tool — confirmed again this session by checking for any change to `.env` configuration since LIVE-01 (none exists). This task's own instruction anticipates exactly this: "If the environment prevents UI verification, clearly mark those items as BLOCKED rather than assuming success." Every item below is marked precisely that way where it applies — nothing here is rounded up to a pass because the underlying code looks correct.

What *was* done, real and verifiable: a live backend check (Section immediately below), using the same real seeded Reference Portfolio accounts LIVE-01 used, confirming that every API call the new shell's own data-loading logic makes actually succeeds against a real, freshly-bootstrapped environment.

### Live backend check performed
Logged in as PM (9800000002, Ananya Sharma) and confirmed all 6 API calls the shell's own `load()` function makes — `/api/projects`, `/api/sites`, `/api/projects/{id}/commercial/summary`, `/api/projects/{id}/explain-health`, `/api/projects/{id}/insights`, `/api/projects/{id}/since-last-visit` — each returned `200` against a real project from the freshly bootstrapped Reference Portfolio. This confirms the shell's own data dependencies are real and reachable; it does not confirm the shell renders or navigates correctly on screen.

---

## PM Walkthrough

| Step | Result |
|---|---|
| Opens project | **BLOCKED** — requires a device to confirm the tap-through actually lands on the new shell |
| Lands in Execute | **BLOCKED** — the role-aware default-phase logic (`DEFAULT_PHASE_FOR_ROLE['pm'] = 'execute'`) was read and confirmed correct in the code, but was not visually exercised |
| Switches to Bill | **BLOCKED** — same reasoning; the tab-press handler was read and confirmed to set state correctly, not visually exercised |
| Switches back to Execute | **BLOCKED** — same reasoning |

## Management Walkthrough

| Step | Result |
|---|---|
| Opens project | **BLOCKED** |
| Lands in Review | **BLOCKED** — `DEFAULT_PHASE_FOR_ROLE['admin'] = 'review'` confirmed correct in code, not visually exercised |
| Can navigate all phases | **BLOCKED** — the visibility logic (`viewRole === 'client' ? [...] : PHASES`) confirms Management gets the full, unrestricted rail in code; not visually exercised |

## Client Walkthrough

| Step | Result |
|---|---|
| Opens project | **BLOCKED** |
| Lands in Review | **BLOCKED** — same default-phase logic as above, not visually exercised |
| Cannot access internal operational details | **PARTIALLY VERIFIED** — the shell's own code confirms a client never receives phase tabs for Setup/Plan/Execute/Bill/Close (`visiblePhases` filters to Review-only before rendering the rail at all, and the phase-content switch below it never renders `UnifiedWorkspace` or `CommercialWorkspaceScreen` for a client), so there is no rendering path in this new code that would expose those screens to a client. This was confirmed by reading the actual conditional logic, not assumed — but whether a client could still reach those screens by some other means (a stale deep link, e.g. typing `/projects/[id]/workspace` and then... there is no separate route per phase to type into, since phase selection is in-memory state, not a URL segment) was not tested live. |

---

## Honest Summary

Every claim in this document is either a real, live backend check (the API-reachability check above) or a code-reading confirmation stated as exactly that, never as a substitute for seeing it work on screen. Nothing in the three walkthroughs above is marked VERIFIED, because nothing was. This matches this task's own explicit instruction precisely, and mirrors LIVE-01's own established precedent for this exact class of limitation.
