# ATLAS INTENT & ORCHESTRATION — PRODUCT SPECIFICATION v1

**Status: design/architecture document. No production code was modified to produce this document.**

This specification is grounded strictly in `docs/ATLAS_ASSISTED_CONSTRUCTION_AUDIT.md` and in the repository itself — every mechanism referenced below as "existing" was re-verified against the actual code while writing this document, not assumed from the audit's own summary. Three additional facts were confirmed specifically for this specification, none of which were fully settled in the audit:

- **`reference_portfolio/` is not historical multi-project data.** It is two permanent, hand-authored synthetic projects (`scripts/reference_portfolio.py`), explicitly built for "regression testing, demonstration, and future AI validation" — a known-answer test fixture, not a source of real comparable-project or benchmark intelligence. This directly shapes Item 28 below.
- **There is no existing conversation or session-persistence mechanism anywhere in Atlas.** Every `session_id` in the codebase (`reasoning_engine.py`, `intelligence_engine.py`) is a fresh, random UUID generated per LLM call — stateless by design, never stored, never reused across turns. This is a genuine greenfield requirement, not an extension of something that already exists (Item 19).
- **A "which project am I in" mechanism already exists on the frontend** — `getActiveSite()` / `setActiveSite()` (`frontend/src/api.ts`), local persistence of the user's current site/project. This is the natural foundation for context resolution (Item 6), not something to invent from scratch.

---

## 1. User Interaction Model

Atlas's existing five-destination structure (Home / Projects / Capture / Inbox / More) is kept unchanged, per the audit's own Section H finding that this structure already maps cleanly onto real needs. The new interaction model adds exactly one new surface: a persistent intent box at the top of Home, available to every role, that accepts typed or spoken input and answers the question "How can Atlas help?"

This is **not** a chat window layered beside the app. It has no message history UI, no "conversation" visual metaphor, and no persona. It behaves like a command box that happens to understand natural language: the user gives it one input, Atlas does the work, and the result appears as the same kind of structured screen Atlas already shows elsewhere (a card, a draft entity for review, an existing detail screen it navigates to) — never as a chat bubble. This distinction matters because it is the difference between "Atlas gained a chatbot feature" and "Atlas gained a new way in" — the brief is explicit that only the second is being asked for.

Every role sees the same intent box; what it can *do* is governed entirely by the existing RBAC layer (Item 18), not by a different UI per role.

## 2. Text Input Model

Typed input is the first entry point to build (see Item 30), because it has no audio-pipeline risk and proves the orchestration model end-to-end. The text box:

- Accepts a single free-text sentence or short paragraph.
- Sends it, verbatim, to the structuring pass (Item 4) — no client-side pre-parsing, keyword matching, or intent guessing in the frontend. Exactly one place resolves intent, matching the audit's Finding 5 principle.
- Shows a lightweight "Atlas is thinking" state while the structuring call and any read-only engine calls run — reusing the same loading-state conventions already used elsewhere in the app (e.g. Capture's own "Saved! AI analyzing in background…", generalized rather than duplicated with new copy).

## 3. Voice Input Model

Voice is text input with one extra step in front of it: Whisper transcription, using the exact transcription call `intelligence_engine._structure()` already makes for Capture — not a second transcription implementation. Once transcribed, the resulting text enters the identical pipeline as typed input (Item 23) with no branching logic downstream of transcription.

This directly satisfies the brief's own instruction not to build two separate intelligence systems for text and voice. The only voice-specific work is: capturing audio (already built, `useVoiceRecorder` hook, generalized beyond the Capture screen to the intent box), and handling transcription failure gracefully (already a solved problem in Capture's own error handling, per `PX04_ROLE_FIRST_FIELD_UX.md`).

**Mixed-language input** (the brief's own Hindi/English example) requires no separate handling in this architecture: Whisper already transcribes mixed-language speech into text reasonably, and the structuring LLM call already receives whatever language mix comes out — GPT-4o's own multilingual capability, not a new capability Atlas must build. This is a genuine claim worth stating carefully: Atlas's role is to route the transcript into structuring, not to itself contain any language-specific logic.

## 4. Intent Taxonomy

A closed, named set of intents — not an open-ended free interpretation — because a closed taxonomy is what makes `required_engines` selection (Item 10) deterministic rather than another LLM decision. Derived directly from the audit's own 10 scenarios and the existing engine capabilities:

| Intent | Example | Primary Engine(s) |
|---|---|---|
| `capture_reality` | "Ravi says the marble won't arrive until Friday." | `reality_engine`, `intelligence_engine` (existing Capture pipeline, unchanged) |
| `create_variation` | "Client wants quartz instead of granite." | `commercial_engine` |
| `create_project` | "Create a 4,000 sq ft luxury residence in Chandigarh." | `commercial_engine`, `workflow_engine`, `knowledge_engine` |
| `prepare_commercial_schedule` | "Prepare the payment schedule: 20/30/30/20." | `commercial_engine` |
| `prepare_budget` | "Make a preliminary budget." | `commercial_engine`, `knowledge_engine` |
| `query_health` | "Why is this project at risk?" | `reasoning_engine.explain_health()` (existing, unchanged) |
| `query_schedule_impact` | "Check if this affects handover." | `workflow_engine`, `reasoning_projections.project_lookahead()` |
| `query_digest` | "What's happening on my projects today?" | `reasoning_engine` (`since_last_visit`, `my_day`, daily digest — existing, unchanged) |
| `query_comparison` | "Compare with our previous residential projects." | `reasoning_engine.compare_projects()` (existing, unchanged) |
| `dispatch_notification` | "Tell the PM about this." | `notification_engine` |
| `unresolved` | Input that doesn't map to any of the above with sufficient confidence | None — routed to a clarifying question, never guessed |

This taxonomy is intentionally exhaustive of the audit's own 10 scenarios and no larger — new intents are added only when a new real workflow is identified, not speculatively, matching the brief's explicit "do not overbuild" instruction.

## 5. Context Resolution

Context resolution answers: *which project, which site, which recent record is "this" or "it" referring to?* Three sources, checked in this order:

1. **Explicit mention in the input itself** ("in Sharma Residence") — resolved via a project-name lookup against the user's own visible project list (existing RBAC-filtered query, not a new capability).
2. **The existing `getActiveSite()` frontend state** — if the user is currently inside a specific project's Workspace when they invoke the intent box, that project is the default context. This reuses existing, working infrastructure rather than inventing a new "current project" concept.
3. **Most recent activity** — if neither of the above resolves unambiguously, the user's most recently touched project (from existing activity data, no new tracking required) is offered as a *suggestion*, never silently assumed.

If none of the three resolves with reasonable confidence, Atlas asks one clarifying question ("Which project?") rather than guessing — this is the audit's own Section I principle, restated as a concrete rule.

## 6. Project Resolution

A refinement of Item 5 specifically for the `create_project` intent, where there is by definition no existing project to resolve *into* — the project doesn't exist yet, so "project resolution" instead means resolving whether the input describes a *new* project or an update to an *existing* one (e.g. "the residence in Chandigarh" could be a new project or a reference to one already underway). This is resolved by checking the input against the user's existing visible project names first; only when there is no plausible match does Atlas treat it as a creation request.

## 7. Entity Extraction

Entities are intent-specific fields extracted in the *same* structuring call as the intent itself (Item 10's "one structured interpretation" principle) — never a second LLM pass. Examples, grounded in the audit's own scenarios:

- `create_project`: contract value, location, area, project type, target duration, client name
- `create_variation`: affected material/area, the change described, any stated cost hint
- `prepare_commercial_schedule`: percentage splits and their associated milestone triggers
- `capture_reality`: the same fields `intelligence_engine._structure()` already extracts today (materials, labour, equipment, urgency) — reused, not reinvented

Entities extracted with low confidence are carried into the assumption model (Item 9) rather than silently discarded or silently trusted.

## 8. Confidence Model

Every extracted intent and every extracted entity carries one of three confidence levels — `high`, `medium`, `low` — assigned by the same structuring LLM call, not computed separately. This mirrors the existing pattern already in `reasoning_engine._ai_review()`, which assigns and clamps a `confidence` field on every AI-derived observation (confirmed in that function's own code). The rule that follows from confidence is fixed, not per-feature:

- **High confidence, low-stakes intent** (a query) → answered directly.
- **High confidence, high-stakes intent** (a variation, a project) → prepared as a draft, confirmation required (Item 14).
- **Medium or low confidence, any intent** → Atlas states its interpretation explicitly before acting ("I understood this as a variation request for the kitchen counters — is that right?") rather than silently proceeding.
- **Confidence below a fixed floor** → treated as `unresolved` (Item 4), a clarifying question is asked.

## 9. Assumption Model

Every field Atlas fills in without the user explicitly stating it is tagged with exactly one of the audit's own five trust labels — FACT / INFERRED / SUGGESTED / ASSUMED / REQUIRES CONFIRMATION — carried as structured metadata on the interpretation object (Item 10), not just phrased carefully in UI copy that could drift from what actually happened. This is a hard architectural requirement, not a presentation guideline: the draft-state entity (Item 13) stores these tags per field, so a user reviewing a draft project sees, field by field, which numbers Atlas is confident about and which are guesses requiring their attention — directly implementing the brief's own repeated instruction never to let a suggestion look like a fact.

## 10. Engine-Selection / Orchestration Model

The intent → `required_engines` mapping is a **fixed lookup table** (Item 4's own taxonomy row-by-row), not a decision the LLM makes at runtime and not a second AI call. Once intent is known, engine selection is deterministic Python — exactly the discipline the audit's Finding 5 documents Atlas already following in its only two real AI call sites. Concretely:

```
structured = await intent_structuring_pass(user_input)   # ONE LLM call
engines_to_call = INTENT_ENGINE_MAP[structured.intent]     # plain dict lookup, no AI
results = await asyncio.gather(*[
    call_engine(e, structured.context, structured.entities) for e in engines_to_call
])
```

Every function inside `call_engine()` is an existing, already-tested engine function (`commercial_engine.create_variation`, `reasoning_engine.explain_health`, etc.) — the orchestration layer contains no business logic of its own, only dispatch. This directly satisfies the brief's own "do not duplicate business logic inside the UI" and "do not create a second business-logic layer" instructions.

## 11. Read-Only Query Architecture

The lowest-risk category, and per the phased roadmap in the audit (Phase 3), the first orchestration category to build. A read-only query (`query_health`, `query_digest`, `query_schedule_impact`, `query_comparison`) never writes anything and therefore requires no draft state, no confirmation gate, and no new audit trail beyond what already exists — it is a fan-out of existing `GET`-equivalent engine calls, exactly as `reasoning_engine.py` already does internally when composing a portfolio digest. The response is the union of those calls' real outputs, phrased as prose by template composition (Item 12), never by a second LLM pass over the results.

## 12. Recommendation Architecture

Directly implements the audit's own Section K. A recommendation is always built from four parts, each sourced from existing, deterministic engine output — never generated as free LLM prose over the raw data:

1. **What happened** — the deterministic fact (e.g. `commercial_engine`'s payment-request status)
2. **Why it matters** — impact framed in units the user already sees elsewhere (₹, days, %), computed by the relevant engine, not reworded by an LLM
3. **What should happen** — template-composed text, following `daily_site_report_service.py`'s own proven pattern (confirmed in that file's own comments: "deterministic template composition, not LLM prose")
4. **Evidence** — a link into the existing "View Calculation" screens (`explain/[type]/[id].tsx`, `explain-health/[id].tsx`), reused unchanged rather than duplicated

This keeps every recommendation's *reasoning* auditable by construction: if a recommendation's text can be traced back through a template to specific engine output, there is no point where an LLM could have silently introduced an unverifiable claim.

## 13. Draft / Proposed-State Architecture

The single largest genuinely new architectural primitive this specification introduces, matching the audit's own explicit finding that no such state exists in Atlas today. A draft is:

- **A new, lightweight wrapper**, not a new copy of each entity type's own schema. Conceptually: `{ id, target_entity_type, target_entity_fields, field_trust_labels (Item 9), created_by, created_at, status: "pending_review" | "confirmed" | "discarded", source_input }`.
- **Never written into the entity's own real collection** until confirmed. A draft project does not appear in `projects` (and therefore not in any other engine's queries) until promotion; a draft variation does not appear in `commercial_engine`'s own variation list until promotion. This is the mechanism that makes the confirmation gate (Item 14) real rather than cosmetic.
- **Promoted via the entity's own existing creation function**, unmodified — e.g. a confirmed draft project calls the same `create_project()` (or equivalent) the manual wizard already calls. The draft layer never reimplements entity creation logic; it only delays the moment that logic runs until a human has confirmed it.
- **Visually distinct** wherever it can appear (Item 17's "prepares" tier in the audit) so a user can never mistake a draft for a live record.

## 14. Confirmation Architecture

Directly implements the audit's own Section L trust table, restated as an enforcement rule rather than a UX guideline:

| Tier | Rule |
|---|---|
| Informs | No confirmation gate — a query response is never a write |
| Suggests | Shown; the user may act on it through the entity's own existing UI, but Atlas takes no write action itself |
| Prepares | A draft (Item 13) is created; **cannot** be promoted to a real entity without an explicit user action |
| Asks confirmation | Same as Prepares, but for actions with financial, contractual, or cross-user consequence — the existing server-side rule that a PM cannot approve their own payment request is the model: this tier's confirmation requirement is enforced in the engine layer itself, not only in the orchestration layer, so it cannot be bypassed by a future caller that skips the intent box entirely |
| Executes automatically | Permitted only for actions with no financial/contractual/audit-irreversible consequence (the brief's own carve-out) — in this specification, limited to `dispatch_notification` where the recipient and content are unambiguous |

## 15. Execution Architecture

Execution never happens inside the orchestration layer's own code — it always calls the target engine's existing write function (`create_variation`, `create_milestone`, `notification_engine.create_notification`), passing exactly the confirmed, human-reviewed field values. The orchestration layer's only responsibility at this stage is: confirm the confirmation gate (Item 14) was actually satisfied, then delegate. This guarantees the orchestration layer can never become a second source of truth — every fact it produces was already computed by an existing engine; every write it performs was already validated by an existing engine's own existing validation logic (e.g. `commercial_engine`'s own amount/status checks, unchanged).

## 16. Audit / History Behaviour

No new audit mechanism is introduced. Every entity the orchestration layer eventually creates becomes a normal Event or record through the entity's own existing creation path (Item 15), which means it is already covered by Atlas's existing immutable-Event history (`memory_engine`) and by each engine's own existing audit fields (`created_by`, `created_at`). The one addition: the *source input* that led to the action (the original sentence or transcript) is stored on the draft (Item 13) and, on promotion, referenced from the created entity — so "why does this variation exist" can always be traced back to the exact words that prompted it, extending rather than replacing the audit trail that already exists.

## 17. Error / Failure Behaviour

Three distinct failure modes, each handled differently:

- **Structuring call fails** (the LLM is unavailable or returns unusable output) — the intent box shows a plain failure message and nothing is guessed; this mirrors `reasoning_engine._ai_review()`'s own "total failure isolation" pattern (confirmed: any exception returns `[]`), generalized to the intent layer.
- **Intent resolves but confidence is below the floor** (Item 8) — not a failure, a clarifying question.
- **A required engine call fails** during orchestration (Item 10's fan-out) — the user sees which specific fact could not be retrieved, and the response is built from whatever succeeded, rather than the entire response failing because one engine call did. This matches the existing pattern in `event_intelligence_service.py`, where a lookahead or milestone-match failure is caught individually and simply omits that section rather than failing the whole response (confirmed in that file's own `try/except` structure).

## 18. Authorization / RBAC Behaviour

The orchestration layer performs **zero authorization logic of its own**. Every engine call it makes goes through the exact same role/visibility checks that call already enforces when invoked from an existing route (e.g. `commercial_engine`'s own `assert_project_visible`, confirmed unchanged throughout this entire engagement's prior work). Concretely: if a Site Supervisor's input resolves to `query_health` for a project, the orchestration layer calls `explain_health()` with that Supervisor's own real user object — and if that function already restricts commercial detail from a Supervisor, the intent-layer response inherits that restriction automatically, because it is the same function producing the same output it always has. This is the direct implementation of the audit's Section O principle 7 ("role-based visibility is enforced once, server-side, and never re-implemented").

## 19. Conversation / Context Persistence

As established in the preamble, no conversation persistence exists in Atlas today — every LLM call is a stateless, single-turn UUID session. This specification proposes the **minimum** persistence necessary, not a general chat-history feature:

- **Within a single intent exchange** (the structuring call, the clarifying question if one was needed, the user's follow-up answer), short-lived state is held only long enough to complete that one exchange — not stored permanently, not visible as a "conversation" anywhere in the UI.
- **Across separate exchanges**, Atlas relies on the *existing* context sources (Item 5: active project, recent activity) rather than a memory of what was previously typed. If the user says "tell the PM about this" in a new, unrelated intent-box invocation, "this" resolves from the same active-project/recent-activity logic every other intent resolves from — not from a remembered chat log.
- This is a deliberate, named scope limit: true multi-turn conversational memory ("as I mentioned earlier...") is explicitly **not** built in Phase 1 (Item 30) or implied to exist. Building it prematurely would be exactly the kind of "general-purpose autonomous agent" scope creep the brief explicitly warns against.

## 20. How Corrections Work

Atlas already has a real, working correction mechanism — `memory_engine`'s own append-only `corrections` pattern, where a fact is never overwritten in place but a correction is linked alongside the original (confirmed in `knowledge_engine.py`'s own header, which explicitly cites this as an existing ADR-established convention). The intent layer reuses this exact pattern rather than inventing a second one: if a user says "no, that should have been the bathroom, not the kitchen" immediately after a capture, this is handled as a correction against the just-created record (the existing mechanism), not as a new intent type. If the correction targets a *draft* still in `pending_review` (Item 13), it is simpler still — the draft's own fields are edited directly, since nothing has been promoted to a real record yet and there is nothing to "correct" in the audit-trail sense.

## 21. How "I Meant Another Project" Works

A specific case of Item 5 (Context Resolution) failing softly rather than hard. If Atlas resolved context to Project A and the user corrects it ("no, the other one — Sector 21"), this is treated as a fresh context-resolution pass with the correction text as an additional signal, re-run against the same three-source logic in Item 5 — not a special-cased conversational memory feature. Because no entity has been written yet (Item 13's draft gate), correcting the project before confirmation has zero cleanup cost: the draft is simply re-targeted.

## 22. How Multi-Step Conversations Work

Given Item 19's deliberate scope limit, "multi-step" in this specification means specifically: **one intent, one clarifying question, one answer** — not an open-ended back-and-forth. Example: user says "prepare the payment schedule" with no project in context and more than one plausible active project; Atlas asks "Which project?"; the user's next message is treated as the answer to that specific question (held in the short-lived exchange state from Item 19), not as a brand-new, independently-resolved intent. Once that one clarifying round completes, the exchange is finished and stateless again. Anything requiring more than one clarifying round in practice is a signal the original input was too ambiguous for this interface, and Atlas says so plainly rather than continuing to guess.

## 23. How Text and Voice Share the Same Pipeline

Stated explicitly as its own item because it is a hard architectural constraint, not just a convenience: **the structuring pass (Item 4) accepts one input shape — text — regardless of source.** Voice input's only special-cased code path is transcription (Item 3); the moment a transcript exists, it is indistinguishable, to every downstream component, from text the user typed directly. There is no `if voice: ... else: ...` branch anywhere past the transcription step. This is verified against the existing Capture pipeline's own design (`intelligence_engine._structure()` already accepts `transcript` and `text_input` as alternative sources feeding the *same* structuring call) — the intent layer generalizes an already-proven pattern rather than inventing a new one.

## 24. How Existing Capture Intelligence Is Generalized

`intelligence_engine._structure()` today does exactly one thing well: turn a captured event's voice/text/photos into a structured construction record, then generate Operational Item proposals from it (11 intents, already built). The intent layer's own structuring pass is this same function's *output shape*, generalized from one intent (`capture_reality`, effectively) to the full taxonomy in Item 4. Concretely: the intent layer does not replace `_structure()` — `capture_reality` inputs are routed to the *existing, unmodified* Capture pipeline exactly as they are today; the intent layer's new structuring pass exists specifically for the other 9 intents that pipeline was never built to handle (project creation, variations, queries, etc.). This is the most literal expression of the brief's own "generalize that architecture" instruction: one proven pattern, extended to more inputs, not duplicated.

## 25. How Project-Type Intelligence Works

Directly addressing the brief's own central example. When `create_project` resolves, entity extraction (Item 7) pulls project type, location, scale, and quality level from the input. These four fields drive a **deterministic lookup** against `knowledge_engine`'s own existing taxonomy — specifically `workflow_template` items (already the exact mechanism `generate_workflow()` consumes, per the audit's Finding in Section F scenario 3) and `phase`/`activity`/`checklist_template` items. Where a template exists for a reasonably close match, its structure is proposed (tagged INFERRED, per Item 9) as the preliminary programme, phases, and milestones. Budget structure (Item 27) and contingency are proposed similarly from the taxonomy's own `category` items. **Where no template reasonably matches** (a genuinely novel project type), Atlas says so explicitly rather than forcing an ill-fitting template — this is a real limit, not a gap to be hidden by generic-sounding output.

## 26. How Preliminary Timelines Are Proposed

A direct consequence of Item 25: once a `workflow_template` is matched, its own activities carry the same duration/dependency data `workflow_engine.generate_workflow()` already uses to build a real activity graph for an existing project. The preliminary programme is this same graph, generated against the *proposed* project (a draft, per Item 13) rather than a real one, with a start date anchored to whatever the user stated ("starting next month") and every subsequent date computed by the same dependency-graph math `reasoning_projections.py` already performs for real projects — not a new date-estimation algorithm. Every date in the preliminary programme is tagged INFERRED; none is presented as a committed schedule until the project itself is confirmed and the actual start date is fixed.

## 27. How Preliminary Budgets Are Proposed

Mirrors Item 26 for the commercial side. The taxonomy's own `category` items (already part of `knowledge_engine`) provide the standard budget-category breakdown; the stated contract value (an entity extracted directly from the input, tagged FACT since the user stated it) is distributed across categories using **typical proportions Atlas can state it is applying, not proportions presented as derived from real historical data it does not have** — this is the audit's own Finding 2 applied directly: Atlas has no real historical cost-distribution data, so a preliminary budget must be honestly labelled ASSUMED at the category level, with the stated total contract value being the only FACT-tagged figure in the whole structure. This is a deliberately more conservative claim than a system with real historical data would be entitled to make.

## 28. How Existing Reference Portfolio Data Can and Cannot Be Used

Stated plainly, per this specification's own preamble finding:

- **Can be used** as a **test fixture** to validate that the intent layer produces correct answers against a known state — e.g. "why is RP-001 at risk?" has a known-correct answer (`health_status: "Critical"`, `health_score: 40`, per its own `expected_state.json`) that the intent layer's `query_health` response can be automatically checked against during development. This is a genuinely valuable, immediately-usable role for this data.
- **Cannot be used** as a source of comparable-project benchmarking, typical-duration estimation, or vendor-performance intelligence. Two hand-authored synthetic projects, built explicitly for regression testing, are not a statistically meaningful sample of anything, and presenting a suggestion derived from them as if it reflected real portfolio history would directly violate this specification's own trust model (Item 9). Any future feature that wants to say "your last 3 residential projects averaged 14 months" needs real project history accumulated over time (Item 29) — this data does not shortcut that requirement.

## 29. How Future Institutional Memory Can Be Introduced Without Pretending It Already Exists

The audit's Section N #20 named this explicitly as out of scope for all 10 roadmap phases; this specification does not change that. What it does define is the **honest path** to eventually building it, so the intent layer's own architecture doesn't foreclose it:

- The draft/promotion model (Item 13) already creates a natural point to eventually capture *why* a decision was made (the source input is already stored, per Item 16) — this is the raw material future pattern-learning would need, being captured as a side effect of Phase 1 even though nothing reads it for that purpose yet.
- No feature in this specification claims to detect "recurring delays" or "vendor performance" from day one. When and if enough real project history accumulates, a genuinely new, separate capability would read that accumulated history — this specification deliberately does not design that capability now, because designing it against data that doesn't exist yet would produce speculative architecture rather than grounded design, the same failure mode Item 28 warns against.
- The single concrete thing this specification does now, to keep that future door open honestly: every draft and every promoted entity retains its own source input and its own assumption tags (Items 9, 13, 16) — real, structured history that a future institutional-memory feature could eventually learn from, once there is enough of it to learn anything real.

## 30. The Minimum Viable Phase 1 Implementation

Directly matching the audit's own Phase 1 + Phase 2 + the read-only slice of Phase 3 (its lowest-risk, highest-confidence combination):

1. **The structuring pass** (Item 4's taxonomy, Items 7-9's entity/confidence/assumption model) — one new, small module, following `intelligence_engine._structure()`'s own pattern.
2. **Text input only** (Item 2) — no voice yet; voice is Item 3 / audit Phase 6, deliberately sequenced after text proves the model.
3. **Read-only intents only**: `query_health`, `query_digest`, `query_schedule_impact`, `query_comparison` (Item 11) — zero new write paths, zero draft-state requirement, zero new confirmation logic needed for Phase 1 specifically.
4. **Context resolution** (Item 5) reusing the existing `getActiveSite()` mechanism — no new persistence.
5. **The one-round clarifying question** (Item 22) for ambiguous project context — the only piece of "conversation" state Phase 1 needs.
6. **Explicit non-goals for Phase 1**, stated directly so scope does not silently creep: no `create_project`, no `create_variation`, no draft-state architecture (Item 13), no voice, no write actions of any kind. These are real, valuable, and sequenced deliberately later (audit Phases 5, 7, 8) — after the orchestration model has been proven safe on read-only queries first.

Phase 1 is deliberately small enough to ship with no new confirmation model, no new draft-entity architecture, and no new audit-trail requirements — every one of its four supported intents is a read, and every read already goes through an existing, correct, already-tested engine function. The risk this phase carries is entirely in the structuring pass's own accuracy, not in anything it writes — because it writes nothing.

---

## Required Example Flows

Ten fully worked flows, each following: USER INPUT → INTENT → CONTEXT → ENTITIES → ENGINES INVOKED → FACTS → INFERENCES → RECOMMENDATION → CONFIRMATION → ACTION → FINAL USER OUTPUT. Every engine call named below is a real, existing function, verified against the repository; every gap is named as a gap, not silently filled.

### Flow 1 — "Create a 4,000 sq ft luxury residence in Chandigarh."

- **Intent:** `create_project`
- **Context:** None — new entity (Item 6)
- **Entities:** area (4,000 sq ft, FACT), location (Chandigarh, FACT), project type (residential/luxury, INFERRED from "luxury residence")
- **Engines invoked:** `knowledge_engine` (template match against `workflow_template` items for residential/luxury), `commercial_engine` (category structure only — not a real budget yet)
- **Facts:** Area and location, as stated
- **Inferences:** A matching workflow template, if one exists (ASSUMED it produces a reasonable fit); no contract value can be inferred — the audit already confirms no benchmark data exists (Finding 2/Item 28), so this is asked for, not guessed
- **Recommendation:** "I can prepare a preliminary project structure based on a similar residential template. I still need a contract value and start date to complete the programme."
- **Confirmation:** Required before promotion (Item 14, "Prepares" tier) — this is a named, real entity
- **Action:** A draft project + draft workflow activities (Item 13), not yet real
- **Final user output:** "I've prepared a preliminary structure using our residential template — [N] phases, [M] milestones (all INFERRED, review before confirming). I still need: contract value, start date. [Review Draft]"

### Flow 2 — "Client wants quartz instead of granite."

- **Intent:** `create_variation`
- **Context:** Resolved via `getActiveSite()` (Item 5) or explicit project mention
- **Entities:** material change (granite → quartz, FACT — the user stated it), affected area (unstated — ASSUMED "kitchen counters" only if a recent related capture exists, otherwise left blank and asked for)
- **Engines invoked:** `commercial_engine.create_variation()` (draft), `knowledge_graph_engine` (check for a related recent Capture event, per the existing Observation→Variation relationship this engine already traverses)
- **Facts:** The material change itself
- **Inferences:** Cost impact — **a genuine gap**: Atlas has no material-pricing database, so cost impact is not inferred, it is left blank and marked REQUIRES CONFIRMATION for the PM to fill in
- **Recommendation:** "This looks like a variation. Client approval will be required once cost and schedule impact are confirmed."
- **Confirmation:** Required (financial + contractual consequence)
- **Action:** A draft variation (Item 13), not yet submitted
- **Final user output:** "I've prepared a variation: granite → quartz. Cost impact needs your input — I don't have current material pricing. [Review Draft]"

### Flow 3 — "Mistri nahi aaya, plaster ka kaam ruk gaya hai." (the brief's own example)

- **Intent:** `capture_reality` — routed to the existing, unmodified Capture pipeline (Item 24), not the new structuring pass
- **Context:** `getActiveSite()`
- **Entities:** Exactly what `intelligence_engine._structure()` already extracts today — labour absence, activity blocked (plaster)
- **Engines invoked:** `reality_engine.capture()`, `intelligence_engine._structure()` + `generate_proposals_for_event()` — all existing, unchanged
- **Facts:** The event is recorded as it always is
- **Inferences:** Schedule impact — via `reasoning_projections.project_lookahead()`'s own real dependency graph if the plaster activity is a tracked `workflow_activity`; otherwise not claimed
- **Recommendation:** "This may affect [downstream activity] — notify the PM?"
- **Confirmation:** Not required for the capture itself (already how Capture works); the *notification* is low-stakes enough to fall in the "executes automatically" tier (Item 14) if the recipient is unambiguous
- **Action:** The existing capture flow, plus one new notification dispatch
- **Final user output:** "Got it — recorded as a site issue. This may affect [activity] by about [N] day(s) based on the schedule. I've notified [PM name]. [Review]"

### Flow 4 — "Check if this affects handover."

- **Intent:** `query_schedule_impact`
- **Context:** `getActiveSite()`; "this" resolved to the most recent capture/variation in that project
- **Entities:** None beyond context — a pure query
- **Engines invoked:** `reasoning_engine.project_lookahead_view()`, `reasoning_projections.project_lookahead()` — existing, unchanged
- **Facts:** The real dependency-graph output
- **Inferences:** None beyond what the graph already computes
- **Recommendation:** N/A — this is an answer, not a recommendation
- **Confirmation:** None (read-only)
- **Action:** None
- **Final user output:** "Based on current dependencies, [activity] is [N days behind / on schedule], and handover is [affected by N days / not currently affected]."

### Flow 5 — "Prepare the payment schedule: 20% advance, 30% structure, 30% MEP, balance on handover."

- **Intent:** `prepare_commercial_schedule`
- **Context:** `getActiveSite()`
- **Entities:** Four percentage splits with their triggers, all FACT (the user stated exact numbers)
- **Engines invoked:** `commercial_engine.create_milestone()` (draft, ×4)
- **Facts:** The stated percentages themselves
- **Inferences:** None needed — the input was already fully specified
- **Recommendation:** "This totals 100% against the current contract value of ₹[X] — ready to review."
- **Confirmation:** Required (financial structure)
- **Action:** Four draft milestones (Item 13)
- **Final user output:** "I've prepared the payment schedule: 20% Advance / 30% Structure / 30% MEP / 20% Handover, against ₹[contract value]. [Review Draft]"

### Flow 6 — "Why is this project at risk?"

- **Intent:** `query_health`
- **Context:** `getActiveSite()`
- **Entities:** None
- **Engines invoked:** `reasoning_engine.explain_health()` — **already fully answers this today**, unchanged
- **Facts:** The real five-dimension health breakdown
- **Inferences:** None — this function is already deterministic and complete
- **Recommendation:** Whatever `explain_health()` already surfaces (unchanged)
- **Confirmation:** None (read-only)
- **Action:** None
- **Final user output:** Identical in substance to what the existing Explain Health screen shows today, delivered through the intent box instead of requiring navigation to find it — this flow requires zero new engine logic, only a new front door.

### Flow 7 — "Tell the PM about this."

- **Intent:** `dispatch_notification`
- **Context:** `getActiveSite()`; "this" resolved to the most recent relevant record in that project
- **Entities:** Recipient role (PM, FACT — explicitly named)
- **Engines invoked:** `notification_engine.create_notification()`
- **Facts:** The project's actual assigned PM (existing role-assignment data)
- **Inferences:** None
- **Recommendation:** N/A
- **Confirmation:** Not required if "this" resolved unambiguously (Item 14's "executes automatically" tier); if ambiguous, one clarifying question (Item 22) before sending
- **Action:** A real notification, sent
- **Final user output:** "Notified [PM name] about [the resolved subject]."

### Flow 8 — "Compare this with our previous residential projects."

- **Intent:** `query_comparison`
- **Context:** `getActiveSite()`
- **Entities:** Comparison scope ("residential" — a project-type filter)
- **Engines invoked:** `reasoning_engine.compare_projects()` — exists and works once given project IDs
- **Facts:** Whatever comparison data those resolved projects actually have
- **Inferences/Gap:** **Named honestly** — "residential" as a filter requires project type to be structured, queryable metadata, which is not consistently captured today (audit Section M #10). If it cannot be resolved reliably, Atlas says so rather than guessing which projects count as "residential."
- **Recommendation:** The comparison itself, once resolved
- **Confirmation:** None (read-only)
- **Action:** None
- **Final user output (if resolvable):** The real comparison. **(if not):** "I can't reliably tell which of your projects are residential yet — project type isn't consistently recorded. Want to compare specific projects by name instead?"

### Flow 9 — "Make a preliminary budget."

- **Intent:** `prepare_budget`
- **Context:** `getActiveSite()`
- **Entities:** Contract value (read from the project's own existing commercial data if already set, FACT; otherwise asked for)
- **Engines invoked:** `knowledge_engine` (category taxonomy), `commercial_engine.create_budget()` (draft)
- **Facts:** The contract value, if already known
- **Inferences:** Category-by-category distribution — explicitly ASSUMED (Item 27), never presented as derived from real historical proportions Atlas does not have
- **Recommendation:** "This is a preliminary structure based on standard category proportions, not your project's own historical data — review and adjust."
- **Confirmation:** Required (financial)
- **Action:** A draft budget (Item 13)
- **Final user output:** "I've prepared a preliminary budget across [N] categories, ASSUMED proportions — please review before confirming. [Review Draft]"

### Flow 10 — "What's happening on my projects today?"

- **Intent:** `query_digest`
- **Context:** The user's own full visible portfolio (no single-project context needed)
- **Entities:** None
- **Engines invoked:** `since_last_visit()`, `my_day()`, the existing daily-digest logic in `inbox_intelligence_service` — all existing, unchanged, currently spread across three separate screens
- **Facts:** The union of what those three already-correct functions return
- **Inferences:** None — pure synthesis, no new computation
- **Recommendation:** N/A — an informational digest
- **Confirmation:** None (read-only)
- **Action:** None
- **Final user output:** One synthesized answer combining what currently requires checking three separate screens — the clearest possible illustration of this specification's own core claim: the capability already exists three times over; the only new work is combining it into one coherent answer.
