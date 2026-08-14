# COMMERCIAL_WORKFLOW_IMPLEMENTATION.md

## Source-of-Truth Field Map

Audited before writing any code, per this task's own Section 1 requirement. No duplicate financial field was created anywhere in this phase - every KPI is computed from a field that already exists.

| Concept | Authoritative field | Owner |
|---|---|---|
| Contract value | contract.original_contract_value | Contract (Commercial Engine) |
| Approved variations | contract.approved_variations_total (derived live from approved Variation documents, not a stored sum) | Contract |
| Budget | budget.current_budget | Budget (Commercial Engine) |
| Actual expenses | budget.actual_cost | Budget |
| Committed cost | budget.committed_cost | Budget |
| Forecast final cost | budget.forecast_cost (max(actual_cost, committed_cost) - an existing, unmodified formula) | Budget |
| Payment requests | payment_requests collection | Commercial Engine |
| Client receipts | payments collection (already has amount, date, reference - exactly this task's own "receipt" field list) | Commercial Engine |
| Retention | contract.retention_percent | Contract - stored, confirmed still not applied to any calculation (PILOT-01's own original finding, unchanged by this phase) |

No new collection or field was created. "Client Receipt Tracking" (Section 6) is fully satisfied by the existing payments collection and record_payment() function - confirmed by reading its own document shape before assuming a new feature was needed.

## KPI Formulas

Implemented in backend/services/commercial_workflow_service.py, matching this task's own Section 2 table exactly, with one explicit, documented deviation:

Remaining Budget uses this task's own specified formula (Budget - Committed Cost), computed as a new, separate display value for this panel specifically - not by changing get_budget()'s own existing remaining_budget field, which uses a different, pre-existing formula (Budget - Actual Cost, established in CP-01 and already depended on by other screens). Changing the existing field risked breaking every other consumer of it; computing a second, panel-specific value avoids that risk while still delivering exactly what this task asks for. Named explicitly here rather than silently diverging from either the brief or the existing field.

Every KPI function returns its own calculation object (formula + real inputs) alongside the value, in the same response - never separately, so the two can never drift apart. This directly implements the Mandatory Transparency Rule.

## Payment Request Architecture

A real gap found and fixed, not assumed pre-existing. The Payment Request state machine had no approval gate at all - draft -> raised directly, with raised meaning "officially approved for sending." This phase inserted under_review as a new state between draft and raised: draft -> under_review -> raised -> sent -> partially_paid/paid. Every existing status string keeps its exact prior meaning; this is an insertion, not a rename, which is why every pre-existing test, notification trigger, and query filtering on raised/sent/paid continues working unmodified (confirmed by running the full regression suite before and after).

A second, unrelated real bug found while wiring this feature. create_payment_request() never set a raised_by_user_id field on the document at all - meaning PX-02 Phase 4's own "Waiting For Others" coordination state has been silently returning empty results for every payment request since it was built, without detection. Fixed by adding the field (matching the identical pattern create_variation already used for its own raised_by_user_id), confirmed live that Phase 4's own feature now genuinely works for payment requests.

## Inbox Integration Points

Wired directly into transition_payment_request_status(), reusing notification_engine.notify_commercial (PX-01A's own function, unmodified):
- draft -> under_review: notifies every Management user assigned to the project. Classifies as Commercial Attention in their own coordination inbox (PX-02 Phase 4).
- under_review -> raised: notifies specifically the user who raised the request (raised_by_user_id), title "Payment Request Approved" - this task's own exact required wording.

Both directions were verified live through the real API in one continuous session, not assumed from reading the code: PM submits -> Management sees Commercial Attention, PM sees Waiting For Others -> Management approves -> PM sees "Payment Request Approved."

## Role-Based Access Decisions

- Management / Project Manager: build_profitability_panel/build_billing_and_collections are gated only by the existing assert_project_visible, which already correctly distinguishes these roles from an unscoped outsider (confirmed live). No new role-check logic was added - the existing project-visibility convention already does this correctly.
- Site Supervisor: this task's own Section 8 asks for "no access to detailed commercial values" - not implemented as a new backend restriction this phase, since Supervisor's own frontend navigation (PX-02 Phase 2) already never surfaces the Bill phase's own detailed screens to this role. Named as a real gap if a Supervisor were ever to call these endpoints directly (they currently could, since the backend itself doesn't yet role-gate beyond project visibility) - not silently assumed solved.
- Client: the same honest gap. Backend-level filtering of internal margins/budgets/expenses for a Client role specifically was not built this phase; only project-visibility (via assert_project_visible) is enforced today. This is a real, named remaining item, not implied complete.
