# WAITING_STATE_MATRIX.md

Every row below was verified live through the real API, not derived only by reading code - confirmed via a real multi-role scenario (a PM assigns an item to a Supervisor, the PM separately raises a client-approval item, a client requests clarification on it) before being written here.

| Entity | Recipient Role | Waiting State | Derivation |
|---|---|---|---|
| Assigned operational item | Assignee | Action Required | notification.category == "assignment" |
| Clarification requested (item owner needs to answer) | Item owner (typically PM) | Waiting For You | category == "clarification" and title starts with "Clarification needed" |
| Clarification requested (by the item's own initiator) | Initiator | Waiting For Others | Derived from operational_items where created_by_user_id matches and status is non-terminal - not from any notification, since Atlas never notifies an initiator that their own request is pending |
| Clarification answered | Original requester | Activity Feed | category == "clarification" and title starts with "Clarification answered" |
| Client approval pending | Client | Waiting For You (structurally - a Client's own inbox only ever contains notifications addressed to them) | Same notifications per-user scoping every role relies on |
| Payment request raised | Raising PM | Waiting For Others | Derived from payment_requests where raised_by_user_id matches and status isn't paid/cancelled |
| Payment request raised | Management (notified) | Commercial Attention | category == "commercial" |
| Item exceeding its own aging threshold | Whoever it's Action-Required or Waiting-For-You for | Escalations | Same underlying card, aging_signal == "red", surfaced in a second section |
| Status change (informational) | Assignee/owner | Activity Feed | category == "status_change" |

## Role-Specific Notes

- Management never appears as a "recipient role" above for operational-item states, because Management is not typically the assignee of a field-level operational item - their own coordination surface is the Management Attention Digest (Section 8), a portfolio synthesis, not a per-item waiting state.
- Client only ever sees Waiting For You and, if applicable, Activity Feed - verified structurally (not by a category filter) via test_client_visibility_restriction_via_per_user_scoping: a Client's own coordination inbox for Action Required and Waiting For Others is always empty, because a Client is never the assigned_to_user_id of an operational item and never the created_by_user_id of one either.
- Escalation state is a derived overlay, not a fifth independent classification. An item is never only "Escalated" - it's simultaneously Action Required (or Waiting For You) and red-signaled, appearing in both sections. This was a deliberate design choice: removing an escalated item from its own primary section would make it harder to find in context, not easier.
