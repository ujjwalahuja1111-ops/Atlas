# Beta-05 — Construction Intelligence Report

Per this sprint's own mandatory requirement, this report begins with the Capability Audit.

---

## Capability Audit

| # | Capability | Status | Action |
|---|---|---|---|
| 2 | Explain Health | NEW - built this pass | This sprint's own named "largest remaining gap." Built explain_health(): Score to Dimensions to Drivers to Recommended Actions, composed entirely from project_health() and list_insights() called exactly as they already exist. See below for the full account, including a real distinction this implementation surfaces rather than hides. |
| 1 | Executive Dashboard - Portfolio Health, Projects at Risk, Delayed Projects, Critical Operational Items, Pending Approvals, Payment/Variation Exposure | VERIFIED (largely pre-existing) | portfolio_control_center() already composes all of this per-project, plus real financials (Beta-01/Beta-02). Confirmed by direct inspection, not rebuilt. |
| 1 | Upcoming Milestones (portfolio-wide) / Recent Site Activity (portfolio-wide) / Daily Review Highlights (integrated into one dashboard) | GAP - not addressed this pass | Genuinely missing from the existing Portfolio Control Center. Named explicitly rather than assumed covered. |
| 3 | Project Risk (deterministic, rule-based) | VERIFIED (already exists, differently named) | CRE's own evaluate_rules() already produces exactly this - deterministic, rule-based findings across delayed workflow, blocked activities, critical operational items, pending inspections, pending approvals, commercial delays. explain_health's own "Drivers" section is this signal, surfaced. No second risk system was built. |
| 4 | Priority Engine (single ranked attention list) | GAP - not addressed this pass | explain_health's recommended actions are ranked by severity per project; a single cross-project ranked list was not built this pass. |
| 5 | Cross-Project Intelligence (repeated blockers/delays/shortages/contractor issues/approval bottlenecks) | GAP - not addressed this pass | Not attempted. |
| 6 | Commercial Intelligence (over budget, large pending variations, payment bottlenecks, cash-flow concerns) | VERIFIED (largely pre-existing) | Commercial Workspace (Beta-02) and Portfolio financials (Beta-01) already surface budget variance, pending variations, and cash-flow signal per project. Not composed into a single cross-project "Commercial Intelligence" narrative this pass. |
| 7 | Operational Recommendations, evidence-cited | NEW - built this pass, as part of Explain Health | explain_health's recommended actions ARE this capability - each one traces to a real, open, persisted CRE insight with its own rule_id and observation (the evidence), and a suggested_operational_action CRE already computes and has never fabricated (Sprint 01A's own architectural boundary: CRE names what a human could do, never creates the item). Verified directly: every recommended action's insight_id was checked to exist among the project's own real open insights. |
| 8 | Management Timeline (one executive chronological history) | GAP - not addressed this pass | timeline_engine.for_project_commercial and for_site both exist independently; a single composed executive timeline merging Commercial/Operations/Workflow/Reality/Approvals/Client was not built. |
| 9 | Portfolio Search | GAP - not addressed this pass | Not audited or built. |
| 10 | Cross-validation | PARTIALLY VERIFIED | explain_health's score/dimensions/drivers confirmed byte-identical to project_health's own output via a permanent regression test - not merely similar, identical. The fuller chain this sprint names (Health -> Dashboard -> Recommendations -> Commercial -> Daily Review -> Site Progress) was not independently re-verified beyond this one link. |
| 11 | Performance Review | NOT AUDITED | explain_health adds one additional list_insights call beyond what project_health already made - a real, small cost, not zero, and not measured against a specific threshold this pass. |
| 12 | End-to-end walkthrough using RP-001/RP-002 | PARTIALLY COMPLETED | Explain Health verified end-to-end against real, live ACDP data (156 real recommended actions, genuinely evidence-backed). The broader walkthrough this sprint describes (contractor attention, commercial impact in one five-minute view) was not attempted, since the Executive Dashboard itself was not rebuilt this pass. |

---

## Explain Health — full account

Built as reasoning_engine.explain_health(project_id, user), composing two existing functions exactly as they already exist:

- Score, status, dimensions, drivers, progress - read directly from project_health(), unchanged, recomputed fresh from the live snapshot on every call.
- Recommended actions - read directly from list_insights(project_id, user, status="open")'s own stored insights, each already carrying a rule_id, severity, observation (the evidence), and a suggested_operational_action CRE's own reasoning already computed (never fabricated for this sprint - the field has existed since CRE's own Sprint 01A, this pass just exposes it composed with health for the first time).

An honest distinction surfaced explicitly, not hidden: dimensions and drivers are always current, recomputed live. Recommended actions reflect whatever CRE's last completed reasoning run persisted for that project - which could be stale if no recent run has happened. Rather than presenting both as equally "live," the response includes an action_currency block stating this plainly, with the count and timestamp of the underlying insights.

Verified end-to-end against real, live ACDP data: score 40 (red), 5 dimensions, 8 drivers, 156 real recommended actions - including, genuinely, "Inspect 'Snagging Inspection Round 2 — Main Residence'," matching this sprint's own worked example ("Inspect Project A") almost exactly, because it's real evidence-backed output, not a written example. Client correctly blocked (403), matching the existing /health route's own RBAC exactly.

A dedicated frontend screen (app/explain-health/[id].tsx) was built and wired into the Project Dashboard, since no health display existed anywhere on the management/PM side before this pass.

---

## Cross-Validation

explain_health's score/status/dimensions/drivers confirmed byte-identical to project_health's own independent output, via a permanent regression test comparing both directly - not just visually similar, structurally identical, which is the actual guarantee "never a second health calculation" requires.

---

## Remaining Known Gaps — Named Explicitly

This sprint's own scope is large (12 areas); one was built thoroughly and verified, one was confirmed already substantially covered by existing capability, and the remainder are genuine gaps:

1. Upcoming Milestones / Recent Site Activity / Daily Review Highlights not yet integrated into a single Executive Dashboard view (though each individually exists).
2. Priority Engine - a single cross-project ranked attention list was not built; explain_health's own severity ranking is per-project only.
3. Cross-Project Intelligence (repeated blockers, delays, shortages, contractor issues, approval bottlenecks) - not attempted.
4. Commercial Intelligence as a unified cross-project narrative - the underlying data exists per-project (Beta-01/Beta-02) but wasn't composed into one view this pass.
5. Management Timeline - a single executive chronological history merging every domain was not built.
6. Portfolio Search - not audited or built.
7. Performance - not measured against a specific threshold.

Given the scale of what remained, this pass deliberately prioritized building and thoroughly verifying the single most explicitly-named capability (Explain Health, called out directly as "the largest remaining gap") over attempting shallow progress across the other eleven areas - consistent with this engagement's own established practice across every prior sprint.

---

## Testing

- 4 new regression tests (111 total in the established pure-unit + mongomock baseline, up from 107, all passing).
- npx tsc --noEmit: zero errors, project-wide.
- End-to-end verification against real, live ACDP data through the actual HTTP API, including RBAC (client correctly blocked).

---

## Files Changed

- backend/engines/reasoning_engine.py - new explain_health().
- backend/routes/reasoning.py - new /projects/{id}/explain-health route.
- backend/tests/test_dev02_bootstrap_reliability.py - 4 new tests.
- frontend/src/cre_api.ts - new ExplainedHealth/RecommendedAction types and apiExplainHealth.
- frontend/app/projects/[id].tsx - Explain Health navigation entry point.
- New: frontend/app/explain-health/[id].tsx.

---

## Beta-05 Readiness Assessment

The single capability this sprint's own brief names as the largest remaining gap is now genuinely built, verified against real evidence-backed data, and cross-validated to be identical to its own underlying source of truth rather than a parallel calculation. The composition itself - reusing project_health and list_insights exactly as they already existed, adding zero new calculation - is a direct demonstration of this sprint's own stated philosophy: Construction Intelligence as an orchestration layer, not a new reasoning system.

Recommendation: Stable with Known Issues — not "Complete." Eleven of this sprint's twelve numbered areas remain either partially covered by pre-existing capability (Executive Dashboard's core, Commercial Intelligence's underlying data) or genuine, unaddressed gaps (Priority Engine, Cross-Project Intelligence, Management Timeline, Portfolio Search). The Capability Audit above states this plainly rather than implying broader completion. The most valuable next step, given what already exists, is composing Portfolio Control Center's existing per-project rows into the still-missing cross-project views (Priority Engine, Cross-Project Intelligence) - the underlying data for most of them already exists project-by-project; the gap is aggregation, not new calculation.
