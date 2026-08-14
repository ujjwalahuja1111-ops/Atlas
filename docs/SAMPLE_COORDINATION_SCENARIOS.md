# SAMPLE_COORDINATION_SCENARIOS.md

## A Note on Role Adaptation, Stated Honestly

This task's own PM Scenario names a "Consultant" role. Atlas's real role system (confirmed throughout this entire engagement) has exactly four: Management, Project Manager, Site Supervisor, Client - there is no Consultant role anywhere in the data model. Rather than fabricate a fifth role that doesn't exist in Atlas today, the scenario below is adapted to use Client in the consultant's place (a client answering a clarification about a drawing is a realistic, already-supported Atlas flow), and this substitution is named directly rather than silently presented as if "Consultant" were real.

---

## PM Scenario

Step 1 - Supervisor raises a blocker.
The Supervisor creates an operational item ("Beam alignment issue," category quality_observation) and it's assigned to the PM.
-> PM's coordination inbox: Action Required (verified live: test_waiting_state_classification_action_required_for_assignee and this phase's own end-to-end run both confirm this).

Step 2 - PM requests clarification (raises a client-approval item needing external input).
The PM creates a client_approval item ("Approve revised beam drawing") - Atlas's real mechanism for "I need someone outside my own role to weigh in."
-> PM's coordination inbox: Waiting For Others (verified live: test_waiting_state_classification_waiting_for_others_for_initiator, and confirmed end-to-end in this phase's own live run - the exact item title "Approve revised beam drawing" appeared in the PM's own Waiting For Others section).

Step 3 - Client (standing in for the brief's "consultant") responds.
The Client calls the existing request-clarification action on that item.
-> PM's coordination inbox: Waiting For You (verified live in this same run: the notification "Clarification needed: Approve revised beam drawing" appeared in the PM's own Waiting For You section immediately after the Client's action - a 201 response, confirmed).

Step 4 - PM closes the blocker.
Once the PM answers (via the existing notify_clarification_answered trigger, already built in PX-01A) and eventually transitions the original blocker to closed, both items leave Action Required/Waiting For You and move into Activity Feed - no longer requiring attention from anyone.

The full transition, exactly as this task's own brief frames it, and confirmed against real, live behavior rather than assumed:
Action Required -> Waiting For Others -> Waiting For You -> Resolved

---

## Client Approval Scenario

Step 1 - PM submits a variation.
Using Atlas's existing Variation flow (CP-02), the PM creates and submits a Variation, then sends it for client review.

Step 2 - Client receives the approval request.
The Variation's own status (client_review) makes it visible in the Client's Plan-phase view. Atlas does not currently send a dedicated notification for "a variation now awaits your review" - confirmed directly by grepping notification_engine.py for every notify_* function before writing this: only notify_assignment, notify_status_change, notify_clarification_requested, notify_clarification_answered, and notify_commercial exist. No variation-specific trigger is called anywhere in commercial_engine.py either. Named here as a real, honest gap rather than assumed to already work, since this task's own scenario implies one should fire.

Step 3 - Reminder escalates after threshold.
If the Variation remains in client_review past the client-approval threshold (48h warning / 72h escalated, per this phase's own aging table), it would appear in the Client's own Waiting For You section with an amber, then red, aging signal - this part is real and does work, since the aging calculation applies uniformly to any card, not specifically to notification-triggered ones. What's missing (per Step 2's own honest gap) is the initial notification prompting the Client to look in the first place; the escalation coloring itself is real, once a card exists to color.

Step 4 - Client approves.
The Client calls the existing Variation decision endpoint (approved) - CP-02's own, already-verified flow, unchanged by this phase.

Step 5 - PM receives completion notification.
Atlas does not currently send the PM a dedicated "your variation was approved" notification either (same grep, same confirmed absence) - a second honest gap. The PM would see the Variation's new approved status the next time they open Plan or Bill, but not proactively via Inbox. Named directly, matching this document's own commitment to distinguishing what was verified from what the brief describes but Atlas doesn't yet do.
