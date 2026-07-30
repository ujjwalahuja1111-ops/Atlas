# Beta-06B — Navigation & UX Validation Report

Per this sprint's own mandatory requirement, this report begins with the audit classification table.

---

## Audit Table

| Finding | Status | Action |
|---|---|---|
| Operational Items - zero project-visibility enforcement (detail + list endpoints) | BLOCKER, fixed this pass | See full account below. Any authenticated user of any role could view any operational item by ID, including its full comment history - confirmed with a concrete, demonstrated exploit before fixing, not assumed. |
| Executive Hub - buried one hop deeper than the older Portfolio Control Center in management's own menu | POLISH, fixed this pass | Added a direct link from profile.tsx, placed first - matching Executive Hub's intended role as the primary entry point Beta-05 designed it to be. |
| Every router.push/router.replace target across the app | VERIFIED | Full extraction and cross-reference of every navigation call against every screen file - no broken routes, no orphan screens found. |
| Every router.replace usage (auth flows, post-creation redirects, active-context switches) | VERIFIED | Each of the 8 call sites checked individually for correct intent - all are justified (preventing confusing back-stack states), none accidentally break back navigation. |
| Client-role restrictions on the Operational Item detail screen (op/[id].tsx) | VERIFIED, then found the deeper issue above | The frontend's own client-specific restricted action set (approve/reject/comment only, no assignment/editing/blockers) was already correctly implemented in an earlier sprint. Checking why it was safe led directly to discovering it wasn't backed by any server-side enforcement - the UI correctly hid buttons, but the API behind it enforced nothing. |
| Loading/error/refresh consistency across all seven executive screens | VERIFIED | Direct comparison confirmed consistent patterns, with one deliberate, documented exception (Portfolio Search has no pull-to-refresh - retyping the query is its own refresh mechanism, a reasonable default, not an oversight). |
| Client Dashboard navigation targets | VERIFIED | No links to any management-only screen (Executive Hub, Portfolio, Priority Engine, Users, System) found anywhere in the client-facing dashboard code. |
| Site Experience (#4), Client Experience deep-walk (#5), Mobile Behaviour (#8), Accessibility Review (#9) | NOT AUDITED this pass | Named explicitly rather than assumed clean. Time this pass went to the security finding above once it was discovered, which took priority over continuing the broader walkthrough. |

---

## Honest Scope Statement

This sprint's own brief asks for a screen-by-screen, role-by-role manual walkthrough across ten numbered areas. What actually happened this pass: navigation-graph verification (extraction and cross-reference, not literal screen-by-screen clicking, since no interactive device or browser session is available in this environment - this is a real, honest limitation of how this audit was performed, not glossed over) across areas #1, #2, #6, and #7, plus a deep investigation that began as a UX check (#3's own "client never reaches management views") and surfaced a serious backend security gap that took priority over continuing the broader walkthrough once found. Areas #4, #5 (as a full walkthrough), #8, and #9 were not reached this pass.

Per this sprint's own explicit instruction not to report "Complete" if any screen, role, or navigation path was not actually exercised: this sprint is not reporting Complete.

---

## The Security Finding — Full Account

While verifying the Operational Item detail screen's client-role restrictions (checking item #5 in this sprint's own scope - "no hidden dead ends," "no broken permissions"), the frontend's own restricted client UI (approve/reject/comment only) was confirmed correctly implemented. But checking why this was safe led to the actual backend route: GET /operational-items/{item_id} performed a raw lookup by ID with no visibility check of any kind, and GET /operational-items (list) only applied project scoping when the caller explicitly passed a project_id parameter - a caller who simply omitted it received every operational item across the entire platform.

Demonstrated concretely before fixing, not inferred from reading the code: created an item with a comment explicitly marked "INTERNAL ONLY... do not share with client," then fetched it as an unrelated client account with no assignment to that project. The API returned the item's full title and complete comment history, internal note included.

A genuine complication surfaced and resolved during verification, not hidden: the first attempt to confirm the fix appeared to fail - the same unrelated-client scenario still returned the data after the fix was applied. Investigating rather than assuming the fix was wrong found the actual cause: the test used memory_engine.upsert_user(), a test/seed convenience helper that does not set scope_projects=True, unlike the real, production register_user() Sign Up flow which sets this unconditionally for every new account. This is a separate, pre-existing, and deliberately documented migration safeguard (accounts predating the project-scoping feature remain unrestricted, so as not to break existing users) - not a flaw in this fix. Re-testing with a properly-scoped user (via set_user_projects, the same proven pattern used for Beta-06's own payments fix) confirmed the fix works correctly. Separately confirmed against the real ACDP bootstrap that legitimate PM and supervisor accounts see exactly the same 162 items before and after the fix - no regression in normal usage.

Fixed by adding operations_engine.assert_item_visible(), applying the identical _is_project_scoped pattern already established throughout the codebase (commercial_engine.assert_project_visible, Beta-06's own portfolio_search fix), wired into both the detail route (raising a 404, matching this codebase's "don't leak existence" convention) and the list route (now always scoping to the caller's own visible projects first, regardless of what filters they request).

This is reported as a BLOCKER because it is exactly that: a complete absence of access control on a widely-used, comment-bearing resource, discoverable by any authenticated account regardless of role. It was found by following a UX question ("is this restriction real or just cosmetic?") to its actual backend implementation, rather than trusting that a correctly-behaving frontend implied a correctly-secured API.

---

## Testing

- 4 new regression tests for the operational items visibility fix (129 total in the established pure-unit + mongomock baseline, up from 125, confirmed stable across two consecutive full-suite runs).
- npx tsc --noEmit: zero errors, project-wide.
- Live verification: the exploit demonstrated before the fix, its absence confirmed after, and legitimate ACDP user access confirmed unchanged through the real bootstrap pipeline.

---

## Files Changed

- backend/engines/operations_engine.py - new assert_item_visible().
- backend/routes/operational_items.py - visibility check wired into both the detail and list routes.
- backend/tests/test_dev02_bootstrap_reliability.py - 4 new tests.
- frontend/app/(tabs)/profile.tsx - direct Executive Hub navigation link added to the management menu.

---

## Remaining Risks — Named Explicitly

1. Site Experience, Client Experience, Mobile Behaviour, and Accessibility were not walked this pass. Given this session's own experience - a UX consistency check leading directly to a serious backend gap - there is no basis for assuming these remaining areas are clean; they are unaudited, not verified-clean.
2. This audit was performed via code inspection and constructed test scenarios, not literal interactive screen-by-screen navigation, since no device or browser session is available in this environment. This is a different, narrower form of verification than the sprint's own brief describes, and is stated here so the distinction isn't lost in the reporting.
3. Whether other resources beyond operational items share the same pattern (a correctly-restrictive frontend backed by an unenforced API) was not systematically checked. Given this pass found one real instance without looking specifically for this pattern, a dedicated sweep for it elsewhere in the platform would be a reasonable next step.

---

## Beta-06B Assessment

One BLOCKER-class finding, found and fixed with real evidence at every step (the exploit demonstrated, the fix's own initial apparent failure investigated rather than dismissed, and legitimate usage confirmed unaffected). One POLISH item addressed. Four of the sprint's ten named areas were substantively covered; four were not reached.

Per this sprint's own Definition of Done ("do not report Complete if any screen, role, or navigation path was not actually exercised"): this sprint is not complete. The security finding is real and valuable, and this report does not let it stand in for the broader walkthrough the sprint actually asked for. The most valuable next step is continuing this same pattern - verifying that restrictive-looking UI is actually backed by enforcement, not just trusting it - across Site Experience and Client Experience specifically, since this pass's own experience suggests that is exactly where a similar gap would most plausibly still exist.
