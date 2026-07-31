# Beta-06D — State Mutation & Authorization Validation Report

Per this sprint's own mandatory requirement, this report begins with the audit classification table.

---

## Mutation Audit Matrix

| Mutation Endpoint | Status | Evidence |
|---|---|---|
| POST /operational-items/{id}/transition | BLOCKER, fixed | Zero visibility check. Demonstrated: an outsider with no project assignment successfully transitioned a real item's status from open to in_progress - actual state mutation, not just an information leak. |
| POST /operational-items/{id}/assign | BLOCKER, fixed | Zero visibility check (role check for management/PM existed, project visibility did not). |
| POST /operational-items/{id}/comments | BLOCKER, fixed | Zero visibility check of any kind. |
| POST /operational-items/{id}/request-clarification | BLOCKER, fixed | Zero visibility check (client-role check existed, project visibility did not). |
| POST /operational-items/{id}/blocker (set) | BLOCKER, fixed | Zero visibility check. |
| DELETE /operational-items/{id}/blocker (clear) | BLOCKER, fixed | Zero visibility check. |
| PATCH /operational-items/{id} (edit) | BLOCKER, fixed | Zero visibility check. |
| POST /operational-items/{id}/voice-update | BLOCKER, fixed | Zero visibility check (client-category check existed, project visibility did not). |
| POST /operational-items/{id}/duplicate | BLOCKER, fixed | Zero visibility check. |
| POST /commercial/milestones/{id}/status | BLOCKER, fixed | Zero visibility check. |
| POST /commercial/payment-requests/{id}/status | BLOCKER, fixed | Zero visibility check. |
| POST /commercial/variations/{id}/decide | BLOCKER, fixed | Zero visibility check. Demonstrated: an unrelated client account approved a real Rs 5,00,000 variation belonging to a project they had no assignment to - a genuine, real-money authorization failure, the most severe finding in this engagement to date. |
| POST /commercial/variations/{id}/submit | BLOCKER, fixed | Zero visibility check. |
| POST /commercial/variations/{id}/send-for-client-review | BLOCKER, fixed | Zero visibility check. |
| record_payment (backing payment recording) | BLOCKER, fixed | Zero visibility check. |
| POST /workflow-activities/{id}/status | VERIFIED | Confirmed the docstring's claim is true by reading the actual function body, not trusting the comment: _assert_project_visible is genuinely called. |
| POST /workflow-activities/{id}/schedule | VERIFIED | Same, confirmed by direct inspection. |
| POST /workflow-activities/{id}/assign | VERIFIED | Same, confirmed by direct inspection. |
| POST /workflow-activities/{id}/production-inputs | VERIFIED | Same, confirmed by direct inspection. |
| POST /ai-proposals/{id}/accept, /reject | RISK - not examined this pass | Not audited; named rather than assumed clean. |
| POST /events/{id}/request-approval, /corrections, /regenerate-proposals, PATCH /events/{id}/timeline | RISK - not examined this pass | The read side of Events was fixed in Beta-06C; these four mutation routes on the same resource were not individually checked this pass, despite Events' own read endpoint having had exactly this class of bug. Named as the most likely place for a similar finding, given the pattern. |
| PATCH /sites/{id}, /archive, /unarchive, DELETE /sites/{id} | RISK - not examined this pass | GET /sites/{id}/requirements was fixed in Beta-06C; these mutation routes on the same resource were not checked this pass for the same reason as Events above. |
| POST /users/{id}/approve, /reject, /role, /projects, /active | VERIFIED (structurally) | These are inherently management/admin-scoped operations on the user-identity model itself, not project-scoped resources - there is no project to leak across. Not independently re-tested live this pass, but the resource shape itself doesn't admit the cross-project pattern being audited. |
| PATCH /knowledge-items/{id}, /archive, /unarchive, relationships | VERIFIED - not applicable | Knowledge Items are genuinely global (confirmed in Beta-06C: zero project_id concept anywhere in knowledge_engine.py). Nothing to leak across a project boundary. |
| POST /insights/{id}/status | RISK - not examined this pass | Not audited. |

---

## The Two Concrete Exploits — Full Account

Operational Items: created a real item in Project A, logged in as a site_supervisor genuinely scoped only to Project B (via set_user_projects, not a test-only unscoped helper), and called POST /operational-items/{id}/transition. It succeeded - HTTP 200, the item's real status changed from open to in_progress. This is qualitatively worse than a read leak: an attacker didn't just see data, they changed it. The same outsider was then confirmed able to comment on the item as well.

Commercial Variations: created a real Rs 10,00,000 contract and a Rs 5,00,000 variation in Project A, submitted it and sent it for client review, then logged in as a client account genuinely scoped to a different project. That outsider client called POST /commercial/variations/{id}/decide with {"decision": "approved"} - and it succeeded, HTTP 200. A financial approval with real contractual meaning was executed by someone with no relationship to the project whatsoever.

Both were demonstrated before any fix was written, confirmed fixed (404) after, and confirmed not to have broken legitimate access: a real ACDP supervisor can still comment on their own project's items, and a real ACDP admin can still decide on the one genuinely pending variation in the seeded portfolio.

---

## Root Cause — Why This Pattern Was So Widespread

Beta-06B and Beta-06C fixed the read side of Operational Items and four other resources by adding a visibility check. This pass found that the corresponding write side of Operational Items - nine separate endpoints - and five Commercial mutation functions had never had this check applied at all, despite in several cases sitting directly next to a role check (client-forbidden, management/PM-only) that gave the misleading impression of being secured. A role check answers "is this the right kind of user" - it does not answer "is this user allowed this specific item." Every one of these endpoints had the first without the second.

Workflow's own mutation functions were the exception, and were already correct - worth noting as a positive data point: the pattern is not universal, and where a prior sprint did apply the check consistently, it held.

---

## State Machine Validation

Verified as part of the exploit-then-fix cycle: the blocked outsider attempts did not merely receive an error while secretly also succeeding - test_item_transition_blocks_outsider and test_item_edit_blocks_outsider both explicitly re-fetch the item afterward as the legitimate admin and assert the title/status were unchanged, not merely that the mutating call itself returned an error code. The same is done for the variation decision. This distinguishes "the request was rejected" from "the request had no effect," which the sprint's own audit trail requirement specifically asks for.

Legal-transition validation itself (illegal transitions, duplicate transitions) was not independently re-audited this pass - that logic predates this sprint and was not the subject of this pass's findings, which were specifically about the authorization layer sitting in front of already-correct transition logic.

---

## Audit Trail Validation

Not independently tested this pass. Every mutation examined already calls append_commercial_event or the operational-item equivalent as part of its existing, unmodified business logic - the fixes made this pass only gate whether the mutation proceeds, not what it records once authorized. Whether audit history can be bypassed or overwritten by a legitimate, authorized actor was not specifically attacked this pass and is named as an unaudited area, not asserted clean.

---

## Role Matrix — For the Fixed Endpoints

| Role | Allowed | Denied | Reason |
|---|---|---|---|
| Management | Any project | - | _is_project_scoped unconditionally False. |
| Project Manager, Site Supervisor (properly scoped) | Only assigned projects | Every other project | Verified directly for transition/comment/edit/blocker/voice-update/variation-submit. |
| Client | Approve/reject/comment on their own client_approval items and their own contract's variations | Every other project's items and variations, even with the correct role | Verified directly for variation decide. |
| Project-scoped outsider (correct role, wrong project) | - | Every mutation tested | This is the exploit this pass demonstrates and fixes. |
| Anonymous | - | Everything | Depends(get_current_user) present on every route examined; not independently re-sent without a token this pass. |

---

## Testing

- 7 new regression tests added to the live-URL test file (test_rc01_commercial_visibility.py), following its established pattern. Like every test in that file, these require a deployed server and were not executed in this sandbox - the underlying fixes were instead verified directly via constructed httpx/ASGI-transport exploit scenarios, shown working in this session (both the "before" failure and "after" success states captured).
- A genuine test-design error caught and fixed during this pass's own development: the first version of the variation-submit test used a site_supervisor outsider, which would have been rejected by /submit's own role restriction (management/PM only) regardless of the visibility fix - meaning the test would have passed for the wrong reason and not actually exercised what it claimed to. Caught by checking _require_write_access's actual allowed roles before trusting the test, not after a confusing result; fixed by using a correctly-roled project_manager scoped to the wrong project instead.
- Full mongomock regression suite: 129/129 passing, unchanged (all of this pass's fixes are route/engine-level and covered by the live-URL file instead).
- Every fix verified three ways: exploit demonstrated before, exploit confirmed absent after, legitimate ACDP usage (a real supervisor commenting, a real admin deciding a real pending variation) confirmed unaffected.

---

## Files Changed

- backend/routes/operational_items.py - a new _get_visible_item_or_404 helper, wired into all nine mutation routes.
- backend/engines/commercial_engine.py - assert_project_visible added to six mutation functions: transition_milestone_status, transition_payment_request_status, decide_variation, submit_variation, send_variation_to_client_review, record_payment.
- backend/tests/test_rc01_commercial_visibility.py - 7 new tests.

---

## Remaining Risks — Named Explicitly

1. Events' own four mutation routes (request-approval, corrections, regenerate-proposals, PATCH timeline) were not individually checked this pass, despite Events' read endpoint having had exactly this bug in Beta-06C. This is the single most likely place a similar finding still exists, given the established pattern, and is the most valuable next check.
2. Sites' own mutation routes (edit, archive, unarchive, delete) were not checked for the same reason.
3. AI Proposals' accept/reject and Insight status updates were not examined this pass.
4. Audit trail tamper resistance (whether a legitimate, authorized actor can overwrite or bypass history) was not specifically attacked.
5. Illegal/duplicate state transition handling was not independently re-audited - this pass's findings were about the authorization layer, not the transition logic itself.

---

## Beta-06D Assessment

Per this sprint's own instruction: two real, severe, financially and operationally consequential BLOCKER-class vulnerabilities were found, each demonstrated with a working exploit before any fix, each fixed by reusing the exact authorization primitive established in Beta-06B/C (no new permission model, no architecture change), each confirmed both to block the exploit and to leave legitimate, real-world usage unaffected, and each covered by a permanent regression test (pending live-server execution, consistent with every other test in that file).

This sprint is not reporting Complete. Per its own Definition of Done ("do not report Complete if any significant mutation category remains untested") - Events' and Sites' own mutation routes, AI Proposals, and Insights were not examined, and are named above rather than silently assumed safe. Given that this pass found the pattern repeated across nine operational-item endpoints and six commercial functions after Beta-06C had already fixed the read side of several of the same resources, there is no reasonable basis for assuming the unaudited write endpoints are clean by default. The next highest-value pass is a targeted check of Events' and Sites' own remaining mutation routes specifically, since those are the two resources where this exact pattern (read fixed, write not yet checked) is most likely to still be live.
