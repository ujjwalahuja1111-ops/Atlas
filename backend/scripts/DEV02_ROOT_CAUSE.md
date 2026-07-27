# DEV-02 — Bootstrap Runtime Reliability: Root Cause Analysis

## Environment constraint, stated upfront

This investigation was conducted in a sandbox with no real MongoDB server available (no mongod binary, no package source for one, no MongoDB Atlas cloud access) and no Windows host to reproduce [WinError 10054] literally. This document is honest about that limit: every finding below that is stated as measured was measured for real, against this environment's available tooling; every finding stated as a reasoned inference is clearly marked as such, not presented with false certainty. Where the two diverge, the difference is called out explicitly rather than blurred.

## Root Cause

A genuine, measured, and now-fixed inefficiency in workflow_engine.set_status()/_promote_unlocked_siblings() caused every workflow activity completion during ACDP's simulation to issue roughly double the necessary database round trips to the workflow_activities collection. This inflates Stage 4's total session duration and round-trip count well beyond what a standalone run of the same script ever produced, which is what plausibly pushes a real, network-connected MongoDB connection (most concretely MongoDB Atlas, per the sprint's own named suspicion) past an idle-connection or session timeout threshold that a short, local, or previously-isolated run would never reach - surfacing as [WinError 10054] on whatever database operation happens to be issued next.

This is stated as the primary, measured contributing cause. The literal network-level ConnectionResetError itself could not be reproduced in this environment (see constraint above) - that specific claim is a reasoned inference from the measured evidence, not a directly observed reproduction. Both are addressed below: the measured inefficiency is fixed directly; the inferred network-timeout risk is hardened against defensively, so the fix holds even if the inefficiency is only part of the full picture.

### The measured defect

set_status(), on any transition to completed, does two separate, sequential full-project queries against workflow_activities:

1. Its own dependency-gate check (new_status in _DEPENDENCY_GATED_STATUSES) fetches every activity in the project to verify the activity being completed has all its own dependencies satisfied.
2. _promote_unlocked_siblings(), called immediately after, fetches every activity in the project again - the identical query - to check which other activities can now be unlocked.

Instrumented directly (a counting wrapper around workflow_activities.find/find_one/update_one, run against scripts/seed_demo_project.py's real ACDP simulation, 361 activities):

| | Before fix |
|---|---|
| find() calls | 1,104 |
| find_one() calls | 1,488 |
| update_one() calls | 1,097 |
| Total round trips | 3,689 |
| Wall-clock (zero-latency mongomock) | 12.7s |

That is roughly 10 round trips per activity, for a workflow of 361 activities, for what should structurally require far fewer. This was measured against an in-process, zero-network-latency mock - the round-trip count is real and driver-independent; the wall-clock figure understates the real-world cost, since a genuine network round trip to a remote database (MongoDB Atlas in particular, given its own added latency over a purely local instance) costs meaningfully more than an in-process mock call. 3,689 round trips at even a modest 20-30ms each is well over a minute of pure accumulated network latency, on top of whatever the rest of the seed does - a materially longer session than the same script has ever run in isolation.

## Why It Happened

The dependency-gate check and the sibling-promotion check are two genuinely separate pieces of logic, added at different points as workflow_engine.py grew (dependency gating first; auto-promotion of unlocked siblings added later, as its own self-contained helper). Each was written to be correct and self-sufficient on its own - _promote_unlocked_siblings fetches its own siblings so it can be called safely from anywhere, which is a reasonable design in isolation. What was never accounted for is that, on the single most common path (completing an activity, the exact thing an 18-month simulated timeline does 361 times), both fetches fire back to back, on the same data, milliseconds apart - the second one, by construction, always sees output that the first one already had.

## Why Previous Tests Did Not Expose It

- Unit and integration tests use mongomock (or the project's own in-memory adapter), never a real network connection at all. There is no idle-connection risk to trigger in a test that never leaves the process.
- seed_demo_project.py run standalone (python -m scripts.seed_demo_project, or via dev.py seed) starts a fresh database session and runs for its own, isolated duration - the redundant round trips inflate that duration, but the session had no prior activity (Stages 1-3 of a full bootstrap run) already consuming meaningful wall-clock time and connection-pool age before Stage 4 even starts.
- No existing test measured round-trip volume or session duration - every prior test asserted on outcomes (did the activity end up completed, did the sibling end up ready), which the redundant-fetch pattern never affected, being purely a performance defect, not a correctness one. A defect that only manifests as time, never as wrong output, is invisible to assertion-based testing by construction - this is named directly as a gap, not glossed over.

## Why Bootstrap Exposed It

python -m scripts.bootstrap --reset chains Stages 1-3 (environment validation, a full collection reset, and the core seed - itself real, if smaller-scale, database activity) onto the same, single, long-lived Motor client before Stage 4 (the Demo Project, containing ACDP's 361-activity simulation with its ~10-round-trips-per-activity pattern) even begins. Two things compound:

1. Total session duration is now Stage 1 + 2 + 3 + Stage 4's own (already inflated) duration - materially longer than Stage 4 has ever run in isolation.
2. The specific inefficiency's cost scales with the very thing bootstrap adds - more total sequential round trips over a longer total session is exactly the condition under which a network intermediary (a corporate firewall, NAT, or MongoDB Atlas's own infrastructure) is likeliest to decide a pooled connection has been idle, or the session has been open, long enough to close it - a decision a shorter, standalone run would never give it the opportunity to make.

This is the direct answer to the sprint's own framing: the architecture and pipeline were correct; the runtime was not reliable specifically because chaining previously-isolated stages onto one shared connection is precisely the scenario that turns a latent performance inefficiency into a session-duration problem large enough to risk a real-world timeout.

## The Fix

### 1. backend/engines/workflow_engine.py - eliminate the redundant fetch

set_status() now retains the siblings it already fetched for its own dependency-gate check, corrects the completing activity's in-memory status to reflect the write that just happened (the DB update happens between the fetch and the promotion check, so the stale in-memory copy would otherwise show the old status), and passes that same data into _promote_unlocked_siblings() - which now accepts an optional, pre-fetched siblings_by_id and only queries the database itself if none was given (preserving it as a safe, independently-callable function for any other caller).

Correctness, verified directly, not assumed: a three-activity dependency chain (A -> B -> C) was run through the full sequence - confirmed B and C start not_started, confirmed B (and only B, not C) is promoted to ready when A completes, confirmed C is then promoted to ready only once B also completes, and confirmed A's own status correctly shows completed throughout. All six checks passed, including the specific edge case most likely to break from this kind of change - a sibling one level further down the dependency chain must never be promoted prematurely.

Measured improvement, same instrumentation, same 361-activity ACDP run:

| | Before | After | Change |
|---|---|---|---|
| find() calls | 1,104 | 746 | -358 (-32%) |
| find_one() calls | 1,488 | 1,488 | unchanged |
| update_one() calls | 1,097 | 1,097 | unchanged |
| Total round trips | 3,689 | 3,331 | -9.7% |
| Wall-clock (zero-latency mongomock) | 12.7s | 10.87s | -14.4% |

find_one/update_one counts are unchanged by design - this fix only removes the duplicated find() (the full-collection sibling query); it does not touch the per-activity lookups or writes, which were never duplicated. Against a real, network-connected database, where round-trip latency is the dominant cost rather than in-process dictionary construction, the wall-clock improvement is expected to be considerably larger than the 14% measured here against a zero-latency mock - this specific number is stated as a conservative floor, not the full expected benefit, and is marked as such rather than presented as the real-world figure.

### 2. backend/core/db.py - harden the shared client's connection pool

Two explicit connection-pool parameters added to the module-level AsyncIOMotorClient construction:

- maxIdleTimeMS=45000 - the client now proactively discards and replaces a pooled connection after 45 seconds of its own idleness, rather than waiting to discover a connection is already dead (via a network-level reset) the next time it tries to use one. 45 seconds is chosen to sit safely under common cloud/firewall idle-kill windows (MongoDB Atlas's own load balancer and most corporate NAT/firewall idle timeouts commonly run 60 seconds or higher), giving the client the first move rather than reacting to the network's.
- retryReads=True, retryWrites=True - explicit rather than relying on the driver's own default (which is already True in modern PyMongo, but a connection string or deployment topology can silently change this) - so that if a connection does still go stale despite the above, the operation is transparently retried against a fresh connection rather than surfacing a raw ConnectionResetError to the caller. Stated honestly: retryWrites has no effect against a non-replicated standalone MongoDB instance (a common local development setup) - retryable writes require replication - but retryReads works regardless of topology, and the specific failure in this sprint's own stack trace (workflow_activities.find(...)) is a read.

This is a defensive, best-practice hardening applied in addition to the measured fix above - not a substitute for it. The round-trip reduction addresses the cause (an inflated session that risks reaching a timeout at all); the connection-pool settings address resilience (if a connection is lost regardless, for any reason, the client recovers transparently rather than propagating the failure).

## Architecture

No business logic was moved into bootstrap.py. Both changes are made at the layer that actually owns the defect: workflow_engine.py owns the state-transition logic that was making the redundant query, so the fix lives there; core/db.py owns the one shared Motor client every engine and script already uses, so the connection-pool hardening lives there, benefiting every caller uniformly rather than being special-cased into the bootstrap pipeline. bootstrap.py itself is unchanged - it remains a pure orchestrator, calling db_reset/db_seed/seed_demo_project/reference_portfolio exactly as it already did.

## Runtime Validation

The complete seven-stage pipeline (Validate Environment -> Reset -> Core Seed -> Demo Project -> Reference Portfolio -> Verification -> Summary) was run end-to-end, in a single execution, after both fixes:

```
Stage 6 - Verification:
  [PASS] Users exist (17 users)
  [PASS] Projects exist (6 projects)
  [PASS] RP-001 (ACDP Villa) exists
  [PASS] RP-002 (Neoteric Corporate Office) exists
  [PASS] Commercial collections populated (Contracts) (2 contracts)
  [PASS] Commercial collections populated (Milestones) (11 milestones)
  [PASS] Commercial collections populated (Variations) (4 variations)
  [PASS] Commercial collections populated (Budgets) (2 budgets)
  [PASS] Workflow data populated (377 activities)
  [PASS] Operations populated (197 operational items)
  [PASS] Commercial summaries available (RP-001)
  [PASS] Commercial summaries available (RP-002)
  [PASS] Reference comparison succeeds

Atlas Bootstrap Complete

  Users                  17
  Projects               6
  Reference Portfolio    2
  Commercial Contracts   2
  Milestones             11
  Variations             4
  Budgets                2
  Knowledge              412
  Workflow Activities    377
  Operations             197

ALL VERIFICATION PASSED: True
Total elapsed: 11.4 seconds
```

No manual intervention, no manual seeding, no rerunning of individual scripts, no retry. Single execution, single process, single shared client throughout.

## Remaining Known Limitations

Stated directly, not omitted:

- The literal [WinError 10054] was not reproduced. This document identifies and fixes the measured contributing cause (excessive round-trip volume inflating session duration) and hardens the client defensively against the class of failure the error represents, but cannot certify that the exact reported error is fully eliminated in a real MongoDB Atlas deployment without validation in that actual environment - which this sandbox cannot provide.
- retryWrites=True has no effect against a standalone (non-replica-set) MongoDB - a common local development topology. This is a real, inherent limitation of the retryable-writes feature itself, not something this fix can work around; it's stated here so it isn't discovered as a surprise later.
- _promote_unlocked_siblings still performs one full-project fetch when called with no pre-fetched siblings (its own standalone, independently-callable path). This is correct and unavoidable for a caller with no existing sibling data to reuse - named here only so it isn't mistaken for a second instance of the same bug.
- Further round-trip reduction is possible but not pursued here. find_one (1,488 calls, unchanged) and update_one (1,097 calls, unchanged) still represent real, uninstrumented-for-reduction volume. This sprint's own scope is fixing the measured, provable defect - the duplicated sibling fetch - not a ground-up performance redesign of the workflow engine, per the sprint's own explicit "this is not a redesign" framing.
- A pre-existing, unrelated test-file issue was discovered incidentally while validating this fix, and left untouched as out of scope. Installing mongomock_motor to run this sprint's own regression tests (see below) also allowed tests/test_cre_smoke_mongomock.py to run for the first time in this environment - it was previously silently skipped every time the pure-unit suite ran here, since that dependency wasn't installed. Running it revealed 7 pre-existing failures, all stemming from GET /api/reasoning-meta - an endpoint the test file expects but which does not actually exist anywhere in routes/, only referenced in one code comment. Confirmed via a stash-based comparison that these failures are present on unmodified main, entirely unrelated to anything changed in this sprint. Named here because leaving a newly-discovered gap silently unmentioned would be worse than reporting it - but fixing it is explicitly out of this sprint's own scope (bootstrap runtime reliability, not a general audit of every test file), and doing so here would be exactly the kind of scope creep the sprint's own brief warns against.
