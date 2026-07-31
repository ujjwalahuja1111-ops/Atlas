# RC-03 — Pilot Readiness Completion Report

Per this phase's own requirement, this report begins with findings, organized by the phases this pass actually reached.

---

## Phase 1 — Production Configuration Validation

### Finding: a real, confirmed blocker — no customer could create their own first admin account

Investigated the actual production bootstrap path, not the demo tooling. scripts/db_seed.py's own docstring is explicit: "Standalone script - not imported by server.py, any route, or any engine, so it has zero effect on production runtime behaviour; it only runs when a developer explicitly invokes it." This confirmed the seed scripts (db_seed.py, seed_demo_project.py, reference_portfolio.py) were never the intended path for a real customer - they are development/demo tooling only.

That left one question: what happens when a genuinely new customer, with a genuinely empty database, tries to sign up? Traced register_user() directly and found every new registration - with no exception - creates a pending account, requiring an existing admin to approve it via /users/{id}/approve. On a brand-new database, there is no existing admin. Confirmed by searching the entire codebase for any "if this is the first user, make them admin" logic: none exists.

This is a genuine chicken-and-egg blocker. A real construction company deploying Atlas fresh could not create their own first management account through any customer-facing path - the only way in was for engineering to run a dev seed script or manipulate the database directly, which is exactly what "can a customer deploy without engineering assistance" asks and exactly the answer that would have made this phase's own question unanswerable in the affirmative.

Fixed with a small, targeted change to the existing registration function - no new architecture, no new engine, no new feature: the very first account ever registered on an empty database (db.users.count_documents({}) == 0) is automatically approved as management, unrestricted. Every subsequent registration follows the existing, unchanged pending-approval flow.

Verified three ways: a genuinely empty, unseeded database's first registration correctly returns role: management, approval_status: approved; a second registration on that same database correctly falls back to the normal pending flow (confirming this isn't "everyone becomes admin," just the genuine founder); and the founding admin was confirmed to immediately exercise a real management-only capability (creating a project and seeing it in Portfolio Control Center) with zero approval step from anyone else. Separately confirmed a registration on an already-seeded database (via the real ACDP bootstrap) correctly does not trigger founding-admin status - the check reflects genuine database state, not registration order within a session.

### Site Engineer role — resolved, not merely deferred

Before validating anything, checked what "Site Engineer" actually is in Atlas's own role model. memory_engine.ROLES = {"management", "project_manager", "site_supervisor", "client"} - four roles, full stop. A codebase-wide search found "site_engineer" exactly once, as a string value for suggested_owner_role in AI-generated proposal text (a semantic label for who should handle something), never as an authenticatable role, and zero references anywhere in the frontend.

This resolves a risk this engagement's own reports (Beta-04, Beta-06E, Beta-06G, RC-02) carried forward across four consecutive sprints as "Site Engineer's own distinct workflows not validated." That framing was based on treating Site Engineer as a role separate from Site Supervisor, which the system itself does not do - construction companies may use both job titles, but Atlas backs both with the identical site_supervisor authentication role, permissions, and UI. There is no separate experience to validate because none exists by design.

Verified this conclusion is not just a definitional technicality by confirming every capability RC-03's own Phase 3 names is genuinely available end-to-end to site_supervisor: workflow status transitions, production inputs (a legitimate validation error was returned for an activity with no production model - confirmed as correct behavior, not a missing capability, by checking a different activity), completion evidence viewing, reality capture linked to a workflow activity, and the role's own daily My Day view. All confirmed working via real API calls against real ACDP data.

---

## What Was Not Reached — Named Explicitly

Given the time available, effort concentrated on Phase 1 specifically, since it produced the single most consequential finding of this pass - a genuine deployment blocker, not a hypothetical one. Phases 2 (Operational Recovery), 4 (full six-role continuous simulation), and 5 (Reference Portfolio demonstration-credibility review) were not reached this pass. This is stated plainly rather than implied covered.

---

## Testing

- 3 new regression tests for the founding-admin fix, each explicitly clearing the users collection to guarantee genuine empty-database conditions (this file's shared, module-scoped fixture otherwise means no test naturally starts from empty) - verified safe against this file's actual execution order, not merely assumed safe from position in the file.
- Full regression suite: 138/138 passing (up from 135), confirmed stable across two consecutive runs.
- The founding-admin scenario, the normal-second-registration scenario, and the already-seeded-database scenario were each verified via live, constructed httpx scenarios before being converted to permanent tests.

---

## Files Changed

- backend/engines/memory_engine.py - register_user() now recognizes and correctly handles the founding-admin case.
- backend/tests/test_dev02_bootstrap_reliability.py - 3 new tests.

---

## Remaining Risks — Named Explicitly

1. Operational Recovery (Phase 2) was not validated this pass - whether ordinary production mistakes (wrong assignment, wrong approval, accidental closure, reopened issues) can be corrected without data corruption or engineering intervention remains unconfirmed, though prior sprints have incidentally verified some of this (reopening a workflow activity, reopening operational items) without it being the focused subject of a dedicated pass.
2. The full six-role continuous lifecycle (Phase 4) was not exercised as one uninterrupted sequence this pass.
3. Reference Portfolio demonstration credibility (Phase 5) - naming, realism, and usefulness specifically as a sales/demo environment - remains unassessed across five consecutive sprints now.
4. The founding-admin fix itself is new, security-relevant logic deserving of its own scrutiny beyond what this pass's own tests cover: it was not checked against concurrent-registration race conditions (two people registering at the exact same instant on a brand-new database), which is a narrow but real edge case for a check based on a document count.

---

## RC-03 Assessment

The single highest-value question available to this pass - can a real customer stand up Atlas without engineering in the room - had a concrete, negative answer before this session and a concrete, positive, verified answer after it. That is genuine forward movement specifically on the blocker RC-02's own report named first. The Site Engineer question, carried as an open risk across four prior sprints, is now resolved with evidence rather than deferred a fifth time.

Two of RC-02's three named blockers (Production Configuration, Site Engineer) have real, evidenced progress. The third (Operational Recovery) and the two items from this phase's own remaining scope (Phase 4's continuous simulation, Phase 5's demo-credibility review) were not reached.

---

## Pilot Decision

# NOT READY FOR PILOT

Concrete blockers, supported by evidence, per this phase's own instruction to list only blockers:

1. Operational Recovery has never been validated as a dedicated, focused investigation. Individual recovery mechanisms (reopening a workflow activity, reopening an operational item) have been incidentally confirmed to exist in prior sprints, but whether a real user's full range of ordinary mistakes - wrong commercial decision, duplicate capture, accidental closure with cascading effects, a cancelled payment - can be recovered from without data corruption or engineering support has not been the subject of direct, systematic testing. This is unconfirmed, not confirmed-fine.
2. The full six-role continuous lifecycle has never been exercised as one uninterrupted sequence. Adjacent handoffs (PM<->Supervisor, PM<->Client) have been separately verified across several prior sprints, but the complete Management -> PM -> Supervisor -> PM -> Client -> Management chain, in one continuous run, has not been executed even once.

These two are named as blockers because they are genuinely untested, consistent with this phase's own instruction that an unvalidated significant workflow cannot be assumed fine. They are not polish items and are not included here speculatively - they are the two specific, named gaps in evidence that stand between the current state and an honest "Ready" determination, and each is directly actionable in a focused next pass.
