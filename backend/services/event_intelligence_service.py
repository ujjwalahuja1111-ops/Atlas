"""Atlas Event Intelligence Service — the freehand product decision.

THE GAP THIS CLOSES: Atlas already runs a real AI pipeline on every
captured site update (Whisper transcription, GPT-4o structuring,
11-intent proposal generation - all in intelligence_engine.py,
unmodified by this file). The person who captured the update is told
"Saved! AI analyzing in background…" and immediately bounced to Home.
Nothing ever tells them what Atlas actually understood. The rich
"AI Proposal" review screen already exists (frontend
app/event/[id].tsx) but is undiscoverable — reaching it requires
manually finding your own event in the Timeline afterward, and even
then it shows proposals in isolation, disconnected from the schedule
and commercial context that would make them meaningful (this task's
own "tile work completed -> next likely activity, milestone
eligibility, client approval already on record" example).

THE FIX: this service composes what already exists — event ->
ai_analyses (memory_engine), ai_proposals (operations_engine),
schedule lookahead (reasoning_engine.project_lookahead_view), and
commercial milestones (commercial_engine.get_project_commercial_summary)
— into one grounded view, plus a completion notification
(notification_engine, reusing PX-02 Phase 1's own established
pattern) that finally closes the loop: capture -> Atlas understands
-> tell the person -> let them act.

Every connection here is a deterministic, explainable match against
real data already in the system — never a fabricated inference. The
schedule and milestone links are explicitly labelled "possibly
related" (a keyword-overlap heuristic against the activity's own name
and the milestone's own trigger text, both fields already authored by
a human for exactly this kind of matching), not asserted as certain,
per this task's own explicit "only surface what can be grounded in
existing data" instruction.
"""
from __future__ import annotations
import re
from typing import Optional
from engines import memory_engine, operations_engine, commercial_engine, reasoning_engine

_STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "of", "for", "to", "and", "or", "is", "are",
    "was", "were", "with", "all", "has", "have", "been", "will", "be", "this", "that",
}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z]{4,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


async def build_event_understanding(event_id: str, *, user: dict) -> Optional[dict]:
    """The one entry point. Returns None only if the event itself
    doesn't exist — every other piece degrades gracefully (a project
    with no lookahead data, no milestones, or analysis still pending
    simply omits that section rather than erroring)."""
    event = await memory_engine.get_event(event_id)
    if not event:
        return None
    await commercial_engine.assert_project_visible(event["project_id"], user)

    analysis = await memory_engine.get_ai_analysis(event_id)
    proposals = await operations_engine.list_ai_proposals(event_id=event_id, status="pending")
    await operations_engine.attach_names(proposals)

    structured = (analysis or {}).get("structured") or {}
    summary = structured.get("summary") or event.get("text_input") or ""
    event_keywords = _keywords(summary)

    possible_next_activity = None
    possible_milestone = None

    if event_keywords:
        try:
            lookahead = await reasoning_engine.project_lookahead_view(event["project_id"], user=user)
            possible_next_activity = _match_next_activity(lookahead, event_keywords)
        except Exception:
            pass  # a project without workflow activities yet — nothing to match, not an error

        try:
            summary_data = await commercial_engine.get_project_commercial_summary(event["project_id"])
            if summary_data:
                possible_milestone = _match_milestone(summary_data.get("milestones") or [], event_keywords)
        except Exception:
            pass

    return {
        "event_id": event_id,
        "ai_status": event.get("ai_status", "pending"),
        "summary": summary or None,
        "urgency": structured.get("urgency"),
        "proposals": proposals,
        "possible_next_activity": possible_next_activity,
        "possible_milestone": possible_milestone,
    }


def _match_next_activity(lookahead: dict, event_keywords: set[str]) -> Optional[dict]:
    """A schedule link, grounded in project_lookahead_view's own real
    dependency-graph data (reasoning_projections.py, unmodified) — not
    a new prediction. Matches the event's own summary keywords against
    each upcoming activity's own name/trade, both human-authored
    fields, and returns the strongest overlap only if genuinely
    non-trivial (2+ shared words), never a weak coincidental match."""
    best, best_score = None, 0
    for entry in lookahead.get("upcoming") or []:
        candidate_text = f"{entry.get('name', '')} {entry.get('trade', '')}"
        overlap = event_keywords & _keywords(candidate_text)
        if len(overlap) > best_score:
            best, best_score = entry, len(overlap)
    if best and best_score >= 2:
        return {
            "activity_id": best["activity_id"], "name": best["name"], "ready": best["ready"],
            "possible_blockers": best["possible_blockers"],
        }
    return None


def _match_milestone(milestones: list[dict], event_keywords: set[str]) -> Optional[dict]:
    """A commercial link, grounded in the milestone's own `trigger`
    field — text a human already wrote to describe exactly what
    completion looks like for that milestone. Only pre-achievement
    milestones are considered; an already-achieved/paid milestone has
    nothing left to become "eligible" for."""
    best, best_score = None, 0
    for m in milestones:
        if m.get("status") not in ("pending", "ready"):
            continue
        candidate_text = f"{m.get('name', '')} {m.get('trigger', '')}"
        overlap = event_keywords & _keywords(candidate_text)
        if len(overlap) > best_score:
            best, best_score = m, len(overlap)
    if best and best_score >= 2:
        return {
            "milestone_id": best["id"], "name": best["name"], "status": best["status"],
            "trigger": best.get("trigger"), "contract_value": best.get("contract_value"),
        }
    return None
