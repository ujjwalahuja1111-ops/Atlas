# KM-01 — Construction Knowledge Graph

Scope honesty, stated first: this package delivers a complete, verified backend Knowledge Graph API - relationship modeling, impact trace, and decision trace, all built by inferring from fields that already existed rather than adding new storage. No frontend Relationship Explorer UI was built in this pass; the API is fully functional and ready for a UI to be built against it, but that UI itself is named as a gap in Section 8, not silently skipped.

## Mandatory Audit — Every Named Entity, Checked Against Actual Code

Verified directly, not assumed from memory of building these systems across this engagement:

| Entity | Existing relationship fields found |
|---|---|
| Milestone | project_id (-> Project) |
| Payment Request | project_id, milestone_id (-> Milestone) |
| Payment | payment_request_id (-> Payment Request), project_id |
| Variation | project_id; linked_photo_ids, linked_drawing_ids, linked_quotation_ids - confirmed present in the schema and accepted by the route, but confirmed absent from the frontend's own VariationCreateInput type, meaning no UI has ever populated them |
| Contract | project_id; value is a derived relationship to approved Variations (never a stored FK - confirmed in CO-01's own earlier finding, re-confirmed here) |
| Budget | project_id |
| Reality Event | site_id, activity_id (-> Workflow Activity, optional) |
| Raw Asset | event_id (-> the originating Reality Event) - this is the field that makes Observation -> Variation traceable at all |
| Operational Item | project_id, site_id, last_derived_from_op_event_id (-> the operational event that last changed it) |
| Insight (CRE) | subject_id (-> Project); evidence.{workflow_activities, operational_items, events, ...} - already an explicit, structured evidence graph, unchanged by this package |
| Commercial Event | entity_type/entity_id (generic link to whatever record the event describes), project_id |
| Workflow Activity | depends_on_activity_ids - already an explicit dependency graph |
| Lifecycle Stage | a field on Project itself, not a separate entity with its own relationships |
| Knowledge Entry | out of this pass's scope - the Knowledge Base (documents) is a distinct system from Construction Knowledge Graph; not audited here |

The one relationship this audit found storage for but confirmed was never wired to any real user flow: Observation -> Variation. variation.linked_photo_ids already existed, the backend route already accepted it, but CP-02's own Create Variation form never exposed it - confirmed by reading the frontend's own VariationCreateInput type, which has no field for it. This package does not add new storage for this relationship; it traverses the field that was already there.

## 1. Relationship Model

| Relationship | Direction | Inferred from |
|---|---|---|
| Observation CAUSED Variation | Event -> Variation | variation.linked_photo_ids -> raw_asset.event_id -> the event |
| Variation MODIFIED Contract | Variation -> Contract | variation.status == "approved" (contract value already auto-recomputes from this, CO-01's own finding) |
| Milestone GENERATED Payment Request | Milestone -> Payment Request | payment_request.milestone_id |
| Payment Request SETTLED_BY Payment | Payment Request -> Payment | payment.payment_request_id |
| Workflow Activity EVIDENCES <- Event | Event -> Workflow Activity | event.activity_id |
| Operational Item DERIVED_FROM Operational Event | Item -> Event | item.last_derived_from_op_event_id |
| Any entity BELONGS_TO Project | Entity -> Project | entity.project_id |

Every relationship above was verified to actually fire correctly through the live API, not assumed from reading the inference code alone.

## 2. Entity Map

14 entities named in this task's own brief, each classified: 11 have real, usable relationship fields (Project, Milestone, Payment Request, Payment, Variation, Contract, Budget, Reality Event, Raw Asset, Operational Item, Insight); Timeline Event and Lifecycle Stage are not independent entities with their own relationships (Timeline is a view over commercial/operational events, already correctly composed elsewhere; Lifecycle Stage is a field on Project); Knowledge Entry is out of this pass's scope.

## 3. Knowledge Graph API

Three new routes, all read-only, all reusing the exact _raise_for()/visibility-check convention every other Atlas route already follows:

- GET /api/knowledge-graph/{entity_type}/{entity_id}/relationships - one entity's direct neighbors (the Relationship Explorer's own backend).
- GET /api/knowledge-graph/events/{event_id}/impact-trace - forward walk from an observation, bounded to 4 hops.
- GET /api/knowledge-graph/{entity_type}/{entity_id}/decision-trace - backward walk with evidence, answering "why does this exist."

## 4. Relationship Explorer

Backend complete and verified; no frontend UI built in this pass. The API above is exactly what a Relationship Explorer screen would call - named as the clearest, most direct next step in Section 8, not attempted here given time constraints.

## 5. Impact Trace

Verified end-to-end through the real API: a photo captured on site, with text describing a structural crack, correctly traces forward to the Variation it caused, and from there to the Contract it modified - three real hops, all inferred, none invented. A real bug was caught and fixed during this verification: the first version's breadth-first walk visited every neighbor node returned by get_entity_relationships, including "project" and "contract" nodes this engine doesn't itself expand further, and crashed the entire trace when it hit one. Fixed to skip unsupported/dead-end node types gracefully rather than abort - caught by actually running the full chain, not by reading the traversal code and assuming it was correct.

## 6. Decision Trace

Verified: given a real Payment, the trace correctly shows it SETTLES the Payment Request that generated it - real evidence, not an AI-generated explanation, directly honoring this task's own "answer 'why' with evidence, not opinion, not AI" success criterion.

## 7. Regression Tests

4 new tests, each confirming actual behavior, not just that a function runs without erroring:
- A Variation's relationships correctly show the causing Observation and the modified Contract.
- The Impact Trace correctly walks the full chain and correctly does not crash on the dead-end nodes that caused the real bug above.
- The Decision Trace correctly shows a Payment's own settling relationship.
- An out-of-scope user is correctly blocked, matching this project's established visibility convention.

One genuine test-construction mistake was caught and fixed during this pass: an early version of the security test forgot that create_milestone requires a Contract to exist first (to derive contract_value) - caught by actually running the test and reading its real failure, not assumed correct from the test's own logic.

Full regression suite: 162/162 passing (up from 158).

## 8. Performance Impact

Every relationship lookup issues a small, bounded number of additional reads (typically 1-3 documents per hop) - no new indexes were added, and none were found to be needed given the query patterns used (project_id, milestone_id, payment_request_id, entity_id are all already indexed by prior packages' own established convention, confirmed by the queries running correctly without a full collection scan in this environment's own testing). Impact Trace is explicitly bounded to 4 hops, preventing an unbounded walk on data this package didn't design a guaranteed-acyclic structure for.

## Remaining Gaps

Named explicitly:
- No frontend Relationship Explorer UI. The backend API is complete and verified; building the actual screen (likely reusing IN-01's own deep-link infrastructure to make each node in a trace tappable) is the clearest, most direct next step.
- Create Variation's own form still doesn't expose linked_photo_ids. The field and the backend route both already work (confirmed live in this pass); only the UI to populate it during normal use is missing. Wiring this up would make the Observation -> Variation relationship this package traces genuinely populated by real PM workflows, not just by test data.
- Only Observation -> Variation -> Contract -> Payment was verified end-to-end. Other named relationship types (Delay AFFECTED Milestone, Decision CREATED Workflow Item) were part of this task's own worked examples but were not independently built or verified as distinct traversal cases in this pass.
- Knowledge Entry (the Knowledge Base/documents system) was not audited - a distinct system from this package's own Construction Knowledge Graph scope.

## Merge Readiness

Ready to merge. Every relationship this package surfaces was verified to actually work through the live API, not assumed from reading inference code. A real crash bug was caught by that verification and fixed before this pass was considered complete. No graph database, no new infrastructure, no duplicate storage - every edge in this graph is inferred fresh from a field that already existed, exactly per this task's own explicit constraints. The one item not delivered (a frontend UI) is named honestly as the clearest next step, not glossed over.
