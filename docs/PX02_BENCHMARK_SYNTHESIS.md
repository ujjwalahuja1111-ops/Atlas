# PX02_BENCHMARK_SYNTHESIS.md — What the Market Has Already Taught Us

Grounded in fresh research on RDash, Powerplay, Buildertrend, Procore, and Raken (not assumed from training knowledge alone), and mapped against Atlas's own actual, verified capabilities from this engagement — not aspirational claims about what Atlas could someday do.

---

## RDash

**Observed user problem:** Before RDash, construction teams ran on "WhatsApp for approvals, Excel for BOQs and progress tracking, Google Drive for drawings, and disconnected accounting software for finance" — the exact fragmentation this entire Atlas engagement has been built to eliminate. RDash's own answer is a single connected workspace spanning lead-to-handover, with an AI co-pilot that answers plain-language questions about margin and delay rather than requiring a manually-built report.

**Atlas-native response:** Atlas already has the structural answer RDash reaches for — a single, project-scoped data model spanning Reality Capture through Commercial through Closeout, with PL-01's own lifecycle stages already modeling exactly the "pre-sales through handover" continuity RDash markets. Atlas's own CRE (Construction Reasoning Engine) already does deterministic-first reasoning over real operational data — the same "answer a plain question without a meeting" ambition RDash's own co-pilot targets, but built on Atlas's own explicit "deterministic before AI" principle (WF-01) rather than a general-purpose chat layer.

**How Atlas can improve beyond the inspiration:** RDash's own procurement-to-execution continuity is real, but it required building a full BOQ/vendor/PO system to get there — exactly what Atlas has repeatedly, deliberately declined to build (CO-01 through PX-02's own instructions). Atlas's differentiator is that its continuity comes from the *data model itself* being unified from day one (Commercial Engine, Operational Items, and Knowledge Graph all sharing the same project_id and event ledger), not from a procurement module bolted onto a project-management core. The lesson to take is guided setup and lifecycle-oriented navigation (RDash's own strength) — not its procurement depth, which Section 7 explicitly declines to chase.

## Powerplay

**Observed user problem:** Powerplay's own positioning is explicit — its entire value proposition is being faster than WhatsApp, with "sub-60-second" style task capture, and daily logs that connect labour/material/photo entry directly into schedule progress with "no double entry needed."

**Atlas-native response:** This is the one area Atlas already matches or exceeds, confirmed repeatedly across this engagement — Capture (voice/photo/text, one screen, minimal friction) was independently verified as "already correct" in UX-01, UX-02, and re-confirmed fresh in "A Day With Atlas." Atlas's own AI structuring (intelligence_engine.py) already converts a raw voice note into a structured proposal automatically — a step beyond Powerplay's own manual daily-log entry.

**How Atlas can improve beyond the inspiration:** Powerplay's own "no double entry" principle — one update automatically propagating to schedule, inventory, receivables/payables — is a genuine gap Atlas hasn't fully closed. WF-01 built exactly two of ten possible orchestration chains (Milestone Completed, Variation Approved); Powerplay's own architecture suggests the next highest-value chain is "Operational Item resolved → Workflow Activity progress updates automatically," which Atlas's own event ledger already has the data for but doesn't yet wire together.

## Buildertrend

**Observed user problem:** Buildertrend's own client portal exists specifically to "stop the daily 'what's the update?' texts" — homeowners want to see progress, approve change orders, and track payments without calling the office, and Buildertrend's own AI-generated weekly summary automates that update.

**Atlas-native response:** Atlas's own client-facing experience (confirmed correct and unchanged across every UX audit in this engagement) already gives a client visibility into variations, payments, and project status without needing to call the PM — the same underlying goal Buildertrend's portal serves. CM-01's own "Since Last Visit" is structurally the same idea as Buildertrend's AI weekly summary, generalized to every role, not just the client, and built from real event data rather than an LLM narrative.

**How Atlas can improve beyond the inspiration:** Buildertrend's own change-order transparency is explicit and dollar-specific — the homeowner sees exactly what changed and what it costs, before approving. Atlas's own Variation flow (CP-02) already supports this mechanically, but CP-02's own "remaining gaps" report named the exact thing Buildertrend does well and Atlas doesn't yet: a client-facing "why did this change" note when a contract's value moves, distinct from the PM-facing revision note RC1-HARDENING already built. This is a small, concrete gap worth closing.

## Procore

**Observed user problem:** Procore's own strength, and its own most-cited weakness, are the same thing — deep, role-aware information architecture built for large commercial GCs, at the cost of a "steep learning curve" that causes field crews to "default to texts and emails when the platform's workflows feel desktop-first."

**Atlas-native response:** Atlas's own IN-01 and EX-01 packages exist specifically to avoid Procore's own failure mode — deep-linking suggestions directly into the exact form needed, and consolidating what used to be four separate per-project screens into one Workspace, rather than Procore's own broader, deeper navigation tree. Atlas's role-aware landing (PX-01B, RC1-HARDENING) already routes each role to their own correct destination automatically, rather than asking every role to learn the same navigation tree.

**How Atlas can improve beyond the inspiration:** Procore's own document/workflow discoverability is genuinely strong for complex commercial projects — RFIs, submittals, drawing sets. Atlas has deliberately not built this (BOQ, drawings, and document management are all confirmed absent throughout this engagement), which is the correct call for Atlas's own current pilot scope (a turnkey design-build firm, not an enterprise commercial GC), but is worth naming as a genuine capability gap if Atlas ever needs to serve larger commercial general contractors.

## Raken

**Observed user problem:** Raken is described industry-wide as "the benchmark" for pure daily reporting — a structured mobile flow (weather auto-populated, crew count, work performed, materials received, photos) that compiles into a distributable report without requiring a superintendent to write prose at the end of a long day.

**Atlas-native response:** This is the single clearest, most direct opportunity in this entire synthesis. Atlas already captures every input Raken's own daily report needs — voice/photo/text events, operational items, blockers, assignments, health signals — but has never composed them into a single, distributable daily document. Section 5 of this sprint's own Workspace Architecture document designs exactly this, reusing data Atlas already has rather than building new capture surfaces.

**How Atlas can improve beyond the inspiration:** Raken's own daily report is a compilation of what happened. Atlas's own CRE can attach *why it matters* and *what it affects going forward* (forecast impact, health-dimension linkage) to the same data — a report that explains consequences, not just logs activity. This is Atlas's own genuine differentiator over every reviewed competitor, none of which combine field reporting with deterministic operational reasoning in the same document.

---

## Cross-Cutting Pattern, Stated Once

Every competitor reviewed here solves "coordination waste" with the same underlying move: reduce the number of places a person has to look, and reduce the number of times the same information has to be re-entered or re-explained. Atlas has already built the *data* to do this (the event ledger, the Commercial Engine, the CRE, the Knowledge Graph) — what's still missing, consistently, is *composition*: turning data Atlas already has into the single artifact (a daily report, a weekly client update, a prioritized inbox) a real person actually wants to open each morning. That is the single throughline this benchmark synthesis surfaces, and it directly motivates Sections 2, 5, and 6 of the Workspace Architecture and Roadmap documents that follow.
