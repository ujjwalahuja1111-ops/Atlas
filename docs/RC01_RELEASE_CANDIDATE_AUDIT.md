# RC-01 — Atlas Release Candidate Audit

This is a coherence audit, not a capability audit - PILOT-01 already assessed whether Atlas can run a real project. This assessment asks a different question: does Atlas feel like one operating system, or a collection of excellent modules that happen to share a login screen. Every finding below was verified by reading the current code fresh this session, not carried forward from memory of building these systems. No code was written; this is Release Candidate sign-off, not engineering.

---

## 1. Release Candidate Defect Register

### Critical
None found. No defect in this audit breaks data integrity, security, or the core project lifecycle PILOT-01 already verified works end-to-end.

### High

RC-D1 — Commercial summary is rendered from three independent screens with overlapping-but-not-identical tile sets. projects/[id].tsx, workspace/[id].tsx's Project Pulse, and commercial/[id].tsx itself each independently render a subset of the same commercial numbers (current contract value, pending variations, cash flow signal). All three ultimately read from the same backend source of truth (apiGetCommercialSummary), so there is no data-integrity risk - but a PM sees "Pending Variations" phrased and positioned three different ways depending on which screen they happen to be on, which is precisely the "collection of modules" feeling this task asks to eliminate. Recommendation for post-pilot: projects/[id].tsx's own full commercial tile grid is the best candidate to trim, now that EX-01 made the Workspace the primary destination and that screen's own Project Pulse already covers the headline numbers.

RC-D2 — A legacy, pre-CP-01 commercial field is still rendered as a silent fallback. In projects/[id].tsx, if commercialSummary (the real, current Commercial engine's own output) isn't loaded, the screen falls back to rendering an older commercial field with a visibly different, smaller set of tiles (no Paid/Outstanding data at all - hardcoded "Not Available Yet"). This is dead functionality from before CP-01 built the real Commercial engine, confirmed still present and still reachable by direct code inspection this session. It doesn't cause incorrect data (it degrades to a visibly incomplete display, not wrong numbers), but it's a genuine "orphaned backend capability" this audit was specifically asked to find.

### Medium

RC-D3 — variation.linked_photo_ids/linked_drawing_ids/linked_quotation_ids exist and work at the API layer but have no UI to populate them. Confirmed in KM-01: the backend route accepts these fields and they were verified working through the live API, but the frontend's own VariationCreateInput type never exposes them. This means the Observation->Variation relationship KM-01's own Knowledge Graph traces is, in practice, populated only by test data today - a real PM has no way to link a photo to a variation through the product itself.

RC-D4 — GST, retention, and advance percentages are stored on Contract but never applied to any calculation. Already the central finding of PILOT-01's own Go/No-Go assessment; repeated here because it is also, independently, a coherence issue - the product asks a PM to enter these numbers during Contract creation and then behaves as if they don't exist everywhere downstream (Payment Requests, Payments). This is the single clearest "the interface promises something the system doesn't deliver" gap in Atlas today.

RC-D5 — WF-01's own orchestration covers 2 of the 10 named workflow chains (Milestone Completed, Variation Approved), stated honestly in that package's own report. The other 8 (Blocked Activity, Inspection Due, Payment Received, etc.) rely on pre-existing, non-orchestrated surfacing (My Day, health rules) rather than WF-01's own automatic-trigger mechanism. Not a defect in what exists, but a real inconsistency in how different kinds of "something happened" get surfaced - some automatically push a suggestion, most still require the user to notice on their own.

### Low

RC-D6 — KG-UI-01's "Explain" entry point reaches 5 of 8 named entities, with Observation, Workflow Item, and Commercial Event left out, named directly in that package's own report. A PM exploring "why does this exist" will find the feature inconsistently available depending on which record they're looking at.

RC-D7 — The variation submission sequence is three separate taps (Create -> Submit -> Send for Client Review) for what a PM experiences as one decision, named in "A Day With Atlas" and never revisited since. Cosmetic-adjacent but real friction, not a blocker.

---

## 2. Integration Matrix

Verified by reading the actual import/call chain for each subsystem pair, not assumed from architecture documentation.

| Subsystem | <-> Commercial | <-> Workflow | <-> Memory | <-> Knowledge Graph | <-> Timeline | <-> Workspace | <-> Executive Hub | <-> Operations | <-> Lifecycle |
|---|---|---|---|---|---|---|---|---|---|
| Commercial | - | Indirect (shares a project, no direct call) | Yes - CM-01 reads commercial_events directly | Yes - KM-01 traverses milestone/variation/payment FKs directly | Yes - Commercial History reuses commercial_events | Yes - EX-01's Project Pulse + Stage Focus both read commercial summary | Yes - Portfolio Control Center's own commercial intelligence | Indirect (shares a project) | Yes - PL-01's Stage Focus reads Contract/Budget existence |
| Workflow | Indirect | - | Not yet reached by CM-01 (Since Last Visit covers commercial events only, named gap) | Partial - KM-01 reaches workflow_activity via Reality Event's activity_id, not workflow's own dependency graph | Yes - Executive Timeline includes workflow activity changes | Yes - My Day / Today's Mission | Indirect via My Day rollups | Yes - Operational items reference workflow activities | Not directly - PL-01's stage is independent of workflow completion |
| Memory (CM-01) | Yes (see above) | No - named gap in CM-01's own report | - | Not integrated - CM-01 and KM-01 are parallel, non-interacting systems as of this audit | Reuses the same event stream Timeline reuses, not Timeline itself | Yes - "Since You Were Last Here" is the Workspace's own first section | Not reached - Executive Hub has no per-project memory view | No - named gap | No - named gap |
| Knowledge Graph (KM-01/KG-UI-01) | Yes | Partial (see above) | No - not integrated (see above) | - | Not integrated - Impact Trace/Decision Trace don't appear in the Timeline UI | Partial - 5 of 8 Explain entry points reachable from Commercial rows inside the Workspace | Not reached | Partial - Operational Item relationships exist in the engine, no UI reaches them | Not integrated |
| Timeline | Yes | Yes | Shares underlying events, no direct call | No - not integrated | - | Yes | Yes - Executive Timeline is the portfolio-wide version | Yes | Not directly |
| Workspace (EX-01) | Yes (Project Pulse, Stage Focus, AI Suggestions deep links) | Yes (Today's Mission) | Yes (CM-01) | Partial (Explain buttons live in Commercial, reached via Workspace navigation, not the Workspace itself) | Partial (Project Feed section, Commercial-events-only, named gap in EX-01's own report) | - | Yes - IN-01 bridged this both ways | Not directly (Executive Hub is portfolio-wide) | Yes - Stage Focus |
| Executive Hub | Yes (Commercial Intelligence) | Indirect via Priority Engine | No - not integrated | No - not integrated | Yes - Executive Timeline | Yes (IN-01) | - | Yes - Portfolio Control Center | Not directly |
| Operations | Indirect | Yes | No - not integrated | Partial (engine-level only) | Yes | Yes | Yes | - | Not directly |
| Lifecycle (PL-01) | Yes (Stage Focus reads Contract/Budget) | Not directly | No - not integrated | No - not integrated | Not directly | Yes | Not directly | Not directly | - |

Overall integration verdict: Commercial is the best-integrated subsystem in Atlas - every other system either reads from it directly or was built with explicit awareness of it. Memory (CM-01) and Knowledge Graph (KM-01) are the two most recently-built systems and are correctly each integrated into the Workspace, but not with each other or with Workflow/Operations/Lifecycle - this is the clearest evidence of "excellent modules" rather than "one operating system" in the current product, and matches this task's own framing precisely.

---

## 3. Data Ownership Matrix

| Business Concept | Owner | Referenced by | Duplicated? |
|---|---|---|---|
| Contract | Commercial Engine | Workspace (Stage Focus, Pulse), Project Dashboard, Knowledge Graph | No - single source, multiple readers (correct pattern) |
| Budget | Commercial Engine | Workspace, Project Dashboard | No |
| Milestone | Commercial Engine | Workspace (AI Suggestions), Knowledge Graph, WF-01's orchestration rule | No |
| Variation | Commercial Engine | Workspace, Knowledge Graph, WF-01's orchestration rule | No |
| Payment Request / Payment | Commercial Engine | Workspace, Knowledge Graph | No |
| Cash Flow Signal | Commercial Engine (cash_flow_signal field on the summary) | Project Dashboard, Workspace Pulse, Workspace Health Strip, Commercial Workspace's own Health Banner | No duplication of computation - same field, four readers. The display is repeated (RC-D1), the ownership is not. |
| Lifecycle Stage | Project document itself (PL-01) | Workspace Stage Focus | No |
| Last Visit / Since Last Visit | project_visits collection (CM-01) | Workspace only | No |
| Relationships (Knowledge Graph) | Nothing stored - inferred live from existing FK fields (KM-01's own explicit design) | Explain screen (KG-UI-01) | N/A by design - this is the one concept that correctly has zero owner, since KM-01 deliberately stores nothing |
| Insights / Suggestions | CRE (reasoning_insights collection) | Workspace AI Suggestions | No |
| Operational Items | Operations Engine | My Day, Workspace Today's Mission, Timeline | No |
| Workflow Activities | Workflow Engine | My Day, Timeline, Reality Events (activity_id) | No |

Overall data ownership verdict: genuinely strong. Every business concept in Atlas has exactly one true owner, confirmed by tracing each field back to the engine that writes it. RC-D1's finding is a display redundancy, not an ownership one - worth stating precisely, since conflating the two would misdiagnose the fix (the fix is UI consolidation, not a data migration).

---

## 4. UX Consistency Audit

Buttons: "Explain" (KG-UI-01) uses a consistent help-circle icon across all five entities it reaches - genuinely consistent where implemented. Edit icons (create-outline) are consistent across Contract/Budget/Milestone.

Terminology: "Blocked" is used consistently across My Day, Workspace, Daily Review, and Executive Timeline - confirmed fresh this session; the "Blocked" vs "Blockers" inconsistency UX-01 originally found and UX-02 fixed has held and did not regress across any subsequent package.

Navigation: IN-01's deep-link shapes are used consistently by every package built after it (CM-01, KG-UI-01 both reuse the exact same URL patterns rather than invent new ones) - this is the clearest evidence of "one operating system" thinking taking hold in the more recent packages, in contrast to RC-D1's own finding about the display redundancy from earlier packages.

Actions: the Variation lifecycle (RC-D7) is the one clear inconsistency - every other multi-step commercial action (Payment Request -> Payment) requires one tap per record; Variation requires three taps to reach the same "ready for the next party to act" state.

Visual hierarchy: consistent use of Section/Tile/Card primitives across Commercial and Workspace - no rogue custom layouts found in this pass.

Role behavior: consistent and correctly enforced - CP-01, CP-02, and PL-01 each independently found and fixed real project-visibility gaps before building on top of them, and this session found no new instance of the same class of bug in a fresh pass over the same route families.

---

## 5. Pilot Blockers

None. Every finding in this audit (RC-D1 through RC-D7) is a coherence or polish issue, not something that would stop Studio Neoteric from running a real project inside Atlas starting Monday. The two items with genuine day-one visibility to a real user - RC-D2 (a legacy fallback screen state) and RC-D4 (GST/retention) - are both already named precisely: RC-D4 is PILOT-01's own central finding and already has a required pre-pilot mitigation (an explicit conversation with Accounts); RC-D2 only surfaces if the real Commercial summary fails to load, which has not been observed in any of this engagement's own live-API testing.

This audit's own overall verdict, stated directly: Atlas is coherent enough to ship as a Release Candidate. The defects found are real and worth fixing, but every one of them is a "make the good thing feel more like one thing" problem, not a "something is broken" problem - which is exactly the state a product should be in when the mission is explicitly "stop adding features, make it feel like one operating system."
