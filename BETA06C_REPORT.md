# Beta-06C — Authorization Boundary Validation Report

Per this sprint's own mandatory requirement, this report begins with the audit table.

---

## Audit Table

| Resource | Endpoint(s) | Status | Evidence |
|---|---|---|---|
| Operational Items | GET /operational-items/{id}, GET /operational-items | BLOCKER, fixed in Beta-06B (re-confirmed this pass) | Zero visibility check on both detail and list. Fixed via assert_item_visible. Re-verified this pass as still correctly blocking outsiders. |
| Reality Events | GET /events/{event_id} | BLOCKER, fixed this pass | Zero visibility check. Demonstrated: an unrelated, properly-scoped outsider retrieved a photo capture's full text and metadata from a project they had no assignment to. Fixed by reusing commercial_engine.assert_project_visible. |
| Raw Assets (photo/audio binary data) | GET /raw-assets/{asset_id} | BLOCKER, fixed this pass | Zero visibility check. Demonstrated: the same outsider retrieved base64 photo data for an asset belonging to a project they had no assignment to. Fixed by resolving the asset's owning event, then applying the same check. |
| Site Requirements (material/labour/equipment) | GET /sites/{site_id}/requirements | BLOCKER, fixed this pass | Zero visibility check. Demonstrated: the same outsider retrieved site-level resource requirements for a site outside their project assignment. Fixed by the same reused check. |
| Commercial (Contract, Milestones, Payment Requests, Payments, Variations, Budget, Events, Summary) | GET /projects/{project_id}/commercial/* | VERIFIED | Every commercial resource is exposed only through a project_id-scoped URL, never a raw entity-ID lookup - no variations/{id} or payments/{id} route exists. All eight routes confirmed to call assert_project_visible (RC-01, re-confirmed this pass by direct inspection of every route in routes/commercial.py). |
| Construction Memory | GET /projects/{project_id}/construction-memory | VERIFIED | Confirmed calls _assert_project_visible internally. |
| Workflow | GET /projects/{project_id}/workflow, GET /workflow-activities/{id}/evidence | VERIFIED | No standalone single-activity GET-by-ID route exists - activities are reachable only via the project-scoped list. The evidence endpoint (built in Beta-04) was confirmed to already call _assert_project_visible via get_activity_evidence. |
| Knowledge Items (templates, activity definitions) | GET /knowledge-items/{id}, /versions | VERIFIED - not applicable | Confirmed by inspection: knowledge_engine.py has zero project_id references anywhere. Knowledge Items are genuinely global, shared construction-knowledge data (templates, activity master definitions), not project-specific - there is nothing to leak across a project boundary here, unlike every other resource in this table. |
| Explain Health, Priority Engine, Executive Hub's own composed views | GET /projects/{id}/explain-health, /portfolio/priorities, /portfolio/cross-project-intelligence, /portfolio/commercial-intelligence, /portfolio/executive-timeline | VERIFIED (carried forward from Beta-05/Beta-05-final/Beta-06) | Re-confirmed by inspection this pass, not re-tested live: each composes _portfolio(user) or _assert_project_visible, both of which enforce _is_project_scoped correctly. |
| Portfolio Search | GET /portfolio/search | VERIFIED (fixed in Beta-06, re-confirmed this pass) | The payments field leak found and fixed in Beta-06; all six categories re-confirmed this pass to use consistent scoping. |
| Daily Review, Site Progress | GET /daily-review, GET /projects/{id}/site-progress | VERIFIED (carried forward from Beta-03/Beta-04) | Both already scope via _portfolio/direct project-id checks; re-confirmed by inspection, not re-tested live this pass. |
| Approvals | (category filter on Operational Items) | VERIFIED, via the operational items fix above | Client approvals are operational items with category=client_approval - no separate endpoint exists; the operational items fix directly closes this. |
| Documents / Attachments | - | NOT APPLICABLE | Confirmed in Beta-01's own audit and unchanged since: no documents store exists anywhere in the platform. There is no resource here to audit. |
| Reports | - | RISK - not found as a distinct resource, not separately audited | No dedicated "reports" endpoint or resource was found distinct from the views already audited above (Explain Health, Commercial Intelligence, etc. are themselves report-like views, already covered). If a distinct reporting/export capability exists elsewhere in the codebase that this search missed, it has not been independently verified this pass - named as a risk rather than silently assumed covered. |
| Voice Notes / Photos | Covered by Events + Raw Assets above | VERIFIED (via the fixes above) | Voice and photo captures are both events with linked raw_assets - no separate resource; both fixes above apply directly. |

---

## UI vs API Validation

The Operational Item detail screen's client-facing restricted action set (approve/reject/comment only - built correctly in an earlier sprint) was the actual starting point for this entire audit line, carried over from Beta-06B: the UI restriction was real and correct, but was not backed by any server-side enforcement until Beta-06B's fix. This pass specifically went looking for the same pattern (a UI that looks restrictive without a backend check behind it) across other resources, rather than assuming Operational Items was an isolated case - and found three more instances of exactly this pattern (Events, Raw Assets, Site Requirements), none of which had any corresponding frontend restriction to begin with (the leak was purely at the API layer, with no UI signal that anything was wrong).

---

## Role Matrix — Verified This Pass

For the four newly-fixed resources (Events, Raw Assets, Site Requirements, plus re-confirmation of Operational Items):

| Role | Allowed | Denied | Reason |
|---|---|---|---|
| Management | All projects | - | _is_project_scoped returns False unconditionally for management, matching the platform-wide rule. |
| Project-scoped roles (PM, Site Supervisor, Site Engineer, Client) with scope_projects=True | Only their own assigned_project_ids | Every other project | Verified directly: an outsider scoped to Project B received 404 for Project A's event, asset, and site requirements; the same outsider (and management) received 200 for their own/any project respectively. |
| Anonymous | - | Everything | Every route requires Depends(get_current_user); unauthenticated requests are rejected before reaching any of the logic audited here (not independently re-tested this pass, but structurally guaranteed by FastAPI's dependency injection - every route in this table has this dependency). |

A genuine nuance surfaced and documented, not glossed over: accounts created via memory_engine.upsert_user() (a test/seed convenience helper, not the production register_user() Sign Up flow) do not have scope_projects=True set by default, and are therefore treated as unrestricted regardless of role. This is a separate, pre-existing, deliberately documented migration safeguard (see _is_project_scoped's own docstring) protecting accounts that predate the project-scoping feature - not a gap this pass introduced or is responsible for closing. All exploit demonstrations and regression tests in this pass and Beta-06B specifically used set_user_projects (or the real /admin/users/{id}/projects endpoint) to construct genuinely scoped accounts, so the findings reported here reflect real production behavior, not an artifact of test setup.

---

## Consistency Audit

Every fix in this pass and Beta-06B reuses the identical primitive: memory_engine._is_project_scoped(user) plus a check against user["assigned_project_ids"], either called directly or via commercial_engine.assert_project_visible (chosen because it is already public, already generic despite its module name, and its own docstring explicitly states this is the intended, reusable pattern). No new permission logic, no endpoint-specific rules, and no new authorization primitive were introduced.

A documented inconsistency, not fixed this pass: this exact check (_is_project_scoped + assigned_project_ids comparison) is currently duplicated across at least three names in the codebase - commercial_engine.assert_project_visible (public), reasoning_engine._assert_project_visible (private), and workflow_engine._assert_project_visible (private). This pass reused the existing public one rather than introducing a fourth, but did not consolidate the existing three into one shared location, since doing so would be an architectural change outside this sprint's own explicit scope ("no architecture changes"). Named here as a real, pre-existing inconsistency worth a dedicated future pass.

---

## Testing

- 4 new regression tests, mongomock-based (129 total in the established baseline, unchanged count from Beta-06B since these three new fixes are route-level and tested via the live-URL file instead).
- 3 new regression tests added to the live-URL test file (test_rc01_commercial_visibility.py), following its established pattern exactly. These specific new tests, like every other test in that file, require a deployed server to execute and were not run in this sandbox - the underlying fixes were instead verified directly via constructed httpx/ASGI-transport scenarios (shown working above), which is real, executed verification, just through a different harness than that file's own convention.
- Every fix verified three ways: the exploit demonstrated before the fix, its absence confirmed after, and legitimate access (a real ACDP supervisor and client viewing their own project's events and site data) confirmed unchanged.

---

## Files Changed

- backend/routes/events.py - visibility check added to GET /events/{event_id}.
- backend/routes/raw_assets.py - visibility check added to GET /raw-assets/{asset_id}.
- backend/routes/operational_center.py - visibility check added to GET /sites/{site_id}/requirements.
- backend/tests/test_rc01_commercial_visibility.py - 3 new tests.

---

## Remaining Risks — Named Explicitly

1. "Reports" was not found as a distinct resource and was not separately audited beyond the report-like views already covered elsewhere in this table. If a genuinely distinct reporting/export capability exists that this pass's search missed, it remains unverified.
2. The three-way duplication of the _is_project_scoped + assigned_project_ids check (public in commercial_engine, private in reasoning_engine and workflow_engine) was documented but not consolidated, per this sprint's own "no architecture changes" constraint.
3. This audit covered every project-facing GET-by-ID and list endpoint found via systematic route extraction, but write endpoints (POST/PATCH/DELETE) were not separately re-audited this pass beyond what prior sprints (RC-01, Beta-02, Beta-05, Beta-06) already covered for specific resources - a full write-path audit using this same methodology would be a reasonable next step.
4. Anonymous access was not independently live-tested this pass; it is structurally guaranteed by FastAPI's Depends(get_current_user) on every route audited, which was confirmed present on each, but a request without a token was not literally sent.

---

## Beta-06C Assessment

Per this sprint's own Definition of Done: every major project-facing resource category named in the brief's own scope was examined (Workflow, Reality/Events, Operational Items, Commercial in full, Approvals, Variations, Payments, Construction Memory, Evidence, Photos, Voice Notes, Search - Documents/Attachments confirmed not to exist, Reports not found as distinct and named as a risk). Three new BLOCKER-class findings were discovered, each demonstrated with a real exploit before fixing, each fixed by reusing the platform's own existing, established visibility primitive, and each covered by a permanent regression test. No new permissions model or architecture was introduced.

This sprint is not claiming unqualified "Complete." Two items are named explicitly as gaps rather than silently closed: "Reports" as a possibly-distinct, unaudited resource, and a full write-path re-audit beyond what prior sprints already covered. Per this sprint's own instruction not to report Complete if any major resource category was not examined - every category named in the brief was examined, which is the honest basis for reporting this pass largely complete against its own stated scope, while still naming the two items above rather than implying zero remaining risk.

The pattern this pass and Beta-06B together establish is worth stating plainly: three of the last four sprints in this engagement have found genuine, exploitable authorization gaps by directly testing real scenarios rather than trusting that existing review, however careful, had already caught everything. That pattern is the strongest evidence for continuing exactly this kind of verification - write-path checks specifically - as the next highest-value use of engineering time, ahead of any new UX or feature work.
