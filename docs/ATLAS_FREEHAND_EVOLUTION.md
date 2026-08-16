# ATLAS_FREEHAND_EVOLUTION.md

## 1. The Problem I Identified

I read the actual code before deciding anything, per this task's own instruction not to rely on documentation. What I found: Atlas already runs a genuinely sophisticated AI pipeline on every captured site update. intelligence_engine.py transcribes voice (Whisper), structures the update via GPT-4o, and generates typed proposals across 11 real construction intents - material, labour, equipment, client approval, drawing request, inspection, site issue, safety observation, quality observation, commitment, follow-up. A full accept/reject review screen for these proposals already exists at app/event/[id].tsx.

None of that is missing. What's missing is the moment that connects capture to understanding. After saving an event, the person sees "Saved! AI analyzing in background..." and is immediately navigated back to Home. Nothing ever tells them what Atlas actually understood. The rich review screen already built is effectively undiscoverable - reaching it requires manually finding your own event in the Timeline afterward, and even then, its proposals are shown in isolation, disconnected from the schedule and commercial context that would make them meaningful.

This is precisely the gap this task's own thesis names: the system already does real intelligence work, but the experience still feels like "capture, then hope something happens" rather than "Atlas understood this and connected it to what I already know."

## 2. Why I Chose It

Three reasons, weighed against the alternatives I considered and rejected:

- It is the highest-leverage single fix available. Every capture event, from every role, passes through this exact moment. Closing this loop touches the most frequently-used action in the entire product.
- It requires zero new intelligence. The AI structuring, the proposal generation, the schedule lookahead (project_lookahead_view), and the commercial milestone data all already exist and are already correct. This is orchestration, not invention - directly matching this task's own "prefer orchestration over feature accumulation" instruction.
- It is the task's own worked example, verbatim. The brief's central illustration ("tile work completed" -> next likely activity, milestone eligibility) is not a hypothetical I invented a system for - it's a description of exactly what closing this gap produces, using data that was already sitting in the database, unconnected.

I considered building new variation-detection or schedule/budget-impact reasoning instead, but concluded that inventing new inference on top of an already-existing pipeline whose own output isn't even shown to the user would be optimizing for the wrong problem. Fix the connection before adding more to connect.

## 3. What I Built

Backend:
- backend/services/event_intelligence_service.py - a new, small, pure-composition service. build_event_understanding(event_id) reads an event's existing ai_analyses doc and existing ai_proposals, then grounds two additional connections against real data already in the system:
  - Possible milestone: matches the event's own AI summary against every non-achieved commercial milestone's own trigger field (a human-authored description of exactly what completion looks like for that milestone) - requires 2+ overlapping keywords, never a coincidental single-word match.
  - Possible next activity: matches the same summary against project_lookahead_view's own real dependency-graph output (reasoning_projections.py, unmodified).
  - Both are explicitly labelled "possibly related," never asserted as certain, per this task's own "only surface what can be grounded in existing data" instruction.
- A new route, GET /api/events/{id}/understanding.
- A new notification, notify_understanding_ready() in the existing notification_engine.py, wired directly into intelligence_engine.py's own AI pipeline right after proposal generation completes - reusing the existing status_change category rather than inventing a new one.
- A real, second bug found and fixed while wiring this: the Inbox screen had no deep-link routing case for entity_type='event' at all. Without this fix, tapping the new notification would have silently opened the wrong screen.

Frontend:
- frontend/src/event_intelligence_api.ts - a thin typed client, reusing the existing AiProposal type from ops_api.ts rather than duplicating it.
- A new "WHAT ATLAS UNDERSTOOD" panel on app/event/[id].tsx, placed immediately before the existing AI Proposal section, visible to every role (it's informational, not an action - the proposal review/accept/reject actions themselves remain Management/PM-only, unchanged). Shows the real AI summary, a tappable "may relate to" milestone card (deep-linking to Commercial), and a "next likely" activity card - only when something was actually found.

## 4. Existing Engines / Data Reused

intelligence_engine.py (AI structuring + proposal generation, unmodified), operations_engine.py (list_ai_proposals, attach_names, unmodified), reasoning_engine.py/reasoning_projections.py (project_lookahead_view, unmodified), commercial_engine.py (get_project_commercial_summary, assert_project_visible, unmodified), notification_engine.py (extended with one new function, matching its own established pattern exactly), memory_engine.py (get_event, get_ai_analysis, unmodified).

## 5. New Code Introduced

One new backend service (~140 lines), one new thin route (~20 lines), one new notification function (~15 lines added to an existing file), one new frontend API client (~35 lines), one new panel in an existing screen (~40 lines added), and one deep-link routing case fixed (2 lines). No new collection, no new engine, no new AI call.

## 6. User Workflow Before

Supervisor captures a voice update -> "Saved! AI analyzing in background..." -> bounced to Home -> the AI's own real analysis and proposals exist in the database but are never shown to anyone unless they manually navigate to their own event afterward -> proposals, when eventually found, are shown with no connection to schedule or money.

## 7. User Workflow After

Supervisor captures the same update -> AI processing completes -> a real, targeted notification arrives: "Atlas understood your update" -> tapping it opens the event, showing Atlas's own real summary, a tappable link to the specific milestone this may relate to (with its own real trigger text visible, so the connection is checkable, not just asserted), and the next likely activity from the real schedule -> the existing proposal review sits right below, now with context instead of in isolation.

## 8. How This Makes Atlas Feel Different

The product no longer just performs analysis - it demonstrates understanding, unprompted, at the exact moment a person would want to know it. This is the "construction intelligence" feeling the brief describes, built entirely from work Atlas was already doing but never showing.

## 9. Test Results

- 4 new backend tests: the task's own worked example reproduced exactly (milestone grounded via real trigger text), a negative case confirming no fabricated match occurs when there's genuinely no overlap, an achieved-milestone exclusion case, and the notification's own content.
- Full backend regression suite: 217/217 passing (up from 213 before this feature).
- npx tsc --noEmit: clean.
- npm run lint: 23 problems, unchanged from the established baseline.
- Live-verified through the real API (not code-inspection only): recreated this task's own "tile work completed" example end-to-end - created a real milestone with trigger text "Tile work complete in all bathrooms," captured a real event, and confirmed the correct milestone was found, the notification fired with the correct copy, and the real HTTP endpoint returned it correctly.

## 10. Known Limitations

- Device verification is BLOCKED, the same constraint stated throughout this entire engagement - no Expo/device environment exists in this sandbox. The frontend panel is tsc/lint-verified and its data path is confirmed live through the API; it has not been tapped through on a real screen.
- The milestone/activity matching is a deterministic keyword-overlap heuristic, not semantic understanding - a milestone whose trigger text uses different words for the same real-world event will not be found. This is a deliberate, stated trade-off (grounded and explainable over powerful and opaque), not an oversight.
- possible_next_activity requires the project to have real workflow_activities data; projects without a populated schedule will never show this section - correctly, since there's nothing real to connect to yet.
- The completion notification's own recipient is only the event's own author; broader visibility (e.g., to the assigned PM if different) was not built this pass, matching this task's own "single strongest intervention" instruction over broader scope.
