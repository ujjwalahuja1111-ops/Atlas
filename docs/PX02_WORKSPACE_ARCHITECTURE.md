# PX02_WORKSPACE_ARCHITECTURE.md

Every "underlying Atlas engines used" claim below is grounded in engines and screens actually built and verified across this engagement (CO-01 through LIVE-01), not aspirational. Where a phase needs something Atlas doesn't have, that's named as a gap, not silently assumed solved.

---

## 2. The Atlas Lifecycle Model

PL-01 already built a five-stage lifecycle (Planning, Mobilization, Execution, Commercial Focus, Closeout) with a real lifecycle_stage field and an adaptive Stage Focus card. This section maps that existing foundation onto the six-phase structure this task requests, reusing PL-01's own stage-transition mechanism rather than inventing a second, parallel lifecycle concept.

### Setup (maps to PL-01's Planning)
- Primary user: Project Manager.
- Key actions: create project (P2-04's own 4-step Wizard), assign PM/Supervisor, define initial Contract/Budget.
- Engines used: memory_engine (project/site), commercial_engine (Contract/Budget creation), the admin-users membership route (PX-01B's own relaxed permission model).
- Visible by default: project name, assigned team, Contract/Budget existence status (PL-01's own Stage Focus already does this).
- Behind "More": GST/retention detail, billing cycle preference (collected in the Wizard, not yet persisted anywhere - a named gap, not fabricated as solved).

### Plan
- Primary user: PM, with Management/Client visibility for approvals.
- Key actions: Milestone creation, Variation raising, Contract review.
- Engines used: commercial_engine (Milestone/Variation state machines, already fully built in CP-01/CP-02), WF-01's own orchestration (Variation Approved trigger).
- Visible by default: Milestone list with status, pending Variations.
- Behind "More": full Variation history, individual milestone dependency detail (named gap - CO-01 confirmed no milestone dependency graph exists).

### Execute (maps to PL-01's Execution)
- Primary user: Site Supervisor, PM.
- Key actions: Capture, operational item assignment/resolution, blocker escalation.
- Engines used: intelligence_engine (AI structuring), operations_engine (items, assignment, notifications via PX-01A), workflow_engine (activity progression).
- Visible by default: Today's Mission (EX-01's own existing section - reused directly, not rebuilt).
- Behind "More": full operational item history, workflow activity dependency detail.

### Review
- Primary user: PM, Management.
- Key actions: check project health, review AI insights, confirm quality/safety trends.
- Engines used: reasoning_engine (Explain Health, CRE insights - Atlas's own differentiator, unchanged), KM-01's Knowledge Graph (KG-UI-01's own Explain entry points).
- Visible by default: Health Strip (EX-01), AI Suggestions (WF-01).
- Behind "More": full Timeline, Relationship Explorer detail traces.

### Bill (maps to PL-01's Commercial Focus)
- Primary user: PM, Management, Accounts.
- Key actions: raise Payment Requests, record Payments, review Commercial Breakdown.
- Engines used: commercial_engine (fully built in CP-01/CP-02), the Commercial Breakdown section (PX-01A's own P2-06).
- Visible by default: Cash Flow signal, Commercial Health banner, Commercial Breakdown (all already built and verified live in LIVE-01).
- Behind "More": individual payment history, GST/retention detail (named gap - PILOT-01's own central finding, unchanged: stored but never applied).

### Close (maps to PL-01's Closeout)
- Primary user: PM, Management.
- Key actions: confirm final Milestone paid, Contract closed.
- Engines used: commercial_engine's own completed/closed Contract states (confirmed to exist, CO-01).
- Visible by default: final Milestone status, Contract status.
- Behind "More": nothing further exists - Snags/Handover/Lessons Learned are all confirmed absent from Atlas today, matching PILOT-01's own honest finding that "Closeout -> show snagging" (this task's own predecessor brief) had no real capability to point to. Named directly here rather than glossed over: Close is the least-built phase in Atlas today, and this task's own "do not overbuild" instruction (Section 7) means this stays a named gap, not a build target for this roadmap.

---

## 3. Global Navigation Redesign — The 5-Tab Model

### 1. Home
Purpose: role-aware landing, not a feature in itself. Existing screens absorbed: the redirect logic already built in RC1-HARDENING/PX-01B (PM/Supervisor -> Workspace, Management -> Executive Hub) becomes the entire content of this tab - Home is a router, not a destination, for PM/Supervisor. For Management, Home is Executive Hub. Screens that disappear as top-level destinations: the standalone Timeline-style Home view for PM/Supervisor (already mostly redirected away in PX-01B; this makes it official rather than a fallback).

### 2. Projects
Purpose: the project list, project creation (P2-04's Wizard), and the entry point into any given project's Workspace. Existing screens absorbed: projects/index.tsx and projects/[id].tsx largely unchanged - this tab's own role is already close to correct, per RC-01's own audit; the main change is trimming projects/[id].tsx's own commercial tile grid further (RC1-HARDENING's H1 already did the first pass) since the Workspace is now the canonical destination.

### 3. Capture
Purpose: unchanged - this tab is already correct (UX-01, re-confirmed repeatedly). No structural change proposed.

### 4. Inbox
Purpose: the notifications screen (PX-01A/B), promoted from a Profile sub-link to a first-class tab, matching this task's own explicit 5-tab target. This is the single most consequential navigation change in this proposal - Inbox currently requires two taps (Profile -> Inbox) to reach; as a tab, it's one.

### 5. More
Purpose: everything role-specific and infrequent. Existing screens absorbed: Profile itself, Knowledge Base, Executive Hub (for non-Management roles who occasionally need portfolio context), User Management (admin-only), System Info.

### What happens to named screens
- Executive Hub: becomes Management's own Home content directly (see above) - not removed, repositioned as the landing experience rather than a Profile sub-link.
- Commercial Workspace: stays exactly where it is - reached from within a project's own Workspace, not promoted to a top-level tab, since it's project-scoped by nature (matching RC-01's own finding that Commercial is already the best-integrated subsystem).
- Timeline screen: the per-project Reality Capture Timeline (Home's own TimelineScreen component today) moves to live inside a project's Workspace as a "Project Feed" section - EX-01 already has this concept, currently commercial-events-only (EX-01's own named gap); this proposal's Phase B extends it to include Reality Capture events too, closing that gap directly.
- OPS screen: its own content (My Day, item lists) is already substantially absorbed into Workspace's Today's Mission (EX-01); the standalone OPS tab becomes redundant for PM/Supervisor and can be removed as a top-level tab, with any remaining OPS-specific views (bulk item management) moved to More.
- Priority Engine: stays as Management's own tool, reached from Executive Hub/Home, unchanged - it's portfolio-wide, not per-project, matching EX-01's own original scoping decision to keep it separate.
- Knowledge views: move to More, unchanged in function.

### Role-specific behavior summary
| Role | Home | Projects | Capture | Inbox | More |
|---|---|---|---|---|---|
| Management | Executive Hub | Full list, create allowed | Hidden or de-emphasized (not their daily job) | Full inbox | Portfolio tools, User Management |
| PM | Redirects to last-active Workspace | Full list, create allowed | Available | Full inbox | Profile, Knowledge |
| Supervisor | Redirects to assigned Workspace | List restricted to assigned projects, create hidden | Primary daily screen | Full inbox | Profile only |
| Client | Client Dashboard (unchanged) | N/A | N/A | Not applicable - client notifications, if any, stay inside the Client Dashboard itself | Profile only |

---

## 4. Project Workspace Consolidation

| Information | Canonical owner | Summary surfaces | Remove from |
|---|---|---|---|
| Commercial KPIs (Contract value, Cash Flow, Margin) | Commercial Engine (apiGetCommercialSummary) | Workspace Project Pulse (2 KPIs, RC1-HARDENING's own trim), Commercial Workspace (full detail) | projects/[id].tsx's own remaining tile grid - trim further to a single navigation card, no tiles at all |
| Project health | CRE (explain-health) | Workspace Health Strip | Nowhere else currently duplicates this - confirmed clean |
| Pending approvals | Operational Items + Commercial Variations (composed, not duplicated storage) | Workspace Today's Mission | Nowhere else currently duplicates this |
| Recent events | commercial_events + Reality Capture events (currently two separate feeds) | Workspace Project Feed (currently Commercial-only - Phase B closes this) | The standalone Home Timeline screen, once its content moves into Workspace's own Project Feed |
| Blockers | Operational Items (health="blocked") + Workflow Activities (status="blocked") | Workspace Today's Mission | Nowhere else currently duplicates this |
| Team assignments | memory_engine (assigned_project_ids) | Workspace (implicitly, via who can act); no dedicated "team" summary view exists today - a named gap, not fabricated as present | N/A |
| Client-facing progress | reasoning_engine's own client-dashboard functions (client_dashboard_view, client_payment_journey, etc. - already built, confirmed in KM-01/CP-02's own work) | Client Dashboard only | N/A - this is correctly single-owned already |

Overall consolidation goal restated per this task's own framing: every row above already has exactly one data owner (RC-01's own Data Ownership Matrix already confirmed this is strong). The work this phase does is trimming display surfaces down to one per audience - Workspace for internal roles, Client Dashboard for the client - not touching any underlying computation.

---

## 5. AI Daily Site Report Generator

### Inputs, all confirmed already captured by Atlas today
Voice/photo/text events (Reality Capture), GPS via site association, operational items and their status/health, blockers, comments (add_comment, confirmed to exist in operations_engine.py), commercial events, Explain Health's own dimension scores, assignments.

### Report structure

Executive Summary - one paragraph, deterministically assembled (not LLM-narrated) from: today's event count, operational items opened/closed, current Health status, any new blockers.

Work Completed Today - Reality Capture events from the last 24 hours, grouped by site, each with its own photo/voice/text content already stored.

Manpower Snapshot - named gap, stated honestly: Atlas has no labour/attendance tracking anywhere in its current data model (confirmed absent throughout this engagement, matching Section 7's own "Ignore" classification for procurement-adjacent labour tooling). This section of the report would be empty or omitted until/unless Atlas ever builds attendance capture - not fabricated with placeholder data.

Materials & Logistics - same honest gap as Manpower: no material-request or inventory tracking exists (Section 7 classifies this "Later," not "Build now"). This section stays empty until that capability exists.

Blockers & Risks - operational items with health="blocked" or "waiting_external", plus workflow activities with status="blocked" - real, already-tracked data, directly reusable.

Client Decisions Pending - operational items of category client_approval still open, plus Variations in client_review status - real, already-tracked data.

AI Forecast Impact - the one section that is Atlas's own genuine differentiator over every competitor reviewed: CRE's own evaluate_rules findings for today, cross-referenced against Explain Health's own dimension deltas. This answers "does today's activity change the forecast," not just "what happened" - no competitor reviewed in Document A combines field reporting with deterministic forecast reasoning in the same artifact.

Attached Photos - direct reuse of raw_assets linked to today's events, no new storage.

### Why this is more useful than a traditional DPR
A traditional daily progress report (Raken's own benchmark, and every competitor reviewed) answers "what happened." Atlas's own version, because it's assembled from the same event ledger the CRE already reasons over, can additionally answer "what does this mean for the schedule and the health of this project" - the Forecast Impact section - without requiring a second tool or a human analyst to connect the two. This is composition of existing intelligence, not a new AI engine, matching this task's own "preserve Atlas's differentiators" instruction precisely.

---

## 6. Notification & Collaboration Evolution

Building directly on PX-01A/B's own working foundation (5 categories, unread-pinning, project context per card - all already built and verified live in LIVE-01), this section proposes a prioritization layer on top of the existing categories, not a replacement of them.

### Prioritization concepts, mapped to existing data
- Action Required: notifications where the current user is the one who must act (assignment, clarification directed at them, a variation awaiting their own decision).
- Waiting For You: a superset of Action Required with a due-date/staleness signal - reuses Beta-06G's own awaiting_clarification_response flag concept, generalized.
- Waiting For Others: the inverse - things the current user raised that are pending someone else's action (a variation they submitted, a clarification they requested).
- FYI / Activity Feed: status-change notifications with no action implied - already exist as PX-01A's own status_change category.
- Escalations: a new, deliberately small addition - a notification that has sat in Action Required past a threshold (e.g., 48 hours) gets re-flagged, reusing the same event timestamp already stored on every notification, no new tracking needed.
- Commercial Attention: already exists as PX-01A's own commercial category, unchanged.

### Grouping rules
- Multiple comments on the same item: collapse into one notification card ("3 new comments on 'Fix crack'"), updating in place rather than creating a new card per comment - requires a small aggregation key (entity_type + entity_id) already present on every notification.
- Repeated status changes: collapse to the latest status only, since intermediate states are rarely actionable - the notification's own title/body already gets overwritten in place rather than accumulating duplicates.
- Clarification conversations: thread by entity_id, showing the most recent message as the card's own summary, with older messages reachable by tapping through - reuses the existing clarification entity link, no new data model.
- Payment workflow updates: group by payment_request_id (already present on the relevant notifications) so a PM sees "Payment Request PR-004: raised -> sent -> paid" as one evolving card, not three separate ones.

Engineering note, stated honestly: none of this requires a new collection or new business logic - every grouping key named above already exists on the notifications document PX-01A built. This is a query/aggregation change on read, not a schema change.

---

## 7. Procurement & Billing Strategy — Deliberately Opinionated

| Capability | Decision | Reason |
|---|---|---|
| Material Request | Later | Real operational need (RDash/Powerplay both treat this as core), but Atlas has zero material-tracking data model today - building it well requires inventory concepts this task's own constraints explicitly forbid rushing into. Revisit after the pilot proves out the commercial/operational core. |
| RFQ Comparison | Ignore | This is deep procurement tooling (RDash's own differentiator) that has no natural extension of Atlas's own current data model. Building this would be the clearest path to the "ERP bloat" this task explicitly warns against. |
| Purchase Orders | Ignore for now, Later at most | Same reasoning as RFQ - genuinely useful eventually, but requires a vendor concept Atlas has never modeled, and this task's own predecessor briefs (CO-01 onward) have repeatedly, correctly declined to build one. |
| GRN / Stock Ledger | Ignore | The deepest procurement dependency of all - GRN only makes sense once Purchase Orders exist. Two "Ignore" decisions deep; not worth revisiting until the pilot itself demands it. |
| Vendor Performance Analytics | Ignore | Depends entirely on the above three existing first. Purely aspirational at this stage. |
| Client Payment Requests | Already built | CP-02 built this fully; PX-01A verified it live. Not a forward-looking decision - stated here for completeness against this task's own table structure. |
| Retention Tracking | Build now, narrowly | The one procurement-adjacent item worth prioritizing: retention_percent is already stored on Contract (confirmed, CO-01) but never applied to any Payment calculation - this is a small, contained fix (apply the existing stored percentage to Payment Request amounts), not a new capability, and directly closes PILOT-01's own central Go/No-Go finding. |

The opinionated summary, stated directly: Atlas should build exactly one procurement-adjacent thing in the next 6 months - making the retention percentage it already stores actually affect a real payment calculation. Everything else in this table (Material Requests, RFQs, POs, GRN, Vendor Analytics) is real, valuable, and exactly the kind of feature creep this task's own Section 7 heading explicitly names as the thing to avoid. Atlas's own differentiation is depth in reasoning and coordination, not breadth in procurement - chasing RDash's own procurement depth would dilute the thing Atlas is actually better at.
