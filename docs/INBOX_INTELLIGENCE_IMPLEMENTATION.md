# INBOX_INTELLIGENCE_IMPLEMENTATION.md

## Coordination-State Architecture

backend/services/inbox_intelligence_service.py - a derived coordination layer, per this task's own explicit "implement as a derived coordination layer, not by storing duplicated state" rule. No new collection exists. Every function reads from data already stored (notifications, operational_items, payment_requests) and classifies it at read time; there is nothing to keep in sync, because nothing is cached.

Action Required / Waiting For You / Commercial Attention / Activity Feed are derived directly from a user's own notifications records, classified by category and (for clarification) by title prefix - see "A Known, Stated Fragility" below.

Waiting For Others cannot be derived from notifications at all: Atlas never notifies an initiator that their own request is still pending. This section is instead derived from the underlying entities the user themselves created - operational_items where created_by_user_id matches the current user and status is non-terminal, and payment_requests where raised_by_user_id matches and status isn't yet paid/cancelled. Both fields were confirmed to already exist on their respective documents before writing any query against them, not assumed.

Escalations is not a separate data source - it's the subset of Action Required and Waiting For You whose own computed aging signal has crossed into red, surfaced as its own section so it can't be missed inside a longer list.

## A Known, Stated Fragility

Distinguishing "clarification requested" (should classify as Waiting For You) from "clarification answered" (should classify as Activity Feed) is done by matching the notification's own title prefix ("Clarification needed:" vs "Clarification answered:"), since both share category="clarification" and no explicit subtype field exists. Adding one would mean modifying notification_engine.py's own already-working, already-tested trigger functions (notify_clarification_requested/notify_clarification_answered) - a change judged riskier than this phase's own scope justified. If either title string is ever changed in a future package, this classification will silently break. Named directly here rather than hidden.

## Grouping Rules

_group_notifications() collapses every notification sharing the same (entity_type, entity_id) into one card: a count, the latest title/body, and the combined read state (unread if any underlying notification is still unread). This matches this task's own exact example ("OPS-104 updated 4 times / Latest: ..."). The same function serves all sections uniformly - there is one grouping implementation, not five separately-tuned ones.

Clarification thread grouping and approval activity grouping (this task's own Section 3 sub-requirements) are satisfied by the same mechanism: a clarification conversation and a sequence of approval actions both notify against the same entity_id, so they group into one card automatically, without any clarification-specific or approval-specific code.

## Escalation Logic

A fixed, auditable threshold table (AGING_THRESHOLDS_HOURS), using exactly the hour values this task's own brief specifies for blockers, clarifications, client approvals, payment requests, and quality observations. _aging_signal() computes elapsed hours from a real timestamp and returns green/amber/red - no business-specific recipient logic is hard-coded, per this task's own explicit instruction; escalation is a color on an existing card, not a new notification or a new recipient rule.

## Deep-Link Routing Matrix

ENTITY_TYPE_TO_PHASE, a single dict mapping each entity type to its target Workspace phase, matching this task's own Section 7 table exactly (operational_item/workflow_activity -> execute; variation/milestone -> plan; payment_request/payment/contract -> bill). This is the one source of truth both the API response (target_phase on every coordination card) and the frontend's own navigation read from - not duplicated in TypeScript. The frontend's onOpenCoordinationCard uses a normal router.push, not replace, so router.back() naturally returns to Inbox, satisfying this task's own back-stack requirement without any special-case navigation code.

## Performance Considerations

build_coordination_inbox makes at most 3 real queries per call (notifications, operational_items for Waiting For Others, payment_requests for Waiting For Others) - no N+1 pattern, since grouping happens in-memory over an already-fetched list, not via a query per notification. list_notifications is capped at 300 records (an existing, pre-Phase-4 limit), keeping the worst case bounded regardless of a user's own total notification history.

## What Was Not Built This Phase

Stated directly, not silently dropped: the Project-Scoped Inbox view inside the Workspace shell (this task's own Section 6, with its four named filters) was not built - the backend's own project_id query parameter on /api/inbox/coordination already supports this filtering, but no frontend screen inside /projects/[id]/workspace/ consumes it yet. The two-pane web layout (Section 10) was also not built - the mobile-first single-column layout this phase did build is functional on web but doesn't take advantage of extra width. Both are named as the clearest next steps, not implied to be complete.
